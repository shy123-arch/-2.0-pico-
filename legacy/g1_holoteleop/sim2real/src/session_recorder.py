import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import yaml


class SessionRecorder:
    def __init__(self):
        self.active = False
        self.session_dir: Optional[Path] = None
        self.metadata: Dict[str, Any] = {}
        self.reset_buffers()

    def reset_buffers(self) -> None:
        self.timestamp_ns: list[int] = []

        self.ref_root_pos: list[np.ndarray] = []
        self.ref_root_quat_wxyz: list[np.ndarray] = []
        self.ref_dof_pos: list[np.ndarray] = []
        self.ref_idx: list[int] = []
        self.motion_name: list[str] = []

        self.qj_isaac: list[np.ndarray] = []
        self.dqj_isaac: list[np.ndarray] = []
        self.qj_real: list[np.ndarray] = []
        self.dqj_real: list[np.ndarray] = []
        self.tau_real: list[np.ndarray] = []
        self.root_pos: list[np.ndarray] = []
        self.root_quat_wxyz: list[np.ndarray] = []
        self.gyro: list[np.ndarray] = []
        self.linacc: list[np.ndarray] = []
        self.root_vel: list[np.ndarray] = []
        self.root_yaw_speed: list[float] = []

        self.policy_action_raw: list[np.ndarray] = []
        self.policy_action_applied_isaac: list[np.ndarray] = []
        self.lowcmd_target_q: list[np.ndarray] = []
        self.lowcmd_target_delta: list[np.ndarray] = []
        self.lowcmd_kp: list[np.ndarray] = []
        self.lowcmd_kd: list[np.ndarray] = []

    def start(self, session_dir: str | Path, metadata: Optional[Dict[str, Any]] = None) -> None:
        if self.active:
            print(f"[SessionRecorder] Already recording: {self.session_dir}")
            return
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.reset_buffers()
        self.metadata = dict(metadata or {})
        self.metadata["session_dir"] = str(self.session_dir)
        self.metadata["started_unix_ms"] = int(time.time() * 1000)
        self.metadata["started_monotonic_ns"] = time.monotonic_ns()
        self.active = True
        self._write_metadata(status="recording")
        print(f"[SessionRecorder] Start: {self.session_dir}")

    def record_step(self, *, timestamp_ns: int, controller, policy) -> None:
        if not self.active:
            return

        self.timestamp_ns.append(int(timestamp_ns))

        ref = self._current_reference(policy)
        self.ref_root_pos.append(ref["root_pos"])
        self.ref_root_quat_wxyz.append(ref["root_quat_wxyz"])
        self.ref_dof_pos.append(ref["dof_pos"])
        self.ref_idx.append(int(getattr(policy, "ref_idx", -1)))
        self.motion_name.append(str(getattr(policy, "current_name", "")))

        self.qj_isaac.append(self._vec_or_nan(getattr(controller, "qj_isaac", None), 1))
        self.dqj_isaac.append(self._vec_or_nan(getattr(controller, "dqj_isaac", None), 1))
        self.qj_real.append(np.asarray(controller.qj_real, dtype=np.float32).copy())
        self.dqj_real.append(np.asarray(controller.dqj_real, dtype=np.float32).copy())
        self.tau_real.append(np.asarray(controller.tau_real, dtype=np.float32).copy())
        self.root_pos.append(self._vec_or_nan(getattr(controller, "root_pos_w", None), 3))
        self.root_quat_wxyz.append(self._vec_or_nan(getattr(controller, "root_quat_w", None), 4))
        self.gyro.append(np.asarray(controller.gyro, dtype=np.float32).copy())
        self.linacc.append(np.asarray(controller.linacc, dtype=np.float32).copy())
        self.root_vel.append(np.asarray(controller.root_vel_w, dtype=np.float32).copy())
        self.root_yaw_speed.append(float(controller.root_yaw_speed))

        self.policy_action_raw.append(np.asarray(policy.last_action, dtype=np.float32).copy())
        self.policy_action_applied_isaac.append(np.asarray(policy.applied_action_isaac, dtype=np.float32).copy())
        target_q, kp, kd = self._lowcmd_arrays(controller)
        self.lowcmd_target_q.append(target_q)
        self.lowcmd_target_delta.append(target_q - np.asarray(controller.default_qpos_real, dtype=np.float32))
        self.lowcmd_kp.append(kp)
        self.lowcmd_kd.append(kd)

    def stop_and_save(self, reason: str = "") -> Optional[Path]:
        if not self.active:
            return None
        self.active = False
        if self.session_dir is None:
            return None

        self.metadata["stopped_unix_ms"] = int(time.time() * 1000)
        self.metadata["stopped_monotonic_ns"] = time.monotonic_ns()
        self.metadata["frames"] = len(self.timestamp_ns)
        if reason:
            self.metadata["stop_reason"] = str(reason)

        self._save_reference()
        self._save_state()
        self._save_action()
        self._write_metadata(status="saved")
        print(f"[SessionRecorder] Saved: {self.session_dir} frames={len(self.timestamp_ns)}")
        return self.session_dir

    def _save_reference(self) -> None:
        if self.session_dir is None:
            return
        np.savez_compressed(
            self.session_dir / "reference.npz",
            timestamp_ns=np.asarray(self.timestamp_ns, dtype=np.int64),
            root_pos=self._stack(self.ref_root_pos),
            root_quat_wxyz=self._stack(self.ref_root_quat_wxyz),
            dof_pos=self._stack(self.ref_dof_pos),
            joint_names=np.asarray(self.metadata.get("isaac_joint_names", [])),
            ref_idx=np.asarray(self.ref_idx, dtype=np.int64),
            motion_name=np.asarray(self.motion_name),
        )

    def _save_state(self) -> None:
        if self.session_dir is None:
            return
        np.savez_compressed(
            self.session_dir / "state.npz",
            timestamp_ns=np.asarray(self.timestamp_ns, dtype=np.int64),
            qj_isaac=self._stack(self.qj_isaac),
            dqj_isaac=self._stack(self.dqj_isaac),
            qj_real=self._stack(self.qj_real),
            dqj_real=self._stack(self.dqj_real),
            tau_real=self._stack(self.tau_real),
            root_pos=self._stack(self.root_pos),
            root_quat_wxyz=self._stack(self.root_quat_wxyz),
            gyro=self._stack(self.gyro),
            linacc=self._stack(self.linacc),
            root_vel=self._stack(self.root_vel),
            root_yaw_speed=np.asarray(self.root_yaw_speed, dtype=np.float32),
            isaac_joint_names=np.asarray(self.metadata.get("isaac_joint_names", [])),
            real_joint_names=np.asarray(self.metadata.get("real_joint_names", [])),
        )

    def _save_action(self) -> None:
        if self.session_dir is None:
            return
        np.savez_compressed(
            self.session_dir / "action.npz",
            timestamp_ns=np.asarray(self.timestamp_ns, dtype=np.int64),
            policy_action_raw=self._stack(self.policy_action_raw),
            policy_action_applied_isaac=self._stack(self.policy_action_applied_isaac),
            lowcmd_target_q=self._stack(self.lowcmd_target_q),
            lowcmd_target_delta=self._stack(self.lowcmd_target_delta),
            lowcmd_kp=self._stack(self.lowcmd_kp),
            lowcmd_kd=self._stack(self.lowcmd_kd),
            action_joint_names=np.asarray(self.metadata.get("action_joint_names", [])),
            real_joint_names=np.asarray(self.metadata.get("real_joint_names", [])),
        )

    def _write_metadata(self, status: str) -> None:
        if self.session_dir is None:
            return
        payload = dict(self.metadata)
        payload["status"] = status
        payload["files"] = {
            "video": "video.h264 or video.h265",
            "video_timestamps": "video_timestamps.csv",
            "reference": "reference.npz",
            "state": "state.npz",
            "action": "action.npz",
        }
        with open(self.session_dir / "metadata.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=True)

    @staticmethod
    def _current_reference(policy) -> Dict[str, np.ndarray]:
        idx = int(getattr(policy, "ref_idx", 0))
        ref_root_pos = getattr(policy, "ref_root_pos", None)
        ref_root_quat = getattr(policy, "ref_root_quat", None)
        ref_joint_pos = getattr(policy, "ref_joint_pos", None)
        if ref_root_pos is not None and len(ref_root_pos) > 0:
            idx = max(0, min(idx, len(ref_root_pos) - 1))
            root_pos = np.asarray(ref_root_pos[idx], dtype=np.float32).reshape(3).copy()
        else:
            root_pos = np.full((3,), np.nan, dtype=np.float32)
        if ref_root_quat is not None and len(ref_root_quat) > 0:
            idx_q = max(0, min(idx, len(ref_root_quat) - 1))
            root_quat_wxyz = np.asarray(ref_root_quat[idx_q], dtype=np.float32).reshape(4).copy()
        else:
            root_quat_wxyz = np.full((4,), np.nan, dtype=np.float32)
        if ref_joint_pos is not None and len(ref_joint_pos) > 0:
            idx_j = max(0, min(idx, len(ref_joint_pos) - 1))
            dof_pos = np.asarray(ref_joint_pos[idx_j], dtype=np.float32).reshape(-1).copy()
        else:
            dof_pos = np.full((1,), np.nan, dtype=np.float32)
        return {"root_pos": root_pos, "root_quat_wxyz": root_quat_wxyz, "dof_pos": dof_pos}

    @staticmethod
    def _lowcmd_arrays(controller) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = int(controller.dof_size_real)
        target_q = np.asarray([controller.low_cmd.motor_cmd[i].q for i in range(n)], dtype=np.float32)
        kp = np.asarray([controller.low_cmd.motor_cmd[i].kp for i in range(n)], dtype=np.float32)
        kd = np.asarray([controller.low_cmd.motor_cmd[i].kd for i in range(n)], dtype=np.float32)
        return target_q, kp, kd

    @staticmethod
    def _vec_or_nan(value: Optional[np.ndarray], fallback_dim: int) -> np.ndarray:
        if value is None:
            return np.full((fallback_dim,), np.nan, dtype=np.float32)
        return np.asarray(value, dtype=np.float32).reshape(-1).copy()

    @staticmethod
    def _stack(items: list[np.ndarray]) -> np.ndarray:
        if not items:
            return np.zeros((0,), dtype=np.float32)
        return np.stack(items, axis=0)
