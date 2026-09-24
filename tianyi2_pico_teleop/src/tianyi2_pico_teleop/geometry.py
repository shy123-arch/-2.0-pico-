"""Small rigid-transform helpers with ROS/PICO quaternion order ``x,y,z,w``."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable


Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


def _vector(values: Iterable[float], length: int, label: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != length:
        raise ValueError(f"{label} must contain {length} values, got {len(result)}")
    return result


def normalize_quaternion(quaternion: Iterable[float]) -> Quaternion:
    x, y, z, w = _vector(quaternion, 4, "quaternion")
    norm = sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-9:
        raise ValueError("quaternion norm is zero")
    return (x / norm, y / norm, z / norm, w / norm)


def quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return normalize_quaternion(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        )
    )


def quaternion_inverse(quaternion: Quaternion) -> Quaternion:
    x, y, z, w = normalize_quaternion(quaternion)
    return (-x, -y, -z, w)


def rotate_vector(quaternion: Quaternion, vector: Vector3) -> Vector3:
    qx, qy, qz, qw = normalize_quaternion(quaternion)
    vx, vy, vz = vector
    # Expanded q * [v, 0] * q^-1, avoiding normalization of the vector term.
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return (
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    )


@dataclass(frozen=True)
class Pose:
    position: Vector3
    quaternion_xyzw: Quaternion

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _vector(self.position, 3, "position"))
        object.__setattr__(
            self, "quaternion_xyzw", normalize_quaternion(self.quaternion_xyzw)
        )

    @classmethod
    def identity(cls) -> "Pose":
        return cls((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))

    @classmethod
    def from_pose7(cls, values: Iterable[float]) -> "Pose":
        pose = _vector(values, 7, "pose")
        return cls(pose[:3], pose[3:7])

    def as_pose7(self) -> list[float]:
        return [*self.position, *self.quaternion_xyzw]


def compose(left: Pose, right: Pose) -> Pose:
    rotated = rotate_vector(left.quaternion_xyzw, right.position)
    return Pose(
        tuple(left.position[index] + rotated[index] for index in range(3)),
        quaternion_multiply(left.quaternion_xyzw, right.quaternion_xyzw),
    )


def inverse(pose: Pose) -> Pose:
    rotation = quaternion_inverse(pose.quaternion_xyzw)
    translation = rotate_vector(rotation, tuple(-value for value in pose.position))
    return Pose(translation, rotation)


def relative(anchor: Pose, current: Pose) -> Pose:
    return compose(inverse(anchor), current)


def scale_translation(pose: Pose, scale: float) -> Pose:
    return Pose(tuple(float(scale) * value for value in pose.position), pose.quaternion_xyzw)


@dataclass
class AnchorMapper:
    """Maps controller motion relative to a captured robot end-effector pose."""

    position_scale: float = 1.0
    controller_to_tool: Pose = Pose.identity()
    _controller_anchor: Pose | None = None
    _robot_anchor: Pose | None = None

    @property
    def calibrated(self) -> bool:
        return self._controller_anchor is not None and self._robot_anchor is not None

    def calibrate(self, controller_pose: Pose, robot_pose: Pose) -> None:
        self._controller_anchor = compose(controller_pose, self.controller_to_tool)
        self._robot_anchor = robot_pose

    def clear(self) -> None:
        self._controller_anchor = None
        self._robot_anchor = None

    def map(self, controller_pose: Pose) -> Pose:
        if not self.calibrated:
            raise RuntimeError("anchor mapper has not been calibrated")
        assert self._controller_anchor is not None
        assert self._robot_anchor is not None
        tool_pose = compose(controller_pose, self.controller_to_tool)
        delta = scale_translation(
            relative(self._controller_anchor, tool_pose), self.position_scale
        )
        return compose(self._robot_anchor, delta)

