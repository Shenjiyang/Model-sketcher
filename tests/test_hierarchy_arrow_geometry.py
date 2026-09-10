#!/usr/bin/env python3
"""Regression tests for shape-aware hierarchy-arrow collision geometry."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from hierarchy_arrow_geometry import (
    box_intersects_polygon,
    polygons_intersect,
    segment_intersects_polygon,
    single_arrow_polygon,
)


class SingleArrowGeometryTests(unittest.TestCase):
    def test_transparent_corner_does_not_collide(self) -> None:
        polygon = single_arrow_polygon(100, 100, 200, 100, "east", 0.5, 0.4)
        self.assertFalse(box_intersects_polygon(110, 105, 30, 10, polygon))
        self.assertFalse(segment_intersects_polygon((110, 110), (140, 110), polygon))

    def test_shaft_and_arrowhead_collisions_are_detected(self) -> None:
        polygon = single_arrow_polygon(100, 100, 200, 100, "east", 0.5, 0.4)
        self.assertTrue(box_intersects_polygon(110, 135, 30, 30, polygon))
        self.assertTrue(segment_intersects_polygon((150, 150), (320, 150), polygon))
        self.assertTrue(segment_intersects_polygon((250, 105), (250, 195), polygon))

    def test_all_directions_place_tip_on_requested_side(self) -> None:
        expected_tips = {
            "east": (300, 150),
            "west": (100, 150),
            "south": (200, 200),
            "north": (200, 100),
        }
        for direction, tip in expected_tips.items():
            with self.subTest(direction=direction):
                polygon = single_arrow_polygon(100, 100, 200, 100, direction, 0.5, 0.4)
                self.assertIn(tip, polygon)

    def test_polygon_overlap_ignores_boundary_only_contact(self) -> None:
        first = single_arrow_polygon(100, 100, 100, 60, "east")
        overlapping = single_arrow_polygon(140, 100, 100, 60, "east")
        touching = single_arrow_polygon(200, 100, 100, 60, "east")
        transparent_corner = single_arrow_polygon(110, 50, 40, 35, "east")
        self.assertTrue(polygons_intersect(first, overlapping))
        self.assertTrue(polygons_intersect(first, first))
        self.assertFalse(polygons_intersect(first, touching))
        self.assertFalse(polygons_intersect(first, transparent_corner))


if __name__ == "__main__":
    unittest.main()
