#!/usr/bin/env python3
"""Regression tests for static Draw.io XML compatibility checks."""

from __future__ import annotations

import importlib.util
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "audit_drawio.py"
SPEC = importlib.util.spec_from_file_location("audit_drawio", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class GeometryCollectionTests(unittest.TestCase):
    def audit_array(self, declaration: str) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target'>"
            f"<mxGeometry relative='1' as='geometry'>{declaration}</mxGeometry>"
            "</mxCell>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry width='10' height='10' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='20' width='10' height='10' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_geometry_collections()
        return audit.errors

    def test_bare_array_is_rejected(self) -> None:
        errors = self.audit_array("<Array><mxPoint x='10' y='10'/></Array>")
        self.assertTrue(any("missing as='points'" in error for error in errors))

    def test_points_array_is_accepted(self) -> None:
        self.assertEqual(
            self.audit_array("<Array as='points'><mxPoint x='10' y='10'/></Array>"),
            [],
        )


class ErrorSummaryTests(unittest.TestCase):
    def test_pairwise_failures_are_grouped_by_category_and_root_edge(self) -> None:
        summary = AUDIT.summarize_errors([
            "[page] edges cross without junction at (1, 2): edge:a / edge:b",
            "[page] edges cross without junction at (3, 4): edge:a / edge:c",
            "[page] edges overlap 10px: edge:a / edge:d",
        ])
        self.assertEqual(summary["categories"]["edge-edge crossing"], 2)
        self.assertEqual(summary["categories"]["edge-edge overlap"], 1)
        self.assertEqual(summary["root_edges"]["edge:a"], 3)


class FixedPortRangeTests(unittest.TestCase):
    def audit_ports(self, style: str, config: dict | None = None) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='200' width='100' height='50' as='geometry'/></mxCell>"
            f"<mxCell id='edge' edge='1' parent='1' source='source' target='target' style='{style}'>"
            "<mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, config or {"require_fixed_ports": True})
        audit.prepare()
        audit.check_ports_and_expected_edges()
        return audit.errors

    def test_out_of_range_fixed_port_is_rejected(self) -> None:
        errors = self.audit_ports("exitX=1.2;exitY=0;entryX=0.5;entryY=1;")
        self.assertTrue(any("outside [0,1]" in error for error in errors))

    def test_boundary_fixed_ports_are_accepted(self) -> None:
        self.assertEqual(
            self.audit_ports("exitX=1;exitY=0;entryX=0;entryY=1;"),
            [],
        )

    def test_interior_and_nonnumeric_ports_fail_cleanly(self) -> None:
        errors = self.audit_ports("exitX=0.5;exitY=0.5;entryX=0.5;entryY=0.5;")
        self.assertTrue(any("lies inside" in error for error in errors))
        errors = self.audit_ports("exitX=oops;exitY=0;entryX=0;entryY=1;")
        self.assertTrue(any("not numeric" in error for error in errors))

    def test_invalid_present_port_cannot_be_excluded(self) -> None:
        errors = self.audit_ports(
            "exitX=-0.1;exitY=0;entryX=0;entryY=1;",
            {"require_fixed_ports": False, "port_check_exclusions": ["edge"]},
        )
        self.assertTrue(any("outside [0,1]" in error for error in errors))


class LineJumpTests(unittest.TestCase):
    def audit_crossing(self, config: dict, *, jump_style: bool = True) -> list[str]:
        style = "jumpStyle=arc;jumpSize=12;" if jump_style else ""
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='left' vertex='1' parent='1'><mxGeometry x='0' y='90' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='right' vertex='1' parent='1'><mxGeometry x='180' y='90' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='top' vertex='1' parent='1'><mxGeometry x='90' y='0' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='bottom' vertex='1' parent='1'><mxGeometry x='90' y='180' width='20' height='20' as='geometry'/></mxCell>"
            f"<mxCell id='h' edge='1' parent='1' source='left' target='right' style='exitX=1;exitY=.5;entryX=0;entryY=.5;{style}'><mxGeometry relative='1' as='geometry'/></mxCell>"
            "<mxCell id='v' edge='1' parent='1' source='top' target='bottom' style='exitX=.5;exitY=1;entryX=.5;entryY=0;'><mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        regions, hierarchy, ignored = audit.vertex_sets()
        audit.check_routes(regions, hierarchy, ignored)
        return audit.errors

    def contract(self) -> dict:
        return {
            "line_jump_crossings": {
                "h|v": {
                    "jumper": "h", "style": "arc", "size": 12,
                    "reason": "An isolated perpendicular crossing remains after lane reflow.",
                }
            }
        }

    def test_unbridged_crossing_fails_and_arc_bridge_passes(self) -> None:
        errors = self.audit_crossing({})
        self.assertTrue(any("cross without junction" in error for error in errors), errors)
        bridged = self.audit_crossing(self.contract())
        self.assertFalse(any("cross without junction" in error for error in bridged), bridged)
        self.assertFalse(any("line-jump" in error or "line jump" in error for error in bridged), bridged)

    def test_legacy_allowlist_and_unrendered_bridge_fail(self) -> None:
        errors = self.audit_crossing({"allowed_edge_crossings": [["h", "v"]]})
        self.assertTrue(any("cannot prove visual separation" in error for error in errors), errors)
        errors = self.audit_crossing(self.contract(), jump_style=False)
        self.assertTrue(any("lacks jumpStyle=arc" in error for error in errors), errors)

class LogicalGranularityTests(unittest.TestCase):
    def test_operator_detail_rejects_fused_composite_exception(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region:detail' value='Level 2 Operator Detail' vertex='1' parent='1' "
            "style='swimlane;'><mxGeometry width='300' height='300' as='geometry'/></mxCell>"
            "<mxCell id='node:fused' value='Norm + Linear' vertex='1' parent='1'>"
            "<mxGeometry x='50' y='80' width='120' height='40' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "regions": ["region:detail"],
            "granularity_contracts": {
                "region:detail": {
                    "mode": "operator-detail",
                    "allowed_composites": {
                        "node:fused": {
                            "classification": "fused-operation",
                            "evidence": "code-confirmed",
                            "reason": "one fused call",
                            "source": "model.py:10",
                        }
                    },
                    "node_exclusions": {},
                }
            }
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        regions, hierarchy, ignored = audit.vertex_sets()
        audit.check_granularity_contracts(regions, hierarchy, ignored)
        self.assertTrue(any("cannot collapse logical members" in error for error in audit.errors))


class HierarchyArrowTests(unittest.TestCase):
    def audit_arrow(
        self, style: str, width: float = 96, height: float = 60,
        extra_config: dict | None = None,
    ) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='parent' vertex='1' parent='1'><mxGeometry width='100' height='60' as='geometry'/></mxCell>"
            f"<mxCell id='expand:test' value='expand' vertex='1' parent='1' style='{style}'>"
            f"<mxGeometry x='100' width='{width}' height='{height}' as='geometry'/></mxCell>"
            f"<mxCell id='child' vertex='1' parent='1'><mxGeometry x='{100 + width}' width='160' height='100' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "hierarchy_anchors": {
                "expand:test": {"parent": "parent", "child": "child", "direction": "right"},
            },
        }
        config.update(extra_config or {})
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        return audit.errors

    def test_large_white_block_arrow_is_accepted(self) -> None:
        self.assertEqual(
            self.audit_arrow("shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;"),
            [],
        )

    def test_region_boundary_attachment_preserves_semantic_parent_ownership(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region:owner' vertex='1' parent='1' style='swimlane;'>"
            "<mxGeometry width='200' height='160' as='geometry'/></mxCell>"
            "<mxCell id='node:parent' vertex='1' parent='1'><mxGeometry x='50' y='60' width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='expand:test' value='KDA Core -&gt; detail' vertex='1' parent='1' "
            "style='shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;'>"
            "<mxGeometry x='200' y='50' width='100' height='60' as='geometry'/></mxCell>"
            "<mxCell id='region:child' vertex='1' parent='1' style='swimlane;'>"
            "<mxGeometry x='300' width='180' height='160' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "regions": ["region:owner", "region:child"],
            "region_content_contracts": {"region:owner": ["node:parent"], "region:child": []},
            "hierarchy_anchors": {
                "expand:test": {
                    "parent": "node:parent", "attachment_mode": "owner-region-boundary",
                    "attachment": "region:owner", "anchor_label": "KDA Core",
                    "child": "region:child", "direction": "right",
                }
            },
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        self.assertEqual(audit.errors, [])

        config["hierarchy_anchors"]["expand:test"]["attachment"] = "region:child"
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        self.assertTrue(any("does not own semantic parent" in error for error in audit.errors))

        config["hierarchy_anchors"]["expand:test"]["attachment"] = "region:owner"
        config["region_content_contracts"]["region:owner"] = []
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        self.assertTrue(any("does not own semantic parent" in error for error in audit.errors))

    def test_tiny_hierarchy_arrow_is_rejected(self) -> None:
        errors = self.audit_arrow("shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;", 30, 20)
        self.assertTrue(any("too small" in error for error in errors))

    def test_cable_like_straight_hierarchy_arrow_is_rejected(self) -> None:
        errors = self.audit_arrow(
            "shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;", 500, 60
        )
        self.assertTrue(any("cable-like" in error for error in errors))
        self.assertEqual(
            self.audit_arrow(
                "shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;", 500, 60,
                {"straight_hierarchy_arrow_aspect_exceptions": {
                    "expand:test": "source-backed obstacle prevents a nearer child slot",
                }},
            ),
            [],
        )

    def test_registered_hierarchy_arrows_cannot_overlap(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='parent' vertex='1' parent='1'><mxGeometry width='100' height='120' as='geometry'/></mxCell>"
            "<mxCell id='expand:first' value='first' vertex='1' parent='1' style='shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;'>"
            "<mxGeometry x='100' y='20' width='100' height='60' as='geometry'/></mxCell>"
            "<mxCell id='expand:second' value='second' vertex='1' parent='1' style='shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;'>"
            "<mxGeometry x='100' y='20' width='100' height='60' as='geometry'/></mxCell>"
            "<mxCell id='child' vertex='1' parent='1'><mxGeometry x='200' width='160' height='120' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "hierarchy_anchors": {
                "expand:first": {"parent": "parent", "child": "child", "direction": "right"},
                "expand:second": {"parent": "parent", "child": "child", "direction": "right"},
            },
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        self.assertTrue(any("hierarchy arrows overlap" in error for error in audit.errors))

    def test_plain_vertex_cannot_satisfy_hierarchy_anchor(self) -> None:
        errors = self.audit_arrow("fillColor=#FFFFFF;strokeColor=#555555;")
        self.assertTrue(any("not a block-arrow vertex" in error for error in errors))

    def test_hierarchy_arrow_cannot_cover_an_execution_edge(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='parent' vertex='1' parent='1'><mxGeometry width='100' height='60' as='geometry'/></mxCell>"
            "<mxCell id='expand:test' value='expand' vertex='1' parent='1' "
            "style='shape=singleArrow;fillColor=#FFFFFF;strokeColor=#555555;'>"
            "<mxGeometry x='100' width='96' height='60' as='geometry'/></mxCell>"
            "<mxCell id='child' vertex='1' parent='1'><mxGeometry x='196' width='160' height='100' as='geometry'/></mxCell>"
            "<mxCell id='edge_source' vertex='1' parent='1'><mxGeometry x='130' y='-100' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='edge_target' vertex='1' parent='1'><mxGeometry x='130' y='100' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='tensor' edge='1' parent='1' source='edge_source' target='edge_target' "
            "style='exitX=0.5;exitY=1;entryX=0.5;entryY=0;'>"
            "<mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "hierarchy_anchors": {
                "expand:test": {"parent": "parent", "child": "child", "direction": "right"},
            },
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        self.assertTrue(any("crosses execution/relation edge" in error for error in audit.errors))

    def test_content_in_single_arrow_transparent_corner_is_not_rejected(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='parent' vertex='1' parent='1'><mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "<mxCell id='expand:test' value='expand' vertex='1' parent='1' "
            "style='shape=singleArrow;arrowWidth=0.5;arrowSize=0.4;fillColor=#FFFFFF;strokeColor=#555555;'>"
            "<mxGeometry x='100' width='200' height='100' as='geometry'/></mxCell>"
            "<mxCell id='child' vertex='1' parent='1'><mxGeometry x='300' width='160' height='100' as='geometry'/></mxCell>"
            "<mxCell id='corner_node' vertex='1' parent='1'><mxGeometry x='110' y='5' width='30' height='10' as='geometry'/></mxCell>"
            "<mxCell id='edge_source' vertex='1' parent='1'><mxGeometry x='110' y='20' width='10' height='10' as='geometry'/></mxCell>"
            "<mxCell id='edge_target' vertex='1' parent='1'><mxGeometry x='140' y='20' width='10' height='10' as='geometry'/></mxCell>"
            "<mxCell id='corner_edge' edge='1' parent='1' source='edge_source' target='edge_target' "
            "style='exitX=1;exitY=0.5;entryX=0;entryY=0.5;'>"
            "<mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "hierarchy_anchors": {
                "expand:test": {"parent": "parent", "child": "child", "direction": "right"},
            },
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_hierarchy()
        self.assertFalse(any("corner_node" in error or "corner_edge" in error for error in audit.errors))

    def test_visual_direction_must_match_manifest(self) -> None:
        errors = self.audit_arrow("shape=singleArrow;direction=west;fillColor=#FFFFFF;strokeColor=#555555;")
        self.assertTrue(any("visual direction disagrees" in error for error in errors))

    def test_expand_colon_vertex_cannot_escape_registration_by_losing_its_shape(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='expand:test' value='expand' vertex='1' parent='1'>"
            "<mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_hierarchy()
        self.assertTrue(any("unregistered hierarchy arrow" in error for error in audit.errors))


class FanoutSideTests(unittest.TestCase):
    def audit_sides(self, exits: list[tuple[float, float]]) -> list[str]:
        root = ET.Element("root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        source = ET.SubElement(root, "mxCell", {"id": "source", "vertex": "1", "parent": "1"})
        ET.SubElement(source, "mxGeometry", {"width": "100", "height": "50", "as": "geometry"})
        for index, (exit_x, exit_y) in enumerate(exits):
            target = ET.SubElement(root, "mxCell", {"id": f"target-{index}", "vertex": "1", "parent": "1"})
            ET.SubElement(target, "mxGeometry", {"x": str(index * 150), "y": "-100", "width": "100", "height": "50", "as": "geometry"})
            edge = ET.SubElement(root, "mxCell", {
                "id": f"edge-{index}", "edge": "1", "parent": "1",
                "source": "source", "target": f"target-{index}",
                "style": f"exitX={exit_x};exitY={exit_y};entryX=0.5;entryY=1;",
            })
            ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        audit = AUDIT.PageAudit("test", ET.Element("mxGraphModel"), {})
        audit.model.append(root)
        audit.cells = list(audit.model.iter("mxCell"))
        audit.prepare()
        audit.check_fanout_shape_contracts()
        return audit.errors

    def test_mixed_source_sides_are_rejected(self) -> None:
        errors = self.audit_sides([(0, 0.5), (0.5, 0), (1, 0.5)])
        self.assertTrue(any("mixed sides" in error for error in errors))

    def test_distinct_ports_on_one_side_are_accepted(self) -> None:
        self.assertEqual(self.audit_sides([(0.2, 0), (0.5, 0), (0.8, 0)]), [])


class VerticalFlowContractTests(unittest.TestCase):
    def audit_positions(
        self, source_y: float, target_y: float,
        source_x: float = 50, target_x: float = 50,
        exclusions: dict[str, str] | None = None,
    ) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region:model' vertex='1' parent='1'><mxGeometry width='1400' height='300' as='geometry'/></mxCell>"
            f"<mxCell id='node:input' vertex='1' parent='1'><mxGeometry x='{source_x}' y='{source_y}' width='100' height='40' as='geometry'/></mxCell>"
            f"<mxCell id='node:output' vertex='1' parent='1'><mxGeometry x='{target_x}' y='{target_y}' width='100' height='40' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "require_vertical_flow_contracts": True,
            "regions": ["region:model"],
            "vertical_flow_contracts": {
                "region:model": {
                    "direction": "bottom-to-top",
                    "sequences": [{"id": "main", "nodes": ["node:input", "node:output"]}],
                },
            },
            "vertical_flow_lateral_gap_exclusions": exclusions or {},
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_vertical_flow_contracts({"region:model"})
        return audit.errors

    def test_bottom_to_top_module_summary_passes(self) -> None:
        self.assertEqual(self.audit_positions(200, 50), [])

    def test_horizontal_or_downward_module_summary_fails(self) -> None:
        errors = self.audit_positions(50, 200)
        self.assertTrue(any("does not rise bottom-to-top" in error for error in errors))

    def test_extreme_lateral_drift_in_vertical_sequence_fails(self) -> None:
        errors = self.audit_positions(200, 50, source_x=50, target_x=1000)
        self.assertTrue(any("excessive lateral drift" in error for error in errors))
        self.assertEqual(
            self.audit_positions(
                200, 50, source_x=50, target_x=1000,
                exclusions={"node:input->node:output": "source-backed distant side lane"},
            ),
            [],
        )

    def test_adjacent_parallel_lane_offset_is_allowed(self) -> None:
        self.assertEqual(self.audit_positions(200, 50, source_x=50, target_x=500), [])

    def test_lateral_gap_exclusions_must_be_reasoned_and_current(self) -> None:
        errors = self.audit_positions(
            200, 50,
            exclusions={"node:missing->node:pair": ""},
        )
        self.assertTrue(any("exclusion missing reason" in error for error in errors))
        self.assertTrue(any("names no sequence step" in error for error in errors))

class EndpointClearanceTests(unittest.TestCase):
    def audit_gap(self, gap: float) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root>"
            "<mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry width='100' height='50' as='geometry'/></mxCell>"
            f"<mxCell id='target' vertex='1' parent='1'><mxGeometry x='{100 + gap}' width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target'><mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_edge_endpoint_clearance()
        return audit.errors

    def test_arrowhead_sized_gap_is_rejected(self) -> None:
        errors = self.audit_gap(10)
        self.assertTrue(any("no clear arrow approach" in error for error in errors))

    def test_visible_approach_gap_is_accepted(self) -> None:
        self.assertEqual(self.audit_gap(24), [])


class ExplicitDepartureTests(unittest.TestCase):
    def test_rectangular_source_cannot_leave_diagonally(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='200' y='-100' width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' style='exitX=0.5;exitY=0;entryX=0.5;entryY=1;'>"
            "<mxGeometry relative='1' as='geometry'><Array as='points'><mxPoint x='150' y='-50'/></Array></mxGeometry></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_routes(set(), set(), set())
        self.assertTrue(any("leaves rectangular source diagonally" in error for error in audit.errors))

    def test_two_point_route_cannot_leave_north_port_horizontally(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='200' width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' style='exitX=0.5;exitY=0;entryX=0.5;entryY=0;'>"
            "<mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.run()
        self.assertTrue(any("leaves endpoint tangentially" in error for error in audit.errors))

    def test_corner_port_uses_manifest_side_for_departure_direction(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='200' width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' style='exitX=0;exitY=0;entryX=0;entryY=0;'>"
            "<mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "expected_ports": {
                "edge": {
                    "exitX": 0, "exitY": 0, "entryX": 0, "entryY": 0,
                    "exitSide": "north", "entrySide": "west",
                }
            }
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.run()
        self.assertTrue(any("leaves endpoint tangentially" in error for error in audit.errors))


class RouteSimplificationTests(unittest.TestCase):
    def test_overlapping_endpoint_spans_require_direct_port_alignment(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry y='100' width='200' height='20' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='20' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' "
            "style='exitX=0.05;exitY=0;entryX=0.5;entryY=1;'>"
            "<mxGeometry relative='1' as='geometry'><Array as='points'>"
            "<mxPoint x='10' y='60'/><mxPoint x='30' y='60'/>"
            "</Array></mxGeometry></mxCell></root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_routes(set(), set(), set())
        self.assertTrue(any("port-alignment dogleg" in error for error in audit.errors))

    def test_port_alignment_dogleg_is_review_only_when_direct_corridor_is_blocked(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry y='100' width='200' height='20' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='20' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='blocker' vertex='1' parent='1'><mxGeometry x='25' y='70' width='10' height='20' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' "
            "style='exitX=0.05;exitY=0;entryX=0.5;entryY=1;'>"
            "<mxGeometry relative='1' as='geometry'><Array as='points'>"
            "<mxPoint x='10' y='60'/><mxPoint x='30' y='60'/>"
            "</Array></mxGeometry></mxCell></root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_routes(set(), set(), set())
        self.assertFalse(any("port-alignment dogleg" in error for error in audit.errors))
        self.assertTrue(any("direct corridor contains an obstacle" in warning for warning in audit.warnings))

    def audit_staircase(self, with_blocker: bool) -> list[str]:
        blocker = (
            "<mxCell id='blocker' vertex='1' parent='1'>"
            "<mxGeometry x='5' y='20' width='10' height='30' as='geometry'/></mxCell>"
            if with_blocker else ""
        )
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry y='100' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='80' width='20' height='20' as='geometry'/></mxCell>"
            f"{blocker}"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' "
            "style='exitX=0.5;exitY=0;entryX=0;entryY=0.5;'>"
            "<mxGeometry relative='1' as='geometry'><Array as='points'>"
            "<mxPoint x='10' y='60'/><mxPoint x='70' y='60'/><mxPoint x='70' y='10'/>"
            "</Array></mxGeometry></mxCell></root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_routes(set(), set(), set())
        return audit.errors

    def test_clear_staircase_is_rejected(self) -> None:
        errors = self.audit_staircase(False)
        self.assertTrue(any("avoidable orthogonal staircase" in error for error in errors))

    def test_staircase_around_real_obstacle_is_not_rejected_as_avoidable(self) -> None:
        errors = self.audit_staircase(True)
        self.assertFalse(any("avoidable orthogonal staircase" in error for error in errors))


class RegionGeometryTests(unittest.TestCase):
    def test_contracted_content_must_fit_region(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "<mxCell id='content' vertex='1' parent='1'><mxGeometry x='80' y='20' width='30' height='30' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {"region_content_contracts": {"region": ["content"]}})
        audit.prepare()
        audit.check_regions({"region"})
        self.assertTrue(any("content escapes region" in error for error in audit.errors))

    def test_edge_cannot_ride_region_boundary(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry x='10' y='100' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='70' y='100' width='20' height='20' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' "
            "style='exitX=0.5;exitY=0;entryX=0.5;entryY=0;'><mxGeometry relative='1' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_routes({"region"}, set(), set())
        self.assertTrue(any("rides on region boundary" in error for error in audit.errors))

    def test_uncontracted_node_cannot_cross_region_boundary(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "<mxCell id='node' vertex='1' parent='1'><mxGeometry x='80' y='20' width='40' height='40' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {})
        audit.prepare()
        audit.check_regions({"region"})
        self.assertTrue(any("partially crosses region boundary" in error for error in audit.errors))


class VisualClearanceTests(unittest.TestCase):
    def audit_nodes(self, gap: float) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='400' height='200' as='geometry'/></mxCell>"
            "<mxCell id='left' vertex='1' parent='1'><mxGeometry x='40' y='60' width='100' height='50' as='geometry'/></mxCell>"
            f"<mxCell id='right' vertex='1' parent='1'><mxGeometry x='{140 + gap}' y='60' width='100' height='50' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        config = {
            "minimum_node_gutter": 24,
            "region_content_contracts": {"region": ["left", "right"]},
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_visual_clearances({"region"}, set(), set())
        return audit.errors

    def audit_side_route(self, lane_x: float, config: dict) -> list[str]:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='300' height='220' as='geometry'/></mxCell>"
            "<mxCell id='source' vertex='1' parent='1'><mxGeometry x='100' y='150' width='60' height='30' as='geometry'/></mxCell>"
            "<mxCell id='target' vertex='1' parent='1'><mxGeometry x='100' y='30' width='60' height='30' as='geometry'/></mxCell>"
            "<mxCell id='edge' edge='1' parent='1' source='source' target='target' "
            "style='exitX=0;exitY=0.5;entryX=0;entryY=0.5;'>"
            "<mxGeometry relative='1' as='geometry'><Array as='points'>"
            f"<mxPoint x='{lane_x}' y='165'/><mxPoint x='{lane_x}' y='45'/>"
            "</Array></mxGeometry></mxCell></root></mxGraphModel>"
        )
        config = {
            **config,
            "region_content_contracts": {"region": ["source", "target"]},
        }
        audit = AUDIT.PageAudit("test", model, config)
        audit.prepare()
        audit.check_visual_clearances({"region"}, set(), set())
        return audit.errors

    def test_sibling_nodes_need_visible_gutter(self) -> None:
        self.assertTrue(any("node gutter is visually collapsed" in error for error in self.audit_nodes(8)))
        self.assertEqual(self.audit_nodes(30), [])

    def test_parallel_route_needs_clearance_from_node_edge(self) -> None:
        errors = self.audit_side_route(80, {"minimum_route_node_clearance": 32})
        self.assertTrue(any("too close and parallel to node" in error for error in errors))

    def test_parallel_route_needs_clearance_from_owner_region(self) -> None:
        errors = self.audit_side_route(5, {"minimum_route_region_boundary_clearance": 54})
        self.assertTrue(any("owner-region boundary" in error for error in errors))


class CompactExecutionGeometryTests(unittest.TestCase):
    def audit_directional_slack(self, node_x, node_y, limits):
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'>"
            "<mxGeometry width='400' height='400' as='geometry'/></mxCell>"
            f"<mxCell id='node' vertex='1' parent='1'><mxGeometry x='{node_x}' y='{node_y}' "
            "width='100' height='100' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "require_compact_execution_geometry": True,
            "maximum_region_content_slack": limits,
            "maximum_parallel_lane_gap": 160,
            "region_content_contracts": {"region": ["node"]},
        })
        audit.prepare()
        audit.check_compact_execution_geometry({"region"}, set(), set())
        return audit.errors

    def test_directional_budget_allows_title_clearance_only_at_top(self) -> None:
        limits = {"left": 200, "right": 200, "top": 160, "bottom": 200}
        self.assertEqual(self.audit_directional_slack(150, 150, limits), [])

        limits = {"left": 200, "right": 132, "top": 200, "bottom": 200}
        errors = self.audit_directional_slack(150, 150, limits)
        self.assertTrue(any("excessive right slack" in error and "> 132px" in error for error in errors))

        limits = {"left": 132, "right": 200, "top": 200, "bottom": 132}
        errors = self.audit_directional_slack(150, 150, limits)
        self.assertTrue(any("excessive left slack" in error for error in errors))
        self.assertTrue(any("excessive bottom slack" in error for error in errors))

    def test_directional_budget_is_fail_closed(self) -> None:
        malformed = {"left": 132, "right": 132, "top": 160}
        errors = self.audit_directional_slack(150, 150, malformed)
        self.assertTrue(any("must contain exactly" in error for error in errors))

        nonpositive = {"left": 132, "right": 132, "top": 160, "bottom": 0}
        errors = self.audit_directional_slack(150, 150, nonpositive)
        self.assertTrue(any("thresholds must be positive" in error for error in errors))

    def test_legacy_uniform_slack_budget_remains_readable(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='400' height='400' as='geometry'/></mxCell>"
            "<mxCell id='node' vertex='1' parent='1'><mxGeometry x='150' y='150' width='100' height='100' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "require_compact_execution_geometry": True,
            "maximum_region_content_side_slack": 140,
            "maximum_parallel_lane_gap": 160,
            "region_content_contracts": {"region": ["node"]},
        })
        audit.prepare()
        audit.check_compact_execution_geometry({"region"}, set(), set())
        self.assertEqual(
            {error.split(" slack:")[0].rsplit(" ", 1)[-1] for error in audit.errors},
            {"left", "right", "top", "bottom"},
        )

    def test_hierarchy_corridor_cannot_inflate_owner_region(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1' style='startSize=40;'>"
            "<mxGeometry width='700' height='300' as='geometry'/></mxCell>"
            "<mxCell id='a' vertex='1' parent='1'><mxGeometry x='60' y='180' width='100' height='50' as='geometry'/></mxCell>"
            "<mxCell id='b' vertex='1' parent='1'><mxGeometry x='60' y='80' width='100' height='50' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "require_compact_execution_geometry": True,
            "maximum_region_content_side_slack": 140,
            "maximum_parallel_lane_gap": 140,
            "region_content_contracts": {"region": ["a", "b"]},
            "vertical_flow_contracts": {"region": {"sequences": [{"id": "main", "nodes": ["a", "b"]}]}},
        })
        audit.prepare()
        audit.check_compact_execution_geometry({"region"}, set(), set())
        self.assertTrue(any("excessive right slack" in error for error in audit.errors))

    def test_parallel_branch_lanes_must_remain_adjacent(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='800' height='360' as='geometry'/></mxCell>"
            "<mxCell id='input' vertex='1' parent='1'><mxGeometry x='350' y='280' width='100' height='40' as='geometry'/></mxCell>"
            "<mxCell id='left' vertex='1' parent='1'><mxGeometry x='80' y='150' width='100' height='40' as='geometry'/></mxCell>"
            "<mxCell id='right' vertex='1' parent='1'><mxGeometry x='620' y='150' width='100' height='40' as='geometry'/></mxCell>"
            "<mxCell id='output' vertex='1' parent='1'><mxGeometry x='350' y='30' width='100' height='40' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "require_compact_execution_geometry": True,
            "maximum_region_content_side_slack": 1000,
            "maximum_parallel_lane_gap": 160,
            "region_content_contracts": {"region": ["input", "left", "right", "output"]},
            "vertical_flow_contracts": {"region": {"sequences": [
                {"id": "left_lane", "nodes": ["input", "left", "output"]},
                {"id": "right_lane", "nodes": ["input", "right", "output"]},
            ]}},
        })
        audit.prepare()
        audit.check_compact_execution_geometry({"region"}, set(), set())
        self.assertTrue(any("parallel lanes are spread apart" in error for error in audit.errors))

    def test_compact_parallel_lanes_and_reasoned_side_slack_exception_pass(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1' style='startSize=40;'>"
            "<mxGeometry width='520' height='340' as='geometry'/></mxCell>"
            "<mxCell id='input' vertex='1' parent='1'><mxGeometry x='210' y='260' width='100' height='40' as='geometry'/></mxCell>"
            "<mxCell id='left' vertex='1' parent='1'><mxGeometry x='110' y='150' width='100' height='40' as='geometry'/></mxCell>"
            "<mxCell id='right' vertex='1' parent='1'><mxGeometry x='260' y='150' width='100' height='40' as='geometry'/></mxCell>"
            "<mxCell id='output' vertex='1' parent='1'><mxGeometry x='210' y='60' width='100' height='40' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "require_compact_execution_geometry": True,
            "maximum_region_content_side_slack": 120,
            "maximum_parallel_lane_gap": 80,
            "region_side_slack_exceptions": {"region|right": "Named side-state route."},
            "parallel_lane_gap_exceptions": {},
            "region_content_contracts": {"region": ["input", "left", "right", "output"]},
            "vertical_flow_contracts": {"region": {"sequences": [
                {"id": "left_lane", "nodes": ["input", "left", "output"]},
                {"id": "right_lane", "nodes": ["input", "right", "output"]},
            ]}},
        })
        audit.prepare()
        audit.check_compact_execution_geometry({"region"}, set(), set())
        self.assertEqual(audit.errors, [])


class DensityContractTests(unittest.TestCase):
    def audit(self) -> AUDIT.PageAudit:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' vertex='1' parent='1'><mxGeometry width='400' height='300' as='geometry'/></mxCell>"
            "<mxCell id='node' vertex='1' parent='1'><mxGeometry x='20' y='60' width='100' height='50' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "regions": ["region"],
            "region_content_contracts": {"region": ["node"]},
            "density_contract": {
                "minimum_region_content_width_ratio": 0.35,
                "minimum_region_content_height_ratio": 0.35,
                "maximum_trailing_right_ratio": 0.30,
                "maximum_trailing_bottom_ratio": 0.30,
            },
        })
        audit.prepare()
        return audit

    def test_sparse_region_emits_actionable_warnings(self) -> None:
        audit = self.audit()
        audit.check_density_contract({"region"})
        self.assertTrue(any("horizontally sparse" in warning for warning in audit.warnings))
        self.assertTrue(any("trailing-bottom whitespace" in warning for warning in audit.warnings))
        self.assertTrue(any("shrinking by about" in warning for warning in audit.warnings))

    def test_region_exception_suppresses_density_warnings(self) -> None:
        audit = self.audit()
        audit.config["density_contract"]["region_exceptions"] = {
            "region": "Intentional routing reserve."
        }
        audit.check_density_contract({"region"})
        self.assertEqual(audit.warnings, [])

    def test_large_internal_void_between_lanes_is_reported(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='region' style='startSize=40;' vertex='1' parent='1'><mxGeometry width='1000' height='600' as='geometry'/></mxCell>"
            "<mxCell id='left-top' vertex='1' parent='1'><mxGeometry x='40' y='80' width='140' height='60' as='geometry'/></mxCell>"
            "<mxCell id='left-bottom' vertex='1' parent='1'><mxGeometry x='40' y='460' width='140' height='60' as='geometry'/></mxCell>"
            "<mxCell id='right-top' vertex='1' parent='1'><mxGeometry x='820' y='80' width='140' height='60' as='geometry'/></mxCell>"
            "<mxCell id='right-bottom' vertex='1' parent='1'><mxGeometry x='820' y='460' width='140' height='60' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "regions": ["region"],
            "region_content_contracts": {
                "region": ["left-top", "left-bottom", "right-top", "right-bottom"]
            },
            "density_contract": {
                "minimum_internal_void_area_ratio": 0.12,
                "minimum_internal_void_width_ratio": 0.30,
                "minimum_internal_void_height_ratio": 0.20,
                "internal_void_grid_size": 20,
                "internal_void_node_padding": 10,
            },
        })
        audit.prepare()
        audit.check_density_contract({"region"})
        self.assertTrue(any("internal whitespace pocket" in warning for warning in audit.warnings))

    def test_excluded_intervening_region_blocks_false_adjacency_warning(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='top' vertex='1' parent='1'><mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "<mxCell id='separator' vertex='1' parent='1'><mxGeometry y='180' width='100' height='200' as='geometry'/></mxCell>"
            "<mxCell id='bottom' vertex='1' parent='1'><mxGeometry y='460' width='100' height='100' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "density_contract": {
                "maximum_vertical_region_gap": 50,
                "region_exceptions": {"separator": "Large container excluded from density scoring."},
            },
        })
        audit.prepare()
        audit.check_density_contract({"top", "separator", "bottom"})
        self.assertFalse(any("top / bottom" in warning for warning in audit.warnings))

    def test_partial_intervening_region_does_not_hide_real_gap_warning(self) -> None:
        model = ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='top' vertex='1' parent='1'><mxGeometry width='100' height='100' as='geometry'/></mxCell>"
            "<mxCell id='separator' vertex='1' parent='1'><mxGeometry x='60' y='180' width='40' height='200' as='geometry'/></mxCell>"
            "<mxCell id='bottom' vertex='1' parent='1'><mxGeometry y='460' width='100' height='100' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )
        audit = AUDIT.PageAudit("test", model, {
            "density_contract": {
                "maximum_vertical_region_gap": 50,
                "region_exceptions": {"separator": "Partial side region."},
            },
        })
        audit.prepare()
        audit.check_density_contract({"top", "separator", "bottom"})
        self.assertTrue(any("top / bottom" in warning for warning in audit.warnings))


class ApparentTypographyTests(unittest.TestCase):
    @staticmethod
    def model() -> ET.Element:
        return ET.fromstring(
            "<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
            "<mxCell id='node' value='RMSNorm' style='fontSize=24;' vertex='1' parent='1'>"
            "<mxGeometry width='160' height='60' as='geometry'/></mxCell>"
            "</root></mxGraphModel>"
        )

    @staticmethod
    def contract(scale: float) -> dict:
        return {"typography_contract": {
            "ordinary_node_font": 24,
            "edge_label_font": 18,
            "annotation_font_min": 18,
            "nested_region_title_font": 24,
            "top_region_title_font": 30,
            "hierarchy_label_font": 19,
            "primary_view_scale": scale,
            "minimum_apparent_ordinary_font": 16,
            "target_apparent_ordinary_font": 18,
        }}

    def test_below_target_is_warning(self) -> None:
        audit = AUDIT.PageAudit("test", self.model(), self.contract(0.67))
        audit.prepare()
        audit.check_typography_contract(set(), set(), set())
        self.assertEqual(audit.errors, [])
        self.assertTrue(any("below target" in warning for warning in audit.warnings))

    def test_below_minimum_fails(self) -> None:
        audit = AUDIT.PageAudit("test", self.model(), self.contract(0.60))
        audit.prepare()
        audit.check_typography_contract(set(), set(), set())
        self.assertTrue(any("below minimum" in error for error in audit.errors))

    def test_legend_uses_annotation_font_floor(self) -> None:
        model = self.model()
        root = model.find("root")
        legend = ET.SubElement(root, "mxCell", {
            "id": "legend:tensor-op", "value": "Tensor Op",
            "style": "fontSize=18;", "vertex": "1", "parent": "1",
        })
        ET.SubElement(legend, "mxGeometry", {
            "x": "200", "width": "122", "height": "36", "as": "geometry",
        })
        audit = AUDIT.PageAudit("test", model, self.contract(0.75))
        audit.prepare()
        audit.check_typography_contract(set(), set(), set())
        self.assertEqual(audit.errors, [])


if __name__ == "__main__":
    unittest.main()
