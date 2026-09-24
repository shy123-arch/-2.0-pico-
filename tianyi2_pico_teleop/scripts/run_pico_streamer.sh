#!/usr/bin/env bash
set -euo pipefail

: "${TIANYI_IP:?Set TIANYI_IP to the Tianyi robot computer address}"
PICO_UDP_PORT="${PICO_UDP_PORT:-28810}"
exec pico_streamer --host "$TIANYI_IP" --port "$PICO_UDP_PORT" "$@"

