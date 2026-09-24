#include "common.hpp"

#include <cstdlib>
#include <ctime>

namespace holo {

uint64_t monotonicNs() {
  timespec ts{};
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return uint64_t(ts.tv_sec) * 1000000000ULL + uint64_t(ts.tv_nsec);
}

int envInt(const char* name, int fallback) {
  const char* value = std::getenv(name);
  if (!value || !*value) return fallback;
  try {
    return std::stoi(value);
  } catch (...) {
    return fallback;
  }
}

std::string envStr(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return (value && *value) ? std::string(value) : fallback;
}

Config loadConfigFromEnv() {
  Config cfg;
  cfg.device = envStr("CAMERA_DEVICE", envStr("WEBCAM_DEVICE", cfg.device));
  cfg.input_format = envStr("CAMERA_INPUT_FORMAT", envStr("WEBCAM_INPUT_FORMAT", cfg.input_format));
  cfg.transport = envStr("CAMERA_TRANSPORT", envStr("WEBCAM_TRANSPORT", cfg.transport));
  cfg.width = envInt("CAMERA_WIDTH", envInt("WEBCAM_WIDTH", cfg.width));
  cfg.height = envInt("CAMERA_HEIGHT", envInt("WEBCAM_HEIGHT", cfg.height));
  cfg.fps = envInt("CAMERA_FPS", envInt("WEBCAM_FPS", cfg.fps));
  cfg.bitrate = envInt("CAMERA_BITRATE", envInt("WEBCAM_BITRATE", cfg.bitrate));
  cfg.transcode = envInt("CAMERA_TRANSCODE", envInt("WEBCAM_TRANSCODE", cfg.transcode));
  cfg.output_width = envInt("CAMERA_OUTPUT_WIDTH", envInt("WEBCAM_OUTPUT_WIDTH", cfg.output_width));
  cfg.output_height = envInt("CAMERA_OUTPUT_HEIGHT", envInt("WEBCAM_OUTPUT_HEIGHT", cfg.output_height));
  cfg.output_fps = envInt("CAMERA_OUTPUT_FPS", envInt("WEBCAM_OUTPUT_FPS", cfg.output_fps));
  cfg.listen_port = envInt("CAMERA_CONTROL_PORT", cfg.listen_port);
  cfg.record_control_port = envInt("RECORD_CONTROL_PORT", cfg.record_control_port);
  cfg.udp_fragment = envInt("CAMERA_UDP_FRAGMENT", envInt("WEBCAM_UDP_FRAGMENT", cfg.udp_fragment));
  cfg.udp_mtu = envInt("CAMERA_UDP_MTU", envInt("WEBCAM_UDP_MTU", cfg.udp_mtu));
  return cfg;
}

}  // namespace holo
