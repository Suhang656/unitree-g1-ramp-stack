import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import app.g1_motion_commands as commands


class MotionCommandTests(unittest.TestCase):
    def test_deterministic_route_commands(self) -> None:
        cases = {
            "\u76f4\u7ebf\u524d\u8fdb": commands.is_continuous_forward_command,
            "\u76f4\u7ebf\u8fd4\u56de": commands.is_ramp_return_command,
            "\u8f6c\u5f2f\u524d\u8fdb": commands.is_turning_forward_command,
            "\u8f6c\u5f2f\u8fd4\u56de": commands.is_turning_return_command,
            "\u505c\u6b62": commands.is_stop_command,
        }
        for text, predicate in cases.items():
            with self.subTest(text=text):
                self.assertTrue(predicate(text))


if __name__ == "__main__":
    unittest.main()
