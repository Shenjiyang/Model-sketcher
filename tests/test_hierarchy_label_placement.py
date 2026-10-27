#!/usr/bin/env python3
"""Regression tests for hierarchy arrow corner protection and label placement."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from plan_layout import (
    HIERARCHY_ARROW_THICKNESS,
    HIERARCHY_CORNER_MARGIN,
    HIERARCHY_LABEL_GAP,
    _place_beside,
    finalize_hierarchy_labels,
    hierarchy_corridor_findings,
    plan_hierarchy_arrows,
)
from hierarchy_arrow_geometry import single_arrow_cell_area
from typography import wrapped_label_ink


def _world(*, parent: dict, child: dict, label: str = "expands",
           typography: dict | None = None, child_label: str = "child") -> tuple[dict, dict]:
    """Minimal parent-node → child-region expand world with final boxes."""
    data = {
        "project": {"typography": typography} if typography else {},
        "nodes": {
            "parent_node": {"label": "parent", "region": "parent_region"},
            "child_node": {"label": child_label, "region": "child_region"},
        },
        "regions": {
            "parent_region": {"label": "parent region"},
            "child_region": {"label": child_label},
        },
        "edges": {
            "e_expand": {"kind": "expand", "source": "parent_node",
                         "target": "child_node", "label": label},
        },
    }
    layout = {
        "nodes": {"parent_node": dict(parent)},
        "regions": {"parent_region": dict(parent), "child_region": dict(child)},
    }
    return data, layout


def _south_world(*, band_low: float, band_high: float, child: dict,
                 label: str = "expands", typography: dict | None = None,
                 gap: float = 120.0, parent_extra: dict | None = None) -> tuple[dict, dict]:
    """Parent above child with an exact horizontal overlap band."""
    parent = {
        "x": band_low, "y": child["y"] - gap - 200.0,
        "w": band_high - band_low, "h": 200.0,
    }
    if parent_extra:
        parent.update(parent_extra)
    return _world(parent=parent, child=child, label=label, typography=typography)


def _arrow_inset(arrow: dict, child: dict) -> float:
    if arrow["direction"] in {"north", "south"}:
        return min(arrow["x"] - child["x"], child["x"] + child["w"] - (arrow["x"] + arrow["w"]))
    return min(arrow["y"] - child["y"], child["y"] + child["h"] - (arrow["y"] + arrow["h"]))


class CrossCenterTests(unittest.TestCase):
    def test_sliver_band_narrows_cross_section_to_keep_the_corner_margin(self) -> None:
        # M3 x-sparse geometry: 108px sliver band flush against the child's
        # right edge. Band centering alone hugs the corner (inset ~12px), so a
        # beside-labelled arrow gives up thickness until both margins fit.
        child = {"x": 1361.92, "y": 300.0, "w": 525.0, "h": 300.0}
        data, layout = _south_world(band_low=1361.92, band_high=1470.27, child=child)
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertEqual(arrow["direction"], "south")
        self.assertEqual(arrow["label_placement"], "beside")
        self.assertAlmostEqual(arrow["w"], 108.35 - 2 * HIERARCHY_CORNER_MARGIN, places=2)
        self.assertGreaterEqual(_arrow_inset(arrow, child), HIERARCHY_CORNER_MARGIN - 1e-6)
        findings = hierarchy_corridor_findings(data, {**layout, "hierarchy_arrows": arrows})
        self.assertFalse(any("hugs the child boundary corner" in f for f in findings), findings)

    def test_band_too_narrow_even_for_the_minimum_still_reports(self) -> None:
        # 80px band cannot hold MIN_HIERARCHY_ARROW_THICKNESS plus two margins;
        # the arrow keeps the band width and the finding must fire.
        child = {"x": 0.0, "y": 300.0, "w": 300.0, "h": 300.0}
        data, layout = _south_world(band_low=0.0, band_high=80.0, child=child)
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertAlmostEqual(arrow["w"], 80.0, places=2)
        findings = hierarchy_corridor_findings(data, {**layout, "hierarchy_arrows": arrows})
        self.assertTrue(any("hugs the child boundary corner" in f for f in findings), findings)

    def test_wide_band_respects_the_corner_margin(self) -> None:
        child = {"x": 0.0, "y": 320.0, "w": 600.0, "h": 300.0}
        data, layout = _south_world(band_low=0.0, band_high=600.0, child=child)
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertGreaterEqual(_arrow_inset(arrow, child), HIERARCHY_CORNER_MARGIN - 1.0)
        findings = hierarchy_corridor_findings(data, {**layout, "hierarchy_arrows": arrows})
        self.assertFalse(any("hugs the child boundary corner" in f for f in findings), findings)


class LabelPlacementTests(unittest.TestCase):
    def _plan(self, label: str, typography: dict | None = None,
              child_w: float = 600.0) -> tuple[dict, dict]:
        child = {"x": 0.0, "y": 320.0, "w": child_w, "h": 300.0}
        data, layout = _south_world(band_low=0.0, band_high=child_w, child=child,
                                    label=label, typography=typography)
        arrows = plan_hierarchy_arrows(data, layout)
        return arrows["e_expand"], layout

    def test_short_label_stays_on_shape(self) -> None:
        arrow, _ = self._plan("expands")
        self.assertEqual(arrow.get("label_placement"), "on-shape")
        self.assertNotIn("label_offset", arrow)

    def test_long_label_moves_beside_in_auto_policy(self) -> None:
        arrow, _ = self._plan("expands the Dense Layers template with a very long label")
        self.assertEqual(arrow.get("label_placement"), "beside")
        offset = arrow["label_offset"]
        ink_w, ink_h = arrow["label_ink"]
        # N-S shaft: label sits on a flank, not over the shaft itself.
        self.assertTrue(
            offset[0] >= arrow["w"] or offset[0] + ink_w + 8.0 <= 0.0,
            f"beside label still covers the shaft: offset={offset} ink={arrow['label_ink']}",
        )
        # The beside box must not cover the arrow box horizontally.
        box = {"x": arrow["x"] + offset[0], "w": ink_w + 8.0}
        self.assertTrue(box["x"] >= arrow["x"] + arrow["w"] or box["x"] + box["w"] <= arrow["x"])

    def test_beside_policy_forces_companion_placement(self) -> None:
        arrow, _ = self._plan("expands", typography={"hierarchy_label_placement": "beside"})
        self.assertEqual(arrow.get("label_placement"), "beside")

    def test_forced_on_shape_keeps_the_label_on_the_arrow(self) -> None:
        arrow, _ = self._plan(
            "expands the Dense Layers template with a very long label",
            typography={"hierarchy_label_placement": "on-shape"},
        )
        self.assertEqual(arrow.get("label_placement"), "on-shape")
        self.assertNotIn("label_offset", arrow)

    def test_on_shape_growth_stays_inside_the_attachment_band(self) -> None:
        # 150px band: growth candidates are clamped to the band width.
        child = {"x": 100.0, "y": 320.0, "w": 600.0, "h": 300.0}
        data, layout = _south_world(
            band_low=100.0, band_high=250.0, child=child,
            label="expands the Dense Layers template with a very long label",
            typography={"hierarchy_label_placement": "on-shape"},
        )
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertLessEqual(arrow["w"], 150.0 + 1.0)
        self.assertGreaterEqual(arrow["x"], 100.0 - 1.0)
        self.assertLessEqual(arrow["x"] + arrow["w"], 250.0 + 1.0)

    def test_growth_recenter_keeps_the_arrow_inside_the_band(self) -> None:
        # Band flush with the child's left edge: growth must not push the
        # cross-section out of the band on either side.
        child = {"x": 0.0, "y": 320.0, "w": 800.0, "h": 300.0}
        data, layout = _south_world(
            band_low=0.0, band_high=200.0, child=child,
            label="expands the Dense Layers template with a very long label",
            typography={"hierarchy_label_placement": "on-shape"},
        )
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertGreaterEqual(arrow["x"], -1.0)
        self.assertLessEqual(arrow["x"] + arrow["w"], 200.0 + 1.0)


class SignpostTests(unittest.TestCase):
    def test_signpost_skips_label_growth(self) -> None:
        child = {"x": 0.0, "y": 320.0, "w": 600.0, "h": 300.0}
        data, layout = _south_world(band_low=0.0, band_high=600.0, child=child,
                                    label="expands the Dense Layers template with a long label")
        data["edges"]["e_expand"]["visual_attachment"] = {
            "mode": "target-signpost", "id": "parent_region", "side": "south",
            "anchor_label": "parent", "display_label": "expands parent",
        }
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertEqual(arrow["attachment_mode"], "target-signpost")
        self.assertEqual(arrow["w"], HIERARCHY_ARROW_THICKNESS)
        self.assertIn(arrow.get("label_placement"), {"on-shape", "beside"})


class RotatedBesideLabelTests(unittest.TestCase):
    def _east_world(self, label: str, moat: float = 120.0) -> tuple[dict, dict]:
        data = {
            "nodes": {
                "parent_node": {"label": "parent", "region": "parent_region"},
                "child_node": {"label": "child", "region": "child_region"},
            },
            "regions": {
                "parent_region": {"label": "parent region"},
                "child_region": {"label": "child"},
            },
            "edges": {
                "e_expand": {"kind": "expand", "source": "parent_node",
                             "target": "child_node", "label": label},
            },
        }
        parent = {"x": 0.0, "y": 0.0, "w": 300.0, "h": 400.0}
        child = {"x": 300.0 + moat, "y": 0.0, "w": 600.0, "h": 400.0}
        layout = {
            "nodes": {"parent_node": dict(parent)},
            "regions": {"parent_region": dict(parent), "child_region": dict(child)},
        }
        return data, layout

    def _label_box(self, arrow: dict) -> dict:
        dx, dy = arrow["label_offset"]
        ink_w, ink_h = arrow["label_ink"]
        box_w, box_h = (ink_h + 8.0, ink_w + 8.0) if arrow.get("label_rotated") else (ink_w + 8.0, ink_h + 8.0)
        return {"x": arrow["x"] + dx, "y": arrow["y"] + dy, "w": box_w, "h": box_h}

    def test_narrow_corridor_rotates_the_label_along_the_corridor(self) -> None:
        data, layout = self._east_world("expands Sparse MoE FFN")
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertEqual(arrow["direction"], "east")
        self.assertEqual(arrow["label_placement"], "beside")
        self.assertTrue(arrow.get("label_rotated"), arrow)
        box = self._label_box(arrow)
        # The rotated footprint fits the 120px corridor between the regions.
        self.assertLessEqual(box["w"], 120.0)
        self.assertGreaterEqual(box["x"], 300.0)
        self.assertLessEqual(box["x"] + box["w"], 420.0)
        # It clears the shaft vertically and every region box.
        self.assertTrue(
            box["y"] >= arrow["y"] + arrow["h"] + HIERARCHY_LABEL_GAP - 1.0
            or box["y"] + box["h"] <= arrow["y"] - HIERARCHY_LABEL_GAP + 1.0
        )
        for region in layout["regions"].values():
            overlap_w = min(box["x"] + box["w"], region["x"] + region["w"]) - max(box["x"], region["x"])
            overlap_h = min(box["y"] + box["h"], region["y"] + region["h"]) - max(box["y"], region["y"])
            self.assertFalse(overlap_w > 0 and overlap_h > 0, (box, region))
        self.assertNotIn("placement_warning", arrow)

    def test_wide_corridor_keeps_the_label_horizontal(self) -> None:
        data, layout = self._east_world("expands Sparse MoE FFN", moat=400.0)
        data["project"] = {"typography": {"hierarchy_label_placement": "beside"}}
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertEqual(arrow["label_placement"], "beside")
        self.assertFalse(arrow.get("label_rotated"), arrow)
        self.assertNotIn("placement_warning", arrow)


class BesideObstacleTests(unittest.TestCase):
    """Besides must dodge sibling companions and re-wrap into tight flanks."""

    TEXT = "expands Sparse Layers template"

    def _moat_layout(self) -> dict:
        return {
            "regions": {
                "above": {"x": 0.0, "y": 0.0, "w": 2000.0, "h": 200.0},
                "below-left": {"x": 0.0, "y": 320.0, "w": 200.0, "h": 600.0},
                "below-right": {"x": 400.0, "y": 320.0, "w": 1600.0, "h": 600.0},
            },
            "nodes": {},
            "hierarchy_arrows": {},
        }

    def _arrow(self, x: float) -> dict:
        return {"direction": "north", "x": x, "y": 200.0, "w": 60.0, "h": 120.0}

    def _flank_box(self, arrow: dict) -> dict:
        ink_w, ink_h = arrow["label_ink"]
        dx, dy = arrow["label_offset"]
        return {"x": arrow["x"] + dx, "y": arrow["y"] + dy, "w": ink_w + 8.0, "h": ink_h + 8.0}

    def _intersects(self, first: dict, second: dict) -> bool:
        overlap_w = min(first["x"] + first["w"], second["x"] + second["w"]) - max(first["x"], second["x"])
        overlap_h = min(first["y"] + first["h"], second["y"] + second["h"]) - max(first["y"], second["y"])
        return overlap_w > 0 and overlap_h > 0

    def test_flank_narrower_than_the_label_rewraps_instead_of_warning(self) -> None:
        layout = self._moat_layout()
        layout["nodes"] = {
            "left-block": {"x": 0.0, "y": 200.0, "w": 396.0, "h": 400.0},
            "right-block": {"x": 600.0, "y": 200.0, "w": 300.0, "h": 400.0},
        }
        arrow = self._arrow(400.0)
        _place_beside("b", arrow, self.TEXT, 20.0, layout)
        self.assertNotIn("placement_warning", arrow)
        base_w, _ = wrapped_label_ink(self.TEXT, 20.0, 180.0)
        self.assertLess(arrow["label_ink"][0], base_w)
        self.assertFalse(self._intersects(self._flank_box(arrow), layout["nodes"]["right-block"]))

    def test_placed_sibling_label_blocks_the_flank(self) -> None:
        layout = self._moat_layout()
        layout["nodes"] = {"right-block": {"x": 472.0, "y": 200.0, "w": 200.0, "h": 250.0}}
        sibling = self._arrow(100.0)
        sibling.update({
            "label_placement": "beside", "label_offset": [108.0, 18.2],
            "label_ink": [170.0, 75.6],
        })
        layout["hierarchy_arrows"]["a"] = sibling
        arrow = self._arrow(400.0)
        _place_beside("b", arrow, self.TEXT, 20.0, layout)
        self.assertNotIn("placement_warning", arrow)
        self.assertFalse(self._intersects(self._flank_box(arrow), self._flank_box(sibling)))
        # The free spot is below the shaft; the mid-height left flank is taken.
        self.assertGreater(arrow["label_offset"][1], 0.0)


class SignpostSharingTests(unittest.TestCase):
    """Only signposts on the same child edge share that edge's slots."""

    def _world(self, far_regions: dict) -> tuple[dict, dict]:
        regions = {
            "child": {"label": "child"},
            "west-corridor": {"label": "west corridor"},
            "child_node": {"label": "child"},
            **{region_id: {"label": region_id} for region_id in far_regions},
        }
        layout = {
            "nodes": {
                "west_node": {"x": 1500.0, "y": 250.0, "w": 200.0, "h": 100.0},
                "child_node": {"x": 2200.0, "y": 250.0, "w": 200.0, "h": 100.0},
            },
            "regions": {
                "child": {"x": 2000.0, "y": 0.0, "w": 1000.0, "h": 600.0},
                "west-corridor": {"x": 1400.0, "y": 0.0, "w": 480.0, "h": 600.0},
                # Visible content behind the signpost's tail. Without it the
                # arrow would stand in open whitespace and the planner anchors
                # it at the owner instead (source-signpost).
                "ground": {"x": 2500.0, "y": 750.0, "w": 200.0, "h": 150.0},
                **far_regions,
            },
        }
        for region_id, box in far_regions.items():
            layout["nodes"][f"{region_id}_node"] = {"x": box["x"] + 20.0, "y": box["y"] + 20.0, "w": 200.0, "h": 100.0}
        edges = {
            "e_corridor": {"kind": "expand", "source": "west_node", "target": "child_node", "label": "expands"},
        }
        for region_id in far_regions:
            edges[f"e_{region_id}"] = {"kind": "expand", "source": f"{region_id}_node",
                                       "target": "child_node", "label": "expands"}
        data = {
            "nodes": {
                "west_node": {"label": "west", "region": "west-corridor"},
                "child_node": {"label": "child", "region": "child"},
                **{f"{region_id}_node": {"label": region_id, "region": region_id} for region_id in far_regions},
            },
            "regions": regions,
            "edges": edges,
        }
        return data, layout

    def test_corridor_peer_on_another_side_keeps_the_signpost_centred(self) -> None:
        data, layout = self._world({"far": {"x": 2200.0, "y": 1500.0, "w": 300.0, "h": 300.0}})
        arrows = plan_hierarchy_arrows(data, layout)
        self.assertNotEqual(arrows["e_corridor"]["attachment_mode"], "target-signpost")
        signpost = arrows["e_far"]
        self.assertEqual(signpost["attachment_mode"], "target-signpost")
        self.assertEqual(signpost["direction"], "north")
        # Centred under the child, not pushed to a fraction slot by the corridor arrow.
        self.assertAlmostEqual(signpost["x"], 2000.0 + (1000.0 - 96.0) * 0.5, places=2)

    def test_two_signposts_on_the_same_edge_still_spread(self) -> None:
        data, layout = self._world({
            "far-a": {"x": 2200.0, "y": 1500.0, "w": 300.0, "h": 300.0},
            "far-b": {"x": 2100.0, "y": 2400.0, "w": 300.0, "h": 300.0},
        })
        arrows = plan_hierarchy_arrows(data, layout)
        first, second = arrows["e_far-a"], arrows["e_far-b"]
        self.assertEqual({first["direction"], second["direction"]}, {"north"})
        self.assertAlmostEqual(first["x"], 2000.0 + 904.0 * 0.25, places=2)
        self.assertAlmostEqual(second["x"], 2000.0 + 904.0 * 0.75, places=2)


class SourceSignpostTests(unittest.TestCase):
    """An ungrounded target slot moves the arrow to the owner region."""

    def _world(self, *, ground: dict | None = None) -> tuple[dict, dict]:
        data = {
            "nodes": {
                "parent_node": {"label": "parent", "region": "owner"},
                "child_node": {"label": "child", "region": "child"},
            },
            "regions": {
                "owner": {"label": "Owner Region"},
                "child": {"label": "Child Detail"},
            },
            "edges": {
                "e_expand": {"kind": "expand", "source": "parent_node",
                             "target": "child_node", "label": "expands the parent"},
            },
        }
        layout = {
            "nodes": {
                "parent_node": {"x": 200.0, "y": 2200.0, "w": 100.0, "h": 60.0},
                "child_node": {"x": 900.0, "y": -400.0, "w": 200.0, "h": 60.0},
            },
            "regions": {
                "owner": {"x": 0.0, "y": 2000.0, "w": 500.0, "h": 500.0},
                "child": {"x": 500.0, "y": -500.0, "w": 1000.0, "h": 600.0},
            },
        }
        if ground is not None:
            layout["regions"]["ground"] = ground
        return data, layout

    def test_ungrounded_child_slot_anchors_the_arrow_at_the_owner(self) -> None:
        data, layout = self._world()
        arrows = plan_hierarchy_arrows(data, layout)
        arrow = arrows["e_expand"]
        self.assertEqual(arrow["attachment_mode"], "source-signpost")
        self.assertEqual(arrow["attachment_id"], "owner")
        # The child is mostly above the owner, so the arrow leaves the north
        # edge, aligned with the semantic parent block.
        self.assertEqual(arrow["direction"], "north")
        self.assertAlmostEqual(arrow["y"] + arrow["h"], 2000.0, places=2)
        self.assertAlmostEqual(arrow["x"] + arrow["w"] / 2, 250.0, places=2)
        # The label names the detail the arrow expands into, which is the only
        # way for a reader to find the distant child; the edge's verb survives
        # while the anchor name is replaced by the target title.
        self.assertEqual(arrow["display_label"], "expands the Child Detail")

    def test_grounded_child_slot_keeps_the_target_signpost(self) -> None:
        # A frame 30px behind the tail makes the child-side arrow legible, so
        # the planner leaves it at the child.
        data, layout = self._world(ground={"x": 1000.0, "y": 250.0, "w": 200.0, "h": 150.0})
        arrows = plan_hierarchy_arrows(data, layout)
        self.assertEqual(arrows["e_expand"]["attachment_mode"], "target-signpost")


class ArrowAreaTests(unittest.TestCase):
    def test_cell_area_matches_the_polygon_formula(self) -> None:
        # 96x120 N-S arrow at 0.52/0.38: 0.5124 * w * h.
        area = single_arrow_cell_area(96.0, 120.0, "south")
        self.assertAlmostEqual(area, 0.5124 * 96.0 * 120.0, places=1)
        # Orientation must not change the polygon area.
        self.assertAlmostEqual(area, single_arrow_cell_area(96.0, 120.0, "north"), places=6)
        self.assertAlmostEqual(
            single_arrow_cell_area(120.0, 96.0, "east"),
            0.5124 * 96.0 * 120.0, places=1,
        )


if __name__ == "__main__":
    unittest.main()
