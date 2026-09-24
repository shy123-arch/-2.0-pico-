"""Versioned UDP protocol used between the PICO PC and the robot computer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .geometry import Pose


SCHEMA = "tianyi2-pico/v1"
MAX_PACKET_BYTES = 32 * 1024


def _bool_map(values: Mapping[str, Any]) -> dict[str, bool]:
    return {str(key): bool(value) for key, value in values.items()}


def _float_map(values: Mapping[str, Any]) -> dict[str, float]:
    return {str(key): float(value) for key, value in values.items()}


@dataclass(frozen=True)
class PicoPacket:
    session_id: str
    sequence: int
    source_monotonic_ns: int
    source_unix_ns: int
    left_controller: Pose
    right_controller: Pose
    headset: Pose | None = None
    buttons: dict[str, bool] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "session_id": self.session_id,
            "sequence": int(self.sequence),
            "source_monotonic_ns": int(self.source_monotonic_ns),
            "source_unix_ns": int(self.source_unix_ns),
            "left_controller": self.left_controller.as_pose7(),
            "right_controller": self.right_controller.as_pose7(),
            "headset": None if self.headset is None else self.headset.as_pose7(),
            "buttons": _bool_map(self.buttons),
            "values": _float_map(self.values),
        }

    def to_bytes(self) -> bytes:
        payload = json.dumps(
            self.to_dict(), separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
        if len(payload) > MAX_PACKET_BYTES:
            raise ValueError(f"packet exceeds {MAX_PACKET_BYTES} bytes")
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PicoPacket":
        if payload.get("schema") != SCHEMA:
            raise ValueError(f"unsupported schema: {payload.get('schema')!r}")
        sequence = int(payload["sequence"])
        if sequence < 0:
            raise ValueError("sequence must be non-negative")
        session_id = str(payload["session_id"]).strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        headset_raw = payload.get("headset")
        return cls(
            session_id=session_id,
            sequence=sequence,
            source_monotonic_ns=int(payload["source_monotonic_ns"]),
            source_unix_ns=int(payload["source_unix_ns"]),
            left_controller=Pose.from_pose7(payload["left_controller"]),
            right_controller=Pose.from_pose7(payload["right_controller"]),
            headset=None if headset_raw is None else Pose.from_pose7(headset_raw),
            buttons=_bool_map(payload.get("buttons", {})),
            values=_float_map(payload.get("values", {})),
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "PicoPacket":
        if len(payload) > MAX_PACKET_BYTES:
            raise ValueError(f"packet exceeds {MAX_PACKET_BYTES} bytes")
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("packet must decode to a JSON object")
        return cls.from_dict(decoded)


class SequenceGuard:
    """Rejects duplicates, reordering and packets from an old session."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.last_sequence = -1

    def accept(self, packet: PicoPacket) -> bool:
        if packet.session_id != self.session_id:
            self.session_id = packet.session_id
            self.last_sequence = packet.sequence
            return True
        if packet.sequence <= self.last_sequence:
            return False
        self.last_sequence = packet.sequence
        return True

