import json
import math
import tempfile
import unittest
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "runtime" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from g1_boot_start_adjustment import (  # noqa: E402
    build_candidates,
    load_adjustment,
    pose_is_plausible,
    save_adjustment,
)


class BootStartAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.canonical = (1.0, 2.0, 0.25)

    def test_nominal_candidate_is_first_without_history(self):
        candidates = build_candidates(self.canonical, maximum_candidates=36)
        self.assertEqual(candidates[0]["name"], "boot_start_canonical_base")
        self.assertEqual(len(candidates), 36)
        self.assertTrue(
            all(item["distance_to_canonical_m"] <= 0.5 for item in candidates)
        )

    def test_learned_candidate_is_first_and_canonical_remains(self):
        learned = (1.08, 1.96, 0.30)
        candidates = build_candidates(
            self.canonical,
            adjusted_pose=learned,
            maximum_candidates=36,
        )
        self.assertEqual(candidates[0]["name"], "boot_start_learned_base")
        self.assertTrue(
            any(item["name"] == "boot_start_canonical_base" for item in candidates)
        )

    def test_adjustment_is_map_bound_and_distance_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adjustment.json"
            accepted = {
                "pose": {"x": 1.1, "y": 2.0, "yaw": 0.30},
                "candidate": {"name": "test"},
            }
            save_adjustment(path, "/map/a.pcd", self.canonical, accepted)
            loaded = load_adjustment(
                path,
                "/map/a.pcd",
                self.canonical,
                0.5,
                math.radians(30),
            )
            self.assertIsNotNone(loaded)
            self.assertIsNone(
                load_adjustment(
                    path,
                    "/map/b.pcd",
                    self.canonical,
                    0.5,
                    math.radians(30),
                )
            )

            data = json.loads(path.read_text(encoding="utf-8"))
            data["pose"]["x"] = 3.0
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertIsNone(
                load_adjustment(
                    path,
                    "/map/a.pcd",
                    self.canonical,
                    0.5,
                    math.radians(30),
                )
            )

    def test_plausibility_rejects_stable_but_wrong_match(self):
        self.assertTrue(
            pose_is_plausible(
                {"x": 1.2, "y": 2.0, "yaw": 0.3},
                self.canonical,
                0.75,
                math.radians(35),
            )
        )
        self.assertFalse(
            pose_is_plausible(
                {"x": 4.0, "y": 2.0, "yaw": 0.3},
                self.canonical,
                0.75,
                math.radians(35),
            )
        )


if __name__ == "__main__":
    unittest.main()
