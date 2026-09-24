"""Optional URDF-based dual-arm inverse kinematics using Pinocchio."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np

from .config import ArmConfig
from .geometry import Pose
from .safety import JointSpec


class PinocchioDualArmIK:
    def __init__(
        self,
        urdf_path: str,
        left: ArmConfig,
        right: ArmConfig,
        *,
        damping: float,
        iterations: int,
    ) -> None:
        try:
            import pinocchio as pin
        except ImportError as exc:
            raise RuntimeError(
                "Pinocchio is required on the robot computer for URDF IK"
            ) from exc
        self.pin = pin
        path = Path(urdf_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Tianyi URDF not found: {path}")
        self.model = pin.buildModelFromUrdf(str(path))
        self.data = self.model.createData()
        self.left = left
        self.right = right
        self.damping = float(damping)
        self.iterations = int(iterations)
        self.specs = [*left.joints, *right.joints]
        self.q = pin.neutral(self.model)
        self._q_indices: dict[str, int] = {}
        self._v_indices: dict[str, int] = {}
        for spec in self.specs:
            joint_id = self.model.getJointId(spec.model_joint)
            if joint_id == 0:
                raise ValueError(f"joint not found in URDF: {spec.model_joint}")
            joint = self.model.joints[joint_id]
            if joint.nq != 1 or joint.nv != 1:
                raise ValueError(
                    f"arm joint must be 1-DoF: {spec.model_joint} nq={joint.nq} nv={joint.nv}"
                )
            self._q_indices[spec.model_joint] = int(joint.idx_q)
            self._v_indices[spec.model_joint] = int(joint.idx_v)
        self._active_v = np.asarray(
            [self._v_indices[spec.model_joint] for spec in self.specs], dtype=np.int64
        )
        self._frame_ids = {
            "left": self._frame_id(left.end_effector_frame),
            "right": self._frame_id(right.end_effector_frame),
        }

    def _frame_id(self, name: str) -> int:
        frame_id = int(self.model.getFrameId(name))
        if frame_id >= len(self.model.frames):
            raise ValueError(f"end-effector frame not found in URDF: {name}")
        return frame_id

    def set_joint_positions(self, positions: Mapping[str, float]) -> np.ndarray:
        q = self.q.copy()
        for name, value in positions.items():
            index = self._q_indices.get(name)
            if index is not None:
                q[index] = float(value)
        self.q = q
        return q.copy()

    def joint_positions(self, q: np.ndarray | None = None) -> dict[str, float]:
        values = self.q if q is None else q
        return {
            spec.model_joint: float(values[self._q_indices[spec.model_joint]])
            for spec in self.specs
        }

    def _forward(self, q: np.ndarray) -> None:
        self.pin.forwardKinematics(self.model, self.data, q)
        self.pin.updateFramePlacements(self.model, self.data)

    def frame_pose(self, side: str, q: np.ndarray | None = None) -> Pose:
        values = self.q if q is None else q
        self._forward(values)
        placement = self.data.oMf[self._frame_ids[side]]
        quaternion = self.pin.Quaternion(placement.rotation).coeffs()
        return Pose(
            tuple(float(value) for value in placement.translation),
            tuple(float(value) for value in quaternion),
        )

    def _target_se3(self, pose: Pose):
        rotation = self.pin.Quaternion(np.asarray(pose.quaternion_xyzw)).matrix()
        return self.pin.SE3(rotation, np.asarray(pose.position, dtype=np.float64))

    def solve(self, left_target: Pose, right_target: Pose) -> dict[str, float]:
        q = self.q.copy()
        targets = {
            "left": self._target_se3(left_target),
            "right": self._target_se3(right_target),
        }
        for _ in range(self.iterations):
            self._forward(q)
            errors: list[np.ndarray] = []
            jacobians: list[np.ndarray] = []
            for side in ("left", "right"):
                frame_id = self._frame_ids[side]
                current = self.data.oMf[frame_id]
                delta = current.actInv(targets[side])
                error = np.asarray(self.pin.log6(delta).vector, dtype=np.float64)
                jacobian = self.pin.computeFrameJacobian(
                    self.model,
                    self.data,
                    q,
                    frame_id,
                    self.pin.ReferenceFrame.LOCAL,
                )
                errors.append(error)
                jacobians.append(np.asarray(jacobian)[:, self._active_v])
            stacked_error = np.concatenate(errors)
            if float(np.linalg.norm(stacked_error)) < 1e-4:
                break
            stacked_jacobian = np.vstack(jacobians)
            lhs = stacked_jacobian @ stacked_jacobian.T
            lhs += self.damping * np.eye(lhs.shape[0])
            delta_active = stacked_jacobian.T @ np.linalg.solve(lhs, stacked_error)
            delta_active = np.clip(delta_active, -0.08, 0.08)
            velocity = np.zeros(self.model.nv, dtype=np.float64)
            velocity[self._active_v] = delta_active
            q = self.pin.integrate(self.model, q, velocity)
            q = self._clip_model_limits(q)
        self.q = q
        return self.joint_positions(q)

    def _clip_model_limits(self, q: np.ndarray) -> np.ndarray:
        result = q.copy()
        for spec in self.specs:
            index = self._q_indices[spec.model_joint]
            result[index] = min(spec.maximum, max(spec.minimum, result[index]))
        return result

