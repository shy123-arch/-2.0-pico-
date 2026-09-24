#pragma once

#include "common.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace holo {

std::string parseControlPacket(const std::vector<uint8_t>& packet, std::vector<uint8_t>& payload);
CameraRequest parseCameraRequest(const std::vector<uint8_t>& data);
bool tryParseControlPacket(
    const std::vector<uint8_t>& buffer,
    size_t& consumed,
    std::string& command,
    std::vector<uint8_t>& payload);

}  // namespace holo
