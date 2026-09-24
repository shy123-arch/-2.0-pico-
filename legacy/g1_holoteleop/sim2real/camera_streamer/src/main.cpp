#include "common.hpp"
#include "protocol.hpp"
#include "recorder.hpp"
#include "streamer.hpp"

#include <arpa/inet.h>
#include <gst/gst.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <cstring>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>

namespace {

std::atomic<bool> stop_requested{false};
holo::Recorder* global_recorder = nullptr;
holo::CameraStreamer* global_streamer = nullptr;

void onSignal(int) {
  stop_requested = true;
  if (global_streamer) global_streamer->stop();
  if (global_recorder) global_recorder->stop();
}

int createListenSocket(int port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) return -1;
  int yes = 1;
  setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = INADDR_ANY;
  addr.sin_port = htons(uint16_t(port));
  if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
    close(fd);
    return -1;
  }
  if (listen(fd, 4) != 0) {
    close(fd);
    return -1;
  }
  return fd;
}

void recordControlLoop(const holo::Config& config, holo::Recorder& recorder) {
  int fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) {
    std::cerr << "record control socket failed: " << strerror(errno) << "\n";
    return;
  }
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  addr.sin_port = htons(uint16_t(config.record_control_port));
  if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
    std::cerr << "record control bind failed: " << strerror(errno) << "\n";
    close(fd);
    return;
  }
  std::cout << "Record control listening on 127.0.0.1:" << config.record_control_port << "\n";

  char buf[4096];
  while (!stop_requested) {
    ssize_t n = recv(fd, buf, sizeof(buf) - 1, 0);
    if (n <= 0) continue;
    buf[n] = '\0';
    std::string msg(buf);
    if (msg.rfind("START ", 0) == 0) {
      recorder.start(msg.substr(6));
    } else if (msg == "STOP") {
      recorder.stop();
    }
  }
  close(fd);
}

void wakeRecordThread(int port) {
  int fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) return;
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  addr.sin_port = htons(uint16_t(port));
  sendto(fd, "STOP", 4, 0, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
  close(fd);
}

void controlLoop(const holo::Config& config, holo::CameraStreamer& streamer) {
  int server_fd = createListenSocket(config.listen_port);
  if (server_fd < 0) {
    std::cerr << "control listen failed: " << strerror(errno) << "\n";
    return;
  }
  std::cout << "Camera control listening on " << config.listen_host << ":" << config.listen_port << "\n";

  while (!stop_requested) {
    sockaddr_in client_addr{};
    socklen_t len = sizeof(client_addr);
    int fd = accept(server_fd, reinterpret_cast<sockaddr*>(&client_addr), &len);
    if (fd < 0) continue;

    char ip[INET_ADDRSTRLEN] = {};
    inet_ntop(AF_INET, &client_addr.sin_addr, ip, sizeof(ip));
    std::cout << "Control client connected: " << ip << ":" << ntohs(client_addr.sin_port) << "\n";

    std::vector<uint8_t> buf(4096);
    std::vector<uint8_t> pending;
    while (!stop_requested) {
      ssize_t n = recv(fd, buf.data(), buf.size(), 0);
      if (n <= 0) break;
      pending.insert(pending.end(), buf.begin(), buf.begin() + n);
      try {
        while (true) {
          size_t consumed = 0;
          std::string command;
          std::vector<uint8_t> payload;
          if (!holo::tryParseControlPacket(pending, consumed, command, payload)) break;
          pending.erase(pending.begin(), pending.begin() + consumed);

        if (command == "OPEN_CAMERA") {
          holo::CameraRequest request = holo::parseCameraRequest(payload);
          std::cout << "OPEN_CAMERA -> " << request.camera << " " << request.width << "x" << request.height
                    << "@" << request.fps << " " << request.ip << ":" << request.port << "\n";
          streamer.start(request);
        } else if (command == "CLOSE_CAMERA") {
          streamer.stop();
        } else {
          std::cout << "Unknown command: " << command << "\n";
        }
        }
      } catch (const std::exception& exc) {
        std::cerr << "control packet error: " << exc.what() << "\n";
        pending.clear();
      }
    }
    close(fd);
    streamer.stop();
    std::cout << "Control client disconnected\n";
  }
  close(server_fd);
}

}  // namespace

int main(int argc, char** argv) {
  gst_init(&argc, &argv);
  holo::Config config = holo::loadConfigFromEnv();

  holo::Recorder recorder;
  holo::CameraStreamer streamer(config, recorder);
  global_recorder = &recorder;
  global_streamer = &streamer;

  signal(SIGINT, onSignal);
  signal(SIGTERM, onSignal);

  std::cout << "HoloTeleop camera streamer\n"
            << "  device: " << config.device << "\n"
            << "  listen: " << config.listen_host << ":" << config.listen_port << "\n"
            << "  default: " << config.width << "x" << config.height << "@" << config.fps << " "
            << config.input_format << "\n"
            << "  transport: " << config.transport << "\n"
            << "  udp_fragment: " << config.udp_fragment << ", udp_mtu: " << config.udp_mtu << "\n"
            << "  bitrate: " << config.bitrate << "\n";

  std::thread record_thread(recordControlLoop, std::cref(config), std::ref(recorder));
  controlLoop(config, streamer);

  stop_requested = true;
  streamer.stop();
  recorder.stop();
  wakeRecordThread(config.record_control_port);
  if (record_thread.joinable()) record_thread.join();
  return 0;
}
