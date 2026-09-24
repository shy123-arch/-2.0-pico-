#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace holo {

struct Config {
  std::string device = "/dev/video0";
  std::string input_format = "H264";
  std::string transport = "TCP";
  std::string listen_host = "0.0.0.0";
  int listen_port = 13579;
  int width = 720;
  int height = 1280;
  int fps = 30;
  int bitrate = 1500000;
  int transcode = 1;
  int output_width = 540;
  int output_height = 960;
  int output_fps = 25;
  int record_control_port = 13600;
  int udp_fragment = 1;
  int udp_mtu = 1200;
};

struct CameraRequest {
  int width = 0;
  int height = 0;
  int fps = 0;
  int bitrate = 0;
  int port = 0;
  std::string camera;
  std::string ip;
};

struct Frame {
  std::vector<uint8_t> bytes;
  uint64_t monotonic_ns = 0;
  int64_t pts_ns = -1;
  int64_t dts_ns = -1;
  uint64_t seq = 0;
};

struct NalInfo {
  bool has_sps = false;
  bool has_pps = false;
  bool has_idr = false;
};

uint64_t monotonicNs();
int envInt(const char* name, int fallback);
std::string envStr(const char* name, const std::string& fallback);
Config loadConfigFromEnv();

}  // namespace holo
