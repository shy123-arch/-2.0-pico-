#include "streamer.hpp"

#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <cctype>
#include <cstring>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace holo {
namespace {

constexpr uint8_t kFragmentMagic[4] = {'H', 'T', 'V', 'F'};
constexpr size_t kFragmentHeaderSize = 24;

void writeU16(uint8_t* dst, uint16_t value) {
  dst[0] = static_cast<uint8_t>((value >> 8) & 0xFF);
  dst[1] = static_cast<uint8_t>(value & 0xFF);
}

void writeU32(uint8_t* dst, uint32_t value) {
  dst[0] = static_cast<uint8_t>((value >> 24) & 0xFF);
  dst[1] = static_cast<uint8_t>((value >> 16) & 0xFF);
  dst[2] = static_cast<uint8_t>((value >> 8) & 0xFF);
  dst[3] = static_cast<uint8_t>(value & 0xFF);
}

}  // namespace

CameraStreamer::CameraStreamer(Config config, Recorder& recorder) : config_(std::move(config)), recorder_(recorder) {}

CameraStreamer::~CameraStreamer() {
  stop();
}

bool CameraStreamer::active() const {
  return active_;
}

bool CameraStreamer::start(const CameraRequest& request) {
  stop();
  if (config_.transcode != 0) {
    if (request.width > 0) config_.output_width = request.width;
    if (request.height > 0) config_.output_height = request.height;
    if (request.fps > 0) config_.output_fps = request.fps;
  } else {
    if (request.width > 0) config_.width = request.width;
    if (request.height > 0) config_.height = request.height;
    if (request.fps > 0) config_.fps = request.fps;
  }
  if (request.bitrate > 0) config_.bitrate = request.bitrate;

  if (!connectStreamSocket(request.ip, request.port)) return false;

  const std::string pipeline_desc = buildPipeline();
  std::cout << "GStreamer pipeline: " << pipeline_desc << "\n";
  GError* error = nullptr;
  pipeline_ = gst_parse_launch(pipeline_desc.c_str(), &error);
  if (!pipeline_) {
    std::cerr << "gst_parse_launch failed: " << (error ? error->message : "unknown") << "\n";
    if (error) g_error_free(error);
    close(stream_fd_);
    stream_fd_ = -1;
    return false;
  }

  GstElement* sink = gst_bin_get_by_name(GST_BIN(pipeline_), "mysink");
  if (!sink) {
    std::cerr << "appsink 'mysink' not found\n";
    gst_object_unref(pipeline_);
    pipeline_ = nullptr;
    close(stream_fd_);
    stream_fd_ = -1;
    return false;
  }
  g_signal_connect(sink, "new-sample", G_CALLBACK(CameraStreamer::onSample), this);
  gst_object_unref(sink);

  active_ = true;
  sender_thread_ = std::thread(&CameraStreamer::senderLoop, this);
  gst_element_set_state(pipeline_, GST_STATE_PLAYING);
  std::cout << "Streaming started: " << config_.device << " " << config_.width << "x" << config_.height << "@"
            << config_.fps << " " << config_.input_format;
  if (config_.transcode != 0) {
    std::cout << " -> " << config_.output_width << "x" << config_.output_height << "@" << config_.output_fps
              << " H264";
  }
  std::cout << "\n";
  return true;
}

void CameraStreamer::stop() {
  if (!active_ && stream_fd_ < 0 && pipeline_ == nullptr) return;
  active_ = false;
  latest_cv_.notify_all();

  if (pipeline_) {
    gst_element_set_state(pipeline_, GST_STATE_NULL);
    gst_object_unref(pipeline_);
    pipeline_ = nullptr;
  }
  if (sender_thread_.joinable()) sender_thread_.join();
  if (stream_fd_ >= 0) {
    close(stream_fd_);
    stream_fd_ = -1;
  }
  std::cout << "Streaming stopped\n";
}

GstFlowReturn CameraStreamer::onSample(GstAppSink* sink, gpointer user_data) {
  return static_cast<CameraStreamer*>(user_data)->handleSample(sink);
}

GstFlowReturn CameraStreamer::handleSample(GstAppSink* sink) {
  GstSample* sample = gst_app_sink_pull_sample(sink);
  if (!sample) return GST_FLOW_OK;

  GstBuffer* buffer = gst_sample_get_buffer(sample);
  GstMapInfo map{};
  if (buffer && gst_buffer_map(buffer, &map, GST_MAP_READ)) {
    Frame frame;
    frame.bytes.assign(map.data, map.data + map.size);
    frame.monotonic_ns = monotonicNs();
    frame.pts_ns = GST_BUFFER_PTS_IS_VALID(buffer) ? int64_t(GST_BUFFER_PTS(buffer)) : -1;
    frame.dts_ns = GST_BUFFER_DTS_IS_VALID(buffer) ? int64_t(GST_BUFFER_DTS(buffer)) : -1;

    NalInfo nal = recorder_.inspectAndCacheH264(frame.bytes.data(), frame.bytes.size());
    recorder_.recordFrame(frame, nal);

    {
      std::lock_guard<std::mutex> lock(latest_mutex_);
      frame.seq = ++latest_seq_;
      latest_frame_ = std::move(frame);
    }
    latest_cv_.notify_one();
    gst_buffer_unmap(buffer, &map);
  }
  gst_sample_unref(sample);
  return GST_FLOW_OK;
}

std::string CameraStreamer::buildPipeline() const {
  std::ostringstream ss;
  ss << "v4l2src device=" << config_.device << " do-timestamp=true ! ";
  if (config_.input_format == "H264" || config_.input_format == "h264") {
    ss << "video/x-h264,width=" << config_.width << ",height=" << config_.height << ",framerate=" << config_.fps
       << "/1 ! h264parse config-interval=-1 ! ";
    if (config_.transcode != 0) {
      ss << "avdec_h264 max-threads=1 ! videoconvert ! videoscale ! videorate ! "
         << "video/x-raw,width=" << config_.output_width << ",height=" << config_.output_height
         << ",framerate=" << config_.output_fps << "/1 ! "
         << "x264enc tune=zerolatency speed-preset=ultrafast key-int-max=" << config_.output_fps
         << " bitrate=" << (config_.bitrate / 1000)
         << " byte-stream=true threads=1 sliced-threads=true ! "
         << "h264parse config-interval=-1 ! ";
    }
    ss << "video/x-h264,stream-format=byte-stream,alignment=au ! ";
  } else if (config_.input_format == "MJPG" || config_.input_format == "MJPEG") {
    ss << "image/jpeg,width=" << config_.width << ",height=" << config_.height << ",framerate=" << config_.fps
       << "/1 ! jpegdec ! videoconvert ! videoscale ! videorate ! "
       << "video/x-raw,width=" << config_.output_width << ",height=" << config_.output_height
       << ",framerate=" << config_.output_fps << "/1 ! "
       << "x264enc tune=zerolatency speed-preset=ultrafast key-int-max=" << config_.output_fps << " bitrate="
       << (config_.bitrate / 1000)
       << " byte-stream=true threads=1 sliced-threads=true ! h264parse config-interval=-1 ! "
       << "video/x-h264,stream-format=byte-stream,alignment=au ! ";
  } else {
    throw std::runtime_error("unsupported input format: " + config_.input_format);
  }
  ss << "appsink name=mysink emit-signals=true sync=false max-buffers=1 drop=true";
  return ss.str();
}

bool CameraStreamer::connectStreamSocket(const std::string& host, int port) {
  stream_fd_ = socket(AF_INET, udpTransport() ? SOCK_DGRAM : SOCK_STREAM, 0);
  if (stream_fd_ < 0) {
    std::cerr << "socket failed: " << strerror(errno) << "\n";
    return false;
  }

  if (!udpTransport()) {
    int yes = 1;
    setsockopt(stream_fd_, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
  }
  int send_buf = udpTransport() ? 512 * 1024 : 256 * 1024;
  setsockopt(stream_fd_, SOL_SOCKET, SO_SNDBUF, &send_buf, sizeof(send_buf));

  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(uint16_t(port));
  if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
    std::cerr << "invalid stream host: " << host << "\n";
    close(stream_fd_);
    stream_fd_ = -1;
    return false;
  }
  if (connect(stream_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
    std::cerr << "connect " << host << ":" << port << " failed: " << strerror(errno) << "\n";
    close(stream_fd_);
    stream_fd_ = -1;
    return false;
  }
  std::cout << "Connected " << (udpTransport() ? "UDP" : "TCP") << " stream socket to " << host << ":" << port
            << "\n";
  return true;
}

void CameraStreamer::senderLoop() {
  uint64_t sent_seq = 0;
  while (active_) {
    Frame frame;
    {
      std::unique_lock<std::mutex> lock(latest_mutex_);
      latest_cv_.wait(lock, [&] { return !active_ || latest_seq_ != sent_seq; });
      if (!active_) break;
      frame = latest_frame_;
      sent_seq = frame.seq;
    }
    if (!frame.bytes.empty() && !sendFramePacket(frame)) {
      active_ = false;
      break;
    }
  }
}

bool CameraStreamer::sendFramePacket(const Frame& frame) {
  uint32_t size = static_cast<uint32_t>(frame.bytes.size());
  size_t packet_count = 1;
  uint8_t header[4] = {
      static_cast<uint8_t>((size >> 24) & 0xFF),
      static_cast<uint8_t>((size >> 16) & 0xFF),
      static_cast<uint8_t>((size >> 8) & 0xFF),
      static_cast<uint8_t>(size & 0xFF),
  };

  if (udpTransport()) {
    if (config_.udp_fragment) {
      const size_t mtu = std::max<size_t>(256, size_t(config_.udp_mtu));
      const size_t payload_max = mtu > kFragmentHeaderSize ? mtu - kFragmentHeaderSize : 1;
      const uint16_t frag_count =
          static_cast<uint16_t>((frame.bytes.size() + payload_max - 1) / payload_max);
      packet_count = frag_count;
      static uint32_t frame_id = 0;
      ++frame_id;

      for (uint16_t frag_id = 0; frag_id < frag_count; ++frag_id) {
        const size_t offset = size_t(frag_id) * payload_max;
        const size_t payload_size = std::min(payload_max, frame.bytes.size() - offset);
        std::vector<uint8_t> packet(kFragmentHeaderSize + payload_size);
        std::memcpy(packet.data(), kFragmentMagic, sizeof(kFragmentMagic));
        packet[4] = 1;
        packet[5] = 0;
        writeU16(packet.data() + 6, uint16_t(kFragmentHeaderSize));
        writeU32(packet.data() + 8, frame_id);
        writeU16(packet.data() + 12, frag_id);
        writeU16(packet.data() + 14, frag_count);
        writeU32(packet.data() + 16, size);
        writeU16(packet.data() + 20, uint16_t(payload_size));
        writeU16(packet.data() + 22, 0);
        std::memcpy(packet.data() + kFragmentHeaderSize, frame.bytes.data() + offset, payload_size);

        ssize_t n = send(stream_fd_, packet.data(), packet.size(), MSG_DONTWAIT | MSG_NOSIGNAL);
        if (n < 0) {
          if (errno == EAGAIN || errno == EWOULDBLOCK || errno == ENOBUFS) return true;
          std::cerr << "UDP stream send failed: " << strerror(errno) << "\n";
          return false;
        }
      }
      updateStats(frame, packet_count);
      return true;
    }

    constexpr size_t kMaxUdpPayload = 65507;
    if (sizeof(header) + frame.bytes.size() > kMaxUdpPayload) {
      std::cerr << "dropping oversized UDP H264 packet: " << (sizeof(header) + frame.bytes.size()) << " > "
                << kMaxUdpPayload << "\n";
      updateStats(frame, 0);
      return true;
    }
    std::vector<uint8_t> packet(sizeof(header) + frame.bytes.size());
    std::memcpy(packet.data(), header, sizeof(header));
    std::memcpy(packet.data() + sizeof(header), frame.bytes.data(), frame.bytes.size());
    ssize_t n = send(stream_fd_, packet.data(), packet.size(), MSG_DONTWAIT | MSG_NOSIGNAL);
    if (n < 0) {
      if (errno == EAGAIN || errno == EWOULDBLOCK || errno == ENOBUFS) return true;
      std::cerr << "UDP stream send failed: " << strerror(errno) << "\n";
      return false;
    }
    updateStats(frame, packet_count);
    return true;
  }

  if (!sendAll(header, sizeof(header)) || !sendAll(frame.bytes.data(), frame.bytes.size())) {
    std::cerr << "TCP stream send failed: " << strerror(errno) << "\n";
    return false;
  }
  updateStats(frame, packet_count);
  return true;
}

bool CameraStreamer::sendAll(const uint8_t* data, size_t size) {
  size_t sent = 0;
  while (sent < size && active_) {
    ssize_t n = send(stream_fd_, data + sent, size - sent, MSG_NOSIGNAL);
    if (n <= 0) {
      if (n == 0) errno = ECONNRESET;
      return false;
    }
    sent += size_t(n);
  }
  return sent == size;
}

bool CameraStreamer::udpTransport() const {
  if (config_.transport.size() != 3) return false;
  return std::toupper(config_.transport[0]) == 'U' && std::toupper(config_.transport[1]) == 'D' &&
         std::toupper(config_.transport[2]) == 'P';
}

void CameraStreamer::updateStats(const Frame& frame, size_t packet_count) {
  const uint64_t now = monotonicNs();
  if (stats_last_ns_ == 0) stats_last_ns_ = now;
  ++stats_frames_;
  stats_bytes_ += frame.bytes.size();
  stats_packets_ += packet_count;
  stats_max_frame_bytes_ = std::max(stats_max_frame_bytes_, frame.bytes.size());

  const uint64_t elapsed_ns = now - stats_last_ns_;
  if (elapsed_ns < 1000000000ULL) return;

  const double elapsed_s = double(elapsed_ns) / 1e9;
  const double fps = double(stats_frames_) / elapsed_s;
  const double avg_kb = stats_frames_ ? double(stats_bytes_) / double(stats_frames_) / 1024.0 : 0.0;
  const double max_kb = double(stats_max_frame_bytes_) / 1024.0;
  const double mbps = double(stats_bytes_) * 8.0 / elapsed_s / 1000000.0;
  const double packets_per_frame = stats_frames_ ? double(stats_packets_) / double(stats_frames_) : 0.0;
  const double age_ms = frame.monotonic_ns > 0 ? double(now - frame.monotonic_ns) / 1e6 : 0.0;

  std::cout << "[VideoStats] transport=" << (udpTransport() ? "UDP" : "TCP") << " fps=" << fps
            << " avg_frame=" << avg_kb << "KB max_frame=" << max_kb << "KB bitrate=" << mbps
            << "Mbps packets_per_frame=" << packets_per_frame << " latest_age=" << age_ms << "ms\n";

  stats_last_ns_ = now;
  stats_frames_ = 0;
  stats_bytes_ = 0;
  stats_packets_ = 0;
  stats_max_frame_bytes_ = 0;
}

}  // namespace holo
