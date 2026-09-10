"""Shortcut proofs include sibling routes and XML-relative label occupancy."""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_drawio import PageAudit, orthogonal_segments_conflict, avoidable_orthogonal_shortcut


class ShortcutObstacleTests(unittest.TestCase):
    def test_collinear_renderer_splits_do_not_count_as_bends(self):
        points = [(0, 100), (0, 90), (0, 80), (0, 70), (40, 70)]
        self.assertIsNone(avoidable_orthogonal_shortcut(points, lambda a, b: False))

    def test_one_pixel_perimeter_adjustment_is_not_a_material_staircase(self):
        points = [(300,201),(300,200),(200,200),(200,100),(100,100)]
        self.assertIsNone(avoidable_orthogonal_shortcut(points, lambda a, b: False))

    def test_common_endpoint_only_is_not_an_obstacle(self):
        self.assertFalse(orthogonal_segments_conflict((0, 0), (0, 100), (0, 0), (100, 0)))

    def test_sibling_positive_length_overlap_is_obstacle(self):
        self.assertTrue(orthogonal_segments_conflict((0, 0), (0, 100), (0, 0), (0, 50)))

    def test_sibling_interior_crossing_is_obstacle(self):
        self.assertTrue(orthogonal_segments_conflict((0, 0), (0, 100), (-50, 50), (50, 50)))

    def test_relative_label_position_matches_mxgraph_normal(self):
        model = ET.fromstring("""<mxGraphModel><root><mxCell id="0"/>
        <mxCell id="1" parent="0"/><mxCell id="e" edge="1" parent="1"
        value="shape" style="fontSize=20"><mxGeometry x="0" y="10" relative="1"
        as="geometry"><mxPoint x="3" y="4" as="offset"/></mxGeometry></mxCell>
        </root></mxGraphModel>""")
        audit = PageAudit('test', model, {})
        audit.prepare()
        box = audit.estimated_edge_label_box('e', [(0, 100), (0, 0)])
        self.assertAlmostEqual(box.x + box.w / 2, -7)
        self.assertAlmostEqual(box.y + box.h / 2, 54)
        self.assertGreater(box.w, 0)


if __name__ == '__main__':
    unittest.main()
