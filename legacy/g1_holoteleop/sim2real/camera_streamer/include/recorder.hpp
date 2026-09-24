#pragma once

#include "common.hpp"

#include <fstream>
#include <mutex>
#include <string>
#include <vector>

namespace holo {

class Recorder {
 public:
  void start(const std::string& session_dir);
  void stop();
  NalInfo inspectAndCacheH264(const uint8_t* data, size_t size);
  void recordFrame(const Frame& frame, const NalInfo& nal);

 private:
  void stopLocked();

  std::mutex mutex_;
  bool active_ = false;
  bool wait_idr_ = true;
  uint64_t frame_idx_ = 0;
  std::string session_dir_;
  std::ofstream video_;
  std::ofstream timestamps_;
  std::vector<uint8_t> cached_sps_;
  std::vector<uint8_t> cached_pps_;
};

}  // namespace holo
