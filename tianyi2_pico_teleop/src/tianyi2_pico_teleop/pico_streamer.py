"""XRoboToolkit callback adapter and low-latency UDP sender."""

from __future__ import annotations

import argparse
import math
import signal
import socket
import threading
import time
import uuid
from typing import Any, Mapping

from .geometry import Pose
from .protocol import PicoPacket


BUTTON_KEYS = {
    "left_key_one": ("left", "primary_button"),
    "left_key_two": ("left", "secondary_button"),
    "left_axis_click": ("left", "axis_click"),
    "right_key_one": ("right", "primary_button"),
    "right_key_two": ("right", "secondary_button"),
    "right_axis_click": ("right", "axis_click"),
}


def _pose7(value: Any) -> Pose:
    if isinstance(value, Mapping):
        for key in ("pose", "controller_pose", "tracking_pose"):
            if key in value:
                value = value[key]
                break
    if not isinstance(value, (list, tuple)) or len(value) < 7:
        raise ValueError("controller pose is unavailable")
    return Pose.from_pose7(value[:7])


def _controller(snapshot: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    controllers = snapshot.get("controllers", {})
    if isinstance(controllers, Mapping):
        controller = controllers.get(side, {})
        if isinstance(controller, Mapping):
            return controller
    return {}


def _controller_pose(snapshot: Mapping[str, Any], side: str) -> Pose:
    controller = _controller(snapshot, side)
    try:
        return _pose7(controller)
    except ValueError:
        pass
    for key in (f"{side}_controller_pose", f"{side}_controller", f"{side}_hand_pose"):
        if key in snapshot:
            return _pose7(snapshot[key])
    raise ValueError(f"{side} controller pose is unavailable")


def packet_from_snapshot(
    snapshot: Mapping[str, Any], *, session_id: str, sequence: int
) -> PicoPacket:
    left = _controller(snapshot, "left")
    right = _controller(snapshot, "right")
    buttons = {
        name: bool(_controller(snapshot, side).get(field, False))
        for name, (side, field) in BUTTON_KEYS.items()
    }
    left_trigger = float(left.get("trigger", 0.0))
    right_trigger = float(right.get("trigger", 0.0))
    left_grip = float(left.get("grip", 0.0))
    right_grip = float(right.get("grip", 0.0))
    buttons.update(
        {
            "left_index_trig": left_trigger > 1e-4,
            "left_grip": left_grip > 1e-4,
            "right_index_trig": right_trigger > 1e-4,
            "right_grip": right_grip > 1e-4,
        }
    )

    def axis(controller: Mapping[str, Any]) -> tuple[float, float]:
        raw = controller.get("axis", [0.0, 0.0])
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            return (0.0, 0.0)
        return (float(raw[0]), float(raw[1]))

    left_axis = axis(left)
    right_axis = axis(right)
    values = {
        "left_trigger": min(1.0, max(0.0, left_trigger)),
        "left_grip": min(1.0, max(0.0, left_grip)),
        "left_axis_x": left_axis[0],
        "left_axis_y": left_axis[1],
        "right_trigger": min(1.0, max(0.0, right_trigger)),
        "right_grip": min(1.0, max(0.0, right_grip)),
        "right_axis_x": right_axis[0],
        "right_axis_y": right_axis[1],
    }
    headset_raw = snapshot.get("headset_pose")
    return PicoPacket(
        session_id=session_id,
        sequence=sequence,
        source_monotonic_ns=time.monotonic_ns(),
        source_unix_ns=time.time_ns(),
        left_controller=_controller_pose(snapshot, "left"),
        right_controller=_controller_pose(snapshot, "right"),
        headset=None if headset_raw is None else _pose7(headset_raw),
        buttons=buttons,
        values=values,
    )


class LatestSnapshot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: Mapping[str, Any] | None = None
        self._received = 0

    def update(self, snapshot: Mapping[str, Any]) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._received += 1

    def get(self) -> tuple[Mapping[str, Any] | None, int]:
        with self._lock:
            return self._snapshot, self._received


def _mock_snapshot(t: float, *, press_start: bool = False) -> dict[str, Any]:
    """Create deterministic controller motion for local integration tests."""
    x = 0.18 * math.sin(t)
    z = 0.08 * math.sin(t * 0.5)
    return {
        "headset_pose": [0.0, 1.65, 0.0, 0.0, 0.0, 0.0, 1.0],
        "controllers": {
            "left": {
                "pose": [-0.3 + x, 1.25, 0.35 + z, 0.0, 0.0, 0.0, 1.0],
                "axis": [0.0, 0.0],
            },
            "right": {
                "pose": [0.3 - x, 1.25, 0.35 - z, 0.0, 0.0, 0.0, 1.0],
                "primary_button": press_start,
                "axis": [0.0, 0.0],
            },
        },
    }


def run(args: argparse.Namespace) -> None:
    target = (args.host, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    session_id = uuid.uuid4().hex
    latest = LatestSnapshot()
    stop = threading.Event()
    xrt = None

    def request_stop(*_: Any) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    if not args.mock:
        try:
            import xrobotoolkit_sdk as xrt_module
        except ImportError as exc:
            raise RuntimeError(
                "xrobotoolkit_sdk is required unless --mock is used"
            ) from exc
        xrt = xrt_module
        for name in ("init", "register_frame_callback", "clear_frame_callback", "close"):
            if not hasattr(xrt, name):
                raise RuntimeError(f"xrobotoolkit_sdk is missing {name}()")
        xrt.init()
        xrt.register_frame_callback(latest.update)

    period = 1.0 / args.fps
    sequence = 0
    sent = 0
    dropped = 0
    next_tick = time.monotonic()
    started_at = next_tick
    last_report = next_tick
    print(f"PICO streamer -> udp://{target[0]}:{target[1]} at {args.fps:g} Hz")
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                stop.wait(next_tick - now)
                continue
            next_tick = max(next_tick + period, now)
            if args.mock:
                elapsed = now - started_at
                # Delay the edge so the receiving ROS node has time to bind its UDP port.
                press_start = args.mock_autostart and 1.0 <= elapsed < 1.5
                snapshot = _mock_snapshot(elapsed, press_start=press_start)
            else:
                snapshot = latest.get()[0]
            if snapshot is None:
                dropped += 1
                continue
            try:
                packet = packet_from_snapshot(
                    snapshot, session_id=session_id, sequence=sequence
                )
                sock.sendto(packet.to_bytes(), target)
                sequence += 1
                sent += 1
            except (OSError, TypeError, ValueError) as exc:
                dropped += 1
                if args.verbose:
                    print(f"drop: {exc}")
            if now - last_report >= 1.0:
                callbacks = 0 if args.mock else latest.get()[1]
                print(f"health sent={sent} dropped={dropped} callbacks={callbacks}")
                last_report = now
    finally:
        if xrt is not None:
            xrt.clear_frame_callback()
            xrt.close()
        sock.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream PICO controllers to Tianyi 2.0")
    parser.add_argument("--host", required=True, help="robot computer IP")
    parser.add_argument("--port", type=int, default=28810)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument(
        "--mock-autostart",
        action="store_true",
        help="pulse the PICO A button after one second (only with --mock)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.port <= 0 or args.port > 65535:
        parser.error("--port must be in 1..65535")
    if args.fps <= 0.0:
        parser.error("--fps must be positive")
    if args.mock_autostart and not args.mock:
        parser.error("--mock-autostart requires --mock")
    return args


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
