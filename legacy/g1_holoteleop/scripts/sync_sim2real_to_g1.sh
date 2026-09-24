#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOLO_ROOT:-/media/william/play/molospace/HoloTeleop-deploy/HoloTeleop}"
LOCAL_SIM2REAL="${LOCAL_SIM2REAL:-${ROOT}/sim2real}"
REMOTE_HOST="${REMOTE_HOST:-unitree@172.18.26.133}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/unitree/HoloTeleop/sim2real}"

echo "[sync] local:  ${LOCAL_SIM2REAL}/"
echo "[sync] remote: ${REMOTE_HOST}:${REMOTE_ROOT}/"

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_ROOT}'"

rsync -av \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  --exclude '.ruff_cache' \
  --exclude 'teleop/teleop_records' \
  "${LOCAL_SIM2REAL}/" \
  "${REMOTE_HOST}:${REMOTE_ROOT}/"

echo "[sync] done"
