#pragma once

#include "common.hpp"
#include "recorder.hpp"

#include <condition_variable>
#include <gst/app/gstappsink.h>
#include <gst/gst.h>
#include <mutex>
#include <thread>

namespace holo {

class CameraStreamer {
 public:
  CameraStreamer(Config config, Recorder& recorder);
  ~CameraStreamer();

  bool start(const CameraRequest& request);
  void stop();
  bool active() const;

 private:
  static GstFlowReturn onSample(GstAppSink* sink, gpointer user_data);
  GstFlowReturn handleSample(GstAppSink* sink);

  std::string buildPipeline() const;
  bool connectStreamSocket(const std::string& host, int port);
  void senderLoop();
  bool sendAll(const uint8_t* data, size_t size);
  bool sendFramePacket(const Frame& frame);
  bool udpTransport() const;
  void updateStats(const Frame& frame, size_t packet_count);

  Config config_;
  Recorder& recorder_;
  bool active_ = false;
  int stream_fd_ = -1;
  GstElement* pipeline_ = nullptr;
  std::thread sender_thread_;

  std::mutex latest_mutex_;
  std::condition_variable latest_cv_;
  Frame latest_frame_;
  uint64_t latest_seq_ = 0;
  uint64_t stats_last_ns_ = 0;
  uint64_t stats_frames_ = 0;
  uint64_t stats_bytes_ = 0;
  uint64_t stats_packets_ = 0;
  size_t stats_max_frame_bytes_ = 0;
};

}  // namespace holo
