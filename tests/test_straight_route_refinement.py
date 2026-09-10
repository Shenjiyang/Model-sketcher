import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from straight_route_refinement import refine_straight_routes


class StraightRouteTests(unittest.TestCase):
    def test_staircase_can_shorten_without_moving_existing_crossing(self):
        boxes = {"a": dict(x=-10, y=400, w=20, h=20),
                 "b": dict(x=190, y=0, w=20, h=20),
                 "c": dict(x=-110, y=330, w=20, h=20),
                 "d": dict(x=90, y=330, w=20, h=20)}
        edges = {"e": dict(source="a", target="b", source_side="north", target_side="south"),
                 "rail": dict(source="c", target="d", source_side="east", target_side="west")}
        paths = {"e": [(0,400),(0,300),(50,300),(50,100),(200,100),(200,20)],
                 "rail": [(-90,340),(90,340)]}
        result = refine_straight_routes(boxes, edges, paths, preserve_existing_crossings=True)
        self.assertEqual(result["e"], [(0,400),(0,100),(200,100),(200,20)])
        self.assertEqual(result["rail"], paths["rail"])

    def fixture(self):
        boxes = {"split": dict(x=200, y=400, w=340, h=60),
                 "left": dict(x=80, y=200, w=270, h=60),
                 "right": dict(x=410, y=200, w=280, h=60)}
        edges = {"a": dict(source="split", target="left", source_side="north", target_side="south"),
                 "b": dict(source="split", target="right", source_side="north", target_side="south")}
        paths = {"a": [(310, 400), (310, 380), (215, 380), (215, 260)],
                 "b": [(430, 400), (430, 380), (550, 380), (550, 260)]}
        return boxes, edges, paths

    def test_fanout_straightens_without_port_collision(self):
        boxes, edges, paths = self.fixture()
        actual = refine_straight_routes(boxes, edges, paths)
        self.assertEqual([len(actual[key]) for key in ("a", "b")], [2, 2])
        self.assertLess(actual["a"][0][0], actual["b"][0][0])
        self.assertEqual(len(paths["a"]), 4)
        self.assertEqual(actual, refine_straight_routes(boxes, edges, actual))

    def test_obstacle_keeps_detour(self):
        boxes, edges, paths = self.fixture()
        boxes["obstacle"] = dict(x=200, y=290, w=150, h=40)
        self.assertEqual(refine_straight_routes(boxes, edges, paths)["a"], paths["a"])

    def test_crossing_keeps_detour(self):
        boxes, edges, paths = self.fixture()
        edges["rail"] = dict(source="left", target="right", source_side="east", target_side="west")
        paths["rail"] = [(80, 330), (700, 330)]
        actual = refine_straight_routes(boxes, edges, paths)
        self.assertEqual(actual["a"], paths["a"])
        self.assertEqual(actual["b"], paths["b"])

    def test_reverse_direction_not_straightened(self):
        boxes, edges, paths = self.fixture()
        edges["a"]["source_side"] = "south"
        edges["a"]["target_side"] = "north"
        self.assertEqual(refine_straight_routes(boxes, edges, paths)["a"], paths["a"])


if __name__ == "__main__":
    unittest.main()
