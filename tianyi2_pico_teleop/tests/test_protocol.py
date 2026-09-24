import unittest

from tianyi2_pico_teleop.geometry import Pose
from tianyi2_pico_teleop.protocol import PicoPacket, SequenceGuard


def packet(session="one", sequence=0):
    return PicoPacket(
        session_id=session,
        sequence=sequence,
        source_monotonic_ns=123,
        source_unix_ns=456,
        left_controller=Pose.identity(),
        right_controller=Pose((1, 2, 3), (0, 0, 0, 1)),
        buttons={"right_key_one": True},
        values={"left_axis_x": 0.25},
    )


class ProtocolTests(unittest.TestCase):
    def test_packet_round_trip(self):
        restored = PicoPacket.from_bytes(packet().to_bytes())
        self.assertEqual(restored, packet())

    def test_sequence_guard_rejects_duplicates_and_reordering(self):
        guard = SequenceGuard()
        self.assertTrue(guard.accept(packet(sequence=4)))
        self.assertFalse(guard.accept(packet(sequence=4)))
        self.assertFalse(guard.accept(packet(sequence=3)))
        self.assertTrue(guard.accept(packet(sequence=5)))
        self.assertTrue(guard.accept(packet(session="new", sequence=0)))


if __name__ == "__main__":
    unittest.main()
