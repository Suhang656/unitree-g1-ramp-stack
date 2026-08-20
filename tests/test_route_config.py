import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RouteConfigTests(unittest.TestCase):
    def test_turning_return_is_exact_reverse(self) -> None:
        path = ROOT / "runtime" / "data" / "embodied_lab_panorama_v2" / "routes_v1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        forward = data["routes"]["turning_forward"]["points"]
        returning = data["routes"]["turning_return"]["points"]
        self.assertEqual(forward[0], data["shared_start"])
        self.assertEqual(forward[-1], data["shared_end"])
        self.assertEqual(list(reversed(forward)), returning)

    def test_all_route_points_exist(self) -> None:
        path = ROOT / "runtime" / "data" / "embodied_lab_panorama_v2" / "routes_v1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        names = set(data["points"])
        for route in data["routes"].values():
            self.assertLessEqual(set(route["points"]), names)


if __name__ == "__main__":
    unittest.main()
