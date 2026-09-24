#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

actual_human_height="${ACTUAL_HUMAN_HEIGHT:-1.6}"
retarget_fps="${RETARGET_FPS:-60}"
lookback_ms="${LOOKBACK_MS:-25}"
log_interval_s="${LOG_INTERVAL_S:-3}"
pico_record_output_dir="${PICO_RECORD_OUTPUT_DIR:-}"
gmr_record_output_dir="${GMR_RECORD_OUTPUT_DIR:-}"
pico_record_auto_start="${PICO_RECORD_AUTO_START:-0}"
pico_record_enable_buttons="${PICO_RECORD_ENABLE_BUTTONS:-1}"
pico_record_disable_buttons="${PICO_RECORD_DISABLE_BUTTONS:-0}"
pico_record_disable_keyboard="${PICO_RECORD_DISABLE_KEYBOARD:-0}"
pico_record_include_snapshot_json="${PICO_RECORD_INCLUDE_SNAPSHOT_JSON:-0}"
record_status_interval_s="${RECORD_STATUS_INTERVAL_S:-5}"
debug_log_file="${DEBUG_LOG_FILE:-}"
debug_warning_interval_s="${DEBUG_WARNING_INTERVAL_S:-3}"
debug_retarget_stall_warn_ms="${DEBUG_RETARGET_STALL_WARN_MS:-500}"
debug_raw_fresh_ms="${DEBUG_RAW_FRESH_MS:-200}"
debug_reply_process_warn_ms="${DEBUG_REPLY_PROCESS_WARN_MS:-50}"
debug_pico_callback_warn_ms="${DEBUG_PICO_CALLBACK_WARN_MS:-100}"
debug_pico_health_interval_s="${DEBUG_PICO_HEALTH_INTERVAL_S:-3}"
udp_stream_host="${UDP_STREAM_HOST:-}"
udp_stream_port="${UDP_STREAM_PORT:-28704}"
udp_stream_fps="${UDP_STREAM_FPS:-50}"
udp_stream_qos="${UDP_STREAM_QOS:-1}"
visualize="${VISUALIZE:-1}"
vis_fps="${VIS_FPS:-5}"
record_log_only="${RECORD_LOG_ONLY:-}"
tiny2_head_follow_host="${TINY2_HEAD_FOLLOW_HOST:-}"
tiny2_head_follow_port="${TINY2_HEAD_FOLLOW_PORT:-29900}"
tiny2_head_follow_rate_hz="${TINY2_HEAD_FOLLOW_RATE_HZ:-30}"
tiny2_head_follow_yaw_gain="${TINY2_HEAD_FOLLOW_YAW_GAIN:-1.0}"
tiny2_head_follow_pitch_gain="${TINY2_HEAD_FOLLOW_PITCH_GAIN:-1.0}"
tiny2_head_follow_yaw_offset="${TINY2_HEAD_FOLLOW_YAW_OFFSET:-0.0}"
tiny2_head_follow_pitch_offset="${TINY2_HEAD_FOLLOW_PITCH_OFFSET:-0.0}"
tiny2_head_forward_axis="${TINY2_HEAD_FORWARD_AXIS:-z}"

if [[ -z "${record_log_only}" ]]; then
    if [[ -n "${pico_record_output_dir}" ]]; then
        record_log_only="1"
    else
        record_log_only="0"
    fi
fi

if [[ -n "${pico_record_output_dir}" && -z "${gmr_record_output_dir}" ]]; then
    gmr_record_output_dir="$(dirname "${pico_record_output_dir}")/gmr_records"
fi

cmd=(
    python -u xrobot_teleop_to_pose_zmq_server.py
    --robot unitree_g1
    --actual_human_height "${actual_human_height}"
    --ctrl_fps 50
    --retarget_fps "${retarget_fps}"
    --lookback_ms "${lookback_ms}"
    --retarget_buffer_window_s 0.5
    --log_interval_s "${log_interval_s}"
    --debug_warning_interval_s "${debug_warning_interval_s}"
    --debug_retarget_stall_warn_ms "${debug_retarget_stall_warn_ms}"
    --debug_raw_fresh_ms "${debug_raw_fresh_ms}"
    --debug_reply_process_warn_ms "${debug_reply_process_warn_ms}"
    --debug_pico_callback_warn_ms "${debug_pico_callback_warn_ms}"
    --debug_pico_health_interval_s "${debug_pico_health_interval_s}"
    --req_bind_addr tcp://*:28701
    --rep_bind_addr tcp://*:28702
    --ctrl_bind_addr tcp://*:28703
    --udp_stream_host "${udp_stream_host}"
    --udp_stream_port "${udp_stream_port}"
    --udp_stream_fps "${udp_stream_fps}"
    --min_link_height 0.0
    --min_link_height_align_strategy startup_fixed
    --min_link_height_bootstrap_frames 10
)

if [[ "${udp_stream_qos}" == "1" ]]; then
    cmd+=(--udp_stream_qos)
else
    cmd+=(--no-udp_stream_qos)
fi

if [[ "${visualize}" == "1" ]]; then
    cmd+=(--visualize)
    cmd+=(--vis_fps "${vis_fps}")
fi

if [[ -n "${debug_log_file}" ]]; then
    cmd+=(--debug_log_file "${debug_log_file}")
fi

if [[ -n "${pico_record_output_dir}" ]]; then
    cmd+=(--pico_record_output_dir "${pico_record_output_dir}")
    cmd+=(--record_status_interval_s "${record_status_interval_s}")
fi
if [[ -n "${gmr_record_output_dir}" ]]; then
    cmd+=(--gmr_record_output_dir "${gmr_record_output_dir}")
fi
if [[ "${pico_record_auto_start}" == "1" ]]; then
    cmd+=(--pico_record_auto_start)
fi
if [[ "${pico_record_enable_buttons}" == "1" ]]; then
    cmd+=(--pico_record_enable_buttons)
fi
if [[ "${pico_record_disable_buttons}" == "1" ]]; then
    cmd+=(--pico_record_disable_buttons)
fi
if [[ "${pico_record_disable_keyboard}" == "1" ]]; then
    cmd+=(--pico_record_disable_keyboard)
fi
if [[ "${pico_record_include_snapshot_json}" == "1" ]]; then
    cmd+=(--pico_record_include_snapshot_json)
fi
if [[ -n "${tiny2_head_follow_host}" ]]; then
    cmd+=(--tiny2_head_follow_host "${tiny2_head_follow_host}")
    cmd+=(--tiny2_head_follow_port "${tiny2_head_follow_port}")
    cmd+=(--tiny2_head_follow_rate_hz "${tiny2_head_follow_rate_hz}")
    cmd+=(--tiny2_head_follow_yaw_gain "${tiny2_head_follow_yaw_gain}")
    cmd+=(--tiny2_head_follow_pitch_gain "${tiny2_head_follow_pitch_gain}")
    cmd+=(--tiny2_head_follow_yaw_offset "${tiny2_head_follow_yaw_offset}")
    cmd+=(--tiny2_head_follow_pitch_offset "${tiny2_head_follow_pitch_offset}")
    cmd+=(--tiny2_head_forward_axis "${tiny2_head_forward_axis}")
fi

if [[ "${record_log_only}" == "1" ]]; then
    set +e
    "${cmd[@]}" "$@" 2>&1 | grep --line-buffered -E '^\[Recorder\]'
    status=${PIPESTATUS[0]}
    set -e
    exit "${status}"
fi

exec "${cmd[@]}" "$@"
