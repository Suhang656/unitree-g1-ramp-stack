import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentRuntimeTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_smart_center_loads_vendor_dependencies(self):
        script = self.read("runtime/scripts/start_ros2_node.sh")
        self.assertIn("$PROJECT_DIR:$PROJECT_DIR/vendor", script)
        self.assertIn("/usr/bin/python3", script)

    def test_assistant_does_not_require_boot_localization(self):
        unit = self.read("systemd/units/g1-local-assistant.service")
        self.assertNotIn("Requires=g1-ramp-v3-bootstrap.service", unit)
        self.assertNotIn("After=g1-ramp-v3-bootstrap.service", unit)

    def test_cli_sources_ros_before_nounset_and_splits_locals(self):
        script = self.read("bin/g1-ramp")
        source_index = script.index("source /opt/ros/humble/setup.bash")
        nounset_index = script.index("set -u")
        self.assertLess(source_index, nounset_index)
        self.assertIn('local target="$1"\n', script)
        self.assertIn('local task="cli-${target}-$(date +%s)"', script)

    def test_long_localization_starts_are_nonblocking(self):
        activate = self.read("deploy/activate.sh")
        motion = self.read("deploy/enable_motion.sh")
        self.assertIn(
            "systemctl start --no-block g1-ramp-v3-bootstrap.service",
            activate,
        )
        self.assertIn(
            "systemctl start --no-block g1-local-assistant.service",
            motion,
        )


if __name__ == "__main__":
    unittest.main()
