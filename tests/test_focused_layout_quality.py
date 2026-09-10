import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from focused_layout_quality import candidate_quality


class CandidateQualityTests(unittest.TestCase):
    def test_straight_beats_avoidable_dogleg(self):
        problem = {"edges": {"e": {"source": "a", "target": "b"}}}
        layout = {"canvas": {"width": 200, "height": 400},
                  "nodes": {"a": dict(x=0, y=300, w=100, h=60),
                            "b": dict(x=0, y=0, w=100, h=60)},
                  "edges": {"e": {"source_port": {"side": "north", "position": .5},
                                  "target_port": {"side": "south", "position": .5}, "waypoints": []}}}
        good = candidate_quality(problem, layout)
        self.assertEqual(good["score"][0], 0)
        layout["edges"]["e"]["target_port"]["position"] = .7
        layout["edges"]["e"]["waypoints"] = [[50, 180], [70, 180]]
        bad = candidate_quality(problem, layout)
        self.assertGreater(bad["score"], good["score"])
        self.assertTrue(any("dogleg" in issue for issue in bad["route_errors"]))


if __name__ == "__main__":
    unittest.main()
