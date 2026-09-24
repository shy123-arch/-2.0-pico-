import unittest

from tianyi2_pico_teleop.safety import (
    JointSpec,
    TeleopState,
    TeleopStateMachine,
    limit_joint_targets,
)


class SafetyTests(unittest.TestCase):
    def test_joint_target_limit_applies_position_velocity_and_step_limits(self):
        specs = [JointSpec("j1", 1, -1.0, 1.0, 0.5)]
        result = limit_joint_targets(
            {"j1": 0.0}, {"j1": 2.0}, specs, dt=0.1, global_max_step=0.02
        )
        self.assertAlmostEqual(result.positions["j1"], 0.02)
        self.assertEqual(result.clipped_joints, ("j1",))

    def test_state_machine_start_pause_estop_and_local_reset(self):
        machine = TeleopStateMachine()
        decision = machine.update(
            {}, packet_fresh=True, feedback_fresh=True, integration_ready=True
        )
        self.assertIs(decision.state, TeleopState.IDLE)

        decision = machine.update(
            {"right_key_one": True},
            packet_fresh=True,
            feedback_fresh=True,
            integration_ready=True,
        )
        self.assertIs(decision.state, TeleopState.ACTIVE)
        self.assertTrue(decision.calibrate)

        decision = machine.update(
            {"left_key_one": True},
            packet_fresh=True,
            feedback_fresh=True,
            integration_ready=True,
        )
        self.assertIs(decision.state, TeleopState.HOLD)

        decision = machine.update(
            {"left_key_one": True, "left_key_two": True},
            packet_fresh=True,
            feedback_fresh=True,
            integration_ready=True,
        )
        self.assertIs(decision.state, TeleopState.ESTOP)
        machine.reset_estop_locally()
        self.assertIs(machine.state, TeleopState.IDLE)

    def test_watchdog_forces_hold(self):
        machine = TeleopStateMachine()
        machine.update(
            {"right_key_one": True},
            packet_fresh=True,
            feedback_fresh=True,
            integration_ready=True,
        )
        decision = machine.update(
            {}, packet_fresh=False, feedback_fresh=True, integration_ready=True
        )
        self.assertIs(decision.state, TeleopState.HOLD)


if __name__ == "__main__":
    unittest.main()
