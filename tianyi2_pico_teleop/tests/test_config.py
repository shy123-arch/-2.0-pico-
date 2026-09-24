from pathlib import Path
import unittest

from tianyi2_pico_teleop.config import load_config


CONFIG = Path(__file__).parents[1] / "config" / "tianyi2.template.yaml"


class ConfigTests(unittest.TestCase):
    def test_template_is_valid_for_dry_run(self):
        config = load_config(CONFIG)
        self.assertTrue(config.dry_run)
        self.assertFalse(config.hardware_verified)
        self.assertEqual(len(config.left.joints), 7)
        self.assertEqual(len(config.right.joints), 7)

    def test_template_refuses_hardware_mode(self):
        config = load_config(CONFIG)
        with self.assertRaisesRegex(ValueError, "hardware output is locked"):
            config.validate(for_hardware=True)


if __name__ == "__main__":
    unittest.main()
