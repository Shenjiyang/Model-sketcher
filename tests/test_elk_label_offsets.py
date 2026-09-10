"""Bounded displaced ELK labels preserve mxGraph geometry and safety checks."""

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plan_layout_elk import _label_position, elk_graph, layout_problem, problem_from_region
from plan_layout import node_size
from view_projection import project_active_view


class ElkLabelOffsetTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("MODEL_SKETCHER_RUN_DRAWIO_RENDER_TESTS") == "1",
                         "Official renderer integration is opt-in")
    def test_official_drawio_negative_y_moves_upward_edge_label_right(self):
        with tempfile.TemporaryDirectory(prefix="elk-label-render-test-") as temp:
            folder = Path(temp)
            tree = ET.Element("mxfile")
            diagram = ET.SubElement(tree, "diagram", id="page", name="Page-1")
            graph = ET.SubElement(diagram, "mxGraphModel")
            root = ET.SubElement(graph, "root")
            ET.SubElement(root, "mxCell", id="0")
            ET.SubElement(root, "mxCell", id="1", parent="0")
            cell = ET.SubElement(root, "mxCell", id="offset-edge", value="LABEL", edge="1", parent="1",
                                 style="endArrow=classic;html=0;fontSize=20;")
            geometry = ET.SubElement(cell, "mxGeometry", x="0", y="-60", relative="1", attrib={"as": "geometry"})
            ET.SubElement(geometry, "mxPoint", x="100", y="300", attrib={"as": "sourcePoint"})
            ET.SubElement(geometry, "mxPoint", x="100", y="0", attrib={"as": "targetPoint"})
            ET.ElementTree(tree).write(folder / "input.drawio")
            result = subprocess.run(["drawio", "--no-sandbox", "--export", "--format", "svg", "--output",
                                     str(folder / "output.svg"), str(folder / "input.drawio")],
                                    text=True, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            svg = ET.parse(folder / "output.svg")
            ns = {"s": "http://www.w3.org/2000/svg"}
            edge = svg.find(".//s:g[@data-cell-id='offset-edge']", ns)
            route = edge.find(".//s:path", ns).get("d").split()
            path_x = float(route[1])
            label_x = float(edge.find(".//s:text", ns).get("x"))
            self.assertAlmostEqual(label_x - path_x, 60, delta=1)

    def test_prefers_on_route_when_clear(self):
        position, box = _label_position("e", [(100, 300), (100, 0)],
                                        {"x": 130, "y": 140, "width": 60, "height": 20}, 0)
        self.assertEqual(position["y"], 0)
        self.assertEqual(box["x"], 70)

    def test_label_reserves_configured_flank_plus_render_background(self):
        _, box = _label_position("e", [(0, 0), (300, 0)],
            {"x": 0, "y": -10, "width": 60, "height": 20}, 0,
            minimum_flank=22)
        self.assertGreaterEqual(box["x"], 30)

    def test_upward_route_preserves_right_label_with_negative_y(self):
        position, box = _label_position("e", [(100, 300), (100, 0)],
            {"x": 130, "y": 140, "width": 60, "height": 20}, 0,
            [{"x": 60, "y": 0, "w": 50, "h": 300}])
        self.assertEqual(position, {"x": 0, "y": -49})
        self.assertEqual(box, {"x": 119, "y": 140, "w": 60, "h": 20})

    def test_eastward_route_preserves_below_label_with_negative_y(self):
        position, box = _label_position("e", [(0, 100), (300, 100)],
            {"x": 120, "y": 150, "width": 60, "height": 20}, 0,
            [{"x": 0, "y": 60, "w": 300, "h": 50}])
        self.assertEqual(position, {"x": 0, "y": -29})
        self.assertEqual(box["y"], 119)

    def test_offset_does_not_bypass_other_route_or_bound(self):
        obstacles = [{"x": 60, "y": 0, "w": 50, "h": 300}]
        blocked_routes = [[(x, 0), (x, 300)] for x in range(-80, 281, 20)]
        with self.assertRaises(ValueError):
            _label_position("e", [(100, 300), (100, 0)],
                {"x": 130, "y": 140, "width": 60, "height": 20}, 0, obstacles, blocked_routes)
        position, _ = _label_position("e", [(100, 300), (100, 0)],
            {"x": 240, "y": 140, "width": 60, "height": 20}, 0, obstacles)
        self.assertLessEqual(abs(position["y"]), 160)
        self.assertNotEqual(position["y"], -170)

    def test_nonfinite_label_rejected(self):
        for key in ("x", "y", "width", "height"):
            label = {"x": 130, "y": 140, "width": 60, "height": 20}
            label[key] = math.nan
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "non-finite"):
                _label_position("e", [(100, 300), (100, 0)], label, 0)

    def test_between_layer_clearance_is_forwarded(self):
        graph = elk_graph({"nodes": {"a": {"w": 100, "h": 50}}, "edges": {},
                           "spacing": {"edge_node": 36}})
        self.assertEqual(float(graph["layoutOptions"]["elk.layered.spacing.edgeNodeBetweenLayers"]), 36)

    def test_real_mla_decode_when_local_fixture_available(self):
        source = ROOT.parent / "note/diagrams/sources/kimi-k3/elk-v0.0.5/architecture.json"
        if not source.exists() or shutil.which("node") is None:
            self.skipTest("Optional pinned local model fixture or Node unavailable")
        before = source.read_bytes()
        data = json.loads(before)
        data["project"]["semantic_view"] = "mla-decode"
        data = project_active_view(data)
        font = float(data["project"]["typography"]["ordinary_node_font"])
        problem = problem_from_region(data, "runtime_mla", {nid: node_size(n, font) for nid, n in data["nodes"].items()})
        layout = layout_problem(problem, ROOT / "scripts/elk_runner.cjs", "node")
        self.assertTrue(layout["edge_label_boxes"])
        self.assertTrue(any(edge.get("label_position", {}).get("y", 0) for edge in layout["edges"].values()))
        for edge in layout["edges"].values():
            if "label_position" in edge:
                self.assertLessEqual(abs(edge["label_position"]["y"]), 160)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
