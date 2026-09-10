#!/usr/bin/env python3
"""Focused regression tests for official-SVG geometry auditing."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import base64
import json
import struct
import zlib
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
AUDITOR = SKILL / "scripts/audit_rendered_svg.py"
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def png_data_uri(width: int, height: int, ink_width: int) -> str:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    rows = []
    for _ in range(height):
        pixels = b"".join(b"\x00\x00\x00\xff" if x < ink_width else b"\x00\x00\x00\x00" for x in range(width))
        rows.append(b"\x00" + pixels)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def cell(root: ET.Element, cell_id: str, *, vertex: bool = False, edge: bool = False,
         source: str = "", target: str = "", style: str = "", value: str = "x") -> None:
    attrs = {"id": cell_id, "parent": "1", "style": style, "value": value}
    if vertex:
        attrs["vertex"] = "1"
    if edge:
        attrs.update({"edge": "1", "source": source, "target": target})
    ET.SubElement(root, "mxCell", attrs)


def group(svg: ET.Element, cell_id: str, *, shape: tuple[float, float, float, float] | None = None,
          label: tuple[float, float, float, float] | None = None,
          route: list[tuple[float, float]] | None = None, label_href: str = "",
          arrow: tuple[float, float, float, float] | None = None,
          route_path: str = "") -> None:
    owner = ET.SubElement(svg, f"{{{SVG_NS}}}g", {"data-cell-id": cell_id})
    if shape:
        x, y, width, height = shape
        ET.SubElement(owner, f"{{{SVG_NS}}}rect", {
            "x": str(x), "y": str(y), "width": str(width), "height": str(height),
        })
    if route or route_path:
        data = route_path or "M " + " L ".join(f"{x} {y}" for x, y in route or [])
        ET.SubElement(owner, f"{{{SVG_NS}}}path", {"d": data, "style": "stroke: #000000;"})
    if arrow:
        x, y, width, height = arrow
        ET.SubElement(owner, f"{{{SVG_NS}}}path", {
            "d": f"M {x} {y} L {x + width} {y} L {x + width / 2} {y + height} Z",
            "style": "stroke: #000000; fill: #000000;",
        })
    if label:
        x, y, width, height = label
        switch = ET.SubElement(owner, f"{{{SVG_NS}}}switch")
        attrs = {
            "x": str(x), "y": str(y), "width": str(width), "height": str(height),
        }
        if label_href:
            attrs[XLINK_HREF] = label_href
        ET.SubElement(switch, f"{{{SVG_NS}}}image", attrs)


class RenderedSvgAuditTest(unittest.TestCase):
    def run_case(
        self, cells: list[dict], groups: list[dict], manifest: dict | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model = ET.Element("mxGraphModel")
            root = ET.SubElement(model, "root")
            ET.SubElement(root, "mxCell", {"id": "0"})
            ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
            for definition in cells:
                cell(root, **definition)
            diagram = directory / "case.drawio"
            ET.ElementTree(model).write(diagram, encoding="utf-8", xml_declaration=True)

            svg = ET.Element(f"{{{SVG_NS}}}svg")
            for definition in groups:
                group(svg, **definition)
            rendered = directory / "case.svg"
            ET.ElementTree(svg).write(rendered, encoding="utf-8", xml_declaration=True)
            command = [sys.executable, str(AUDITOR), str(diagram), str(rendered)]
            if manifest is not None:
                manifest_path = directory / "case.audit.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                command.extend(["--manifest", str(manifest_path)])
            return subprocess.run(
                command,
                capture_output=True, text=True, check=False,
            )

    def test_declared_line_jump_requires_rendered_arc(self) -> None:
        cells = [
            {"cell_id": "a", "vertex": True},
            {"cell_id": "b", "vertex": True},
            {"cell_id": "jumper", "edge": True, "source": "a", "target": "b", "value": ""},
        ]
        groups = [
            {"cell_id": "a", "shape": (0, 0, 20, 20), "label": (4, 4, 12, 12)},
            {"cell_id": "b", "shape": (100, 0, 20, 20), "label": (104, 4, 12, 12)},
            {"cell_id": "jumper", "route": [(20, 10), (100, 10)]},
        ]
        manifest = {
            "schema_version": 1,
            "defaults": {
                "rendered_svg_audit": {
                    "line_jump_crossings": {
                        "crossed|jumper": {
                            "jumper": "jumper", "style": "arc", "size": 12, "reason": "isolated crossing"
                        }
                    }
                }
            },
        }
        result = self.run_case(cells, groups, manifest)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("rendered arc bridges missing", result.stdout)
        groups[-1] = {
            "cell_id": "jumper",
            "route_path": "M 20 10 L 52 10 Q 60 2 68 10 L 100 10",
        }
        result = self.run_case(cells, groups, manifest)
        self.assertNotIn("rendered arc bridges missing", result.stdout)
        self.assertNotIn("near-horizontal dogleg", result.stdout)

    def base_nodes(self) -> tuple[list[dict], list[dict]]:
        cells = [
            {"cell_id": "a", "vertex": True},
            {"cell_id": "b", "vertex": True},
            {"cell_id": "e", "edge": True, "source": "a", "target": "b", "value": ""},
        ]
        groups = [
            {"cell_id": "a", "shape": (0, 0, 20, 20), "label": (4, 4, 12, 12)},
            {"cell_id": "b", "shape": (80, 0, 20, 20), "label": (84, 4, 12, 12)},
        ]
        return cells, groups

    def test_edge_through_unrelated_node_fails(self) -> None:
        cells, groups = self.base_nodes()
        cells.append({"cell_id": "blocker", "vertex": True})
        groups.extend([
            {"cell_id": "blocker", "shape": (40, 0, 20, 20), "label": (44, 4, 12, 12)},
            {"cell_id": "e", "route": [(35, 10), (80, 10)]},
        ])
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("edge crosses unrelated node: e / blocker", result.stdout)

    def test_edge_through_region_title_fails(self) -> None:
        cells, groups = self.base_nodes()
        cells.append({"cell_id": "region", "vertex": True, "style": "container=1;"})
        groups.extend([
            {"cell_id": "region", "shape": (30, -20, 40, 60), "label": (35, 4, 30, 12)},
            {"cell_id": "e", "route": [(20, 10), (80, 10)]},
        ])
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("edge crosses region-title text: e / region", result.stdout)

    def test_label_outside_own_node_fails(self) -> None:
        cells = [{"cell_id": "a", "vertex": True}]
        groups = [{"cell_id": "a", "shape": (0, 0, 20, 20), "label": (4, 4, 30, 12)}]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("label exceeds its node", result.stdout)

    def test_material_label_overlap_fails(self) -> None:
        cells = [{"cell_id": "a", "vertex": True}, {"cell_id": "b", "vertex": True}]
        groups = [
            {"cell_id": "a", "shape": (0, 0, 20, 20), "label": (4, 4, 20, 12)},
            {"cell_id": "b", "shape": (25, 0, 20, 20), "label": (18, 4, 20, 12)},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("rendered labels overlap: a / b", result.stdout)

    def test_narrow_but_legibility_destroying_label_overlap_fails(self) -> None:
        cells = [
            {"cell_id": "left", "edge": True, "value": "dense FFN output"},
            {"cell_id": "right", "edge": True, "value": "MoE output"},
        ]
        groups = [
            {"cell_id": "left", "label": (0, 0, 160, 24)},
            {"cell_id": "right", "label": (151, 8, 102, 24)},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("rendered labels overlap: left / right", result.stdout)

    def test_own_edge_label_on_straight_route_passes(self) -> None:
        cells, groups = self.base_nodes()
        cells[-1]["value"] = "shape"
        groups.append({"cell_id": "e", "route": [(20, 10), (80, 10)], "label": (42, 4, 16, 12)})
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_label_on_collinear_renderer_split_is_not_a_bend(self) -> None:
        cells, groups = self.base_nodes()
        cells[-1]["value"] = "shape"
        groups.append({
            "cell_id": "e",
            "route": [(20, 10), (50, 10), (80, 10)],
            "label": (42, 4, 16, 12),
        })
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("label contains a route bend", result.stdout)
        self.assertIn("rendered SVG audit: PASS", result.stdout)

    def test_own_edge_label_consuming_short_route_flank_fails(self) -> None:
        cells, groups = self.base_nodes()
        cells[-1]["value"] = "shape"
        groups.append({"cell_id": "e", "route": [(20, 10), (60, 10)], "label": (24, 4, 20, 12)})
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("label leaves an unreadably short visible flank", result.stdout)

    def test_split_point_near_label_does_not_shorten_actual_flank(self) -> None:
        cells, groups = self.base_nodes()
        cells[-1]["value"] = "shape"
        groups.append({"cell_id": "e", "route": [(20,10),(61,10),(80,10)],
                       "label": (42,4,16,12)})
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_edge_crossing_another_edge_label_fails(self) -> None:
        cells = [
            {"cell_id": "a", "vertex": True},
            {"cell_id": "b", "vertex": True},
            {"cell_id": "c", "vertex": True},
            {"cell_id": "d", "vertex": True},
            {"cell_id": "horizontal", "edge": True, "source": "a", "target": "b", "value": ""},
            {"cell_id": "vertical", "edge": True, "source": "c", "target": "d", "value": "v"},
        ]
        groups = [
            {"cell_id": "a", "shape": (0, 40, 20, 20)},
            {"cell_id": "b", "shape": (100, 40, 20, 20)},
            {"cell_id": "c", "shape": (50, 0, 20, 20)},
            {"cell_id": "d", "shape": (50, 100, 20, 20)},
            {"cell_id": "horizontal", "route": [(20, 50), (100, 50)]},
            {"cell_id": "vertical", "route": [(60, 20), (60, 100)], "label": (54, 44, 12, 12)},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "edge crosses or crowds unrelated edge label: horizontal / vertical",
            result.stdout,
        )

    def test_edge_crowding_another_edge_label_clearance_fails(self) -> None:
        cells = [
            {"cell_id": "a", "vertex": True},
            {"cell_id": "b", "vertex": True},
            {"cell_id": "c", "vertex": True},
            {"cell_id": "d", "vertex": True},
            {"cell_id": "route", "edge": True, "source": "a", "target": "b", "value": ""},
            {"cell_id": "label_owner", "edge": True, "source": "c", "target": "d", "value": "shape"},
        ]
        groups = [
            {"cell_id": "a", "shape": (0, 40, 20, 20)},
            {"cell_id": "b", "shape": (100, 40, 20, 20)},
            {"cell_id": "c", "shape": (0, 80, 20, 20)},
            {"cell_id": "d", "shape": (100, 80, 20, 20)},
            {"cell_id": "route", "route": [(20, 50), (100, 50)]},
            {"cell_id": "label_owner", "route": [(20, 90), (100, 90)], "label": (40, 51.5, 20, 12)},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "edge crosses or crowds unrelated edge label: route / label_owner",
            result.stdout,
        )

    def test_edge_label_detached_from_own_route_fails(self) -> None:
        cells, groups = self.base_nodes()
        cells[-1]["value"] = "shape"
        groups.append({"cell_id": "e", "route": [(20, 10), (80, 10)], "label": (500, 300, 40, 12)})
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("label is detached from its route", result.stdout)

    def test_overlapping_endpoint_spans_reject_port_alignment_dogleg(self) -> None:
        cells = [
            {"cell_id": "source", "vertex": True},
            {"cell_id": "target", "vertex": True},
            {
                "cell_id": "e", "edge": True, "source": "source", "target": "target",
                "style": "exitX=0.05;exitY=0;entryX=0.5;entryY=1;", "value": "",
            },
        ]
        groups = [
            {"cell_id": "source", "shape": (0, 100, 200, 20)},
            {"cell_id": "target", "shape": (20, 0, 20, 20)},
            {"cell_id": "e", "route": [(10, 100), (10, 60), (30, 60), (30, 20)]},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("port-alignment dogleg", result.stdout)

    def test_port_alignment_dogleg_with_direct_obstacle_is_review_only(self) -> None:
        cells = [
            {"cell_id": "source", "vertex": True},
            {"cell_id": "target", "vertex": True},
            {"cell_id": "blocker", "vertex": True},
            {
                "cell_id": "e", "edge": True, "source": "source", "target": "target",
                "style": "exitX=0.05;exitY=0;entryX=0.5;entryY=1;", "value": "",
            },
        ]
        groups = [
            {"cell_id": "source", "shape": (0, 100, 200, 20)},
            {"cell_id": "target", "shape": (20, 0, 20, 20)},
            {"cell_id": "blocker", "shape": (25, 70, 10, 20)},
            {"cell_id": "e", "route": [(10, 100), (10, 60), (30, 60), (30, 20)]},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("direct corridor contains an obstacle", result.stdout)

    def test_sibling_route_can_block_a_hypothetical_port_shortcut(self) -> None:
        cells = [
            {"cell_id": "source", "vertex": True},
            {"cell_id": "target", "vertex": True},
            {"cell_id": "side", "vertex": True},
            {"cell_id": "e", "edge": True, "source": "source", "target": "target",
             "style": "exitX=0.05;exitY=0;entryX=0.5;entryY=1;", "value": ""},
            {"cell_id": "sibling", "edge": True, "source": "source", "target": "side",
             "value": ""},
        ]
        groups = [
            {"cell_id": "source", "shape": (0, 100, 200, 20)},
            {"cell_id": "target", "shape": (20, 0, 20, 20)},
            {"cell_id": "side", "shape": (60, 60, 20, 20)},
            {"cell_id": "e", "route": [(10, 100), (10, 60), (30, 60), (30, 20)]},
            {"cell_id": "sibling", "route": [(20, 100), (20, 80), (70, 80)]},
        ]
        result = self.run_case(cells, groups)
        self.assertNotIn("ERROR: rendered avoidable vertical port-alignment dogleg", result.stdout)
        self.assertIn("direct corridor contains an obstacle", result.stdout)

    def test_shortcut_must_respect_route_node_clearance(self) -> None:
        cells = [{"cell_id": n, "vertex": True} for n in ["source", "target", "blocker"]]
        cells.append({"cell_id": "e", "edge": True, "source": "source", "target": "target",
                      "style": "exitX=0.05;exitY=0;entryX=0.5;entryY=1;", "value": ""})
        groups = [{"cell_id": "source", "shape": (0,100,200,20)},
                  {"cell_id": "target", "shape": (20,0,20,20)},
                  {"cell_id": "blocker", "shape": (40,70,10,20)},
                  {"cell_id": "e", "route": [(10,100),(10,60),(30,60),(30,20)]}]
        result = self.run_case(cells, groups, {"defaults": {"minimum_route_node_clearance": 20}})
        self.assertNotIn("ERROR: rendered avoidable vertical port-alignment dogleg", result.stdout)
        self.assertIn("direct corridor contains an obstacle", result.stdout)

    def test_parent_region_containing_child_passes(self) -> None:
        cells = [
            {"cell_id": "region", "vertex": True, "style": "container=1;"},
            {"cell_id": "child", "vertex": True},
        ]
        groups = [
            {"cell_id": "region", "shape": (0, 0, 100, 80), "label": (5, 5, 40, 12)},
            {"cell_id": "child", "shape": (20, 35, 30, 20), "label": (24, 39, 22, 12)},
        ]
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_transparent_region_label_padding_does_not_block_route(self) -> None:
        cells, groups = self.base_nodes()
        cells.append({"cell_id": "region", "vertex": True, "style": "container=1;"})
        groups.extend([
            {
                "cell_id": "region", "shape": (20, -20, 60, 60), "label": (20, 4, 60, 12),
                "label_href": png_data_uri(60, 12, 10),
            },
            {"cell_id": "e", "route": [(35, 10), (80, 10)]},
        ])
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_legal_source_target_contact_passes(self) -> None:
        cells, groups = self.base_nodes()
        groups.append({"cell_id": "e", "route": [(20, 10), (80, 10)]})
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_edge_label_covering_arrowhead_fails(self) -> None:
        cells, groups = self.base_nodes()
        cells[-1]["value"] = "shape"
        groups.append({
            "cell_id": "e", "route": [(20, 10), (80, 10)],
            "label": (72, 4, 16, 12), "arrow": (76, 6, 8, 8),
        })
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("label overlaps its arrowhead", result.stdout)

    def test_route_reentering_source_fails(self) -> None:
        cells, groups = self.base_nodes()
        groups.append({"cell_id": "e", "route": [(10, 0), (10, 12), (40, 12), (80, 10)]})
        result = self.run_case(cells, groups)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("enters or re-enters source node", result.stdout)

    def staircase_case(self, with_blocker: bool) -> subprocess.CompletedProcess[str]:
        cells = [
            {"cell_id": "source", "vertex": True},
            {"cell_id": "target", "vertex": True},
            {
                "cell_id": "edge", "edge": True, "source": "source", "target": "target",
                "style": "exitX=0.5;exitY=0;entryX=0;entryY=0.5;", "value": "",
            },
        ]
        groups = [
            {"cell_id": "source", "shape": (0, 100, 20, 20), "label": (4, 104, 12, 12)},
            {"cell_id": "target", "shape": (80, 0, 20, 20), "label": (84, 4, 12, 12)},
            {"cell_id": "edge", "route": [(10, 100), (10, 60), (70, 60), (70, 10), (80, 10)]},
        ]
        if with_blocker:
            cells.append({"cell_id": "blocker", "vertex": True})
            groups.append({"cell_id": "blocker", "shape": (5, 20, 10, 30), "label": (6, 24, 8, 10)})
        return self.run_case(cells, groups)

    def test_clear_rendered_staircase_fails(self) -> None:
        result = self.staircase_case(False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("rendered avoidable orthogonal staircase", result.stdout)

    def test_rendered_staircase_around_real_obstacle_is_not_flagged_as_avoidable(self) -> None:
        result = self.staircase_case(True)
        self.assertNotIn("rendered avoidable orthogonal staircase", result.stdout)

    def hierarchy_arrow_crossing_case(self, route_y: float) -> subprocess.CompletedProcess[str]:
        cells = [
            {"cell_id": "source", "vertex": True},
            {"cell_id": "target", "vertex": True},
            {
                "cell_id": "edge", "edge": True, "source": "source", "target": "target",
                "style": "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", "value": "",
            },
            {
                "cell_id": "expand:test", "vertex": True,
                "style": "shape=singleArrow;direction=east;arrowWidth=0.3;arrowSize=0.2;",
            },
        ]
        groups = [
            {"cell_id": "source", "shape": (0, route_y - 10, 20, 20), "label": (4, route_y - 6, 12, 12)},
            {"cell_id": "target", "shape": (80, route_y - 10, 20, 20), "label": (84, route_y - 6, 12, 12)},
            {"cell_id": "edge", "route": [(20, route_y), (80, route_y)]},
            {"cell_id": "expand:test", "shape": (30, 0, 100, 40)},
        ]
        return self.run_case(cells, groups)

    def test_rendered_route_in_single_arrow_transparent_corner_does_not_collide(self) -> None:
        result = self.hierarchy_arrow_crossing_case(5)
        self.assertNotIn("edge crosses unrelated node: edge / expand:test", result.stdout)

    def test_rendered_route_through_single_arrow_shaft_collides(self) -> None:
        result = self.hierarchy_arrow_crossing_case(20)
        self.assertIn("edge crosses unrelated node: edge / expand:test", result.stdout)


if __name__ == "__main__":
    unittest.main()
