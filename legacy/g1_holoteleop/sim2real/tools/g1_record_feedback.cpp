#include <iostream>
#include <string>
#include <thread>

#include <unitree/common/time/time_tool.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/audio/g1_audio_client.hpp>

namespace {

void sleep_ms(int ms) {
  unitree::common::Sleep(static_cast<double>(ms) / 1000.0);
}

int set_led(unitree::robot::g1::AudioClient& client, uint8_t r, uint8_t g, uint8_t b) {
  int ret = client.LedControl(r, g, b);
  if (ret != 0) {
    std::cerr << "LedControl failed: " << ret << std::endl;
  }
  return ret;
}

void say(unitree::robot::g1::AudioClient& client, const std::string& text) {
  int ret = client.TtsMaker(text, 0);
  if (ret != 0) {
    std::cerr << "TtsMaker failed: " << ret << std::endl;
  }
}

void start_feedback(unitree::robot::g1::AudioClient& client, bool tts) {
  set_led(client, 255, 0, 0);
  if (tts) {
    say(client, "开始录制");
  }
}

void stop_feedback(unitree::robot::g1::AudioClient& client, bool tts) {
  set_led(client, 0, 0, 255);
  if (tts) {
    say(client, "结束录制");
  }
  sleep_ms(400);
  set_led(client, 0, 0, 0);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "Usage: g1_record_feedback <net> <start|stop|test|say> [text...] [--no-tts]" << std::endl;
    return 2;
  }

  const std::string net = argv[1];
  const std::string mode = argv[2];
  bool tts = true;
  std::string say_text;
  for (int i = 3; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--no-tts") {
      tts = false;
    } else {
      if (!say_text.empty()) {
        say_text += " ";
      }
      say_text += arg;
    }
  }

  unitree::robot::ChannelFactory::Instance()->Init(0, net);
  unitree::robot::g1::AudioClient client;
  client.Init();
  client.SetTimeout(1.0f);

  if (mode == "start") {
    start_feedback(client, tts);
  } else if (mode == "stop") {
    stop_feedback(client, tts);
  } else if (mode == "test") {
    start_feedback(client, tts);
    sleep_ms(1200);
    stop_feedback(client, tts);
  } else if (mode == "say") {
    if (say_text.empty()) {
      std::cerr << "say mode requires text" << std::endl;
      return 2;
    }
    if (tts) {
      say(client, say_text);
    }
  } else {
    std::cerr << "Unknown mode: " << mode << std::endl;
    return 2;
  }

  return 0;
}
