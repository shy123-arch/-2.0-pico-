#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_ as LowCmdHG
from unitree_sdk2py.utils.crc import CRC

from common.command_helper import MotorMode, create_zero_cmd, init_cmd_hg


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish zero low-level commands to G1.")
    parser.add_argument("--net", default="eth0")
    parser.add_argument("--topic", default="rt/lowcmd")
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--rate", type=float, default=50.0)
    args = parser.parse_args()

    ChannelFactoryInitialize(0, args.net)
    publisher = ChannelPublisher(args.topic, LowCmdHG)
    publisher.Init()

    cmd = unitree_hg_msg_dds__LowCmd_()
    init_cmd_hg(cmd, 0, MotorMode.PR)
    create_zero_cmd(cmd)

    period = 1.0 / max(args.rate, 1.0)
    deadline = time.monotonic() + max(args.duration, 0.0)
    count = 0
    while time.monotonic() < deadline:
        cmd.crc = CRC().Crc(cmd)
        publisher.Write(cmd)
        count += 1
        time.sleep(period)

    print(f"sent zero lowcmd: count={count}, duration={args.duration:.2f}s, net={args.net}, topic={args.topic}")


if __name__ == "__main__":
    main()
