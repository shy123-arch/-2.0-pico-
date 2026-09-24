import os
import json
import socket
import sys
import time
import yaml
from multiprocessing import Process, Value
from typing import Dict, Optional

import numpy as np

from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_, unitree_hg_msg_dds__LowState_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_ as LowCmdHG
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_ as LowStateHG
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
from unitree_sdk2py.utils.crc import CRC
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
from unitree_sdk2py.go2.robot_state.robot_state_client import RobotStateClient

from common.command_helper import create_damping_cmd, create_zero_cmd, init_cmd_hg, MotorMode
from common.remote_controller import RemoteController, KeyMap
from common.utils import DictToClass, Timer
from common.joint_mapper import create_isaac_to_real_mapper
from common.dex3_hand import Dex3HandCommandPublisher, get_hand_pose, hand_pose_from_vr_controls

from policy import Policy, TrackingPolicyRaw
from record_control import VideoRecordControlClient
from robot_feedback import RobotAudioFeedback
from session_recorder import SessionRecorder
from pathlib import Path
from paths import REAL_G1_ROOT

np.set_printoptions(formatter={'float': lambda x: "{0:0.2f}".format(x)})


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def enable_debug_log_file(path: str):
    if not str(path).strip():
        return
    log_path = Path(path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", buffering=1)
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)
    print(f"[DebugLog] tee stdout/stderr -> {log_path}")


class PicoTelemetryPublisher:
    def __init__(self, host: str, port: int, rate_hz: float):
        self.host = str(host or "").strip()
        self.port = int(port)
        self.period_s = 1.0 / float(rate_hz) if float(rate_hz) > 0.0 else 0.0
        self._last_send = 0.0
        self._sock = None
        if self.host and self.port > 0 and self.period_s > 0.0:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setblocking(False)
            print(f"[PicoTelemetry] UDP enabled -> {self.host}:{self.port} @ {float(rate_hz):.1f}Hz")

    @property
    def enabled(self) -> bool:
        return self._sock is not None

    def maybe_send(self, payload: dict, force: bool = False) -> None:
        if self._sock is None:
            return
        now = time.monotonic()
        if not force and now - self._last_send < self.period_s:
            return
        self._last_send = now
        try:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            self._sock.sendto(data, (self.host, self.port))
        except Exception as exc:
            print(f"[PicoTelemetry][Warning] send failed: {exc}")

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

def get_config(policy_cfg_path: str) -> DictToClass:
    policy_cfg_path = Path(policy_cfg_path)
    if not policy_cfg_path.is_absolute():
        policy_cfg_path = REAL_G1_ROOT / policy_cfg_path
    with open(str(policy_cfg_path), 'r') as f:
        policy_cfg = DictToClass(yaml.load(f, Loader=yaml.FullLoader))
    return policy_cfg

class Controller:
    def __init__(self, args, ctrl_cfg):
        self.args = args
        self.config = ctrl_cfg
        self.remote_controller = RemoteController()
        self.control_dt = 1.0 / self.config.control_freq
        self.debug_log_interval_s = float(getattr(args, "debug_log_interval_s", 1.0))
        self.control_health_log_interval_s = float(getattr(args, "control_health_log_interval_s", 0.5))
        self.service_health_log_interval_s = float(getattr(args, "service_health_log_interval_s", 2.0))
        self._last_debug_log: Dict[str, float] = {}
        self._last_control_health_monotonic: Optional[float] = None
        self._last_control_health_q: Optional[np.ndarray] = None
        self._last_control_health_cmd_q: Optional[np.ndarray] = None
        self._last_service_health_monotonic: Optional[float] = None
        self._robot_state_client: Optional[RobotStateClient] = None
        self._motion_switcher_client: Optional[MotionSwitcherClient] = None

        self.isaac_to_real_mapper_state = create_isaac_to_real_mapper(
            self.config.isaac_joint_names_state,
            self.config.real_joint_names
        )
        m_info = self.isaac_to_real_mapper_state.get_mapping_info()
        print(f"[Controller] State mapping: {m_info['mapped_joints']}/{m_info['from_space_size']} mapped")

        if bool(getattr(args, "real", False)):
            self._prepare_low_level_control()

        self.dof_size_real = len(self.config.real_joint_names)

        self.qj_real = np.zeros(self.dof_size_real, dtype=np.float32)
        self.dqj_real = np.zeros(self.dof_size_real, dtype=np.float32)
        self.tau_real = np.zeros(self.dof_size_real, dtype=np.float32)
        self.motor_mode_real = np.zeros(self.dof_size_real, dtype=np.int32)
        self.motor_state_real = np.zeros(self.dof_size_real, dtype=np.int32)
        self.motor_temp_real = np.zeros((self.dof_size_real, 2), dtype=np.int32)
        self.motor_reserve_real = np.zeros((self.dof_size_real, 4), dtype=np.int32)
        self.motor_vol_real = np.zeros(self.dof_size_real, dtype=np.float32)
        self.quat = np.zeros(4, dtype=np.float32)
        self.gyro = np.zeros(3, dtype=np.float32)
        self.linacc = np.zeros(3, dtype=np.float32)
        self.root_pos_w = None
        self.root_quat_w = None
        self.root_vel_w = np.zeros(3, dtype=np.float32)
        self.root_yaw_speed = 0.0
        self._odom_origin_xy = None
        self._odom_latest_position_w = None
        self._odom_seen = False

        self.qj_isaac = None
        self.dqj_isaac = None
        self.tau_isaac = None

        self.default_qpos_real = np.array(self.config.default_qpos_real, dtype=np.float32)
        self.init_qpos_real    = np.array(self.config.init_qpos_real, dtype=np.float32)
        self.kps_real          = np.array(self.config.kps_real, dtype=np.float32)
        self.kds_real          = np.array(self.config.kds_real, dtype=np.float32)
        self.dof_size_real = len(self.default_qpos_real)

        self.counter = 0
        self.policy_step = 0
        self.is_alive = True
        self._shutdown_reason = "normal"
        self.current_policy: Optional[Policy] = None
        self.pending_policy: Optional[Policy] = None
        self._low_state_miss_count = 0
        self._low_state_last_ok_monotonic: Optional[float] = None
        self._last_remote_keys = None
        self._select_down_since: Optional[float] = None
        self._select_hold_exit_s = float(getattr(args, "select_hold_exit_s", 0.2))
        self._qerr_limit_enabled = not bool(getattr(args, "disable_qerr_limit", False))
        self._qerr_limit_default = float(getattr(args, "qerr_limit", 1.8))
        self._qerr_limit_waist = float(getattr(args, "waist_qerr_limit", 1.2))
        self._qerr_limit_waist_pitch = float(getattr(args, "waist_pitch_qerr_limit", 0.5))
        self._qerr_limits = self._build_qerr_limits()
        self.pico_telemetry = PicoTelemetryPublisher(
            getattr(args, "pico_telemetry_host", ""),
            int(getattr(args, "pico_telemetry_port", 13601)),
            float(getattr(args, "pico_telemetry_rate_hz", 5.0)),
        )

        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.low_state = unitree_hg_msg_dds__LowState_()
        self.mode_pr_ = MotorMode.PR
        self.mode_machine_ = 0

        self.lowcmd_publisher_ = ChannelPublisher(self.config.lowcmd_topic, LowCmdHG)
        self.lowcmd_publisher_.Init()
        self.dex3_hand_publisher = None
        self.dex3_left_q = None
        self.dex3_right_q = None
        self.dex3_teleop_hands = bool(getattr(args, "dex3_teleop_hands", False))
        if getattr(args, "enable_dex3_hands", False):
            self.dex3_left_q, self.dex3_right_q = get_hand_pose(args.dex3_hand_pose)
            self.dex3_hand_publisher = Dex3HandCommandPublisher()
            print(
                f"[Controller] Dex3 hands enabled | pose={args.dex3_hand_pose} "
                f"teleop={self.dex3_teleop_hands}"
            )

        self.lowstate_subscriber = ChannelSubscriber(self.config.lowstate_topic, LowStateHG)
        self.lowstate_subscriber.Init()
        self.odom_subscriber = ChannelSubscriber("rt/odommodestate", SportModeState_)
        self.odom_subscriber.Init()

        self.loop_count = Value('i', 0)
        self.p_loop_rate = Process(target=self.count_loop_rate, args=(self.loop_count,), daemon=True)

        self.wait_for_low_state()
        init_cmd_hg(self.low_cmd, self.mode_machine_, self.mode_pr_)

        tracking_cfg = get_config("config/tracking.yaml")
        if getattr(args, "policy_path", None):
            tracking_cfg.policy_path = str(Path(args.policy_path).expanduser())
            print(f"[deploy] Overriding policy_path -> '{tracking_cfg.policy_path}'")
        if getattr(args, "motion_source", None):
            tracking_cfg.motion_source = str(args.motion_source)
            print(f"[deploy] Overriding motion_source -> '{tracking_cfg.motion_source}'")
        tracking_policy = TrackingPolicyRaw("tracking", tracking_cfg, self)
        self.policies = {
            "tracking": tracking_policy,
        }

        self.session_recording_enabled = not bool(getattr(args, "disable_session_recording", False))
        self.recording_root = Path(getattr(args, "recording_root", "/mnt/nexus/workspace/recordings")).expanduser()
        self.session_recorder = SessionRecorder()
        self.session_record_start_buttons = self._parse_button_combo(
            getattr(args, "session_record_start_buttons", "right_axis_click")
        )
        self.session_record_stop_buttons = self._parse_button_combo(
            getattr(args, "session_record_stop_buttons", "left_axis_click")
        )
        self.video_record_control = VideoRecordControlClient(
            getattr(args, "video_record_control_host", "127.0.0.1"),
            int(getattr(args, "video_record_control_port", 13600)),
        )
        self.record_feedback = RobotAudioFeedback(
            enabled=not bool(getattr(args, "disable_record_audio_feedback", False)),
            net=args.net,
            unitree_tool=str(Path(__file__).resolve().parents[1] / "tools" / "g1_record_feedback"),
        )
        self.temperature_feedback = RobotAudioFeedback(
            enabled=(
                bool(getattr(args, "real", False))
                and bool(getattr(args, "enable_temperature_audio_warning", False))
                and not bool(getattr(args, "disable_temperature_audio_warning", False))
            ),
            net=args.net,
            unitree_tool=str(Path(__file__).resolve().parents[1] / "tools" / "g1_record_feedback"),
        )
        self.temperature_audio_warning_enabled = self.temperature_feedback.enabled
        self.temperature_audio_warning_threshold_c = float(
            getattr(args, "temperature_audio_warning_threshold_c", 100.0)
        )
        self.temperature_audio_warning_clear_c = float(
            getattr(args, "temperature_audio_warning_clear_c", 95.0)
        )
        self.temperature_audio_warning_cooldown_s = float(
            getattr(args, "temperature_audio_warning_cooldown_s", 10.0)
        )
        self.temperature_audio_warning_message = str(
            getattr(args, "temperature_audio_warning_message", "Warning! High temperature")
        )
        self._temperature_audio_warning_active = False
        self._last_temperature_audio_warning_monotonic = 0.0

        self._prev_buttons = None
        self.btn_rise = None
        self.btn_fall = None
        self._prev_vr_record_start = False
        self._prev_vr_record_stop = False

    @staticmethod
    def _button_names(buttons) -> list[str]:
        names = [
            "R1", "L1", "start", "select", "R2", "L2", "F1", "F2",
            "A", "B", "X", "Y", "up", "right", "down", "left",
        ]
        return [names[i] for i, v in enumerate(buttons) if int(v) == 1]

    def _prepare_low_level_control(self):
        self._disable_high_level_services(verbose=True)
        self._release_motion_mode()

    def _disable_high_level_services(self, verbose: bool = True):
        try:
            client = RobotStateClient()
            client.SetTimeout(1.0)
            client.Init()
            code, services = client.ServiceList()
            if code != 0 or services is None:
                if verbose:
                    print(f"[Controller][Warning] RobotState ServiceList failed: code={code}")
                return
            blocking_services = {"ai_sport", "sport_mode"}
            for service in services:
                is_active = int(service.status) == 1
                if service.name not in blocking_services:
                    continue
                if verbose:
                    print(
                        f"[Controller] High-level service '{service.name}': "
                        f"status={service.status}, protect={service.protect}"
                    )
                if is_active:
                    switch_code = client.ServiceSwitch(service.name, False)
                    if verbose:
                        print(f"[Controller] Disable high-level service '{service.name}': code={switch_code}")
        except Exception as exc:
            if verbose:
                print(f"[Controller][Warning] Failed to disable high-level services: {exc}")

    def _release_motion_mode(self):
        try:
            client = MotionSwitcherClient()
            client.SetTimeout(1.0)
            client.Init()
            code, mode = client.CheckMode()
            mode_name = ""
            mode_form = ""
            if isinstance(mode, dict):
                mode_name = str(mode.get("name", "") or "")
                mode_form = str(mode.get("form", "") or mode.get("mode", "") or "")
            print(f"[Controller] Motion mode check: status={code}, name='{mode_name}', form='{mode_form}'")
            if code == 0 and mode_name:
                release_code, _ = client.ReleaseMode()
                print(f"[Controller] Release motion mode '{mode_name}': status={release_code}")
                for _ in range(10):
                    time.sleep(0.1)
                    code, mode = client.CheckMode()
                    mode_name = ""
                    mode_form = ""
                    if isinstance(mode, dict):
                        mode_name = str(mode.get("name", "") or "")
                        mode_form = str(mode.get("form", "") or mode.get("mode", "") or "")
                    print(f"[Controller] Motion mode check: status={code}, name='{mode_name}', form='{mode_form}'")
                    if code == 0 and not mode_name:
                        break
            if code == 0 and not mode_name:
                print("[Controller] Motion mode released; low-level control can take over.")
        except Exception as exc:
            print(f"[Controller][Warning] Failed to release motion mode: {exc}")

    def count_loop_rate(self, loop_count):
        count_loop_timer = Timer(1.0)
        while self.is_alive:
            if loop_count.value < self.config.control_freq - 2 or loop_count.value > self.config.control_freq + 2:
                print(f'[Warning] Loop rate: {loop_count.value} Hz')
            loop_count.value = 0
            count_loop_timer.sleep()

    def _debug_event(self, key: str, msg: str, interval_s: Optional[float] = None):
        interval = self.debug_log_interval_s if interval_s is None else float(interval_s)
        now = time.monotonic()
        last = self._last_debug_log.get(key)
        if last is None or (now - last) >= interval:
            print(msg)
            self._last_debug_log[key] = now

    def _target_root_z_debug(self) -> Optional[float]:
        policy = self.current_policy
        if policy is None:
            return None
        ref_root_pos = getattr(policy, "ref_root_pos", None)
        ref_len = int(getattr(policy, "ref_len", 0))
        if ref_root_pos is None or ref_len <= 0:
            return None
        idx = int(np.clip(int(getattr(policy, "ref_idx", 0)), 0, ref_len - 1))
        offset = float(getattr(getattr(policy, "config", None), "target_root_z_offset", 0.035))
        return float(ref_root_pos[idx, 2] + offset)

    def _future_horizon_debug(self) -> Optional[int]:
        policy = self.current_policy
        source = getattr(policy, "source", None)
        horizon_fn = getattr(source, "_future_horizon", None)
        if callable(horizon_fn):
            try:
                return int(horizon_fn())
            except Exception:
                return None
        return None

    def _reference_debug(self) -> str:
        policy = self.current_policy
        if policy is None:
            return "policy=None"
        parts = [
            f"policy={getattr(policy, 'name', type(policy).__name__)}",
            f"ref={int(getattr(policy, 'ref_idx', -1))}/{int(getattr(policy, 'ref_len', -1))}",
            f"motion={getattr(policy, 'current_name', '')}",
        ]
        source = getattr(policy, "source", None)
        if source is not None:
            parts.extend([
                f"vr_active={bool(getattr(source, '_vr_active', False))}",
                f"vr_enabled={bool(getattr(source, '_vr_user_enabled', False))}",
                f"vr_pending={bool(getattr(source, '_pending_start_request', False))}",
            ])
        horizon = self._future_horizon_debug()
        if horizon is not None:
            parts.append(f"h={horizon}")
        return " | ".join(parts)

    @staticmethod
    def _nonfinite_summary(name: str, values: np.ndarray, limit: int = 6) -> Optional[str]:
        arr = np.asarray(values).reshape(-1)
        bad = np.flatnonzero(~np.isfinite(arr))
        if bad.size == 0:
            return None
        shown = bad[:limit]
        pairs = ", ".join(f"{int(i)}={arr[i]}" for i in shown)
        suffix = "" if bad.size <= limit else f", ... total={bad.size}"
        return f"{name}[{pairs}{suffix}]"

    def _debug_state_suffix(self, action_real_delta: Optional[np.ndarray] = None) -> str:
        target_z = self._target_root_z_debug()
        root_z = None
        if self.root_pos_w is not None:
            root_z = float(np.asarray(self.root_pos_w, dtype=np.float32).reshape(3)[2])
        parts = [
            f"step={self.policy_step}",
            f"gyro_norm={float(np.linalg.norm(self.gyro)):.2f}",
            f"tau_max={float(np.max(np.abs(self.tau_real))):.2f}",
        ]
        if target_z is not None:
            parts.append(f"target_root_z={target_z:.3f}")
        if root_z is not None:
            parts.append(f"odom_root_z={root_z:.3f}")
        horizon = self._future_horizon_debug()
        if horizon is not None:
            parts.append(f"h={horizon}")
        if action_real_delta is not None and np.all(np.isfinite(action_real_delta)):
            parts.append(f"action_delta_max={float(np.max(np.abs(action_real_delta))):.3f}")
        return " | ".join(parts)

    def _top_joint_values(self, values: np.ndarray, limit: int = 8) -> str:
        arr = np.asarray(values, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return ""
        order = np.argsort(-np.abs(arr))[:limit]
        return ", ".join(
            f"{self.config.real_joint_names[int(i)]}={float(arr[int(i)]):+.3f}"
            for i in order
            if int(i) < len(self.config.real_joint_names)
        )

    def _pose_mismatch_debug(self, context: str) -> None:
        if self.qj_real is None or self.qj_real.shape[0] != self.default_qpos_real.shape[0]:
            return
        diff_default = self.qj_real - self.default_qpos_real
        diff_init = self.qj_real - self.init_qpos_real
        imax = int(np.argmax(np.abs(diff_default)))
        root_z = None
        if self.root_pos_w is not None:
            root_z = float(np.asarray(self.root_pos_w, dtype=np.float32).reshape(3)[2])
        print(
            f"[Controller][PoseDiag] context={context} "
            f"default_abs_max={float(np.max(np.abs(diff_default))):.3f}@{self.config.real_joint_names[imax]} "
            f"default_abs_mean={float(np.mean(np.abs(diff_default))):.3f} "
            f"init_abs_max={float(np.max(np.abs(diff_init))):.3f} "
            f"gyro_norm={float(np.linalg.norm(self.gyro)):.3f} "
            f"root_z={root_z if root_z is not None else 'n/a'} "
            f"top_default_diff=[{self._top_joint_values(diff_default)}]"
        )

    def _consume_low_state(self, msg: LowStateHG) -> bool:
        if msg is None or not hasattr(msg, "motor_state"):
            return False

        self.low_state = msg
        self.qj_real[:] = np.array([msg.motor_state[i].q for i in range(self.dof_size_real)], dtype=np.float32)
        self.dqj_real[:] = np.array([msg.motor_state[i].dq for i in range(self.dof_size_real)], dtype=np.float32)
        self.tau_real[:] = np.array([msg.motor_state[i].tau_est for i in range(self.dof_size_real)], dtype=np.float32)
        self.motor_mode_real[:] = np.array(
            [int(getattr(msg.motor_state[i], "mode", 0)) for i in range(self.dof_size_real)],
            dtype=np.int32,
        )
        self.motor_state_real[:] = np.array(
            [int(getattr(msg.motor_state[i], "motorstate", 0)) for i in range(self.dof_size_real)],
            dtype=np.int32,
        )
        self.motor_vol_real[:] = np.array(
            [float(getattr(msg.motor_state[i], "vol", 0.0)) for i in range(self.dof_size_real)],
            dtype=np.float32,
        )
        for i in range(self.dof_size_real):
            temp = list(getattr(msg.motor_state[i], "temperature", []))
            reserve = list(getattr(msg.motor_state[i], "reserve", []))
            for j in range(min(2, len(temp))):
                self.motor_temp_real[i, j] = int(temp[j])
            for j in range(min(4, len(reserve))):
                self.motor_reserve_real[i, j] = int(reserve[j])
        self.quat[:] = np.array(msg.imu_state.quaternion, dtype=np.float32)
        self.gyro[:] = np.array(msg.imu_state.gyroscope, dtype=np.float32)
        self.linacc[:] = np.array(msg.imu_state.accelerometer, dtype=np.float32)
        nonfinite = [
            self._nonfinite_summary("qj_real", self.qj_real),
            self._nonfinite_summary("dqj_real", self.dqj_real),
            self._nonfinite_summary("tau_real", self.tau_real),
            self._nonfinite_summary("imu_quat", self.quat),
            self._nonfinite_summary("gyro", self.gyro),
            self._nonfinite_summary("linacc", self.linacc),
        ]
        nonfinite = [item for item in nonfinite if item is not None]
        if nonfinite:
            self._debug_event(
                "low_state_nonfinite",
                "[Controller][Error] low_state contains nan/inf | "
                + "; ".join(nonfinite)
                + f" | {self._debug_state_suffix()}",
            )

        if self.args.sim2sim:
            self.remote_controller.set_sim2sim(msg.wireless_remote)
        elif self.args.real:
            self.remote_controller.set(msg.wireless_remote)

        self.mode_machine_ = msg.mode_machine
        self._low_state_last_ok_monotonic = time.monotonic()
        return True

    def _consume_odom_state(self, msg: SportModeState_) -> bool:
        if msg is None or not hasattr(msg, "position"):
            return False

        pos = np.asarray(msg.position, dtype=np.float32).reshape(-1)
        if pos.size < 3 or not np.all(np.isfinite(pos[:3])):
            return False

        if self._odom_origin_xy is None:
            self._odom_origin_xy = pos[:2].copy()
            print(f"[Controller] Odom origin xy set to {np.round(self._odom_origin_xy, 3).tolist()}")

        self._odom_latest_position_w = pos[:3].copy()
        root_pos_w = pos[:3].copy()
        root_pos_w[:2] -= self._odom_origin_xy
        self.root_pos_w = root_pos_w
        self.root_quat_w = self.quat.copy()

        vel = np.asarray(getattr(msg, "velocity", [0.0, 0.0, 0.0]), dtype=np.float32).reshape(-1)
        if vel.size >= 3:
            self.root_vel_w[:] = vel[:3]
        self.root_yaw_speed = float(getattr(msg, "yaw_speed", 0.0))

        if not self._odom_seen:
            self._odom_seen = True
            print(f"[Controller] Received odom root pose rel_xy={np.round(self.root_pos_w[:2], 3).tolist()}")
        return True

    def reset_root_xy_origin(self, reason: str = "") -> bool:
        odom_msg = self.odom_subscriber.Read(0.0)
        self._consume_odom_state(odom_msg)

        if self._odom_latest_position_w is None:
            print("[Controller][Warning] Cannot reset root_xy origin: no odom position yet")
            return False

        self._odom_origin_xy = self._odom_latest_position_w[:2].copy()
        root_pos_w = self._odom_latest_position_w.copy()
        root_pos_w[:2] = 0.0
        self.root_pos_w = root_pos_w
        self.root_quat_w = self.quat.copy()
        suffix = f" ({reason})" if reason else ""
        print(
            "[Controller] Reset root_xy origin"
            f"{suffix} | origin_xy={np.round(self._odom_origin_xy, 3).tolist()}"
        )
        return True

    def send_cmd(self, cmd):
        cmd.crc = CRC().Crc(cmd)
        try:
            self.lowcmd_publisher_.Write(cmd)
        except Exception as exc:
            self._debug_event(
                "lowcmd_write_failed",
                f"[Controller][Error] lowcmd publish failed | {exc} | {self._debug_state_suffix()}",
            )
            raise
        self.send_dex3_hand_cmd()

    def send_dex3_hand_cmd(self):
        if self.dex3_hand_publisher is None:
            return
        self.dex3_hand_publisher.publish(self.dex3_left_q, self.dex3_right_q)

    def set_dex3_from_controller_buttons(self, buttons: dict):
        if self.dex3_hand_publisher is None or not self.dex3_teleop_hands:
            return
        self.dex3_left_q, self.dex3_right_q = hand_pose_from_vr_controls(
            float(buttons.get("left_trigger_value", 0.0)),
            float(buttons.get("left_grip_value", 0.0)),
            float(buttons.get("right_trigger_value", 0.0)),
            float(buttons.get("right_grip_value", 0.0)),
        )

    def handle_vr_record_buttons(self, buttons: dict):
        if not self.session_recording_enabled:
            return
        start_btn = self._button_combo_pressed(buttons, self.session_record_start_buttons)
        stop_btn = self._button_combo_pressed(buttons, self.session_record_stop_buttons)
        start_rise = start_btn and (not self._prev_vr_record_start)
        stop_rise = stop_btn and (not self._prev_vr_record_stop)
        self._prev_vr_record_start = start_btn
        self._prev_vr_record_stop = stop_btn

        if start_rise:
            self.start_session_recording()
        if stop_rise:
            self.stop_session_recording("PICO record stop")

    @staticmethod
    def _parse_button_combo(value: str) -> list[str]:
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @staticmethod
    def _button_combo_pressed(buttons: dict, combo: list[str]) -> bool:
        return bool(combo) and all(bool(buttons.get(name, False)) for name in combo)

    def start_session_recording(self):
        if not self.session_recording_enabled:
            return
        if self.session_recorder.active:
            print(f"[Recorder] Session recording already active: {self.session_recorder.session_dir}")
            return

        session_dir = self.recording_root / time.strftime("session_%Y%m%d_%H%M%S")
        self.session_recorder.start(session_dir, self._recording_metadata())
        self.video_record_control.send_start(session_dir)
        self.record_feedback.record_start()
        print(f"[Recorder] Session START -> {session_dir}")

    def stop_session_recording(self, reason: str = ""):
        if not self.session_recording_enabled:
            return
        if not self.session_recorder.active:
            return
        self.video_record_control.send_stop()
        session_dir = self.session_recorder.stop_and_save(reason=reason)
        self.record_feedback.record_stop()
        if session_dir is not None:
            print(f"[Recorder] Session STOP -> {session_dir}")

    def _recording_metadata(self) -> dict:
        tracking = self.policies.get("tracking")
        return {
            "format": "holo_vla_session_v1",
            "recording_root": str(self.recording_root),
            "sim2sim": bool(self.args.sim2sim),
            "real": bool(self.args.real),
            "net": self.args.net,
            "control_freq": int(self.config.control_freq),
            "policy_path": str(getattr(tracking, "policy_path", "")),
            "motion_source": str(getattr(tracking, "motion_source", "")),
            "isaac_joint_names": list(self.config.isaac_joint_names_state),
            "real_joint_names": list(self.config.real_joint_names),
            "action_joint_names": list(getattr(tracking, "action_joint_names", [])),
            "video_record_control": {
                "host": str(getattr(self.args, "video_record_control_host", "127.0.0.1")),
                "port": int(getattr(self.args, "video_record_control_port", 13600)),
            },
        }

    def wait_for_low_state(self):
        while self.low_state.tick == 0:
            msg = self.lowstate_subscriber.Read()
            self._consume_low_state(msg)
        print("Successfully connected to the robot.")

    def zero_torque_state(self):
        print("Enter zero torque state.")
        print("Waiting for the start signal...")
        while self.remote_controller.button[KeyMap.start] != 1:
            self.process_state()
            create_zero_cmd(self.low_cmd)
            self.send_cmd(self.low_cmd)
            time.sleep(self.control_dt)

    def move_to_default_qpos(self):
        print("Moving to init pos....")
        total_time = 2.0
        num_step = int(total_time / self.control_dt)

        init_dof_pos = np.zeros(self.dof_size_real, dtype=np.float32)
        for i in range(self.dof_size_real):
            init_dof_pos[i] = self.low_state.motor_state[i].q
        start_dof_pos = init_dof_pos.copy()

        for t in range(num_step):
            alpha = t / num_step
            for i in range(self.dof_size_real):
                target_pos = self.init_qpos_real[i]
                self.low_cmd.motor_cmd[i].q  = init_dof_pos[i] * (1 - alpha) + target_pos * alpha
                self.low_cmd.motor_cmd[i].qd = 0
                self.low_cmd.motor_cmd[i].kp = self.kps_real[i]
                self.low_cmd.motor_cmd[i].kd = self.kds_real[i]
                self.low_cmd.motor_cmd[i].tau = 0
            self.send_cmd(self.low_cmd)
            time.sleep(self.control_dt)

        self.process_state()
        observed_delta = float(np.max(np.abs(self.qj_real - start_dof_pos)))
        commanded_delta = float(np.max(np.abs(self.init_qpos_real - start_dof_pos)))
        if commanded_delta > 0.05 and observed_delta < min(0.02, commanded_delta * 0.1):
            raise RuntimeError(
                "[Safety] LowCmd is not moving joints during init. "
                f"commanded_delta={commanded_delta:.3f}, observed_delta={observed_delta:.3f}. "
                "Robot may not have accepted low-level control."
            )
        self._pose_mismatch_debug("after_move_to_init")

    def default_qpos_state(self):
        initial_policy: Optional[Policy] = None

        print("Press A to tracking policy...")

        while True:
            self.process_state()
            
            for i in range(self.dof_size_real):
                self.low_cmd.motor_cmd[i].q  = self.init_qpos_real[i]
                self.low_cmd.motor_cmd[i].qd = 0
                self.low_cmd.motor_cmd[i].kp = self.kps_real[i]
                self.low_cmd.motor_cmd[i].kd = self.kds_real[i]
                self.low_cmd.motor_cmd[i].tau = 0
            self.send_cmd(self.low_cmd)
            time.sleep(self.control_dt)

            if self._select_hold_exit_requested("default_state"):
                self._shutdown_reason = "remote_select_in_default_state"
                raise KeyboardInterrupt

            if self.btn_rise[KeyMap.A]:
                initial_policy = self.policies["tracking"]
                print("Initial policy: tracking")
                self._pose_mismatch_debug("before_tracking_fade_in")
                break

        self.current_policy = initial_policy
        if hasattr(self.current_policy, "kps_real") and hasattr(self.current_policy, "kds_real"):
            self.kps_real[:] = self.current_policy.kps_real
            self.kds_real[:] = self.current_policy.kds_real
            print(f"[Controller] Updated gains to policy defaults.")
        if getattr(self.current_policy, "uses_root_xy_obs", False):
            self.reset_root_xy_origin("tracking start")
            reset_reference_to_state = getattr(self.current_policy, "reset_reference_to_state", None)
            read_robot_state = getattr(self.current_policy, "read_robot_state", None)
            if callable(reset_reference_to_state) and callable(read_robot_state):
                reset_reference_to_state(read_robot_state(), name="tracking_anchor")
        self.current_policy.fade_in()
        self.low_cmd.reserve[0] = 1
        self.send_cmd(self.low_cmd)

    def process_state(self):
        msg = self.lowstate_subscriber.Read(0.0)
        if self._consume_low_state(msg):
            if self._low_state_miss_count > 0:
                self._debug_event(
                    "low_state_recovered",
                    f"[Controller] low_state recovered after {self._low_state_miss_count} missed reads",
                    interval_s=0.0,
                )
            self._low_state_miss_count = 0
        else:
            self._low_state_miss_count += 1
            if self._low_state_miss_count >= max(3, int(self.config.control_freq * 0.1)):
                age_msg = "unknown"
                if self._low_state_last_ok_monotonic is not None:
                    age_msg = f"{(time.monotonic() - self._low_state_last_ok_monotonic) * 1000.0:.1f} ms"
                self._debug_event(
                    "low_state_missing",
                    "[Controller][Warning] low_state missing or invalid "
                    f"| missed_reads={self._low_state_miss_count}, last_ok_age={age_msg}, step={self.policy_step}",
                )
        odom_msg = self.odom_subscriber.Read(0.0)
        self._consume_odom_state(odom_msg)

        now = np.array(self.remote_controller.button, dtype=np.int8)
        remote_keys = int(getattr(self.remote_controller, "keys", 0))
        if self._last_remote_keys is None:
            self._last_remote_keys = remote_keys
        elif remote_keys != self._last_remote_keys:
            print(
                "[Controller][Remote] "
                f"keys=0x{remote_keys:04x}, pressed={self._button_names(now)}"
            )
            self._last_remote_keys = remote_keys

        if self._prev_buttons is None or len(self._prev_buttons) != len(now):
            self._prev_buttons = now.copy()
            self.btn_rise = np.zeros_like(now, dtype=bool)
            self.btn_fall = np.zeros_like(now, dtype=bool)
        else:
            self.btn_rise = (self._prev_buttons == 0) & (now == 1)
            self.btn_fall = (self._prev_buttons == 1) & (now == 0)
            self._prev_buttons = now

        self.qj_isaac = self.isaac_to_real_mapper_state.map_state_to_from(self.qj_real)
        self.dqj_isaac = self.isaac_to_real_mapper_state.map_state_to_from(self.dqj_real)
        self.tau_isaac = self.isaac_to_real_mapper_state.map_state_to_from(self.tau_real)
        self._service_health_debug()

    def _select_hold_exit_requested(self, context: str) -> bool:
        now = time.monotonic()
        if bool(self.remote_controller.button[KeyMap.select]):
            if self._select_down_since is None:
                self._select_down_since = now
                print(f"[Controller] Select pressed in {context}; hold {self._select_hold_exit_s:.1f}s to exit")
                return False
            held_s = now - self._select_down_since
            if held_s >= self._select_hold_exit_s:
                print(f"[Controller] Select hold exit in {context}; held={held_s:.2f}s")
                return True
            return False
        self._select_down_since = None
        return False

    def _build_qerr_limits(self) -> Optional[np.ndarray]:
        if not self._qerr_limit_enabled or self._qerr_limit_default <= 0.0:
            return None
        limits = np.full(self.dof_size_real, self._qerr_limit_default, dtype=np.float32)
        for i, name in enumerate(self.config.real_joint_names):
            if str(name).startswith("waist_") and self._qerr_limit_waist > 0.0:
                limits[i] = min(float(limits[i]), self._qerr_limit_waist)
            if str(name) == "waist_pitch_joint" and self._qerr_limit_waist_pitch > 0.0:
                limits[i] = min(float(limits[i]), self._qerr_limit_waist_pitch)
        print(
            "[Controller] QErr limit enabled: "
            f"default={self._qerr_limit_default:.2f}, "
            f"waist={self._qerr_limit_waist:.2f}, "
            f"waist_pitch={self._qerr_limit_waist_pitch:.2f}"
        )
        return limits

    def _limit_target_qerr(self, target: np.ndarray) -> np.ndarray:
        if self._qerr_limits is None:
            return target
        if target.shape[0] != self.qj_real.shape[0]:
            return target

        raw_err = target - self.qj_real
        clipped_err = np.clip(raw_err, -self._qerr_limits, self._qerr_limits)
        clipped_mask = np.abs(clipped_err - raw_err) > 1e-6
        if not np.any(clipped_mask):
            return target

        limited = self.qj_real + clipped_err
        raw_abs = np.abs(raw_err)
        imax = int(np.argmax(raw_abs))
        clipped_names = [
            self.config.real_joint_names[i]
            for i in np.flatnonzero(clipped_mask)[:6]
        ]
        self._debug_event(
            "qerr_limit",
            "[Controller][QErrLimit] "
            f"clipped={int(np.sum(clipped_mask))} "
            f"max={float(raw_abs[imax]):.3f}@{self.config.real_joint_names[imax]} "
            f"limit={float(self._qerr_limits[imax]):.3f} "
            f"joints={clipped_names}",
            interval_s=0.25,
        )
        return limited

    def _apply_action_real(self, action_real_delta: np.ndarray):
        if action_real_delta is None or not np.all(np.isfinite(action_real_delta)):
            print(f"[Controller][Error] action invalid; entering shutdown | {self._debug_state_suffix()}")
            self._shutdown_reason = "invalid_action"
            raise KeyboardInterrupt
        else:
            desired = self.default_qpos_real + action_real_delta
            target = self._limit_target_qerr(desired)

        for i in range(self.dof_size_real):
            self.low_cmd.motor_cmd[i].q  = float(target[i])
            self.low_cmd.motor_cmd[i].qd = 0.0
            self.low_cmd.motor_cmd[i].kp = float(self.kps_real[i])
            self.low_cmd.motor_cmd[i].kd = float(self.kds_real[i])
            self.low_cmd.motor_cmd[i].tau = 0.0

    @staticmethod
    def _format_unique_counts(values: np.ndarray) -> str:
        unique, counts = np.unique(np.asarray(values).reshape(-1), return_counts=True)
        return ",".join(f"{int(v)}x{int(c)}" for v, c in zip(unique, counts))

    def _publish_pico_telemetry(self, action_real_delta: Optional[np.ndarray]) -> None:
        if not self.pico_telemetry.enabled:
            return

        temp_flat_idx = int(np.argmax(self.motor_temp_real)) if self.motor_temp_real.size else 0
        temp_joint_idx = int(temp_flat_idx // max(1, self.motor_temp_real.shape[1]))
        temp_sensor_idx = int(temp_flat_idx % max(1, self.motor_temp_real.shape[1]))
        temp_max = int(self.motor_temp_real[temp_joint_idx, temp_sensor_idx]) if self.motor_temp_real.size else 0
        temp_joint = (
            self.config.real_joint_names[temp_joint_idx]
            if temp_joint_idx < len(self.config.real_joint_names)
            else str(temp_joint_idx)
        )
        joint_temp_max = np.max(self.motor_temp_real, axis=1) if self.motor_temp_real.size else np.zeros(0, dtype=np.int32)
        top_indices = np.argsort(joint_temp_max)[::-1][:5]

        payload = {
            "type": "robot_thermal",
            "version": 1,
            "time_ns": int(time.monotonic_ns()),
            "step": int(self.policy_step),
            "temperature": {
                "max": temp_max,
                "joint": temp_joint,
                "index": temp_joint_idx,
                "sensor": temp_sensor_idx,
                "pair": [int(v) for v in self.motor_temp_real[temp_joint_idx].tolist()] if self.motor_temp_real.size else [],
                "top": [
                    {
                        "index": int(i),
                        "name": self.config.real_joint_names[int(i)] if int(i) < len(self.config.real_joint_names) else str(i),
                        "max": int(joint_temp_max[int(i)]),
                        "pair": [int(v) for v in self.motor_temp_real[int(i)].tolist()],
                    }
                    for i in top_indices
                ],
            },
        }
        self.pico_telemetry.maybe_send(payload)

    def notify_vr_fail_safe_pause(self, reason: str, *, action: str = "hold") -> None:
        if not self.pico_telemetry.enabled:
            return
        payload = {
            "type": "robot_event",
            "version": 1,
            "event": "vr_fail_safe_pause",
            "time_ns": int(time.monotonic_ns()),
            "step": int(self.policy_step),
            "policy": self.current_policy.name if self.current_policy is not None else None,
            "action": str(action),
            "reason": str(reason),
        }
        self.pico_telemetry.maybe_send(payload, force=True)
        print(f"[PicoTelemetry] event=vr_fail_safe_pause action={action} reason={reason}")

    def _highest_motor_temperature(self) -> tuple[int, int, int]:
        if self.motor_temp_real.size == 0:
            return 0, 0, 0
        temp_flat_idx = int(np.argmax(self.motor_temp_real))
        sensor_count = max(1, self.motor_temp_real.shape[1])
        joint_idx = int(temp_flat_idx // sensor_count)
        sensor_idx = int(temp_flat_idx % sensor_count)
        return int(self.motor_temp_real[joint_idx, sensor_idx]), joint_idx, sensor_idx

    @staticmethod
    def _spoken_joint_name(joint_name: str) -> str:
        name = str(joint_name or "").replace("_joint", "").replace("_", " ").strip()
        return " ".join(part.capitalize() for part in name.split()) if name else "Motor"

    def _temperature_warning_message(self, joint_name: str, temp_c: int) -> str:
        spoken_joint = self._spoken_joint_name(joint_name)
        template = self.temperature_audio_warning_message.strip()
        if not template:
            return "Warning! High temperature"
        try:
            return template.format(
                joint=spoken_joint,
                temp=int(temp_c),
                threshold=float(self.temperature_audio_warning_threshold_c),
            )
        except (KeyError, IndexError, ValueError):
            return template

    def _maybe_temperature_audio_warning(self) -> None:
        if not self.temperature_audio_warning_enabled:
            return

        temp_c, joint_idx, sensor_idx = self._highest_motor_temperature()
        if temp_c <= 0:
            return

        threshold_c = float(self.temperature_audio_warning_threshold_c)
        clear_c = min(float(self.temperature_audio_warning_clear_c), threshold_c)
        joint_name = (
            self.config.real_joint_names[joint_idx]
            if joint_idx < len(self.config.real_joint_names)
            else str(joint_idx)
        )

        if temp_c > threshold_c:
            self._temperature_audio_warning_active = True
            now = time.monotonic()
            if now - self._last_temperature_audio_warning_monotonic < self.temperature_audio_warning_cooldown_s:
                return

            message = self._temperature_warning_message(joint_name, temp_c)
            audio_started = self.temperature_feedback.say(message)
            self._last_temperature_audio_warning_monotonic = now
            print(
                "[Controller][TemperatureWarning] "
                f"max={temp_c}C joint={joint_name} sensor={sensor_idx} "
                f"threshold={threshold_c:.1f}C audio={audio_started} message='{message}'"
            )
            return

        if self._temperature_audio_warning_active and temp_c <= clear_c:
            self._temperature_audio_warning_active = False
            print(
                "[Controller][TemperatureWarning] clear "
                f"max={temp_c}C clear={clear_c:.1f}C"
            )

    def _service_health_debug(self, force: bool = False) -> None:
        if not bool(getattr(self.args, "real", False)):
            return
        if self.service_health_log_interval_s <= 0.0 and not force:
            return
        now = time.monotonic()
        if (
            not force
            and self._last_service_health_monotonic is not None
            and now - self._last_service_health_monotonic < self.service_health_log_interval_s
        ):
            return

        try:
            if self._robot_state_client is None:
                self._robot_state_client = RobotStateClient()
                self._robot_state_client.SetTimeout(0.2)
                self._robot_state_client.Init()
            if self._motion_switcher_client is None:
                self._motion_switcher_client = MotionSwitcherClient()
                self._motion_switcher_client.SetTimeout(0.2)
                self._motion_switcher_client.Init()

            code, services = self._robot_state_client.ServiceList()
            mode_code, mode = self._motion_switcher_client.CheckMode()
            mode_name = ""
            mode_form = ""
            if isinstance(mode, dict):
                mode_name = str(mode.get("name", "") or "")
                mode_form = str(mode.get("form", "") or mode.get("mode", "") or "")

            watch = {
                "ai_sport",
                "sport_mode",
                "auto_test_arm",
                "auto_test_low",
                "motion_switcher",
                "emergency_stop",
                "basic_service",
                "robot_state",
                "ota_box",
            }
            parts = []
            if code == 0 and services is not None:
                for service in services:
                    if service.name in watch or int(service.status) == 1 or int(service.protect) == 1:
                        parts.append(f"{service.name}:s{int(service.status)}p{int(service.protect)}")
            else:
                parts.append(f"ServiceList code={code}")
            print(
                "[Controller][ServiceHealth] "
                f"step={self.policy_step} mode_code={mode_code} mode='{mode_name}' form='{mode_form}' "
                + " ".join(parts)
            )
            self._last_service_health_monotonic = now
        except Exception as exc:
            self._debug_event(
                "service_health_failed",
                f"[Controller][ServiceHealth][Warning] query failed: {exc}",
                interval_s=max(1.0, self.service_health_log_interval_s),
            )

    def _control_health_debug(self, action_real_delta: Optional[np.ndarray]) -> None:
        if self.control_health_log_interval_s <= 0.0:
            return
        now = time.monotonic()
        if (
            self._last_control_health_monotonic is not None
            and now - self._last_control_health_monotonic < self.control_health_log_interval_s
        ):
            return

        cmd_q = np.array([self.low_cmd.motor_cmd[i].q for i in range(self.dof_size_real)], dtype=np.float32)
        cmd_kp = np.array([self.low_cmd.motor_cmd[i].kp for i in range(self.dof_size_real)], dtype=np.float32)
        qerr = cmd_q - self.qj_real
        qerr_abs = np.abs(qerr)
        imax = int(np.argmax(qerr_abs)) if qerr_abs.size else 0
        jname = self.config.real_joint_names[imax] if imax < len(self.config.real_joint_names) else str(imax)

        low_age_ms = -1.0
        if self._low_state_last_ok_monotonic is not None:
            low_age_ms = (now - self._low_state_last_ok_monotonic) * 1000.0

        dt_ms = 0.0
        q_step = 0.0
        cmd_step = 0.0
        if self._last_control_health_monotonic is not None:
            dt_ms = (now - self._last_control_health_monotonic) * 1000.0
        if self._last_control_health_q is not None:
            q_step = float(np.max(np.abs(self.qj_real - self._last_control_health_q)))
        if self._last_control_health_cmd_q is not None:
            cmd_step = float(np.max(np.abs(cmd_q - self._last_control_health_cmd_q)))

        prefix = "[Controller][ControlHealth]"
        if (
            float(np.max(cmd_kp)) > 1.0
            and float(np.max(qerr_abs)) > 0.35
            and dt_ms > 200.0
            and q_step < 0.01
            and cmd_step > 0.02
        ):
            prefix = "[Controller][ControlHealth][Warning]"

        print(
            f"{prefix} step={self.policy_step} "
            f"qerr_max={float(np.max(qerr_abs)):.3f}@{jname} "
            f"cmd={float(cmd_q[imax]):.3f} q={float(self.qj_real[imax]):.3f} "
            f"dq_max={float(np.max(np.abs(self.dqj_real))):.3f} "
            f"tau_max={float(np.max(np.abs(self.tau_real))):.2f} "
            f"kp_max={float(np.max(cmd_kp)):.1f} "
            f"cmd_step={cmd_step:.3f} q_step={q_step:.3f} "
            f"motor_mode={self._format_unique_counts(self.motor_mode_real)} "
            f"motorstate={self._format_unique_counts(self.motor_state_real)} "
            f"temp_max={int(np.max(self.motor_temp_real))} "
            f"vol_min={float(np.min(self.motor_vol_real)):.1f} "
            f"reserve_max={np.max(self.motor_reserve_real, axis=0).astype(int).tolist()} "
            f"low_age_ms={low_age_ms:.1f} remote=0x{int(getattr(self.remote_controller, 'keys', 0)):04x} "
            f"{self._reference_debug()} | {self._debug_state_suffix(action_real_delta)}"
        )

        self._last_control_health_monotonic = now
        self._last_control_health_q = self.qj_real.copy()
        self._last_control_health_cmd_q = cmd_q.copy()

    def run(self):
        print("Running high level...")
        self.p_loop_rate.start()
        timer = Timer(self.control_dt)
        loop_count = self.loop_count

        try:
            while True:
                self.process_state()

                if self._select_hold_exit_requested("run"):
                    self._shutdown_reason = "remote_select_in_run"
                    break

                self.current_policy.update_obs()
                action_real = self.current_policy.compute_action()
                self._apply_action_real(action_real)
                self.current_policy.post_step()
                self._control_health_debug(action_real)
                self._publish_pico_telemetry(action_real)
                self._maybe_temperature_audio_warning()
                self.session_recorder.record_step(
                    timestamp_ns=time.monotonic_ns(),
                    controller=self,
                    policy=self.current_policy,
                )

                self.send_cmd(self.low_cmd)
                loop_count.value += 1
                self.policy_step += 1
                timer.sleep()
        finally:
            pass

    def close(self):
        print("Closing...")
        self.stop_session_recording("controller close")
        self.video_record_control.close()
        self.pico_telemetry.close()
        self.is_alive = False
        if self.p_loop_rate is not None and self.p_loop_rate.is_alive():
            self.p_loop_rate.terminate()
        sys.exit(0)

import traceback

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--net", type=str, default=None)
    parser.add_argument("--sim2sim", action='store_true')
    parser.add_argument("--real", action='store_true')
    parser.add_argument("--policy-path", type=str, default=None)
    parser.add_argument("--motion-source", choices=["udp", "vr"], default=None)
    parser.add_argument("--enable-dex3-hands", action="store_true")
    parser.add_argument("--dex3-hand-pose", type=str, default="closed_fist", choices=["closed_fist", "fist", "closed", "open"])
    parser.add_argument("--dex3-teleop-hands", action="store_true")
    parser.add_argument("--recording-root", type=str, default="/mnt/nexus/workspace/recordings")
    parser.add_argument("--video-record-control-host", type=str, default="127.0.0.1")
    parser.add_argument("--video-record-control-port", type=int, default=13600)
    parser.add_argument("--session-record-start-buttons", type=str, default="right_axis_click")
    parser.add_argument("--session-record-stop-buttons", type=str, default="left_axis_click")
    parser.add_argument("--disable-record-audio-feedback", action="store_true")
    parser.add_argument("--enable-temperature-audio-warning", action="store_true")
    parser.add_argument("--disable-temperature-audio-warning", action="store_true")
    parser.add_argument("--temperature-audio-warning-threshold-c", type=float, default=100.0)
    parser.add_argument("--temperature-audio-warning-clear-c", type=float, default=95.0)
    parser.add_argument("--temperature-audio-warning-cooldown-s", type=float, default=10.0)
    parser.add_argument(
        "--temperature-audio-warning-message",
        type=str,
        default="Warning! High temperature",
    )
    parser.add_argument("--disable-session-recording", action="store_true")
    parser.add_argument("--debug-log-interval-s", type=float, default=3.0)
    parser.add_argument("--control-health-log-interval-s", type=float, default=2.0)
    parser.add_argument("--service-health-log-interval-s", type=float, default=5.0)
    parser.add_argument("--debug-log-file", type=str, default="")
    parser.add_argument("--pico-telemetry-host", type=str, default="")
    parser.add_argument("--pico-telemetry-port", type=int, default=13601)
    parser.add_argument("--pico-telemetry-rate-hz", type=float, default=5.0)
    parser.add_argument("--disable-qerr-limit", action="store_true")
    parser.add_argument("--qerr-limit", type=float, default=1.8)
    parser.add_argument("--waist-qerr-limit", type=float, default=1.2)
    parser.add_argument("--waist-pitch-qerr-limit", type=float, default=0.5)
    args = parser.parse_args()
    assert args.sim2sim ^ args.real, "Please specify either sim2sim or real."

    enable_debug_log_file(args.debug_log_file)

    ChannelFactoryInitialize(0, args.net)

    controller = Controller(args, get_config("config/controller.yaml"))

    controller.zero_torque_state()
    controller.move_to_default_qpos()
    try:
        controller.default_qpos_state()
        controller.run()
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")
        if getattr(controller, "_shutdown_reason", "normal") == "normal":
            controller._shutdown_reason = "keyboard_interrupt"
    except Exception as e:
        print(f"An exception occurred: {e}")
        controller._shutdown_reason = f"exception:{type(e).__name__}"
        traceback.print_exc()
    finally:
        print(
            "[Controller] Sending damping command on shutdown "
            f"(reason={getattr(controller, '_shutdown_reason', 'unknown')}). "
            "This disables position kp and will not stand the robot back up."
        )
        create_damping_cmd(controller.low_cmd)
        controller.send_cmd(controller.low_cmd)
        controller.close()
