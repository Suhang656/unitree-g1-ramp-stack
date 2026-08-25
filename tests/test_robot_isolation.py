from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RobotIsolationTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_command_plane_is_local_only_and_namespaced(self) -> None:
        helper = self.read("runtime/scripts/load_g1_command_plane.sh")
        self.assertIn("export ROS_LOCALHOST_ONLY=1", helper)
        self.assertIn('G1_COMMAND_PREFIX="/${G1_ROBOT_ID}/smart_center"', helper)
        self.assertIn("G1_ROBOT_ID 未配置", helper)

    def test_motion_bridge_requires_matching_robot_id(self) -> None:
        bridge = self.read("runtime/ros2/g1_motion_bridge.py")
        self.assertIn("request_robot_id != ROBOT_ID", bridge)
        self.assertIn("动作请求机器人ID不匹配", bridge)

    def test_dangerous_mode_and_return_are_locked_by_default(self) -> None:
        bridge = self.read("runtime/ros2/g1_motion_bridge.py")
        config = self.read("config/g1-ramp-stack.example")
        self.assertIn('G1_ALLOW_MODE_COMMANDS", "0"', bridge)
        self.assertIn('G1_ALLOW_RAMP_RETURN", "0"', bridge)
        self.assertIn("G1_ALLOW_MODE_COMMANDS=0", config)
        self.assertIn("G1_ALLOW_RAMP_RETURN=0", config)
        self.assertIn('G1_ALLOW_REAL_MOTION", "0"', bridge)
        self.assertIn("G1_ALLOW_REAL_MOTION=0", config)
        self.assertIn("真实运动总开关未授权", bridge)

    def test_unitree_interface_has_no_operational_default(self) -> None:
        config = self.read("config/g1-ramp-stack.example")
        bridge = self.read("runtime/ros2/g1_motion_bridge.py")
        guard = self.read("runtime/scripts/require_g1_unitree_interface.sh")
        self.assertIn("G1_UNITREE_INTERFACE=CHANGE_ME", config)
        self.assertIn('G1_UNITREE_INTERFACE", ""', bridge)
        self.assertNotIn("enP8p1s0", guard)

    def test_cli_uses_local_command_plane_and_robot_id(self) -> None:
        cli = self.read("bin/g1-ramp")
        self.assertIn("load_g1_command_plane.sh", cli)
        self.assertIn('\\"robot_id\\":\\"$G1_ROBOT_ID\\"', cli)
    def test_motion_topics_have_no_shared_fallback(self) -> None:
        bridge = self.read("runtime/ros2/g1_motion_bridge.py")
        launcher = self.read("runtime/scripts/start_g1_motion_bridge.sh")
        self.assertIn('"--request-topic",\n        required=True', bridge)
        self.assertNotIn(':-/smart_center/robot_action_request', launcher)
        self.assertIn('--response-topic "$ROS2_RESPONSE_TOPIC"', launcher)

    def test_tour_does_not_autostart_by_default(self) -> None:
        config = self.read("config/g1-ramp-stack.example")
        activate = self.read("deploy/activate.sh")
        self.assertIn("G1_ENABLE_TOUR=0", config)
        self.assertIn("G1_ENABLE_TOUR:-0", activate)


if __name__ == "__main__":
    unittest.main()
