"""Validate a Tianyi configuration without starting ROS or opening a socket."""

from __future__ import annotations

import argparse

from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--hardware", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    config.validate(for_hardware=args.hardware)
    mode = "hardware" if args.hardware else "dry-run"
    print(f"OK: {args.config} is valid for {mode}")


if __name__ == "__main__":
    main()

