#include "protocol.hpp"

#include <stdexcept>

namespace holo {

namespace {

int32_t readI32LE(const std::vector<uint8_t>& data, size_t offset) {
  if (offset + 4 > data.size()) throw std::runtime_error("int32 out of range");
  return int32_t(uint32_t(data[offset]) | (uint32_t(data[offset + 1]) << 8) |
                 (uint32_t(data[offset + 2]) << 16) | (uint32_t(data[offset + 3]) << 24));
}

std::string readCompactString(const std::vector<uint8_t>& data, size_t& offset) {
  if (offset >= data.size()) throw std::runtime_error("string length out of range");
  size_t length = data[offset++];
  if (offset + length > data.size()) throw std::runtime_error("string data out of range");
  std::string out(reinterpret_cast<const char*>(&data[offset]), length);
  offset += length;
  return out;
}

}  // namespace

std::string parseControlPacket(const std::vector<uint8_t>& packet, std::vector<uint8_t>& payload) {
  if (packet.size() < 8) throw std::runtime_error("control packet too small");
  size_t offset = 0;
  int32_t command_len = readI32LE(packet, offset);
  offset += 4;
  if (command_len < 0 || offset + size_t(command_len) + 4 > packet.size()) {
    throw std::runtime_error("invalid command length");
  }
  std::string command(reinterpret_cast<const char*>(packet.data() + offset), size_t(command_len));
  size_t nul = command.find('\0');
  if (nul != std::string::npos) command.resize(nul);
  offset += size_t(command_len);

  int32_t data_len = readI32LE(packet, offset);
  offset += 4;
  if (data_len < 0 || offset + size_t(data_len) > packet.size()) {
    throw std::runtime_error("invalid payload length");
  }
  payload.assign(packet.begin() + offset, packet.begin() + offset + data_len);
  return command;
}

bool tryParseControlPacket(
    const std::vector<uint8_t>& buffer,
    size_t& consumed,
    std::string& command,
    std::vector<uint8_t>& payload) {
  consumed = 0;
  command.clear();
  payload.clear();
  if (buffer.size() < 4) return false;

  uint32_t body_len = (uint32_t(buffer[0]) << 24) | (uint32_t(buffer[1]) << 16) |
                      (uint32_t(buffer[2]) << 8) | uint32_t(buffer[3]);
  if (body_len == 0 || body_len > 1024 * 1024) {
    throw std::runtime_error("invalid wrapped payload length");
  }
  if (buffer.size() < 4 + size_t(body_len)) return false;

  std::vector<uint8_t> body(buffer.begin() + 4, buffer.begin() + 4 + size_t(body_len));

  size_t offset = 0;
  int32_t command_len = readI32LE(body, offset);
  offset += 4;
  if (command_len < 0 || command_len > 1024) {
    throw std::runtime_error("invalid command length");
  }
  if (offset + size_t(command_len) + 4 > body.size()) {
    throw std::runtime_error("truncated command frame");
  }

  command.assign(reinterpret_cast<const char*>(body.data() + offset), size_t(command_len));
  size_t nul = command.find('\0');
  if (nul != std::string::npos) command.resize(nul);
  offset += size_t(command_len);

  int32_t data_len = readI32LE(body, offset);
  offset += 4;
  if (data_len < 0 || data_len > 1024 * 1024) {
    throw std::runtime_error("invalid payload length");
  }
  if (offset + size_t(data_len) > body.size()) {
    throw std::runtime_error("truncated payload frame");
  }

  payload.assign(body.begin() + offset, body.begin() + offset + data_len);
  consumed = 4 + size_t(body_len);
  return true;
}

CameraRequest parseCameraRequest(const std::vector<uint8_t>& data) {
  if (data.size() < 32 || data[0] != 0xCA || data[1] != 0xFE || data[2] != 1) {
    throw std::runtime_error("invalid camera request");
  }
  size_t offset = 3;
  CameraRequest req;
  req.width = readI32LE(data, offset + 0);
  req.height = readI32LE(data, offset + 4);
  req.fps = readI32LE(data, offset + 8);
  req.bitrate = readI32LE(data, offset + 12);
  req.port = readI32LE(data, offset + 24);
  offset += 28;
  req.camera = readCompactString(data, offset);
  req.ip = readCompactString(data, offset);
  return req;
}

}  // namespace holo
