#!/usr/bin/env bash
set -euo pipefail

: "${TIANYI_CONFIG:?Set TIANYI_CONFIG to an absolute YAML path}"
if [[ -f "$HOME/xos/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/xos/setup.bash"
fi
exec robot_node --config "$TIANYI_CONFIG" "$@"

