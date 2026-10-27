#!/usr/bin/env python3
"""Project typography schema: declaration, validation, and resolution.

`project.typography` in the architecture IR accepts one of two mutually
exclusive sizing schemas plus optional visibility metadata:

- absolute role fonts (the calibrated desktop-review baseline):
  ordinary_node_font=18, edge_label_font=14, annotation_font=14,
  region_title_font=20, hierarchy_label_font=20
- a relative schema: `native_base_size` (the comfortable on-screen base)
  scaled per role by `role_ratios`; missing roles use the baseline ratios.

Both resolve to absolute integers here so every downstream tool reads one
shape. Optional keys (`viewing_profile`, `primary_view_scale`,
`minimum_apparent_ordinary_font`, `target_apparent_ordinary_font`,
`hierarchy_label_placement`) pass through to the generated audit contract so
the "readable at the declared reading frame" rule is enforced per project
instead of by habit.
"""

from __future__ import annotations

import unicodedata

BASELINE_FONTS = {
    "ordinary_node_font": 18,
    "edge_label_font": 14,
    "annotation_font": 14,
    "region_title_font": 20,
    "hierarchy_label_font": 20,
}
# Canonical role ratios of the baseline (base = ordinary_node_font).
ROLE_RATIOS = {
    "node_label": 1.0,
    "edge_label": 14 / 18,
    "annotation": 14 / 18,
    "region_title": 20 / 18,
    "hierarchy_label": 20 / 18,
}
RATIO_TO_FONT_KEY = {
    "node_label": "ordinary_node_font",
    "edge_label": "edge_label_font",
    "annotation": "annotation_font",
    "region_title": "region_title_font",
    "hierarchy_label": "hierarchy_label_font",
}
ABSOLUTE_KEYS = tuple(BASELINE_FONTS)
PLACEMENTS = ("auto", "on-shape", "beside")
_SCALE_KEYS = (
    "primary_view_scale",
    "minimum_apparent_ordinary_font",
    "target_apparent_ordinary_font",
)
_ALLOWED_KEYS = (
    set(ABSOLUTE_KEYS)
    | {"native_base_size", "role_ratios", "viewing_profile", "hierarchy_label_placement"}
    | set(_SCALE_KEYS)
)


def validate_typography_schema(typography: object) -> list[str]:
    if typography is None:
        return []
    if not isinstance(typography, dict):
        return ["project.typography must be an object"]
    errors: list[str] = []
    for key in typography:
        if key not in _ALLOWED_KEYS:
            errors.append(f"project.typography has unknown key {key!r}")
    absolute = [key for key in ABSOLUTE_KEYS if key in typography]
    relative = [key for key in ("native_base_size", "role_ratios") if key in typography]
    if absolute and relative:
        errors.append(
            "project.typography mixes absolute font keys with native_base_size/role_ratios; "
            "declare exactly one sizing schema"
        )
    for key in (*absolute, "native_base_size", *_SCALE_KEYS):
        value = typography.get(key)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
        ):
            errors.append(f"project.typography.{key} must be a positive number")
    ratios = typography.get("role_ratios")
    if ratios is not None:
        if not isinstance(ratios, dict):
            errors.append("project.typography.role_ratios must be a role-to-ratio object")
        else:
            for role, value in ratios.items():
                if role not in ROLE_RATIOS:
                    errors.append(f"project.typography.role_ratios has unknown role {role!r}")
                elif not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    errors.append(f"project.typography.role_ratios.{role} must be a positive number")
    placement = typography.get("hierarchy_label_placement")
    if placement is not None and placement not in PLACEMENTS:
        errors.append(f"project.typography.hierarchy_label_placement must be one of {PLACEMENTS}")
    profile = typography.get("viewing_profile")
    if profile is not None and not isinstance(profile, str):
        errors.append("project.typography.viewing_profile must be a string")
    return errors


def resolve_typography(typography: object) -> dict:
    """Resolve the declared schema to absolute integer role fonts plus metadata."""
    declared = typography if isinstance(typography, dict) else {}
    fonts = dict(BASELINE_FONTS)
    if any(key in declared for key in ABSOLUTE_KEYS):
        for key in ABSOLUTE_KEYS:
            if key in declared:
                fonts[key] = max(1, int(round(float(declared[key]))))
        if "annotation_font" not in declared:
            fonts["annotation_font"] = fonts["edge_label_font"]
    elif "native_base_size" in declared:
        base = float(declared["native_base_size"])
        ratios = declared.get("role_ratios") or {}
        for role, ratio in ROLE_RATIOS.items():
            fonts[RATIO_TO_FONT_KEY[role]] = max(
                1, int(round(base * float(ratios.get(role, ratio))))
            )
    resolved = {
        **fonts,
        "viewing_profile": declared.get("viewing_profile"),
        "hierarchy_label_placement": declared.get("hierarchy_label_placement", "auto"),
    }
    for key in _SCALE_KEYS:
        if declared.get(key) is not None:
            resolved[key] = float(declared[key])
    return resolved


def _advance_units(char: str) -> float:
    if unicodedata.combining(char):
        return 0.0
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 1.0
    if char in "ilI.,:;!|' `":
        return 0.3
    if char in "MW@%":
        return 0.95
    return 0.68 if char.isupper() else 0.58


def wrapped_label_lines(
    text: str,
    font_size: float,
    wrap_width: float,
    *,
    bold: bool = True,
) -> list[str]:
    """Word-then-character wrap of `text` to `wrap_width` px at `font_size`."""
    font_size = float(font_size)
    if font_size <= 0 or wrap_width <= 0:
        raise ValueError("label ink estimation needs positive font and wrap width")

    def measure(value: str) -> float:
        return sum(_advance_units(char) for char in value) * font_size * (1.1 if bold else 1.0)

    lines: list[str] = []
    for paragraph in str(text).replace("\\n", "\n").split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if line and measure(candidate) > wrap_width:
                lines.append(line)
                line = ""
            if measure(word) <= wrap_width:
                line = f"{line} {word}" if line else word
                continue
            for char in word:
                if line and measure(line + char) > wrap_width:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return lines


def wrapped_label_ink(
    text: str,
    font_size: float,
    wrap_width: float,
    *,
    bold: bool = True,
    line_height: float = 1.26,
) -> tuple[float, float]:
    """Estimated ink box (width, height) of `text` wrapped to `wrap_width` px.

    Mirrors the word-then-character wrapping of region_title_layout so the
    plan-time estimate matches what the compiler's wrapped label produces;
    the bold factor tracks fontStyle=1 labels. Estimates err slightly wide so
    placement decisions stay conservative.
    """
    font_size = float(font_size)
    lines = wrapped_label_lines(text, font_size, wrap_width, bold=bold)
    if not lines:
        return 0.0, 0.0
    width = max(
        sum(_advance_units(char) for char in line) * font_size * (1.1 if bold else 1.0)
        for line in lines
    )
    height = len(lines) * line_height * font_size
    return round(width, 2), round(height, 2)
