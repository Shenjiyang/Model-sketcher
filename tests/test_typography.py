#!/usr/bin/env python3
"""Regression tests for the shared typography schema."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from typography import (
    BASELINE_FONTS,
    resolve_typography,
    validate_typography_schema,
    wrapped_label_ink,
)


class TypographySchemaTests(unittest.TestCase):
    def test_defaults_resolve_to_the_calibrated_baseline(self) -> None:
        resolved = resolve_typography(None)
        self.assertEqual({key: resolved[key] for key in BASELINE_FONTS}, BASELINE_FONTS)
        self.assertEqual(resolved["hierarchy_label_placement"], "auto")
        self.assertNotIn("primary_view_scale", resolved)

    def test_absolute_schema_overrides_and_annotation_follows_edge(self) -> None:
        resolved = resolve_typography({"ordinary_node_font": 20, "edge_label_font": 16})
        self.assertEqual(resolved["ordinary_node_font"], 20)
        self.assertEqual(resolved["edge_label_font"], 16)
        self.assertEqual(resolved["annotation_font"], 16)
        self.assertEqual(resolved["region_title_font"], 20)
        self.assertEqual(resolved["hierarchy_label_font"], 20)

    def test_relative_schema_derives_roles_from_native_base(self) -> None:
        resolved = resolve_typography({
            "viewing_profile": "desktop-review",
            "native_base_size": 14,
            "role_ratios": {"node_label": 1.0, "edge_label": 0.85, "annotation": 0.8, "region_title": 1.15},
        })
        self.assertEqual(resolved["ordinary_node_font"], 14)
        self.assertEqual(resolved["edge_label_font"], round(14 * 0.85))
        self.assertEqual(resolved["annotation_font"], round(14 * 0.8))
        self.assertEqual(resolved["region_title_font"], round(14 * 1.15))
        # Undeclared roles keep the baseline ratio.
        self.assertEqual(resolved["hierarchy_label_font"], round(14 * 20 / 18))

    def test_visibility_metadata_passes_through(self) -> None:
        resolved = resolve_typography({"primary_view_scale": 0.67})
        self.assertEqual(resolved["primary_view_scale"], 0.67)
        self.assertNotIn("minimum_apparent_ordinary_font", resolved)

    def test_mixed_schemas_are_rejected(self) -> None:
        errors = validate_typography_schema({"native_base_size": 14, "ordinary_node_font": 18})
        self.assertTrue(any("mixes" in error for error in errors), errors)

    def test_unknown_keys_and_bad_values_are_rejected(self) -> None:
        errors = validate_typography_schema({
            "native_base_size": "big",
            "role_ratios": {"title": 1.2, "node_label": -1},
            "hierarchy_label_placement": "over",
            "mystery": 1,
        })
        joined = "\n".join(errors)
        self.assertIn("unknown key 'mystery'", joined)
        self.assertIn("native_base_size must be a positive number", joined)
        self.assertIn("unknown role 'title'", joined)
        self.assertIn("hierarchy_label_placement must be one of", joined)

    def test_valid_schemas_pass_validation(self) -> None:
        self.assertEqual(validate_typography_schema(None), [])
        self.assertEqual(validate_typography_schema({"ordinary_node_font": 18}), [])
        self.assertEqual(
            validate_typography_schema({"native_base_size": 14, "role_ratios": {"node_label": 1.0}}),
            [],
        )


class WrappedLabelInkTests(unittest.TestCase):
    def test_single_line_short_label(self) -> None:
        width, height = wrapped_label_ink("expands", 20, 96)
        self.assertLess(width, 96)
        self.assertAlmostEqual(height, 20 * 1.26, places=1)

    def test_long_label_wraps_and_grows_height(self) -> None:
        width, height = wrapped_label_ink("expands Dense Layers template", 20, 96)
        self.assertLessEqual(width, 96 * 1.15)
        self.assertGreater(height, 3 * 20 * 1.26)

    def test_wider_wrap_needs_fewer_lines(self) -> None:
        _, narrow_height = wrapped_label_ink("expands Dense Layers template", 20, 96)
        _, wide_height = wrapped_label_ink("expands Dense Layers template", 20, 320)
        self.assertLess(wide_height, narrow_height)

    def test_explicit_line_breaks_are_honored(self) -> None:
        _, height = wrapped_label_ink("alpha\\nBeta", 20, 320)
        self.assertAlmostEqual(height, 2 * 20 * 1.26, places=1)


if __name__ == "__main__":
    unittest.main()
