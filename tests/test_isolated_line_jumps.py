from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from isolated_line_jumps import plan_isolated_line_jumps


def fixture(paths):
    problem, layout = {"edges": {}}, {"nodes": {}, "edges": {}, "edge_label_boxes": {}, "engine": {}}
    for eid, points in paths.items():
        source, target = eid + "-source", eid + "-target"
        problem["edges"][eid] = {"source": source, "target": target}
        for nid, p in ((source, points[0]), (target, points[-1])):
            layout["nodes"][nid] = {"x": p[0], "y": p[1] - 1, "w": 2, "h": 2}
        layout["edges"][eid] = {"source_port": {"side": "west", "position": .5},
                                 "target_port": {"side": "west", "position": .5},
                                 "waypoints": [list(p) for p in points[1:-1]]}
    return problem, layout


class IsolatedLineJumpTests(unittest.TestCase):
    def plan(self, paths, labels=None):
        problem, layout = fixture(paths)
        layout["edge_label_boxes"] = labels or {}
        return plan_isolated_line_jumps(problem, layout)

    def test_one_isolated_crossing_gets_deterministic_upper_edge(self):
        paths = {"a": [(-100, 0), (100, 0)], "z": [(0, -100), (0, 100)]}
        layout = self.plan(paths)
        self.assertNotIn("line_jump", layout["edges"]["a"])
        self.assertEqual(set(layout["edges"]["z"]["line_jump"]["crossings"]), {"a"})
        again = self.plan(dict(reversed(list(paths.items()))))
        self.assertEqual(layout["edges"], again["edges"])

    def test_two_well_separated_crossings_are_allowed(self):
        layout = self.plan({"z": [(-200, 0), (200, 0)],
                            "a": [(-60, -100), (-60, 100)], "b": [(60, -100), (60, 100)]})
        self.assertEqual(len(layout["edges"]["z"]["line_jump"]["crossings"]), 2)

    def test_cluster_is_not_papered_over(self):
        layout = self.plan({"z": [(-200, 0), (200, 0)],
                            "a": [(0, -100), (0, 100)], "b": [(20, -100), (20, 100)]})
        self.assertFalse(any("line_jump" in e for e in layout["edges"].values()))

    def test_one_upper_edge_cannot_mix_registered_and_unsafe_arcs(self):
        layout = self.plan({"z": [(-200, 0), (200, 0)],
                            "a": [(-100, -100), (-100, 100)],
                            "b": [(0, -100), (0, 100)], "c": [(20, -100), (20, 100)]})
        self.assertNotIn("line_jump", layout["edges"]["z"])

    def test_label_or_third_route_neighborhood_blocks_jump(self):
        paths = {"a": [(-100, 0), (100, 0)], "z": [(0, -100), (0, 100)]}
        layout = self.plan(paths, {"near": {"x": 10, "y": 10, "w": 30, "h": 10}})
        self.assertFalse(layout["engine"]["isolated_line_jumps"]["planned"])
        paths["neighbor"] = [(-40, 10), (40, 10)]
        self.assertFalse(self.plan(paths)["engine"]["isolated_line_jumps"]["planned"])

    def test_t_contact_and_short_bend_approach_are_not_jumps(self):
        for vertical in ([(0, 0), (0, 100)], [(0, -10), (0, 100)]):
            layout = self.plan({"a": [(-100, 0), (100, 0)], "z": vertical})
            self.assertFalse(layout["engine"]["isolated_line_jumps"]["planned"])

    def test_repeated_pair_and_dense_four_crossing_edge_rejected(self):
        layout = self.plan({"a": [(-100, 0), (100, 0)],
                            "z": [(-40, -100), (-40, 100), (40, 100), (40, -100)]})
        self.assertFalse(layout["engine"]["isolated_line_jumps"]["planned"])
        paths = {"z": [(-400, 0), (400, 0)]}
        paths.update({str(i): [(x, -100), (x, 100)] for i, x in enumerate((-240, -80, 80, 240))})
        self.assertFalse(self.plan(paths)["engine"]["isolated_line_jumps"]["planned"])


if __name__ == "__main__":
    unittest.main()
