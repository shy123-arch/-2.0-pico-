#include "recorder.hpp"

#include <sys/stat.h>

#include <iostream>

namespace holo {

namespace {

std::vector<size_t> annexbStarts(const uint8_t* data, size_t size) {
  std::vector<size_t> starts;
  for (size_t i = 0; i + 3 < size;) {
    if (data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 1) {
      starts.push_back(i);
      i += 3;
    } else if (i + 4 < size && data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 0 && data[i + 3] == 1) {
      starts.push_back(i);
      i += 4;
    } else {
      ++i;
    }
  }
  return starts;
}

size_t startCodeLen(const uint8_t* data, size_t offset, size_t size) {
  if (offset + 3 <= size && data[offset] == 0 && data[offset + 1] == 0 && data[offset + 2] == 1) return 3;
  if (offset + 4 <= size && data[offset] == 0 && data[offset + 1] == 0 && data[offset + 2] == 0 &&
      data[offset + 3] == 1) {
    return 4;
  }
  return 0;
}

}  // namespace

void Recorder::start(const std::string& session_dir) {
  std::lock_guard<std::mutex> lock(mutex_);
  stopLocked();
  mkdir(session_dir.c_str(), 0755);
  session_dir_ = session_dir;
  video_.open(session_dir + "/video.h264", std::ios::binary | std::ios::trunc);
  timestamps_.open(session_dir + "/video_timestamps.csv", std::ios::out | std::ios::trunc);
  if (!video_.is_open() || !timestamps_.is_open()) {
    std::cerr << "Failed to open recording files under " << session_dir << "\n";
    stopLocked();
    return;
  }
  timestamps_ << "frame_idx,monotonic_ns,gst_pts_ns,gst_dts_ns,size_bytes\n";
  active_ = true;
  wait_idr_ = true;
  frame_idx_ = 0;
  std::cout << "Recording START -> " << session_dir << "\n";
}

void Recorder::stop() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (active_) std::cout << "Recording STOP -> " << session_dir_ << "\n";
  stopLocked();
}

void Recorder::stopLocked() {
  if (video_.is_open()) {
    video_.flush();
    video_.close();
  }
  if (timestamps_.is_open()) {
    timestamps_.flush();
    timestamps_.close();
  }
  active_ = false;
  wait_idr_ = true;
  frame_idx_ = 0;
}

NalInfo Recorder::inspectAndCacheH264(const uint8_t* data, size_t size) {
  NalInfo info;
  auto starts = annexbStarts(data, size);
  std::lock_guard<std::mutex> lock(mutex_);
  for (size_t idx = 0; idx < starts.size(); ++idx) {
    size_t begin = starts[idx];
    size_t header = begin + startCodeLen(data, begin, size);
    size_t end = (idx + 1 < starts.size()) ? starts[idx + 1] : size;
    if (header >= end) continue;
    uint8_t type = data[header] & 0x1F;
    if (type == 7) {
      info.has_sps = true;
      cached_sps_.assign(data + begin, data + end);
    } else if (type == 8) {
      info.has_pps = true;
      cached_pps_.assign(data + begin, data + end);
    } else if (type == 5) {
      info.has_idr = true;
    }
  }
  return info;
}

void Recorder::recordFrame(const Frame& frame, const NalInfo& nal) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!active_ || !video_.is_open()) return;

  if (wait_idr_) {
    if (!nal.has_idr) return;
    if (!cached_sps_.empty()) video_.write(reinterpret_cast<const char*>(cached_sps_.data()), cached_sps_.size());
    if (!cached_pps_.empty()) video_.write(reinterpret_cast<const char*>(cached_pps_.data()), cached_pps_.size());
    wait_idr_ = false;
  }

  video_.write(reinterpret_cast<const char*>(frame.bytes.data()), frame.bytes.size());
  if (timestamps_.is_open()) {
    timestamps_ << frame_idx_++ << "," << frame.monotonic_ns << "," << frame.pts_ns << "," << frame.dts_ns
                << "," << frame.bytes.size() << "\n";
  }
}

}  // namespace holo
