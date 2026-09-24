from math import cos, pi, sin
import unittest

from tianyi2_pico_teleop.geometry import AnchorMapper, Pose, compose, inverse


class GeometryTests(unittest.TestCase):
    def assert_sequence_close(self, actual, expected, places=8):
        self.assertEqual(len(actual), len(expected))
        for left, right in zip(actual, expected):
            self.assertAlmostEqual(left, right, places=places)

    def test_pose_inverse_round_trip(self):
        pose = Pose((1.0, -2.0, 0.5), (0.0, 0.0, sin(pi / 4), cos(pi / 4)))
        identity = compose(pose, inverse(pose))
        self.assert_sequence_close(identity.position, (0.0, 0.0, 0.0))
        self.assert_sequence_close(identity.quaternion_xyzw, (0.0, 0.0, 0.0, 1.0))

    def test_anchor_mapper_keeps_robot_anchor_at_calibration(self):
        controller = Pose((10.0, 4.0, -2.0), (0.0, 0.0, 0.0, 1.0))
        robot = Pose((0.4, 0.2, 1.1), (0.0, 0.0, 0.0, 1.0))
        mapper = AnchorMapper(position_scale=0.5)
        mapper.calibrate(controller, robot)
        mapped = mapper.map(controller)
        self.assert_sequence_close(mapped.position, robot.position)
        self.assert_sequence_close(mapped.quaternion_xyzw, robot.quaternion_xyzw)

    def test_anchor_mapper_scales_relative_translation(self):
        mapper = AnchorMapper(position_scale=0.5)
        mapper.calibrate(Pose.identity(), Pose((1, 2, 3), (0, 0, 0, 1)))
        mapped = mapper.map(Pose((0.2, -0.4, 0.6), (0, 0, 0, 1)))
        self.assert_sequence_close(mapped.position, (1.1, 1.8, 3.3))


if __name__ == "__main__":
    unittest.main()
