import unittest

from tianyi2_pico_teleop.pico_streamer import packet_from_snapshot


class PicoStreamerTests(unittest.TestCase):
    def test_snapshot_mapping_matches_xrobot_callback_shape(self):
        snapshot = {
            "headset_pose": [0, 1.7, 0, 0, 0, 0, 1],
            "controllers": {
                "left": {
                    "pose": [-0.2, 1.2, 0.3, 0, 0, 0, 1],
                    "primary_button": True,
                    "trigger": 0.4,
                    "grip": 0.2,
                    "axis": [0.1, -0.2],
                },
                "right": {
                    "pose": [0.2, 1.2, 0.3, 0, 0, 0, 1],
                    "secondary_button": True,
                    "trigger": 0.7,
                    "grip": 0.8,
                    "axis": [-0.3, 0.4],
                },
            },
        }
        packet = packet_from_snapshot(snapshot, session_id="test", sequence=9)
        self.assertEqual(packet.sequence, 9)
        self.assertTrue(packet.buttons["left_key_one"])
        self.assertTrue(packet.buttons["right_key_two"])
        self.assertEqual(packet.values["right_grip"], 0.8)
        self.assertEqual(packet.values["left_axis_y"], -0.2)


if __name__ == "__main__":
    unittest.main()
