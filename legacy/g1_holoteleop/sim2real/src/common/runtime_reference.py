from pathlib import Path
from typing import Dict, List

import numpy as np
import pinocchio as pin
from scipy.spatial.transform import Rotation as R

from common.utils import RuntimeReferenceUDPClient


class RuntimeReferencePublisher:
    """Publishes the runtime reference skeleton that the tracker is actually following."""

    FRAME_NAMES: List[str] = [
        "pelvis",
        "left_hip_pitch_link",
        "left_hip_roll_link",
        "left_hip_yaw_link",
        "left_knee_link",
        "left_ankle_pitch_link",
        "left_ankle_roll_link",
        "pelvis_contour_link",
        "right_hip_pitch_link",
        "right_hip_roll_link",
        "right_hip_yaw_link",
        "right_knee_link",
        "right_ankle_pitch_link",
        "right_ankle_roll_link",
        "waist_yaw_link",
        "waist_roll_link",
        "torso_link",
        "head_link",
        "head_mimic",
        "imu_in_torso",
        "left_shoulder_pitch_link",
        "left_shoulder_roll_link",
        "left_shoulder_yaw_link",
        "left_elbow_link",
        "left_wrist_roll_link",
        "left_wrist_pitch_link",
        "left_wrist_yaw_link",
        "left_hand_mimic",
        "left_rubber_hand",
        "right_shoulder_pitch_link",
        "right_shoulder_roll_link",
        "right_shoulder_yaw_link",
        "right_elbow_link",
        "right_wrist_roll_link",
        "right_wrist_pitch_link",
        "right_wrist_yaw_link",
        "right_hand_mimic",
        "right_rubber_hand",
    ]

    CHAINS: List[List[str]] = [
        ["pelvis", "waist_yaw_link", "waist_roll_link", "torso_link", "head_link", "head_mimic"],
        ["pelvis", "left_hip_pitch_link", "left_hip_roll_link", "left_hip_yaw_link", "left_knee_link", "left_ankle_pitch_link", "left_ankle_roll_link"],
        ["pelvis", "right_hip_pitch_link", "right_hip_roll_link", "right_hip_yaw_link", "right_knee_link", "right_ankle_pitch_link", "right_ankle_roll_link"],
        ["torso_link", "left_shoulder_pitch_link", "left_shoulder_roll_link", "left_shoulder_yaw_link", "left_elbow_link", "left_wrist_roll_link", "left_wrist_pitch_link", "left_wrist_yaw_link", "left_hand_mimic", "left_rubber_hand"],
        ["torso_link", "right_shoulder_pitch_link", "right_shoulder_roll_link", "right_shoulder_yaw_link", "right_elbow_link", "right_wrist_roll_link", "right_wrist_pitch_link", "right_wrist_yaw_link", "right_hand_mimic", "right_rubber_hand"],
    ]

    def __init__(
        self,
        urdf_path: str,
        joint_names_state: List[str],
        host: str = "127.0.0.1",
        port: int = 28564,
    ):
        self.model = pin.buildModelFromUrdf(str(Path(urdf_path)))
        self.data = self.model.createData()
        self.client = RuntimeReferenceUDPClient(host, port)
        self.frame_names = [n for n in self.FRAME_NAMES if self.model.existFrame(n)]
        self.frame_ids = [self.model.getFrameId(name) for name in self.frame_names]
        self.joint_to_q_idx = {name: i - 1 for i, name in enumerate(self.model.names) if i > 0}
        self.state_to_q_idx = [self.joint_to_q_idx[name] for name in joint_names_state]
        name_to_payload_idx = {name: i for i, name in enumerate(self.frame_names)}
        self.edges = []
        for chain in self.CHAINS:
            for a, b in zip(chain[:-1], chain[1:]):
                if a in name_to_payload_idx and b in name_to_payload_idx:
                    self.edges.append((name_to_payload_idx[a], name_to_payload_idx[b]))

    def close(self):
        self.client.close()

    def _local_frame_positions(self, joint_pos_state: np.ndarray) -> np.ndarray:
        q = np.zeros(self.model.nq, dtype=np.float64)
        q[np.asarray(self.state_to_q_idx, dtype=np.int64)] = np.asarray(joint_pos_state, dtype=np.float64)
        pin.forwardKinematics(self.model, self.data, q)
        pin.updateFramePlacements(self.model, self.data)
        local = np.zeros((len(self.frame_ids), 3), dtype=np.float32)
        for i, frame_id in enumerate(self.frame_ids):
            local[i] = self.data.oMf[frame_id].translation.astype(np.float32)
        return local

    def publish(self, motion_name: str, joint_pos_state: np.ndarray, root_pos: np.ndarray, root_quat_wxyz: np.ndarray):
        local = self._local_frame_positions(joint_pos_state)
        quat_xyzw = np.asarray([root_quat_wxyz[1], root_quat_wxyz[2], root_quat_wxyz[3], root_quat_wxyz[0]], dtype=np.float32)
        world = R.from_quat(quat_xyzw).apply(local) + np.asarray(root_pos, dtype=np.float32).reshape(1, 3)
        payload: Dict = {
            "motion_name": str(motion_name),
            "frame_names": self.frame_names,
            "edges": self.edges,
            "body_pos": world.tolist(),
        }
        self.client.send(payload)
