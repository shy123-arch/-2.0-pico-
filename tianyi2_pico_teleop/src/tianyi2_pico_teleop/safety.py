"""Safety primitives kept independent from ROS so they can be unit tested."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


@dataclass(frozen=True)
class JointSpec:
    model_joint: str
    motor_id: int
    minimum: float
    maximum: float
    max_velocity: float

    def validate(self) -> None:
        if not self.model_joint or self.model_joint.startswith("CHANGE_ME"):
            raise ValueError("model_joint is not configured")
        if self.motor_id < 0:
            raise ValueError(f"motor id for {self.model_joint} is not configured")
        if self.minimum >= self.maximum:
            raise ValueError(f"invalid limits for {self.model_joint}")
        if self.max_velocity <= 0.0:
            raise ValueError(f"max_velocity must be positive for {self.model_joint}")


@dataclass(frozen=True)
class LimitedTarget:
    positions: dict[str, float]
    clipped_joints: tuple[str, ...]


def limit_joint_targets(
    current: Mapping[str, float],
    desired: Mapping[str, float],
    specs: list[JointSpec],
    dt: float,
    global_max_step: float,
) -> LimitedTarget:
    if dt <= 0.0:
        raise ValueError("dt must be positive")
    if global_max_step <= 0.0:
        raise ValueError("global_max_step must be positive")

    output: dict[str, float] = {}
    clipped: list[str] = []
    for spec in specs:
        if spec.model_joint not in current or spec.model_joint not in desired:
            raise KeyError(f"missing joint value for {spec.model_joint}")
        now = float(current[spec.model_joint])
        requested = float(desired[spec.model_joint])
        bounded = min(spec.maximum, max(spec.minimum, requested))
        allowed_step = min(global_max_step, spec.max_velocity * dt)
        stepped = min(now + allowed_step, max(now - allowed_step, bounded))
        if abs(stepped - requested) > 1e-9:
            clipped.append(spec.model_joint)
        output[spec.model_joint] = stepped
    return LimitedTarget(output, tuple(clipped))


class TeleopState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    HOLD = "hold"
    ESTOP = "estop"


@dataclass(frozen=True)
class StateDecision:
    state: TeleopState
    calibrate: bool = False
    reason: str = ""


class TeleopStateMachine:
    """Edge-triggered PICO state machine. E-stop requires a local reset."""

    def __init__(
        self,
        start_button: str = "right_key_one",
        stop_button: str = "left_key_one",
        estop_buttons: tuple[str, str] = ("left_key_one", "left_key_two"),
    ) -> None:
        self.state = TeleopState.IDLE
        self.start_button = start_button
        self.stop_button = stop_button
        self.estop_buttons = estop_buttons
        self._previous: dict[str, bool] = {}

    def _rising(self, buttons: Mapping[str, bool], name: str) -> bool:
        return bool(buttons.get(name, False)) and not bool(self._previous.get(name, False))

    def update(
        self,
        buttons: Mapping[str, bool],
        *,
        packet_fresh: bool,
        feedback_fresh: bool,
        integration_ready: bool,
    ) -> StateDecision:
        estop = all(bool(buttons.get(name, False)) for name in self.estop_buttons)
        start_edge = self._rising(buttons, self.start_button)
        stop_edge = self._rising(buttons, self.stop_button)
        self._previous = _bool_copy(buttons)

        if estop:
            self.state = TeleopState.ESTOP
            return StateDecision(self.state, reason="PICO emergency-stop combination")
        if self.state is TeleopState.ESTOP:
            return StateDecision(self.state, reason="local reset required")
        if stop_edge:
            self.state = TeleopState.HOLD
            return StateDecision(self.state, reason="PICO pause button")
        if not packet_fresh:
            self.state = TeleopState.HOLD
            return StateDecision(self.state, reason="PICO packet watchdog")
        if not feedback_fresh:
            self.state = TeleopState.HOLD
            return StateDecision(self.state, reason="robot feedback watchdog")
        if start_edge:
            if not integration_ready:
                self.state = TeleopState.HOLD
                return StateDecision(self.state, reason="integration contract is not ready")
            self.state = TeleopState.ACTIVE
            return StateDecision(self.state, calibrate=True, reason="PICO start button")
        return StateDecision(self.state)

    def reset_estop_locally(self) -> None:
        self.state = TeleopState.IDLE
        self._previous.clear()


def _bool_copy(values: Mapping[str, bool]) -> dict[str, bool]:
    return {str(key): bool(value) for key, value in values.items()}

