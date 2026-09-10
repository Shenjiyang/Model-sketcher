#!/usr/bin/env python3
"""Audit final Draw.io XML, with optional project-specific semantic rules."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from semantic_palette import SEMANTIC_GLYPHS, SEMANTIC_PALETTE, TP_PARTITION_MODIFIER, VISUAL_MODIFIERS
from hierarchy_arrow_geometry import (
    box_intersects_polygon,
    polygons_intersect,
    segment_intersects_polygon,
    single_arrow_polygon,
)


ROOT_IDS = {"0", "1", None}
MAX_EDGE_LABEL_OFFSET = 160.0

OPERATOR_PATTERNS = (
    re.compile(r"\blinear\b", re.IGNORECASE),
    re.compile(r"\bconv[123]d\b", re.IGNORECASE),
    re.compile(r"\b(?:rmsnorm|layernorm|groupnorm|batchnorm)\b", re.IGNORECASE),
    re.compile(r"\b(?:silu|gelu|relu|sigmoid|softmax|softplus)\b", re.IGNORECASE),
    re.compile(r"\b(?:matmul|dot product|outer product|matrix multiply)\b", re.IGNORECASE),
    re.compile(r"\b(?:mean|sum|divide|scale|sqrt|rsqrt)\b", re.IGNORECASE),
    re.compile(r"\b(?:reshape|unflatten|flatten|repeat|split|concat(?:enate)?)\b", re.IGNORECASE),
    re.compile(r"\b(?:avgpool|maxpool|pool|gather|scatter|sort|index_add)\b", re.IGNORECASE),
    re.compile(r"\btop-?k\b|\btop-?\d+\b", re.IGNORECASE),
    re.compile(r"\blm head\b", re.IGNORECASE),
    re.compile(r"\b(?:gate|up|down|q|k|v|o)_proj\b", re.IGNORECASE),
)

COMPOSITE_CLASSIFICATIONS = {
    "fused-operation",
    "module-boundary",
    "expanded-elsewhere",
}


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def parse_style(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value.split(";"):
        if not item:
            continue
        key, separator, val = item.partition("=")
        result[key] = val if separator else "1"
    return result


def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def decode_diagram(diagram: ET.Element) -> ET.Element:
    model = diagram.find("mxGraphModel")
    if model is not None:
        return model
    payload = (diagram.text or "").strip()
    if not payload:
        raise ValueError("diagram has neither mxGraphModel nor compressed payload")
    compressed = base64.b64decode(payload)
    xml_text = urllib.parse.unquote(zlib.decompress(compressed, -15).decode("utf-8"))
    return ET.fromstring(xml_text)


def graph_pages(path: Path) -> list[tuple[str, ET.Element]]:
    root = ET.parse(path).getroot()
    if root.tag == "mxGraphModel":
        return [(path.stem, root)]
    pages = []
    for index, diagram in enumerate(root.findall("diagram"), start=1):
        pages.append((diagram.get("name") or f"page-{index}", decode_diagram(diagram)))
    if not pages:
        raise ValueError("no Draw.io diagram pages found")
    return pages


def cell_geometry(cell: ET.Element) -> ET.Element | None:
    return cell.find("mxGeometry")


def number(value: str | None, default: float = 0.0) -> float:
    return float(value) if value not in {None, ""} else default


def pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def configured_pairs(values: list[list[str]]) -> set[tuple[str, str]]:
    return {pair_key(value[0], value[1]) for value in values if len(value) == 2}


def summarize_errors(errors: list[str]) -> dict[str, Any]:
    """Collapse pairwise geometry explosions into actionable categories and root edges."""
    patterns = (
        ("edge-edge crossing", "edges cross without junction"),
        ("edge-edge overlap", "edges overlap"),
        ("edge-node crossing", "edge crosses unrelated node"),
        ("source re-entry", "edge doubles back through source node"),
        ("target re-entry", "edge approaches target through its interior"),
        ("route clearance", "route runs too close"),
        ("parallel-lane spacing", "parallel lanes are spread apart"),
        ("region slack", "region execution envelope has excessive"),
        ("fan-out sides", "fan-out leaves source from mixed sides"),
        ("route simplicity", "avoidable"),
        ("route detour", "route detour needs review"),
    )
    categories: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    for error in errors:
        category = next((name for name, marker in patterns if marker in error), "other")
        categories[category] = categories.get(category, 0) + 1
        for edge_id in re.findall(r"\bedge:[A-Za-z0-9_.:-]+", error):
            edge_counts[edge_id] = edge_counts.get(edge_id, 0) + 1
    roots = sorted(edge_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
    return {
        "categories": dict(sorted(categories.items(), key=lambda item: (-item[1], item[0]))),
        "root_edges": dict(roots),
    }


def strip_markup(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def markup_lines(value: str) -> list[str]:
    text = html.unescape(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def text_width_units(value: str) -> float:
    units = 0.0
    for character in value:
        if character.isspace():
            units += 0.45
        elif ord(character) > 127:
            units += 1.0
        elif character in "ilI1|.,:;'`":
            units += 0.4
        elif character in "MW@#%":
            units += 0.95
        else:
            units += 0.62
    return units


def avoidable_orthogonal_shortcut(
    points: list[tuple[float, float]],
    segment_blocked: Callable[[tuple[float, float], tuple[float, float]], bool],
    tolerance: float = 1.0,
) -> tuple[int, int, list[tuple[float, float]]] | None:
    """Find a same-port-direction shortcut that removes at least two bends."""
    def axis(first: tuple[float, float], last: tuple[float, float]) -> str:
        if math.isclose(first[0], last[0], abs_tol=tolerance):
            return "v"
        if math.isclose(first[1], last[1], abs_tol=tolerance):
            return "h"
        return "d"

    def signed_delta(first: tuple[float, float], last: tuple[float, float], route_axis: str) -> float:
        return last[1] - first[1] if route_axis == "v" else last[0] - first[0]

    def compact(candidate: list[tuple[float, float]]) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for point in candidate:
            if result and math.dist(result[-1], point) <= tolerance:
                continue
            result.append(point)
        return result

    for start_index in range(len(points) - 3):
        for end_index in range(len(points) - 1, start_index + 2, -1):
            original = points[start_index : end_index + 1]
            if min(math.dist(*original[:2]), math.dist(*original[-2:])) < max(2.0, tolerance):
                continue
            original_axes = [axis(first, last) for first, last in zip(original, original[1:])]
            if "d" in original_axes:
                continue
            first, last = original[0], original[-1]
            candidates = (
                [first, (first[0], last[1]), last],
                [first, (last[0], first[1]), last],
            )
            original_length = sum(
                abs(end[0] - begin[0]) + abs(end[1] - begin[1])
                for begin, end in zip(original, original[1:])
            )
            for candidate in candidates:
                candidate = compact(candidate)
                candidate_axes = [axis(begin, end) for begin, end in zip(candidate, candidate[1:])]
                if not candidate_axes or "d" in candidate_axes:
                    continue
                # Preserve endpoint port directions so the shortcut cannot introduce a hook.
                if candidate_axes[0] != original_axes[0] or candidate_axes[-1] != original_axes[-1]:
                    continue
                if signed_delta(*candidate[:2], candidate_axes[0]) * signed_delta(*original[:2], original_axes[0]) <= 0:
                    continue
                if signed_delta(*candidate[-2:], candidate_axes[-1]) * signed_delta(*original[-2:], original_axes[-1]) <= 0:
                    continue
                # Renderer splits and bridge endpoints are not extra bends.
                original_bends = sum(a != b for a, b in zip(original_axes, original_axes[1:]))
                candidate_bends = sum(a != b for a, b in zip(candidate_axes, candidate_axes[1:]))
                if original_bends - candidate_bends < 2:
                    continue
                candidate_length = sum(
                    abs(end[0] - begin[0]) + abs(end[1] - begin[1])
                    for begin, end in zip(candidate, candidate[1:])
                )
                if candidate_length > original_length + tolerance:
                    continue
                if any(segment_blocked(begin, end) for begin, end in zip(candidate, candidate[1:])):
                    continue
                return start_index, end_index, candidate
    return None


def orthogonal_segments_conflict(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
    tolerance: float = 1.0,
) -> bool:
    """Return true for an interior crossing or visible collinear overlap."""
    def describe(start: tuple[float, float], end: tuple[float, float]) -> tuple[str, float, float, float]:
        if math.isclose(start[0], end[0], abs_tol=tolerance):
            return "v", start[0], min(start[1], end[1]), max(start[1], end[1])
        if math.isclose(start[1], end[1], abs_tol=tolerance):
            return "h", start[1], min(start[0], end[0]), max(start[0], end[0])
        return "d", 0.0, 0.0, 0.0

    first_axis, first_fixed, first_low, first_high = describe(first_start, first_end)
    second_axis, second_fixed, second_low, second_high = describe(second_start, second_end)
    if "d" in {first_axis, second_axis}:
        return True
    if first_axis == second_axis:
        return (
            math.isclose(first_fixed, second_fixed, abs_tol=tolerance)
            and min(first_high, second_high) - max(first_low, second_low) > tolerance
        )
    horizontal = (first_fixed, first_low, first_high) if first_axis == "h" else (second_fixed, second_low, second_high)
    vertical = (first_fixed, first_low, first_high) if first_axis == "v" else (second_fixed, second_low, second_high)
    return (
        horizontal[1] + tolerance < vertical[0] < horizontal[2] - tolerance
        and vertical[1] + tolerance < horizontal[0] < vertical[2] - tolerance
    )


class PageAudit:
    def __init__(self, name: str, model: ET.Element, config: dict[str, Any]):
        self.name = name
        self.model = model
        self.config = config
        self.cells = list(model.iter("mxCell"))
        self.by_id: dict[str, ET.Element] = {}
        self.styles: dict[str, dict[str, str]] = {}
        self.box_cache: dict[str, Box] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def fail(self, message: str) -> None:
        self.errors.append(f"[{self.name}] {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(f"[{self.name}] {message}")

    def prepare(self) -> None:
        for cell in self.cells:
            cell_id = cell.get("id")
            if not cell_id:
                self.fail("mxCell without id")
                continue
            if cell_id in self.by_id:
                self.fail(f"duplicate cell id: {cell_id}")
                continue
            self.by_id[cell_id] = cell
            raw_style = cell.get("style", "")
            seen_style_values: dict[str, str] = {}
            for item in raw_style.split(";"):
                if not item:
                    continue
                key, separator, value = item.partition("=")
                value = value if separator else "1"
                if key in seen_style_values and seen_style_values[key] != value:
                    self.fail(
                        f"conflicting duplicate style key: {cell_id} "
                        f"{key}={seen_style_values[key]!r}/{value!r}"
                    )
                seen_style_values[key] = value
            self.styles[cell_id] = parse_style(raw_style)

    def absolute_box(self, cell_id: str, trail: tuple[str, ...] = ()) -> Box | None:
        if cell_id in self.box_cache:
            return self.box_cache[cell_id]
        if cell_id in trail:
            self.fail(f"parent cycle: {' -> '.join((*trail, cell_id))}")
            return None
        cell = self.by_id.get(cell_id)
        if cell is None or cell.get("vertex") != "1":
            return None
        geometry = cell_geometry(cell)
        if geometry is None:
            self.fail(f"vertex missing mxGeometry: {cell_id}")
            return None
        try:
            x = number(geometry.get("x"))
            y = number(geometry.get("y"))
            width = number(geometry.get("width"))
            height = number(geometry.get("height"))
        except ValueError:
            self.fail(f"non-numeric geometry: {cell_id}")
            return None
        if width <= 0 or height <= 0:
            self.fail(f"non-positive vertex size: {cell_id} ({width}x{height})")
        parent_id = cell.get("parent")
        if parent_id not in ROOT_IDS and parent_id in self.by_id:
            parent_box = self.absolute_box(parent_id, (*trail, cell_id))
            if parent_box is not None:
                x += parent_box.x
                y += parent_box.y
        box = Box(x, y, width, height)
        self.box_cache[cell_id] = box
        return box

    def check_references(self) -> None:
        for cell_id, cell in self.by_id.items():
            parent = cell.get("parent")
            if parent is not None and parent not in self.by_id:
                self.fail(f"invalid parent: {cell_id} -> {parent}")
            if cell.get("edge") == "1":
                for field in ("source", "target"):
                    target = cell.get(field)
                    if not target:
                        self.fail(f"edge missing {field}: {cell_id}")
                    elif target not in self.by_id:
                        self.fail(f"invalid edge {field}: {cell_id} -> {target}")
            if cell.get("vertex") == "1":
                self.absolute_box(cell_id)

    def check_geometry_collections(self) -> None:
        for cell_id, cell in self.by_id.items():
            geometry = cell_geometry(cell)
            if geometry is None:
                continue
            for array in geometry.findall("Array"):
                if array.get("as") != "points":
                    self.fail(
                        f"non-canonical geometry Array missing as='points': {cell_id}"
                    )

    def check_edge_endpoint_clearance(self) -> None:
        minimum = number(self.config.get("minimum_edge_endpoint_gap"), 16.0)
        exclusions = set(self.config.get("edge_endpoint_gap_exclusions", []))
        for cell_id, cell in self.by_id.items():
            if cell.get("edge") != "1" or cell_id in exclusions:
                continue
            source = self.absolute_box(cell.get("source", ""))
            target = self.absolute_box(cell.get("target", ""))
            if source is None or target is None:
                continue
            dx = max(source.x - target.right, target.x - source.right, 0.0)
            dy = max(source.y - target.bottom, target.y - source.bottom, 0.0)
            clearance = math.hypot(dx, dy)
            if clearance + 1e-6 < minimum:
                self.fail(
                    f"edge endpoints leave no clear arrow approach: {cell_id} "
                    f"({clearance:g} < {minimum:g})"
                )

    def vertex_sets(self) -> tuple[set[str], set[str], set[str]]:
        region_ids = set(self.config.get("regions", []))
        hierarchy_ids = set(self.config.get("hierarchy_anchors", {}))
        ignored_ids = set(self.config.get("ignore_geometry", []))
        for cell_id, cell in self.by_id.items():
            if cell.get("vertex") != "1":
                continue
            style = self.styles[cell_id]
            if style.get("dashed") == "1" and style.get("container") == "1":
                region_ids.add(cell_id)
            if style.get("shape") in {"singleArrow", "flexArrow"}:
                hierarchy_ids.add(cell_id)
            if "text" in style and style.get("strokeColor") in {"none", None}:
                ignored_ids.add(cell_id)
        return region_ids, hierarchy_ids, ignored_ids

    def check_required_and_text(self) -> None:
        for cell_id in self.config.get("required_cells", []):
            if cell_id not in self.by_id:
                self.fail(f"required cell missing: {cell_id}")
        expected_labels = self.config.get("expected_edge_labels", {})
        if not isinstance(expected_labels, dict):
            self.fail("expected_edge_labels must be an edge-ID-to-text object")
        else:
            for cell_id, expected in expected_labels.items():
                if not isinstance(expected, str) or cell_id not in self.by_id:
                    self.fail(f"expected edge label missing or malformed: {cell_id}")
                    continue
                actual = strip_markup(self.by_id[cell_id].get("value", ""))
                # Wrapping is visual; names, punctuation and dimensions cannot drift.
                normalize = lambda text: re.sub(r"\s+", "", text)
                if normalize(actual) != normalize(strip_markup(expected)):
                    self.fail(f"edge label text differs from generated contract: {cell_id}")
        exact = set(self.config.get("forbidden_exact_text", []))
        patterns = [re.compile(value) for value in self.config.get("forbidden_text_patterns", [])]
        for cell_id, cell in self.by_id.items():
            text = strip_markup(cell.get("value", ""))
            if text in exact:
                self.fail(f"forbidden exact text in {cell_id}: {text!r}")
            for pattern in patterns:
                if pattern.search(text):
                    self.fail(f"forbidden text pattern in {cell_id}: {pattern.pattern!r}")

        for cell_id, semantic in self.config.get("node_semantics", {}).items():
            if cell_id not in self.by_id:
                self.fail(f"semantic-ledger cell missing: {cell_id}")
            if not semantic.get("kind") or not semantic.get("evidence"):
                self.fail(f"incomplete semantic-ledger entry: {cell_id}")

    def check_semantic_styles(self) -> None:
        contract = self.config.get("semantic_style_contract")
        if contract is None:
            if self.config.get("require_semantic_style_contract") is True:
                self.fail("required DPSK V4 semantic-style contract is missing")
            return
        if not isinstance(contract, dict):
            self.fail("semantic_style_contract must be an object")
            return
        if contract.get("profile") != "dpsk-v4-original":
            self.fail("semantic_style_contract.profile must be 'dpsk-v4-original'")
        if contract.get("palette") != SEMANTIC_PALETTE:
            self.fail("semantic_style_contract palette differs from the canonical DPSK V4 palette")
        if contract.get("tp_partition_modifier") != TP_PARTITION_MODIFIER:
            self.fail("semantic_style_contract TP modifier differs from the canonical DPSK V4 style")
        if self.config.get("require_semantic_glyph_contract") is True and contract.get("glyphs") != SEMANTIC_GLYPHS:
            self.fail("semantic_style_contract glyph registry differs from the canonical glyph contract")

        canonical_entries = list(SEMANTIC_PALETTE)[:4] + ["tp-partition"] + list(SEMANTIC_PALETTE)[4:]
        expected_legend = {entry: f"legend:{entry}" for entry in canonical_entries}
        if contract.get("legend_title") != "legend:title" or contract.get("legend_entries") != expected_legend:
            self.fail("semantic Legend must contain the complete canonical nine-entry DPSK V4 key")
        expected_legend_ids = {"legend:title", *expected_legend.values()}
        actual_legend_ids = {cell_id for cell_id in self.by_id if cell_id.startswith("legend:")}
        if actual_legend_ids != expected_legend_ids:
            self.fail(
                "semantic Legend cells do not match the canonical key: "
                f"expected={sorted(expected_legend_ids)} actual={sorted(actual_legend_ids)}"
            )
        visible_legend_titles = [
            cell_id for cell_id, cell in self.by_id.items()
            if strip_markup(cell.get("value", "")) == "Legend / 图例"
        ]
        if visible_legend_titles != ["legend:title"]:
            self.fail(
                "diagram must contain exactly one canonical semantic Legend title: "
                f"actual={sorted(visible_legend_titles)}"
            )

        def check_style(cell_id: str, expected: dict[str, str], glyph: str = "operator") -> None:
            cell = self.by_id.get(cell_id)
            if cell is None or cell.get("vertex") != "1":
                self.fail(f"semantic-style cell missing or not a vertex: {cell_id}")
                return
            style = self.styles.get(cell_id, {})
            for field in ("fillColor", "strokeColor", "fontColor", "dashed"):
                actual = style.get(field, "0" if field == "dashed" else "")
                wanted = expected[field]
                if actual.casefold() != wanted.casefold():
                    self.fail(
                        f"semantic style mismatch: {cell_id} {field}={actual!r}; expected {wanted!r}"
                    )
            if self.config.get("require_semantic_glyph_contract") is True:
                if glyph not in SEMANTIC_GLYPHS:
                    self.fail(f"semantic-style cell has invalid glyph: {cell_id} -> {glyph!r}")
                    return
                expected_shape = SEMANTIC_GLYPHS[glyph]["shape"]
                actual_shape = (
                    "slanted-storage" if style.get("shape") == "parallelogram"
                    else "rounded-rectangle" if style.get("rounded") == "1" and "shape" not in style
                    else "unknown"
                )
                if actual_shape != expected_shape:
                    self.fail(
                        f"semantic glyph mismatch: {cell_id} shape={actual_shape!r}; expected {expected_shape!r}"
                    )

        nodes = contract.get("nodes")
        if not isinstance(nodes, dict):
            self.fail("semantic_style_contract.nodes must be an ID-to-style mapping")
            nodes = {}
        semantic_nodes = {
            cell_id for cell_id, semantic in self.config.get("node_semantics", {}).items()
            if semantic.get("kind") != "junction"
        }
        if set(nodes) != semantic_nodes:
            self.fail("semantic-style node coverage does not match the semantic node ledger")
        for cell_id, semantic in nodes.items():
            if not isinstance(semantic, dict):
                self.fail(f"semantic-style node entry must be an object: {cell_id}")
                continue
            visual_class = semantic.get("visual_class")
            modifiers = semantic.get("visual_modifiers", [])
            if visual_class not in SEMANTIC_PALETTE:
                self.fail(f"semantic-style node has invalid class: {cell_id} -> {visual_class!r}")
                continue
            if not isinstance(modifiers, list) or any(item not in VISUAL_MODIFIERS for item in modifiers):
                self.fail(f"semantic-style node has invalid modifiers: {cell_id}")
                continue
            expected = dict(SEMANTIC_PALETTE[visual_class])
            expected.pop("label")
            if "tp-partition" in modifiers:
                expected["fontColor"] = TP_PARTITION_MODIFIER["fontColor"]
            check_style(cell_id, expected, semantic.get("glyph", "operator"))

        title = self.by_id.get("legend:title")
        if title is not None and strip_markup(title.get("value", "")) != "Legend / 图例":
            self.fail("semantic Legend title text is not canonical")
        for visual_class, palette in SEMANTIC_PALETTE.items():
            cell_id = expected_legend[visual_class]
            cell = self.by_id.get(cell_id)
            if cell is not None and strip_markup(cell.get("value", "")) != palette["label"]:
                self.fail(f"semantic Legend label mismatch: {cell_id}")
            expected = dict(palette)
            expected.pop("label")
            glyph = contract.get("legend_glyphs", {}).get(visual_class, "operator")
            check_style(cell_id, expected, glyph)
        tp_id = expected_legend["tp-partition"]
        tp_cell = self.by_id.get(tp_id)
        if tp_cell is not None and strip_markup(tp_cell.get("value", "")) != TP_PARTITION_MODIFIER["label"]:
            self.fail(f"semantic Legend label mismatch: {tp_id}")
        check_style(tp_id, {
            "fillColor": TP_PARTITION_MODIFIER["legend_fillColor"],
            "strokeColor": TP_PARTITION_MODIFIER["legend_strokeColor"],
            "fontColor": TP_PARTITION_MODIFIER["fontColor"],
            "dashed": TP_PARTITION_MODIFIER["legend_dashed"],
        })

    def check_ports_and_expected_edges(self) -> None:
        require_ports = bool(self.config.get("require_fixed_ports", False))
        excluded = set(self.config.get("port_check_exclusions", []))
        actual_ports: dict[str, dict[str, float]] = {}
        for cell_id, cell in self.by_id.items():
            if cell.get("edge") != "1":
                continue
            style = self.styles[cell_id]
            if require_ports and cell_id not in excluded:
                missing = [key for key in ("exitX", "exitY", "entryX", "entryY") if key not in style]
                if missing:
                    self.fail(f"edge missing fixed ports {missing}: {cell_id}")
            values: dict[str, float] = {}
            for key in ("exitX", "exitY", "entryX", "entryY"):
                if key not in style:
                    continue
                try:
                    value = float(style[key])
                except (TypeError, ValueError):
                    self.fail(f"edge fixed port coordinate is not numeric: {cell_id} {key}={style[key]!r}")
                    continue
                if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                    self.fail(f"edge fixed port coordinate outside [0,1]: {cell_id} {key}={value}")
                    continue
                values[key] = value
            actual_ports[cell_id] = values
            for prefix in ("exit", "entry"):
                x_key, y_key = f"{prefix}X", f"{prefix}Y"
                if x_key not in values or y_key not in values:
                    continue
                boundary_hits = sum(
                    math.isclose(values[key], boundary, abs_tol=1e-9)
                    for key in (x_key, y_key) for boundary in (0.0, 1.0)
                )
                if boundary_hits == 0:
                    self.fail(
                        f"edge fixed port lies inside the endpoint instead of on its boundary: "
                        f"{cell_id} {prefix}=({values[x_key]:g},{values[y_key]:g})"
                    )

        expected_ports = self.config.get("expected_ports", {})
        if not isinstance(expected_ports, dict):
            self.fail("expected_ports must be an edge-ID-to-coordinate object")
            expected_ports = {}
        if self.config.get("require_port_geometry_contracts") is True:
            expected_edge_ids = set(self.config.get("expected_edges", {}))
            if set(expected_ports) != expected_edge_ids:
                self.fail(
                    "expected_ports must cover every expected ordinary edge exactly: "
                    f"expected={sorted(expected_edge_ids)} actual={sorted(expected_ports)}"
                )
        for edge_id, expected in expected_ports.items():
            if edge_id not in self.by_id or self.by_id[edge_id].get("edge") != "1":
                self.fail(f"expected port contract references missing edge: {edge_id}")
                continue
            required_fields = {"exitX", "exitY", "entryX", "entryY", "exitSide", "entrySide"}
            if not isinstance(expected, dict) or set(expected) != required_fields:
                self.fail(f"expected port contract is invalid: {edge_id}")
                continue
            for side_key in ("exitSide", "entrySide"):
                if expected[side_key] not in {"north", "south", "east", "west"}:
                    self.fail(f"expected port side is invalid: {edge_id} {side_key}={expected[side_key]!r}")
            actual = actual_ports.get(edge_id, {})
            wanted_values: dict[str, float] = {}
            for key in ("exitX", "exitY", "entryX", "entryY"):
                wanted = expected[key]
                try:
                    wanted_value = float(wanted)
                except (TypeError, ValueError):
                    self.fail(f"expected port coordinate is not numeric: {edge_id} {key}={wanted!r}")
                    continue
                if not math.isfinite(wanted_value) or not 0.0 <= wanted_value <= 1.0:
                    self.fail(f"expected port coordinate outside [0,1]: {edge_id} {key}={wanted_value}")
                    continue
                wanted_values[key] = wanted_value
                if key not in actual or not math.isclose(actual[key], wanted_value, abs_tol=1e-9):
                    self.fail(
                        f"edge port differs from layout contract: {edge_id} "
                        f"{key}={actual.get(key)!r}; expected {wanted_value:g}"
                    )
            side_coordinates = {
                "north": ("Y", 0.0), "south": ("Y", 1.0),
                "west": ("X", 0.0), "east": ("X", 1.0),
            }
            for prefix in ("exit", "entry"):
                side = expected.get(f"{prefix}Side")
                if side not in side_coordinates:
                    continue
                axis, boundary = side_coordinates[side]
                key = f"{prefix}{axis}"
                if key in wanted_values and not math.isclose(wanted_values[key], boundary, abs_tol=1e-9):
                    self.fail(
                        f"expected port side disagrees with its coordinates: {edge_id} "
                        f"{prefix}Side={side!r} {key}={wanted_values[key]:g}"
                    )

        for edge_id, expected in self.config.get("expected_edges", {}).items():
            edge = self.by_id.get(edge_id)
            if edge is None or edge.get("edge") != "1":
                self.fail(f"expected edge missing: {edge_id}")
                continue
            for field in ("source", "target"):
                value = expected.get(field)
                if value is not None and edge.get(field) != value:
                    self.fail(
                        f"edge {edge_id} {field}={edge.get(field)!r}; expected {value!r}"
                    )

    def check_edge_label_positions(self) -> None:
        expected = self.config.get("expected_edge_label_positions", {})
        if not isinstance(expected, dict):
            self.fail("expected_edge_label_positions must be an edge-ID-to-position object")
            expected = {}
        actual: dict[str, dict[str, float]] = {}
        for cell_id, cell in self.by_id.items():
            if cell.get("edge") != "1":
                continue
            geometry = cell_geometry(cell)
            if geometry is None:
                continue
            present = {key for key in ("x", "y") if geometry.get(key) is not None}
            if not present:
                continue
            if present != {"x", "y"}:
                self.fail(f"edge label position must contain both x and y: {cell_id}")
                continue
            try:
                x, y = float(geometry.get("x", "")), float(geometry.get("y", ""))
            except (TypeError, ValueError):
                self.fail(f"edge label position is not numeric: {cell_id}")
                continue
            if not math.isfinite(x) or not -1.0 <= x <= 1.0:
                self.fail(f"edge label relative x outside [-1,1]: {cell_id} x={x}")
            if not math.isfinite(y) or abs(y) > MAX_EDGE_LABEL_OFFSET:
                self.fail(
                    f"edge label offset y outside [-{MAX_EDGE_LABEL_OFFSET:g},{MAX_EDGE_LABEL_OFFSET:g}]: "
                    f"{cell_id} y={y}"
                )
            actual[cell_id] = {"x": x, "y": y}

        if self.config.get("require_registered_edge_label_positions") is True:
            for edge_id in sorted(set(actual) - set(expected)):
                self.fail(f"unregistered edge label position; update layout.json instead of XML: {edge_id}")
            for edge_id in sorted(set(expected) - set(actual)):
                self.fail(f"expected edge label position missing from Draw.io XML: {edge_id}")
        for edge_id, wanted in expected.items():
            if not isinstance(wanted, dict) or set(wanted) != {"x", "y"}:
                self.fail(f"expected edge label position contract is invalid: {edge_id}")
                continue
            if edge_id not in actual:
                continue
            for key in ("x", "y"):
                try:
                    wanted_value = float(wanted[key])
                except (TypeError, ValueError):
                    self.fail(f"expected edge label position is not numeric: {edge_id} {key}")
                    continue
                if not math.isclose(actual[edge_id][key], wanted_value, abs_tol=1e-9):
                    self.fail(
                        f"edge label position differs from layout contract: {edge_id} "
                        f"{key}={actual[edge_id][key]:g}; expected {wanted_value:g}"
                    )

    def check_fanout_shape_contracts(self) -> None:
        contracts = self.config.get("fanout_shape_contracts", {})
        if not isinstance(contracts, dict):
            self.fail("fanout_shape_contracts must be an ID-to-contract object")
            return
        outgoing: dict[str, list[ET.Element]] = {}
        for cell in self.by_id.values():
            if cell.get("edge") == "1":
                outgoing.setdefault(cell.get("source", ""), []).append(cell)

        exclusions = set(self.config.get("fanout_shape_exclusions", []))
        side_exclusions = set(self.config.get("fanout_side_exclusions", []))
        for source_id, edges in outgoing.items():
            if len(edges) >= 3 and source_id not in side_exclusions:
                sides: set[str] = set()
                for edge in edges:
                    style = self.styles.get(edge.get("id", ""), {})
                    exit_x = number(style.get("exitX"), 0.5)
                    exit_y = number(style.get("exitY"), 0.5)
                    if math.isclose(exit_y, 0.0):
                        sides.add("top")
                    elif math.isclose(exit_y, 1.0):
                        sides.add("bottom")
                    elif math.isclose(exit_x, 0.0):
                        sides.add("left")
                    elif math.isclose(exit_x, 1.0):
                        sides.add("right")
                    else:
                        sides.add("interior")
                if len(sides) > 1:
                    self.fail(
                        f"fan-out leaves source from mixed sides and can read as a pass-through: "
                        f"{source_id} ({', '.join(sorted(sides))})"
                    )
            if len(edges) < 3 or source_id in exclusions or source_id in contracts:
                continue
            labels = [bool(strip_markup(edge.get("value", ""))) for edge in edges]
            if any(labels) and not all(labels):
                self.fail(
                    f"fan-out has ambiguous mixed edge labels without a shape contract: {source_id}"
                )

        for source_id, contract in contracts.items():
            if source_id not in self.by_id:
                self.fail(f"fanout shape contract references missing source: {source_id}")
                continue
            if not isinstance(contract, dict):
                self.fail(f"fanout shape contract must be an object: {source_id}")
                continue
            edges = outgoing.get(source_id, [])
            expected_ids = set(contract.get("edge_ids", []))
            actual_ids = {edge.get("id", "") for edge in edges}
            if expected_ids and expected_ids != actual_ids:
                self.fail(
                    f"fanout shape contract edge set drifted: {source_id} "
                    f"expected={sorted(expected_ids)} actual={sorted(actual_ids)}"
                )
            shape = contract.get("shape", "")
            mode = contract.get("mode")
            if not isinstance(shape, str) or not shape.strip():
                self.fail(f"fanout shape contract missing shape: {source_id}")
                continue
            if mode == "source-node":
                if shape not in strip_markup(self.by_id[source_id].get("value", "")):
                    self.fail(f"fanout source node does not state {shape!r}: {source_id}")
                for edge in edges:
                    if shape in strip_markup(edge.get("value", "")):
                        self.fail(
                            f"fanout source-node shape is redundantly attached to one branch: {edge.get('id')}"
                        )
            elif mode == "every-branch":
                for edge in edges:
                    if shape not in strip_markup(edge.get("value", "")):
                        self.fail(f"fanout branch is missing {shape!r}: {edge.get('id')}")
            else:
                self.fail(f"invalid fanout shape mode for {source_id}: {mode!r}")

    def check_regions(self, region_ids: set[str]) -> None:
        parent_map = self.config.get("region_parents", {})
        min_gutter = float(self.config.get("min_region_gutter", 20))
        for child_id, parent_id in parent_map.items():
            child = self.absolute_box(child_id)
            parent = self.absolute_box(parent_id)
            if child is None or parent is None:
                self.fail(f"region ownership references missing geometry: {child_id} -> {parent_id}")
                continue
            if not (
                parent.x <= child.x and parent.y <= child.y
                and child.right <= parent.right and child.bottom <= parent.bottom
            ):
                self.fail(f"child region escapes parent: {child_id} -> {parent_id}")

        content_contracts = self.config.get("region_content_contracts", {})
        if not isinstance(content_contracts, dict):
            self.fail("region_content_contracts must be a region-to-cell-list object")
        else:
            for region_id, content_ids in content_contracts.items():
                region = self.absolute_box(region_id)
                if region is None:
                    self.fail(f"region content contract references missing region: {region_id}")
                    continue
                for content_id in content_ids:
                    content = self.absolute_box(content_id)
                    if content is None:
                        self.fail(f"region content contract references missing cell: {content_id}")
                    elif not self.box_contains(region, content):
                        self.fail(f"contracted content escapes region: {content_id} -> {region_id}")

        allowed_boundary_nodes = configured_pairs(
            self.config.get("allowed_region_boundary_nodes", [])
        )
        for cell_id, cell in self.by_id.items():
            if cell.get("vertex") != "1" or cell_id in region_ids:
                continue
            style = self.styles.get(cell_id, {})
            if style.get("shape") in {"singleArrow", "flexArrow"}:
                continue
            if "text" in style and style.get("strokeColor") in {"none", None}:
                continue
            cell_box = self.absolute_box(cell_id)
            if cell_box is None:
                continue
            for region_id in region_ids:
                if pair_key(cell_id, region_id) in allowed_boundary_nodes:
                    continue
                region = self.absolute_box(region_id)
                if region is None:
                    continue
                intersects = (
                    max(cell_box.x, region.x) < min(cell_box.right, region.right)
                    and max(cell_box.y, region.y) < min(cell_box.bottom, region.bottom)
                )
                if intersects and not self.box_contains(region, cell_box):
                    self.fail(f"node partially crosses region boundary: {cell_id} / {region_id}")

        siblings: dict[str | None, list[str]] = {}
        for region_id in region_ids:
            if region_id in self.by_id:
                siblings.setdefault(parent_map.get(region_id), []).append(region_id)
        allowed = configured_pairs(self.config.get("allowed_region_contacts", []))
        for sibling_ids in siblings.values():
            for index, left_id in enumerate(sibling_ids):
                left = self.absolute_box(left_id)
                if left is None:
                    continue
                for right_id in sibling_ids[index + 1 :]:
                    if pair_key(left_id, right_id) in allowed:
                        continue
                    right = self.absolute_box(right_id)
                    if right is None:
                        continue
                    x_overlap = min(left.right, right.right) - max(left.x, right.x)
                    y_overlap = min(left.bottom, right.bottom) - max(left.y, right.y)
                    if x_overlap > 0 and y_overlap > 0:
                        self.fail(f"sibling regions intersect: {left_id} / {right_id}")
                    elif y_overlap > 0:
                        gap = max(right.x - left.right, left.x - right.right)
                        if 0 <= gap < min_gutter:
                            self.fail(f"horizontal region gutter {gap:g}px: {left_id} / {right_id}")
                    elif x_overlap > 0:
                        gap = max(right.y - left.bottom, left.y - right.bottom)
                        if 0 <= gap < min_gutter:
                            self.fail(f"vertical region gutter {gap:g}px: {left_id} / {right_id}")

    def check_node_overlaps(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        excluded = region_ids | hierarchy_ids | ignored_ids
        nodes = [
            cell_id for cell_id, cell in self.by_id.items()
            if cell.get("vertex") == "1" and cell_id not in excluded
        ]
        allowed = configured_pairs(self.config.get("allowed_node_overlaps", []))
        for index, left_id in enumerate(nodes):
            left = self.absolute_box(left_id)
            if left is None:
                continue
            for right_id in nodes[index + 1 :]:
                if pair_key(left_id, right_id) in allowed:
                    continue
                right = self.absolute_box(right_id)
                if right is None:
                    continue
                if min(left.right, right.right) > max(left.x, right.x) and min(
                    left.bottom, right.bottom
                ) > max(left.y, right.y):
                    self.fail(f"nodes overlap: {left_id} / {right_id}")

    def immediate_content_regions(self, cell_ids: set[str]) -> dict[str, str]:
        """Resolve each contracted cell to its smallest visual owner region."""
        owners: dict[str, tuple[str, float]] = {}
        contracts = self.config.get("region_content_contracts", {})
        if not isinstance(contracts, dict):
            return {}
        for region_id, members in contracts.items():
            region = self.absolute_box(region_id)
            if region is None or not isinstance(members, list):
                continue
            area = region.w * region.h
            for cell_id in members:
                if cell_id not in cell_ids:
                    continue
                current = owners.get(cell_id)
                if current is None or area < current[1]:
                    owners[cell_id] = (region_id, area)
        return {cell_id: owner[0] for cell_id, owner in owners.items()}

    def check_visual_clearances(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        """Reject visually merged nodes and border-riding parallel routes."""
        def reasoned_pairs(name: str) -> set[tuple[str, str]]:
            values = self.config.get(name, {})
            if not isinstance(values, dict):
                self.fail(f"{name} must be a 'left|right'-to-reason object")
                return set()
            result: set[tuple[str, str]] = set()
            for key, reason in values.items():
                parts = key.split("|") if isinstance(key, str) else []
                if len(parts) != 2 or not all(parts):
                    self.fail(f"{name} has an invalid pair key: {key!r}")
                    continue
                if not isinstance(reason, str) or not reason.strip():
                    self.fail(f"{name} has an empty reason: {key}")
                    continue
                result.add(pair_key(parts[0], parts[1]))
            return result

        ordinary_nodes = {
            cell_id for cell_id, cell in self.by_id.items()
            if cell.get("vertex") == "1"
            and cell_id not in region_ids | hierarchy_ids | ignored_ids
        }
        owner_by_node = self.immediate_content_regions(ordinary_nodes)

        node_gutter = self.config.get("minimum_node_gutter")
        if node_gutter is not None:
            minimum = float(node_gutter)
            exclusions = reasoned_pairs("node_gutter_exclusions")
            node_ids = sorted(ordinary_nodes)
            for index, left_id in enumerate(node_ids):
                left = self.absolute_box(left_id)
                if left is None:
                    continue
                for right_id in node_ids[index + 1:]:
                    if owner_by_node.get(left_id) != owner_by_node.get(right_id):
                        continue
                    if pair_key(left_id, right_id) in exclusions:
                        continue
                    right = self.absolute_box(right_id)
                    if right is None:
                        continue
                    x_overlap = min(left.right, right.right) - max(left.x, right.x)
                    y_overlap = min(left.bottom, right.bottom) - max(left.y, right.y)
                    if x_overlap > 0 and y_overlap <= 0:
                        gap = max(right.y - left.bottom, left.y - right.bottom)
                    elif y_overlap > 0 and x_overlap <= 0:
                        gap = max(right.x - left.right, left.x - right.right)
                    else:
                        continue
                    if 0 <= gap + 1e-6 < minimum:
                        self.fail(
                            f"node gutter is visually collapsed: {left_id} / {right_id} "
                            f"({gap:g} < {minimum:g})"
                        )

        route_node_minimum = self.config.get("minimum_route_node_clearance")
        route_region_minimum = self.config.get("minimum_route_region_boundary_clearance")
        if route_node_minimum is None and route_region_minimum is None:
            return
        route_node_exclusions = reasoned_pairs("route_node_clearance_exclusions")
        route_region_exclusions = reasoned_pairs("route_region_clearance_exclusions")
        for edge_id, edge in self.by_id.items():
            if edge.get("edge") != "1":
                continue
            points = self.edge_points(edge_id)
            if len(points) < 2:
                continue
            source_id = edge.get("source", "")
            target_id = edge.get("target", "")
            if route_node_minimum is not None:
                minimum = float(route_node_minimum)
                for node_id in ordinary_nodes:
                    if pair_key(edge_id, node_id) in route_node_exclusions:
                        continue
                    box = self.absolute_box(node_id)
                    if box is None:
                        continue
                    for first, last in zip(points, points[1:]):
                        axis, fixed, low, high = self.segment(first, last)
                        clearance = None
                        overlap = 0.0
                        if axis == "v" and (fixed < box.x or fixed > box.right):
                            clearance = min(abs(fixed - box.x), abs(fixed - box.right))
                            overlap = min(high, box.bottom) - max(low, box.y)
                        elif axis == "h" and (fixed < box.y or fixed > box.bottom):
                            clearance = min(abs(fixed - box.y), abs(fixed - box.bottom))
                            overlap = min(high, box.right) - max(low, box.x)
                        if overlap > 1 and clearance is not None and clearance + 1e-6 < minimum:
                            self.fail(
                                f"route runs too close and parallel to node: {edge_id} / {node_id} "
                                f"({clearance:g} < {minimum:g})"
                            )
                            break

            if route_region_minimum is None:
                continue
            source_owner = owner_by_node.get(source_id)
            target_owner = owner_by_node.get(target_id)
            if source_owner is None or source_owner != target_owner:
                continue
            region_id = source_owner
            if pair_key(edge_id, region_id) in route_region_exclusions:
                continue
            region = self.absolute_box(region_id)
            if region is None:
                continue
            minimum = float(route_region_minimum)
            for first, last in zip(points, points[1:]):
                axis, fixed, low, high = self.segment(first, last)
                clearance = None
                overlap = 0.0
                if axis == "v":
                    clearance = min(abs(fixed - region.x), abs(fixed - region.right))
                    overlap = min(high, region.bottom) - max(low, region.y)
                elif axis == "h":
                    clearance = min(abs(fixed - region.y), abs(fixed - region.bottom))
                    overlap = min(high, region.right) - max(low, region.x)
                if overlap > 1 and clearance is not None and clearance + 1e-6 < minimum:
                    self.fail(
                        f"route runs too close and parallel to owner-region boundary: "
                        f"{edge_id} / {region_id} ({clearance:g} < {minimum:g})"
                    )
                    break

    def check_compact_execution_geometry(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        """Keep execution content compact independently of hierarchy-arrow corridors."""
        if not self.config.get("require_compact_execution_geometry", False):
            return

        ordinary_nodes = {
            cell_id for cell_id, cell in self.by_id.items()
            if cell.get("vertex") == "1"
            and cell_id not in region_ids | hierarchy_ids | ignored_ids
        }
        owner_by_node = self.immediate_content_regions(ordinary_nodes)
        parent_map = self.config.get("region_parents", {})
        if not isinstance(parent_map, dict):
            self.fail("region_parents must be an object for compact execution geometry")
            return

        slack_sides = ("left", "right", "top", "bottom")
        directional_slack = self.config.get("maximum_region_content_slack")
        try:
            if directional_slack is None:
                # Migration fallback for manifests generated before directional budgets.
                legacy_slack = number(self.config.get("maximum_region_content_side_slack"), 160.0)
                max_slacks = {side: legacy_slack for side in slack_sides}
            else:
                if not isinstance(directional_slack, dict) or set(directional_slack) != set(slack_sides):
                    self.fail(
                        "maximum_region_content_slack must contain exactly "
                        "left, right, top, and bottom"
                    )
                    return
                max_slacks = {
                    side: number(directional_slack[side]) for side in slack_sides
                }
            max_lane_gap = number(self.config.get("maximum_parallel_lane_gap"), 160.0)
        except (TypeError, ValueError):
            self.fail("compact execution geometry thresholds must be finite positive numbers")
            return
        if (
            any(not math.isfinite(value) or value <= 0 for value in max_slacks.values())
            or not math.isfinite(max_lane_gap)
            or max_lane_gap <= 0
        ):
            self.fail("compact execution geometry thresholds must be positive")
            return

        slack_exceptions = self.config.get("region_side_slack_exceptions", {})
        lane_exceptions = self.config.get("parallel_lane_gap_exceptions", {})
        for name, values in (
            ("region_side_slack_exceptions", slack_exceptions),
            ("parallel_lane_gap_exceptions", lane_exceptions),
        ):
            if not isinstance(values, dict):
                self.fail(f"{name} must be an ID-to-reason object")
                return
            for key, reason in values.items():
                if not isinstance(key, str) or not key or not isinstance(reason, str) or not reason.strip():
                    self.fail(f"{name} has an invalid or unreasoned entry: {key!r}")

        children: dict[str, list[str]] = {}
        for child_id, parent_id in parent_map.items():
            children.setdefault(parent_id, []).append(child_id)

        for region_id in sorted(region_ids):
            if region_id in slack_exceptions:
                continue
            region = self.absolute_box(region_id)
            if region is None:
                continue
            content_ids = [
                node_id for node_id, owner_id in owner_by_node.items() if owner_id == region_id
            ] + children.get(region_id, [])
            boxes = [self.absolute_box(cell_id) for cell_id in content_ids]
            boxes = [box for box in boxes if box is not None]
            if not boxes:
                continue
            start_size = number(self.styles.get(region_id, {}).get("startSize"), 0.0)
            content_left = min(box.x for box in boxes)
            content_right = max(box.right for box in boxes)
            content_top = min(box.y for box in boxes)
            content_bottom = max(box.bottom for box in boxes)
            slacks = {
                "left": content_left - region.x,
                "right": region.right - content_right,
                "top": content_top - (region.y + start_size),
                "bottom": region.bottom - content_bottom,
            }
            for side, slack in slacks.items():
                exception_key = f"{region_id}|{side}"
                if exception_key in slack_exceptions:
                    continue
                max_slack = max_slacks[side]
                if slack > max_slack + 1e-6:
                    self.fail(
                        f"region execution envelope has excessive {side} slack: {region_id} "
                        f"({slack:g}px > {max_slack:g}px); hierarchy arrows and routing lanes "
                        "must stay outside the content-derived region extent"
                    )

        legal_slack_keys = set(region_ids) | {
            f"{region_id}|{side}"
            for region_id in region_ids for side in ("left", "right", "top", "bottom")
        }
        for key in set(slack_exceptions) - legal_slack_keys:
            self.fail(f"region-side slack exception references no region side: {key}")

        contracts = self.config.get("vertical_flow_contracts", {})
        if not isinstance(contracts, dict):
            return
        legal_lane_keys: set[str] = set()
        for region_id, contract in contracts.items():
            sequences = contract.get("sequences", []) if isinstance(contract, dict) else []
            if not isinstance(sequences, list):
                continue
            sequence_boxes: list[tuple[str, Box]] = []
            valid_sequences = [
                sequence for sequence in sequences
                if isinstance(sequence, dict) and isinstance(sequence.get("nodes", []), list)
            ]
            all_members = [set(sequence.get("nodes", [])) for sequence in valid_sequences]
            for index, sequence in enumerate(valid_sequences):
                members = all_members[index]
                shared = set().union(*(other for other_index, other in enumerate(all_members) if other_index != index)) if len(all_members) > 1 else set()
                exclusive = members - shared
                boxes = [self.absolute_box(node_id) for node_id in exclusive]
                boxes = [box for box in boxes if box is not None]
                if not boxes:
                    continue
                sequence_boxes.append((
                    str(sequence.get("id", index)),
                    Box(
                        min(box.x for box in boxes), min(box.y for box in boxes),
                        max(box.right for box in boxes) - min(box.x for box in boxes),
                        max(box.bottom for box in boxes) - min(box.y for box in boxes),
                    ),
                ))
            sequence_boxes.sort(key=lambda item: item[1].x)
            # Sequences at different execution heights are not adjacent parallel lanes.
            # Sweep overlap bands so an unrelated intermediate lane cannot hide a gap.
            levels = sorted({value for _, box in sequence_boxes for value in (box.y, box.bottom)})
            adjacent_pairs = {}
            for low, high in zip(levels, levels[1:]):
                if high <= low:
                    continue
                middle = (low + high) / 2
                active = [(name, box) for name, box in sequence_boxes if box.y < middle < box.bottom]
                for left_item, right_item in zip(active, active[1:]):
                    adjacent_pairs[(left_item[0], right_item[0])] = (left_item, right_item)
            for (left_name, left), (right_name, right) in adjacent_pairs.values():
                gap = right.x - left.right
                key = f"{region_id}|{left_name}|{right_name}"
                reverse_key = f"{region_id}|{right_name}|{left_name}"
                legal_lane_keys.update((key, reverse_key))
                if key in lane_exceptions or reverse_key in lane_exceptions:
                    continue
                if gap > max_lane_gap:
                    # Shared trunk nodes are excluded from sequence envelopes, but
                    # their occupied columns still break an allegedly empty strip.
                    overlap_top = max(left.y, right.y)
                    overlap_bottom = min(left.bottom, right.bottom)
                    occupied = []
                    for node_id, owner_id in owner_by_node.items():
                        if owner_id != region_id:
                            continue
                        box = self.absolute_box(node_id)
                        if (box is not None and box.y < overlap_bottom and box.bottom > overlap_top
                                and box.x < right.x and box.right > left.right):
                            occupied.append((max(left.right, box.x), min(right.x, box.right)))
                    cursor, empty_gaps = left.right, []
                    for start, end in sorted(occupied):
                        empty_gaps.append(max(0.0, start - cursor))
                        cursor = max(cursor, end)
                    empty_gaps.append(max(0.0, right.x - cursor))
                    gap = max(empty_gaps)
                if gap > max_lane_gap + 1e-6:
                    self.fail(
                        f"parallel lanes are spread apart: {region_id} / {left_name} / {right_name} "
                        f"({gap:g}px > {max_lane_gap:g}px); keep branch lanes adjacent and "
                        "route hierarchy expansion through an external egress"
                    )
        for key in set(lane_exceptions) - legal_lane_keys:
            self.fail(f"parallel-lane gap exception references no adjacent lane pair: {key}")

    def check_semantic_coverage(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        if not self.config.get("require_semantic_coverage", False):
            return
        covered = set(self.config.get("node_semantics", {}))
        excluded = (
            region_ids
            | hierarchy_ids
            | ignored_ids
            | set(self.config.get("semantic_coverage_exclusions", []))
        )
        for cell_id, cell in self.by_id.items():
            if cell.get("vertex") == "1" and cell_id not in excluded and cell_id not in covered:
                self.fail(f"semantic-ledger coverage missing: {cell_id}")

    @staticmethod
    def operator_hit_count(text: str, semantics: dict | None = None) -> int:
        if (isinstance(semantics, dict) and semantics.get("op_type") == "scale"
                and semantics.get("operator_classification") == "atomic-operator"
                and semantics.get("shape_rule") == "preserve"
                and semantics.get("source_symbols")):
            # An inverse-root coefficient describes one scale, not a runtime sqrt
            # followed by scaling. Explicit "sqrt -> scale" still counts twice.
            text = re.sub(r"\binverse[- ](?:sqrt|square[- ]root)\b", "reciprocal-root", text, flags=re.IGNORECASE)
        return sum(len(pattern.findall(text)) for pattern in OPERATOR_PATTERNS)

    @staticmethod
    def box_contains(outer: Box, inner: Box) -> bool:
        return (
            outer.x <= inner.x
            and outer.y <= inner.y
            and inner.right <= outer.right
            and inner.bottom <= outer.bottom
        )

    def check_vertical_flow_contracts(self, region_ids: set[str]) -> None:
        contracts = self.config.get("vertical_flow_contracts", {})
        if not isinstance(contracts, dict):
            self.fail("vertical_flow_contracts must be an object")
            return
        if self.config.get("require_vertical_flow_contracts", False):
            for region_id in sorted(region_ids - set(contracts)):
                self.fail(f"required vertical-flow contract missing: {region_id}")

        try:
            lateral_ratio = float(self.config.get("maximum_vertical_flow_lateral_gap_ratio", 4.0))
            lateral_floor = float(self.config.get("minimum_vertical_flow_lateral_gap_allowance", 240.0))
        except (TypeError, ValueError):
            self.fail("vertical-flow lateral-gap thresholds must be numbers")
            return
        if lateral_ratio <= 0 or lateral_floor < 0:
            self.fail("vertical-flow lateral-gap thresholds must be positive")
            return
        lateral_exclusions = self.config.get("vertical_flow_lateral_gap_exclusions", {})
        if not isinstance(lateral_exclusions, dict):
            self.fail("vertical_flow_lateral_gap_exclusions must be an ID-pair-to-reason object")
            return
        for key, reason in lateral_exclusions.items():
            if not isinstance(reason, str) or not reason.strip():
                self.fail(f"vertical-flow lateral-gap exclusion missing reason: {key}")
        declared_steps: set[str] = set()
        reviewed_steps: set[str] = set()

        for region_id, contract in contracts.items():
            if region_id not in region_ids or region_id not in self.by_id:
                self.fail(f"vertical-flow contract region missing or not declared: {region_id}")
                continue
            if not isinstance(contract, dict):
                self.fail(f"vertical-flow contract must be an object: {region_id}")
                continue
            if contract.get("direction") != "bottom-to-top":
                self.fail(f"vertical-flow contract has invalid direction: {region_id}")
            sequences = contract.get("sequences")
            if not isinstance(sequences, list):
                self.fail(f"vertical-flow contract sequences must be a list: {region_id}")
                continue
            for index, sequence in enumerate(sequences):
                if not isinstance(sequence, dict) or not isinstance(sequence.get("nodes"), list):
                    self.fail(f"vertical-flow sequence is invalid: {region_id} / index {index}")
                    continue
                sequence_id = sequence.get("id", f"index-{index}")
                path = sequence["nodes"]
                for node_id in path:
                    if node_id not in self.by_id:
                        self.fail(f"vertical-flow sequence names missing node: {region_id} / {node_id}")
                for source_id, target_id in zip(path, path[1:]):
                    step_key = f"{source_id}->{target_id}"
                    declared_steps.add(step_key)
                    source = self.absolute_box(source_id)
                    target = self.absolute_box(target_id)
                    if source is None or target is None:
                        continue
                    source_center = source.y + source.h / 2
                    target_center = target.y + target.h / 2
                    if target_center >= source_center:
                        self.fail(
                            f"vertical-flow sequence does not rise bottom-to-top: {region_id} "
                            f"/ {sequence_id!r} / {source_id} -> {target_id}"
                        )
                    if step_key in reviewed_steps or step_key in lateral_exclusions:
                        continue
                    reviewed_steps.add(step_key)
                    lateral_gap = max(0.0, max(source.x, target.x) - min(source.right, target.right))
                    allowance = max(lateral_floor, lateral_ratio * max(source.w, target.w))
                    if lateral_gap > allowance + 1e-6:
                        self.fail(
                            f"vertical-flow sequence has excessive lateral drift: {region_id} "
                            f"/ {sequence_id!r} / {source_id} -> {target_id} "
                            f"gap={lateral_gap:g}px allowance={allowance:g}px; "
                            "compact the shared trunk/adjacent lanes or record a source-backed exception"
                        )
        for key in sorted(set(lateral_exclusions) - declared_steps):
            self.fail(f"vertical-flow lateral-gap exclusion names no sequence step: {key}")

    def check_granularity_contracts(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        contracts = self.config.get("granularity_contracts", {})
        if not isinstance(contracts, dict):
            self.fail("granularity_contracts must be an object")
            return

        if self.config.get("require_granularity_contracts", False):
            pattern_values = self.config.get(
                "granularity_region_patterns",
                [r"\bLEVEL\s+[23][A-Z]?\b", r"\bFLOPS?\b", r"\bOPERATOR(?:-DETAIL)?\b"],
            )
            try:
                required_patterns = [re.compile(value, re.IGNORECASE) for value in pattern_values]
            except (TypeError, re.error) as error:
                self.fail(f"invalid granularity_region_patterns: {error}")
                required_patterns = []
            for candidate_id in region_ids:
                cell = self.by_id.get(candidate_id)
                if cell is None:
                    continue
                text = strip_markup(cell.get("value", ""))
                if any(pattern.search(text) for pattern in required_patterns) and candidate_id not in contracts:
                    self.fail(f"required granularity contract missing: {candidate_id} ({text!r})")

        for region_id, contract in contracts.items():
            if region_id not in self.by_id or region_id not in region_ids:
                self.fail(f"granularity contract region missing or not declared: {region_id}")
                continue
            if not isinstance(contract, dict):
                self.fail(f"granularity contract must be an object: {region_id}")
                continue
            mode = contract.get("mode")
            if mode not in {"module-summary", "operator-detail", "implementation-detail"}:
                self.fail(f"invalid granularity mode for {region_id}: {mode!r}")
                continue

            allowed = contract.get("allowed_composites", {})
            exclusions = contract.get("node_exclusions", {})
            if not isinstance(allowed, dict) or not isinstance(exclusions, dict):
                self.fail(f"granularity exceptions must be ID-keyed objects: {region_id}")
                continue

            region_box = self.absolute_box(region_id)
            if region_box is None:
                continue
            for node_id, reason in exclusions.items():
                if node_id not in self.by_id:
                    self.fail(f"granularity exclusion cell missing: {region_id} / {node_id}")
                if not isinstance(reason, str) or not reason.strip():
                    self.fail(f"granularity exclusion missing reason: {region_id} / {node_id}")

            for node_id, exception in allowed.items():
                if node_id not in self.by_id:
                    self.fail(f"allowed composite cell missing: {region_id} / {node_id}")
                    continue
                if not isinstance(exception, dict):
                    self.fail(f"allowed composite must be an object: {region_id} / {node_id}")
                    continue
                classification = exception.get("classification")
                if classification not in COMPOSITE_CLASSIFICATIONS:
                    self.fail(
                        f"invalid composite classification: {region_id} / {node_id} -> {classification!r}"
                    )
                if not exception.get("evidence") or not exception.get("reason"):
                    self.fail(f"allowed composite missing evidence/reason: {region_id} / {node_id}")
                if classification == "fused-operation" and not exception.get("source"):
                    self.fail(f"fused composite missing source: {region_id} / {node_id}")
                if classification == "fused-operation" and mode == "operator-detail":
                    self.fail(
                        f"fused-operation cannot collapse logical members in operator-detail: "
                        f"{region_id} / {node_id}"
                    )
                if classification == "expanded-elsewhere":
                    detail_target = exception.get("detail_target")
                    if not detail_target or detail_target not in self.by_id:
                        self.fail(f"expanded composite missing detail target: {region_id} / {node_id}")

            if mode != "operator-detail":
                continue

            excluded = region_ids | hierarchy_ids | ignored_ids | set(exclusions)
            for node_id, cell in self.by_id.items():
                if cell.get("vertex") != "1" or node_id in excluded:
                    continue
                node_box = self.absolute_box(node_id)
                if node_box is None or not self.box_contains(region_box, node_box):
                    continue
                text = strip_markup(cell.get("value", ""))
                semantics = self.config.get("node_semantics", {}).get(node_id, {})
                hit_count = self.operator_hit_count(text, semantics)
                if hit_count >= 2 and node_id not in allowed:
                    self.fail(
                        f"unreviewed composite node in operator-detail region {region_id}: "
                        f"{node_id} ({hit_count} operator terms, {text!r})"
                    )

    def check_typography_contract(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        contract = self.config.get("typography_contract")
        if contract is None:
            return
        if not isinstance(contract, dict):
            self.fail("typography_contract must be an object")
            return

        exception_fields = (
            "node_font_exceptions",
            "edge_font_exceptions",
            "annotation_font_exceptions",
            "region_font_exceptions",
            "wide_node_exceptions",
            "text_height_exceptions",
            "region_title_clearance_exceptions",
        )
        exceptions: dict[str, dict[str, str]] = {}
        for field in exception_fields:
            values = contract.get(field, {})
            if not isinstance(values, dict):
                self.fail(f"{field} must be an ID-to-reason object")
                values = {}
            for cell_id, reason in values.items():
                if cell_id not in self.by_id:
                    self.fail(f"{field} cell missing: {cell_id}")
                if not isinstance(reason, str) or not reason.strip():
                    self.fail(f"{field} missing reason: {cell_id}")
            exceptions[field] = values

        def font_size(cell_id: str) -> float | None:
            value = self.styles[cell_id].get("fontSize")
            try:
                return None if value is None else float(value)
            except ValueError:
                return None

        ordinary_font = float(contract.get("ordinary_node_font", 0))
        edge_font = float(contract.get("edge_label_font", 0))
        annotation_min = float(contract.get("annotation_font_min", 0))
        nested_title = float(contract.get("nested_region_title_font", 0))
        top_title = float(contract.get("top_region_title_font", 0))
        hierarchy_font = float(contract.get("hierarchy_label_font", 0))
        parent_map = self.config.get("region_parents", {})

        if ordinary_font > 0 and bool(contract.get("warn_role_ratio_drift", True)):
            role_ratios = {
                "edge label": (edge_font, 0.72, 0.78),
                "nested region title": (nested_title, 1.00, 1.10),
                "top region title": (top_title, 1.20, 1.30),
                "hierarchy label": (hierarchy_font, 0.74, 0.82),
            }
            for role, (value, lower, upper) in role_ratios.items():
                if value <= 0:
                    continue
                ratio = value / ordinary_font
                if ratio < lower or ratio > upper:
                    self.warn(
                        f"typography role ratio needs visual review: {role}={ratio:.2f}F "
                        f"(recommended {lower:.2f}F-{upper:.2f}F)"
                    )

        viewing_scale = contract.get("primary_view_scale")
        apparent_minimum = contract.get("minimum_apparent_ordinary_font")
        apparent_target = contract.get("target_apparent_ordinary_font")
        viewing_values = (viewing_scale, apparent_minimum, apparent_target)
        if any(value is not None for value in viewing_values):
            if not all(isinstance(value, (int, float)) and value > 0 for value in viewing_values):
                self.fail(
                    "primary_view_scale, minimum_apparent_ordinary_font, and "
                    "target_apparent_ordinary_font must all be positive numbers"
                )
            elif apparent_minimum > apparent_target:
                self.fail("minimum apparent ordinary font exceeds its target")
            else:
                apparent = ordinary_font * viewing_scale
                if apparent + 1e-6 < apparent_minimum:
                    self.fail(
                        f"ordinary-node apparent font {apparent:.1f}px is below minimum "
                        f"{apparent_minimum:g}px at primary scale {viewing_scale:g}"
                    )
                elif apparent + 1e-6 < apparent_target:
                    self.warn(
                        f"ordinary-node apparent font {apparent:.1f}px is below target "
                        f"{apparent_target:g}px at primary scale {viewing_scale:g}"
                    )

        for cell_id, cell in self.by_id.items():
            text = strip_markup(cell.get("value", ""))
            if not text:
                continue
            size = font_size(cell_id)
            if cell_id.startswith("legend:"):
                if size is None or size < annotation_min:
                    self.fail(
                        f"Legend font {size!r}; minimum annotation size "
                        f"{annotation_min:g}: {cell_id}"
                    )
                continue
            if cell.get("edge") == "1":
                if cell_id not in exceptions["edge_font_exceptions"] and (
                    size is None or not math.isclose(size, edge_font)
                ):
                    self.fail(f"edge font {size!r}; expected {edge_font:g}: {cell_id}")
                continue
            if cell.get("vertex") != "1":
                continue
            if cell_id in region_ids:
                expected = nested_title if cell_id in parent_map else top_title
                if cell_id not in exceptions["region_font_exceptions"] and (
                    size is None or not math.isclose(size, expected)
                ):
                    self.fail(f"region font {size!r}; expected {expected:g}: {cell_id}")
                continue
            if cell_id in hierarchy_ids:
                if cell_id not in exceptions["node_font_exceptions"] and (
                    size is None or not math.isclose(size, hierarchy_font)
                ):
                    self.fail(f"hierarchy font {size!r}; expected {hierarchy_font:g}: {cell_id}")
                continue
            style = self.styles[cell_id]
            is_annotation = "text" in style and style.get("strokeColor") in {"none", None}
            if is_annotation:
                if cell_id not in exceptions["annotation_font_exceptions"] and (
                    size is None or size < annotation_min
                ):
                    self.fail(f"annotation font {size!r}; minimum {annotation_min:g}: {cell_id}")
                continue
            if cell_id not in exceptions["node_font_exceptions"] and (
                size is None or not math.isclose(size, ordinary_font)
            ):
                self.fail(f"ordinary-node font {size!r}; expected {ordinary_font:g}: {cell_id}")

        fill_floor = float(contract.get("minimum_text_fill_ratio", 0))
        if fill_floor <= 0:
            return
        legend_regions = {
            region_id
            for region_id in region_ids
            if "legend" in strip_markup(self.by_id[region_id].get("value", "")).lower()
        }
        for cell_id, cell in self.by_id.items():
            if (
                cell.get("vertex") != "1"
                or cell_id in region_ids
                or cell_id in hierarchy_ids
                or cell_id in ignored_ids
                or cell_id in exceptions["wide_node_exceptions"]
            ):
                continue
            style = self.styles[cell_id]
            if style.get("shape") in {"ellipse", "cylinder3"}:
                continue
            box = self.absolute_box(cell_id)
            size = font_size(cell_id)
            lines = markup_lines(cell.get("value", ""))
            if box is None or size is None or not lines:
                continue
            plain_text = "".join(lines).strip()
            if len(plain_text) <= 3:
                # Junction glyphs and ellipsis markers are sized for hit area,
                # not for prose-like text occupancy.
                continue
            if any(
                (region_box := self.absolute_box(region_id)) is not None
                and self.box_contains(region_box, box)
                for region_id in legend_regions
            ):
                continue
            estimated = max(text_width_units(line) for line in lines) * size
            fill_ratio = estimated / max(box.w, 1)
            # Text width is a font-independent estimate. Reserve a small
            # tolerance so borderline glyph metrics do not become false
            # positives; this check targets conspicuous dead width.
            if fill_ratio < max(0, fill_floor - 0.05):
                self.fail(
                    f"node width needs review: {cell_id} text-fill={fill_ratio:.2f} "
                    f"(< {fill_floor:.2f})"
                )

            if cell_id not in exceptions["text_height_exceptions"]:
                inner_width = max(box.w - 1.4 * size, size)
                rendered_lines = sum(
                    max(1, math.ceil(text_width_units(line) * size * 0.65 / inner_width))
                    for line in lines
                )
                line_height = float(contract.get("estimated_line_height_ratio", 1.0)) * size
                padding_ratio = float(contract.get("minimum_vertical_padding_ratio", 0.25))
                if style.get("shape") == "cylinder3":
                    padding_ratio = max(padding_ratio, 0.8)
                padding = padding_ratio * size
                required_height = rendered_lines * line_height + padding
                if box.h + 3 < required_height:
                    self.fail(
                        f"node text height needs review: {cell_id} "
                        f"box={box.h:g}px estimated={required_height:.1f}px "
                        f"({rendered_lines} rendered lines)"
                    )

        # Region titles are rendered inside the container's upper-left corner.
        # Check their approximate occupied rectangle, rather than reserving a
        # wasteful full-width title band.
        for region_id in region_ids - legend_regions:
            if region_id in exceptions["region_title_clearance_exceptions"]:
                continue
            region_box = self.absolute_box(region_id)
            size = font_size(region_id)
            title_lines = markup_lines(self.by_id[region_id].get("value", ""))
            if region_box is None or size is None or not title_lines:
                continue
            padding = max(10.0, 0.4 * size)
            title_width = min(
                region_box.w,
                max(text_width_units(line) for line in title_lines) * size * 0.65 + 2 * padding,
            )
            title_height = len(title_lines) * 1.2 * size + 2 * padding
            title_box = Box(region_box.x, region_box.y, title_width, title_height)
            for node_id, node in self.by_id.items():
                if (
                    node.get("vertex") != "1"
                    or node_id in region_ids
                    or node_id in hierarchy_ids
                    or node_id in ignored_ids
                ):
                    continue
                node_box = self.absolute_box(node_id)
                if node_box is None or not self.box_contains(region_box, node_box):
                    continue
                intersects = (
                    max(title_box.x, node_box.x) < min(title_box.right, node_box.right)
                    and max(title_box.y, node_box.y) < min(title_box.bottom, node_box.bottom)
                )
                if intersects:
                    self.fail(f"node intrudes into region title: {region_id} / {node_id}")

    @staticmethod
    def largest_bracketed_empty_box(
        region: Box, occupied_boxes: list[Box], grid_size: float, header: float, padding: float
    ) -> Box | None:
        inner = Box(region.x, region.y + header, region.w, max(0.0, region.h - header))
        if inner.w <= 0 or inner.h <= 0:
            return None
        columns = max(1, math.ceil(inner.w / grid_size))
        rows = max(1, math.ceil(inner.h / grid_size))
        occupied = [[False] * columns for _ in range(rows)]
        for box in occupied_boxes:
            left = max(inner.x, box.x - padding)
            right = min(inner.right, box.right + padding)
            top = max(inner.y, box.y - padding)
            bottom = min(inner.bottom, box.bottom + padding)
            if right <= left or bottom <= top:
                continue
            first_column = max(0, int((left - inner.x) // grid_size))
            last_column = min(columns - 1, int(math.ceil((right - inner.x) / grid_size) - 1))
            first_row = max(0, int((top - inner.y) // grid_size))
            last_row = min(rows - 1, int(math.ceil((bottom - inner.y) / grid_size) - 1))
            for row in range(first_row, last_row + 1):
                for column in range(first_column, last_column + 1):
                    occupied[row][column] = True

        def bracketed(top: int, bottom: int, left: int, right: int) -> bool:
            has_left = any(any(row[:left]) for row in occupied[top:bottom]) if left else False
            has_right = any(any(row[right:]) for row in occupied[top:bottom]) if right < columns else False
            has_top = any(any(row[left:right]) for row in occupied[:top]) if top else False
            has_bottom = any(any(row[left:right]) for row in occupied[bottom:]) if bottom < rows else False
            return (has_left and has_right) or (has_top and has_bottom)

        heights = [0] * columns
        best: tuple[int, int, int, int] | None = None
        best_area = 0
        for row_index in range(rows):
            for column in range(columns):
                heights[column] = 0 if occupied[row_index][column] else heights[column] + 1
            stack: list[tuple[int, int]] = []
            for column in range(columns + 1):
                height = 0 if column == columns else heights[column]
                start = column
                while stack and stack[-1][1] > height:
                    left, candidate_height = stack.pop()
                    start = left
                    top = row_index - candidate_height + 1
                    bottom = row_index + 1
                    area = candidate_height * (column - left)
                    if area > best_area and bracketed(top, bottom, left, column):
                        best = (top, bottom, left, column)
                        best_area = area
                if not stack or stack[-1][1] < height:
                    stack.append((start, height))

        if best is None:
            return None
        top, bottom, left, right = best
        return Box(
            inner.x + left * grid_size,
            inner.y + top * grid_size,
            min(inner.right, inner.x + right * grid_size) - (inner.x + left * grid_size),
            min(inner.bottom, inner.y + bottom * grid_size) - (inner.y + top * grid_size),
        )

    def check_density_contract(self, region_ids: set[str]) -> None:
        contract = self.config.get("density_contract")
        if contract is None:
            return
        if not isinstance(contract, dict):
            self.fail("density_contract must be an object")
            return

        ratio_fields = {
            "minimum_region_content_width_ratio": 0.0,
            "minimum_region_content_height_ratio": 0.0,
            "maximum_trailing_right_ratio": 1.0,
            "maximum_trailing_bottom_ratio": 1.0,
            "minimum_perpendicular_overlap_ratio": 0.25,
            "minimum_internal_void_area_ratio": 0.0,
            "minimum_internal_void_width_ratio": 0.0,
            "minimum_internal_void_height_ratio": 0.0,
        }
        ratios: dict[str, float] = {}
        for field, default in ratio_fields.items():
            try:
                value = float(contract.get(field, default))
            except (TypeError, ValueError):
                self.fail(f"density_contract.{field} must be a number")
                return
            if value < 0 or value > 1:
                self.fail(f"density_contract.{field} must be between 0 and 1")
                return
            ratios[field] = value

        gap_limits: dict[str, float | None] = {}
        for field in ("maximum_horizontal_region_gap", "maximum_vertical_region_gap"):
            raw = contract.get(field)
            if raw is None:
                gap_limits[field] = None
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                self.fail(f"density_contract.{field} must be a positive number or null")
                return
            if value <= 0:
                self.fail(f"density_contract.{field} must be a positive number or null")
                return
            gap_limits[field] = value

        region_exceptions = contract.get("region_exceptions", {})
        gap_exceptions = contract.get("gap_exceptions", {})
        for field, values in (
            ("region_exceptions", region_exceptions),
            ("gap_exceptions", gap_exceptions),
        ):
            if not isinstance(values, dict):
                self.fail(f"density_contract.{field} must be an ID-to-reason object")
                return
            for key, reason in values.items():
                if not isinstance(reason, str) or not reason.strip():
                    self.fail(f"density_contract.{field} missing reason: {key}")
        for region_id in region_exceptions:
            if region_id not in self.by_id:
                self.fail(f"density_contract.region_exceptions cell missing: {region_id}")

        content_contracts = self.config.get("region_content_contracts", {})
        if not isinstance(content_contracts, dict):
            return
        try:
            void_grid_size = float(contract.get("internal_void_grid_size", 40))
            void_padding = float(contract.get("internal_void_node_padding", 12))
        except (TypeError, ValueError):
            self.fail("density_contract internal-void grid size and padding must be numbers")
            return
        if void_grid_size <= 0 or void_padding < 0:
            self.fail("density_contract internal-void grid size must be positive and padding non-negative")
            return
        parent_map = self.config.get("region_parents", {})
        for region_id, content_ids in content_contracts.items():
            if region_id not in region_ids or region_id in region_exceptions:
                continue
            region = self.absolute_box(region_id)
            if region is None or region.w <= 0 or region.h <= 0 or not isinstance(content_ids, list):
                continue
            boxes = [self.absolute_box(cell_id) for cell_id in content_ids]
            boxes = [box for box in boxes if box is not None and self.box_contains(region, box)]
            if not boxes:
                self.warn(f"density review has no contracted visible content: {region_id}")
                continue
            content = Box(
                min(box.x for box in boxes),
                min(box.y for box in boxes),
                max(box.right for box in boxes) - min(box.x for box in boxes),
                max(box.bottom for box in boxes) - min(box.y for box in boxes),
            )
            width_ratio = content.w / region.w
            height_ratio = content.h / region.h
            trailing_right = (region.right - content.right) / region.w
            trailing_bottom = (region.bottom - content.bottom) / region.h
            if width_ratio + 1e-6 < ratios["minimum_region_content_width_ratio"]:
                self.warn(
                    f"region content is horizontally sparse: {region_id} "
                    f"bbox-width={width_ratio:.2f} "
                    f"(< {ratios['minimum_region_content_width_ratio']:.2f})"
                )
            if height_ratio + 1e-6 < ratios["minimum_region_content_height_ratio"]:
                self.warn(
                    f"region content is vertically sparse: {region_id} "
                    f"bbox-height={height_ratio:.2f} "
                    f"(< {ratios['minimum_region_content_height_ratio']:.2f})"
                )
            if trailing_right > ratios["maximum_trailing_right_ratio"] + 1e-6:
                excess = trailing_right - ratios["maximum_trailing_right_ratio"]
                self.warn(
                    f"region has excessive trailing-right whitespace: {region_id} "
                    f"ratio={trailing_right:.2f}; review shrinking by about {excess * region.w:.0f}px"
                )
            if trailing_bottom > ratios["maximum_trailing_bottom_ratio"] + 1e-6:
                excess = trailing_bottom - ratios["maximum_trailing_bottom_ratio"]
                self.warn(
                    f"region has excessive trailing-bottom whitespace: {region_id} "
                    f"ratio={trailing_bottom:.2f}; review shrinking by about {excess * region.h:.0f}px"
                )

            internal_boxes = list(boxes)
            for child_id, parent_id in parent_map.items():
                if parent_id == region_id:
                    child = self.absolute_box(child_id)
                    if child is not None:
                        internal_boxes.append(child)
            start_size = number(self.styles.get(region_id, {}).get("startSize"), 0.0)
            empty = self.largest_bracketed_empty_box(
                region, internal_boxes, void_grid_size, start_size, void_padding
            )
            if empty is not None:
                usable_height = max(region.h - start_size, 1.0)
                area_ratio = empty.w * empty.h / max(region.w * usable_height, 1.0)
                width_ratio = empty.w / region.w
                height_ratio = empty.h / usable_height
                if (
                    area_ratio + 1e-6 >= ratios["minimum_internal_void_area_ratio"]
                    and width_ratio + 1e-6 >= ratios["minimum_internal_void_width_ratio"]
                    and height_ratio + 1e-6 >= ratios["minimum_internal_void_height_ratio"]
                    and ratios["minimum_internal_void_area_ratio"] > 0
                ):
                    self.warn(
                        f"region contains a large internal whitespace pocket: {region_id} "
                        f"box=({empty.x:.0f},{empty.y:.0f},{empty.w:.0f},{empty.h:.0f}) "
                        f"area={area_ratio:.2f}, width={width_ratio:.2f}, height={height_ratio:.2f}; "
                        "review branch compaction or record an intentional routing reserve"
                    )

        all_siblings: dict[str | None, list[str]] = {}
        for region_id in region_ids:
            if region_id in self.by_id:
                all_siblings.setdefault(parent_map.get(region_id), []).append(region_id)

        siblings: dict[str | None, list[str]] = {}
        for region_id in region_ids - set(region_exceptions):
            if region_id in self.by_id:
                siblings.setdefault(parent_map.get(region_id), []).append(region_id)

        def corridor_is_blocked(source_id: str, target_id: str, axis: str) -> bool:
            """Return whether another sibling fully separates this region pair."""
            source = self.absolute_box(source_id)
            target = self.absolute_box(target_id)
            if source is None or target is None:
                return False
            parent_id = parent_map.get(source_id)
            for blocker_id in all_siblings.get(parent_id, []):
                if blocker_id in {source_id, target_id}:
                    continue
                blocker = self.absolute_box(blocker_id)
                if blocker is None:
                    continue
                if axis == "vertical":
                    overlap_lo = max(source.x, target.x)
                    overlap_hi = min(source.right, target.right)
                    covers_projection = blocker.x <= overlap_lo + 1e-6 and blocker.right >= overlap_hi - 1e-6
                    crosses_gap = blocker.y < target.y - 1e-6 and blocker.bottom > source.bottom + 1e-6
                else:
                    overlap_lo = max(source.y, target.y)
                    overlap_hi = min(source.bottom, target.bottom)
                    covers_projection = blocker.y <= overlap_lo + 1e-6 and blocker.bottom >= overlap_hi - 1e-6
                    crosses_gap = blocker.x < target.x - 1e-6 and blocker.right > source.right + 1e-6
                if overlap_hi > overlap_lo and covers_projection and crosses_gap:
                    return True
            return False

        overlap_floor = ratios["minimum_perpendicular_overlap_ratio"]
        reviewed_pairs: set[tuple[str, str, str]] = set()
        for sibling_ids in siblings.values():
            for source_id in sibling_ids:
                source = self.absolute_box(source_id)
                if source is None:
                    continue
                candidates: dict[str, list[tuple[float, str]]] = {"horizontal": [], "vertical": []}
                for target_id in sibling_ids:
                    if target_id == source_id:
                        continue
                    target = self.absolute_box(target_id)
                    if target is None:
                        continue
                    y_overlap = max(0.0, min(source.bottom, target.bottom) - max(source.y, target.y))
                    x_overlap = max(0.0, min(source.right, target.right) - max(source.x, target.x))
                    min_height = min(source.h, target.h)
                    min_width = min(source.w, target.w)
                    if min_height > 0 and target.x >= source.right and y_overlap / min_height >= overlap_floor:
                        candidates["horizontal"].append((target.x - source.right, target_id))
                    if min_width > 0 and target.y >= source.bottom and x_overlap / min_width >= overlap_floor:
                        candidates["vertical"].append((target.y - source.bottom, target_id))
                for axis, values in candidates.items():
                    limit = gap_limits[f"maximum_{axis}_region_gap"]
                    if limit is None or not values:
                        continue
                    gap, target_id = min(values)
                    left_id, right_id = sorted((source_id, target_id))
                    pair = (left_id, right_id, axis)
                    if pair in reviewed_pairs:
                        continue
                    reviewed_pairs.add(pair)
                    exception_key = f"{left_id}|{right_id}"
                    if exception_key in gap_exceptions:
                        continue
                    if corridor_is_blocked(source_id, target_id, axis):
                        continue
                    if gap > limit + 1e-6:
                        self.warn(
                            f"adjacent regions have a large {axis} gap: {source_id} / {target_id} "
                            f"({gap:g}px > {limit:g}px); review reducing by about {gap - limit:.0f}px"
                        )

    def port_point(self, cell_id: str, x_key: str, y_key: str) -> tuple[float, float] | None:
        cell = self.by_id[cell_id]
        target_id = cell.get("source" if x_key == "exitX" else "target")
        if target_id is None:
            return None
        box = self.absolute_box(target_id)
        if box is None:
            return None
        style = self.styles[cell_id]
        if x_key not in style or y_key not in style:
            return None
        return (box.x + box.w * float(style[x_key]), box.y + box.h * float(style[y_key]))

    def edge_points(self, edge_id: str) -> list[tuple[float, float]]:
        cell = self.by_id[edge_id]
        start = self.port_point(edge_id, "exitX", "exitY")
        end = self.port_point(edge_id, "entryX", "entryY")
        geometry = cell_geometry(cell)
        middle: list[tuple[float, float]] = []
        if geometry is not None:
            points = geometry.find("Array[@as='points']")
            if points is not None:
                parent_offset = (0.0, 0.0)
                parent_id = cell.get("parent")
                if parent_id not in ROOT_IDS:
                    parent_box = self.absolute_box(parent_id or "")
                    if parent_box is not None:
                        parent_offset = (parent_box.x, parent_box.y)
                for point in points.findall("mxPoint"):
                    middle.append(
                        (number(point.get("x")) + parent_offset[0], number(point.get("y")) + parent_offset[1])
                    )
        result = ([] if start is None else [start]) + middle + ([] if end is None else [end])
        deduplicated: list[tuple[float, float]] = []
        for point in result:
            if not deduplicated or point != deduplicated[-1]:
                deduplicated.append(point)
        return deduplicated

    @staticmethod
    def segment(first: tuple[float, float], last: tuple[float, float]) -> tuple[str, float, float, float]:
        # Draw.io serializes some calculated ports with sub-pixel float noise.
        if math.isclose(first[0], last[0], abs_tol=1.0):
            return ("v", first[0], min(first[1], last[1]), max(first[1], last[1]))
        if math.isclose(first[1], last[1], abs_tol=1.0):
            return ("h", first[1], min(first[0], last[0]), max(first[0], last[0]))
        return ("d", 0.0, 0.0, 0.0)

    @staticmethod
    def crosses_box(first: tuple[float, float], last: tuple[float, float], box: Box) -> bool:
        axis, fixed, low, high = PageAudit.segment(first, last)
        if axis == "v":
            return box.x < fixed < box.right and low < box.bottom and high > box.y
        if axis == "h":
            return box.y < fixed < box.bottom and low < box.right and high > box.x
        return False

    @staticmethod
    def overlaps_box_boundary(first: tuple[float, float], last: tuple[float, float], box: Box) -> bool:
        axis, fixed, low, high = PageAudit.segment(first, last)
        if axis == "v" and (
            math.isclose(fixed, box.x, abs_tol=1.0)
            or math.isclose(fixed, box.right, abs_tol=1.0)
        ):
            return min(high, box.bottom) - max(low, box.y) > 1
        if axis == "h" and (
            math.isclose(fixed, box.y, abs_tol=1.0)
            or math.isclose(fixed, box.bottom, abs_tol=1.0)
        ):
            return min(high, box.right) - max(low, box.x) > 1
        return False

    @staticmethod
    def inset_box(box: Box, amount: float = 3.0) -> Box:
        return Box(
            box.x + amount,
            box.y + amount,
            max(0.0, box.w - 2 * amount),
            max(0.0, box.h - 2 * amount),
        )

    def is_rectangular_node(self, cell_id: str) -> bool:
        """Return true for ordinary rectangles whose explicit paths must be orthogonal."""
        shape = self.styles.get(cell_id, {}).get("shape", "rectangle")
        return shape in {"", "rectangle"}

    def estimated_edge_label_box(self, edge_id: str, points: list[tuple[float, float]]) -> Box | None:
        """Estimate XML-relative label occupancy for hypothetical route checks.

        This is not a rendered text-fit assertion; official SVG auditing remains
        authoritative. Labels on the edge being rerouted are not fixed obstacles.
        """
        cell = self.by_id[edge_id]
        lines = markup_lines(cell.get("value", ""))
        geometry = cell.find("mxGeometry")
        if not lines or geometry is None or geometry.get("relative") != "1":
            return None
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        total = sum(lengths)
        if total <= 0:
            return None
        distance = (number(geometry.get("x"), 0) + 1) * total / 2
        normal_offset = number(geometry.get("y"), 0)
        offset = geometry.find("mxPoint[@as='offset']")
        ox = number(offset.get("x"), 0) if offset is not None else 0
        oy = number(offset.get("y"), 0) if offset is not None else 0
        font = number(self.styles[edge_id].get("fontSize"), 12)
        width = max(text_width_units(line) for line in lines) * font
        height = len(lines) * font * 1.2
        for (first, last), length in zip(zip(points, points[1:]), lengths):
            if length <= 0:
                continue
            if distance <= length + 1e-6:
                dx, dy = last[0] - first[0], last[1] - first[1]
                cx = first[0] + dx * distance / length + dy / length * normal_offset + ox
                cy = first[1] + dy * distance / length - dx / length * normal_offset + oy
                return Box(cx - width / 2, cy - height / 2, width, height)
            distance -= length
        return None

    def check_junction_rails(self) -> dict:
        from junction_routes import rail_contracts, rail_markers
        semantics = self.config.get('node_semantics', {})
        junctions = {nid for nid, node in semantics.items() if node.get('kind') == 'junction'}
        edges = {eid: {'source': cell.get('source'), 'target': cell.get('target')}
                 for eid, cell in self.by_id.items() if cell.get('edge') == '1'}
        nodes, routes = {}, {}
        for edge in edges.values():
            for nid in edge.values():
                box = self.absolute_box(nid)
                if box:
                    nodes[nid] = dict(x=box.x, y=box.y, w=box.w, h=box.h)
        for eid, edge in edges.items():
            if not ({edge['source'], edge['target']} & junctions):
                continue
            if edge['target'] in junctions and self.styles[eid].get('endArrow', 'none') != 'none':
                self.fail(f'arrowhead crowds junction: {eid}')
            ports = {}
            for role, prefix in [('source', 'exit'), ('target', 'entry')]:
                try:
                    x, y = (float(self.styles[eid][prefix + key]) for key in ('X', 'Y'))
                except (KeyError, ValueError):
                    self.fail(f'junction edge lacks valid explicit ports: {eid}')
                    return {}
                if y in (0, 1):
                    side, position = ('north' if y == 0 else 'south'), x
                else:
                    side, position = ('west' if x == 0 else 'east'), y
                ports[role + '_port'] = dict(side=side, position=position)
            routes[eid] = {**ports, 'waypoints': self.edge_points(eid)[1:-1]}
        data = {'nodes': {nid: {'kind': 'junction' if nid in junctions else 'operator'} for nid in nodes},
                'edges': edges, 'project': {'typography': self.config.get('typography_contract', {})}}
        try:
            actual = rail_contracts(data, {'nodes': nodes, 'edges': routes})
        except ValueError as error:
            self.fail(str(error))
            return {}
        expected = self.config.get('junction_rails', {})
        if not isinstance(expected, dict) or any(
            not isinstance(r, dict) or not isinstance(r.get('junction'), str)
            or not isinstance(r.get('terminals'), dict) or r.get('role') not in ('source', 'target')
            or r.get('side') not in ('north', 'south', 'east', 'west')
            for r in expected.values()
        ):
            self.fail('malformed junction rail registry')
            return {}
        # Registry uses canonical IR IDs; XML uses namespaced cell IDs.
        converted = {key: {**r, 'junction': 'node:' + r['junction'],
                          'terminals': {'edge:' + eid: p for eid, p in r['terminals'].items()}}
                     for key, r in expected.items()}
        actual = {key.removeprefix('node:'): r for key, r in actual.items()}
        def rounded(value):
            if isinstance(value, dict):
                return {k: rounded(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [rounded(v) for v in value]
            return round(value, 2) if isinstance(value, float) else value
        if rounded(actual) != rounded(converted):
            self.fail('junction rail registry missing or stale')
            return {}
        markers = rail_markers(expected)
        if markers != self.config.get('junction_rail_markers', {}):
            self.fail('junction rail marker registry missing or stale')
        for mid, expected_box in markers.items():
            box = self.absolute_box(mid)
            if not box or any(abs(getattr(box, key) - val) > .02 for key, val in expected_box.items()):
                self.fail(f'junction rail marker missing or moved: {mid}')
            style = self.styles.get(mid, {})
            if style.get('ellipse') != '1' or style.get('fillColor') != '#000000':
                self.fail(f'junction rail marker must be a black dot: {mid}')
        return converted

    def check_routes(
        self, region_ids: set[str], hierarchy_ids: set[str], ignored_ids: set[str]
    ) -> None:
        edges = [cell_id for cell_id, cell in self.by_id.items() if cell.get("edge") == "1"]
        node_excluded = region_ids | hierarchy_ids | ignored_ids | set(self.config.get("route_node_exclusions", []))
        node_ids = [
            cell_id for cell_id, cell in self.by_id.items()
            if cell.get("vertex") == "1" and cell_id not in node_excluded
        ]
        edge_paths = {edge_id: self.edge_points(edge_id) for edge_id in edges}
        junction_rails = self.check_junction_rails()
        label_boxes = {edge_id: self.estimated_edge_label_box(edge_id, points)
                       for edge_id, points in edge_paths.items()}

        # Route quality is a geometry invariant. Explicit paths must leave and
        # approach rectangular endpoint ports normally; tangential endpoint
        # segments create the short hooks and border-riding lines that remain
        # ambiguous even when they do not intersect another node.
        def reasoned_exception_ids(name: str) -> set[str]:
            value = self.config.get(name, {})
            if not isinstance(value, dict):
                self.fail(f"{name} must be an ID-to-reason object")
                return set()
            for item_id, reason in value.items():
                if not isinstance(reason, str) or not reason.strip():
                    self.fail(f"{name} has an empty reason: {item_id}")
            return set(value)

        quality_exclusions = reasoned_exception_ids("route_quality_exclusions")
        configured_near_axis_tolerance = self.config.get("near_axis_dogleg_tolerance")
        configured_backtrack_floor = self.config.get("minimum_route_backtrack")
        degree_exclusions = reasoned_exception_ids("route_degree_exclusions")
        incoming_count: dict[str, int] = {}
        outgoing_count: dict[str, int] = {}
        for candidate_id in edges:
            candidate = self.by_id[candidate_id]
            candidate_style = self.styles[candidate_id]
            # Expansion/reuse arrows do not make an execution-chain operator a
            # computational fan-out. Their thick hollow style is compiler-owned.
            relation_only = (
                candidate_id in degree_exclusions
                or (
                    number(candidate_style.get("strokeWidth"), 1.0) >= 3.0
                    and "endFill=0" in candidate.get("style", "").split(";")
                )
            )
            if relation_only:
                continue
            source_id = candidate.get("source", "")
            target_id = candidate.get("target", "")
            outgoing_count[source_id] = outgoing_count.get(source_id, 0) + 1
            incoming_count[target_id] = incoming_count.get(target_id, 0) + 1

        def endpoint_side(edge_id: str, prefix: str) -> str | None:
            contracted = self.config.get("expected_ports", {}).get(edge_id, {})
            contracted_side = contracted.get(f"{prefix}Side") if isinstance(contracted, dict) else None
            if contracted_side in {"north", "south", "east", "west"}:
                return contracted_side
            style = self.styles[edge_id]
            x_value = style.get(f"{prefix}X")
            y_value = style.get(f"{prefix}Y")
            if x_value is None or y_value is None:
                return None
            x, y = float(x_value), float(y_value)
            sides = []
            if math.isclose(y, 0.0):
                sides.append("north")
            if math.isclose(y, 1.0):
                sides.append("south")
            if math.isclose(x, 0.0):
                sides.append("west")
            if math.isclose(x, 1.0):
                sides.append("east")
            return sides[0] if len(sides) == 1 else None

        def expected_axis(side: str | None) -> str | None:
            if side in {"north", "south"}:
                return "v"
            if side in {"east", "west"}:
                return "h"
            return None

        for edge_id, points in edge_paths.items():
            if len(points) < 2:
                continue
            edge = self.by_id[edge_id]
            source_box = self.absolute_box(edge.get("source", ""))
            target_box = self.absolute_box(edge.get("target", ""))
            source_side = endpoint_side(edge_id, "exit")
            target_side = endpoint_side(edge_id, "entry")
            first_axis = self.segment(points[0], points[1])[0]
            last_axis = self.segment(points[-2], points[-1])[0]
            source_axis = expected_axis(source_side)
            target_axis = expected_axis(target_side)
            source_rectangular = self.is_rectangular_node(edge.get("source", ""))
            target_rectangular = self.is_rectangular_node(edge.get("target", ""))
            if source_rectangular and source_axis is not None and first_axis not in {source_axis, "d"}:
                self.fail(
                    f"route leaves endpoint tangentially and forms a hook: {edge_id} "
                    f"({source_side} port, first segment={first_axis})"
                )
            if target_rectangular and target_axis is not None and last_axis not in {target_axis, "d"}:
                self.fail(
                    f"route approaches endpoint tangentially and forms a hook: {edge_id} "
                    f"({target_side} port, last segment={last_axis})"
                )
            if edge_id not in quality_exclusions and len(points) > 2:
                backtrack_floor = (
                    float(configured_backtrack_floor)
                    if configured_backtrack_floor is not None
                    else max(
                        2.0,
                        min(source_box.h, target_box.h) * 0.05
                        if source_box is not None and target_box is not None
                        else 2.0,
                    )
                )
                for index in range(1, len(points) - 1):
                    before = points[index - 1]
                    middle = points[index]
                    after = points[index + 1]
                    first_leg = self.segment(before, middle)[0]
                    second_leg = self.segment(middle, after)[0]
                    if first_leg == second_leg and first_leg in {"h", "v"}:
                        if first_leg == "h":
                            first_delta = middle[0] - before[0]
                            second_delta = after[0] - middle[0]
                        else:
                            first_delta = middle[1] - before[1]
                            second_delta = after[1] - middle[1]
                        if first_delta * second_delta < 0:
                            reversal = min(abs(first_delta), abs(second_delta))
                            message = f"route backtracks {reversal:g}px: {edge_id} at {middle}"
                            if reversal > backtrack_floor:
                                self.fail(message)
                            else:
                                self.warn(f"subpixel/short {message}; normalize the waypoint")
                        else:
                            self.warn(
                                f"route has redundant collinear waypoint: {edge_id} at {middle}"
                            )

                # If both execution-flow ends are not branching and the node centers are nearly
                # aligned, a V-H-V/H-V-H path is layout drift, not useful routing.
                source_id = edge.get("source", "")
                target_id = edge.get("target", "")
                single_chain = (
                    outgoing_count.get(source_id) == 1
                    and incoming_count.get(target_id) == 1
                )
                port_axes = [
                    self.segment(start, end)[0]
                    for start, end in zip(points, points[1:])
                ]
                normalized_port_axes: list[str] = []
                for axis in port_axes:
                    if not normalized_port_axes or normalized_port_axes[-1] != axis:
                        normalized_port_axes.append(axis)

                def direct_port_corridor_blocked(vertical: bool, coordinate: float) -> bool:
                    if vertical:
                        first = (coordinate, min(source_box.bottom, target_box.bottom))
                        last = (coordinate, max(source_box.y, target_box.y))
                    else:
                        first = (min(source_box.right, target_box.right), coordinate)
                        last = (max(source_box.x, target_box.x), coordinate)
                    if first == last:
                        return False
                    if any(box is not None and label_id != edge_id and self.crosses_box(first, last, box)
                           for label_id, box in label_boxes.items()):
                        return True
                    for node_id in set(node_ids) | hierarchy_ids:
                        if node_id in {source_id, target_id}:
                            continue
                        obstacle = self.absolute_box(node_id)
                        if obstacle is None:
                            continue
                        style = self.styles.get(node_id, {})
                        if style.get("shape") == "singleArrow":
                            polygon = single_arrow_polygon(
                                obstacle.x, obstacle.y, obstacle.w, obstacle.h,
                                style.get("direction", "east"),
                                float(style.get("arrowWidth", 0.3)),
                                float(style.get("arrowSize", 0.2)),
                            )
                            if segment_intersects_polygon(first, last, polygon):
                                return True
                        elif self.crosses_box(first, last, obstacle):
                            return True
                    for region_id in region_ids:
                        region_box = self.absolute_box(region_id)
                        if region_box is None:
                            continue
                        title_height = number(self.styles.get(region_id, {}).get("startSize"), 36.0)
                        title_box = Box(region_box.x, region_box.y, region_box.w, min(title_height, region_box.h))
                        if self.crosses_box(first, last, title_box):
                            return True
                    for other_id, other_points in edge_paths.items():
                        if other_id == edge_id:
                            continue
                        if any(
                            orthogonal_segments_conflict(first, last, other_first, other_last)
                            for other_first, other_last in zip(other_points, other_points[1:])
                        ):
                            return True
                    return False

                port_alignable = False
                if source_rectangular and target_rectangular and source_box is not None and target_box is not None:
                    if (
                        {source_side, target_side} == {"north", "south"}
                        and len(normalized_port_axes) >= 3
                        and normalized_port_axes[0] == normalized_port_axes[-1] == "v"
                        and "h" in normalized_port_axes
                    ):
                        overlap_left = max(source_box.x, target_box.x)
                        overlap_right = min(source_box.right, target_box.right)
                        if overlap_right - overlap_left > 2:
                            coordinate = min(
                                max(target_box.x + target_box.w / 2, overlap_left + 1),
                                overlap_right - 1,
                            )
                            port_alignable = True
                            message = (
                                f"avoidable vertical port-alignment dogleg: {edge_id}; "
                                "endpoint spans overlap, so align ports on one straight route"
                            )
                            self.warn(f"{message}; direct corridor contains an obstacle") if direct_port_corridor_blocked(True, coordinate) else self.fail(message)
                    elif (
                        {source_side, target_side} == {"east", "west"}
                        and len(normalized_port_axes) >= 3
                        and normalized_port_axes[0] == normalized_port_axes[-1] == "h"
                        and "v" in normalized_port_axes
                    ):
                        overlap_top = max(source_box.y, target_box.y)
                        overlap_bottom = min(source_box.bottom, target_box.bottom)
                        if overlap_bottom - overlap_top > 2:
                            coordinate = min(
                                max(target_box.y + target_box.h / 2, overlap_top + 1),
                                overlap_bottom - 1,
                            )
                            port_alignable = True
                            message = (
                                f"avoidable horizontal port-alignment dogleg: {edge_id}; "
                                "endpoint spans overlap, so align ports on one straight route"
                            )
                            self.warn(f"{message}; direct corridor contains an obstacle") if direct_port_corridor_blocked(False, coordinate) else self.fail(message)
                if (
                    single_chain
                    and not port_alignable
                    and source_rectangular
                    and target_rectangular
                    and source_box is not None
                    and target_box is not None
                ):
                    near_axis_tolerance = (
                        float(configured_near_axis_tolerance)
                        if configured_near_axis_tolerance is not None
                        else min(source_box.h, target_box.h) * 0.75
                    )
                    source_center = (
                        source_box.x + source_box.w / 2,
                        source_box.y + source_box.h / 2,
                    )
                    target_center = (
                        target_box.x + target_box.w / 2,
                        target_box.y + target_box.h / 2,
                    )
                    axes = [
                        self.segment(start, end)[0]
                        for start, end in zip(points, points[1:])
                    ]
                    normalized_axes: list[str] = []
                    for axis in axes:
                        if not normalized_axes or normalized_axes[-1] != axis:
                            normalized_axes.append(axis)

                    def corridor_blocked(vertical: bool) -> bool:
                        if vertical:
                            corridor = Box(
                                min(source_center[0], target_center[0]) - 1,
                                min(source_box.bottom, target_box.bottom),
                                abs(target_center[0] - source_center[0]) + 2,
                                max(source_box.y, target_box.y) - min(source_box.bottom, target_box.bottom),
                            )
                        else:
                            corridor = Box(
                                min(source_box.right, target_box.right),
                                min(source_center[1], target_center[1]) - 1,
                                max(source_box.x, target_box.x) - min(source_box.right, target_box.right),
                                abs(target_center[1] - source_center[1]) + 2,
                            )
                        if corridor.w <= 0 or corridor.h <= 0:
                            return False
                        for node_id in node_ids:
                            if node_id in {source_id, target_id}:
                                continue
                            obstacle = self.absolute_box(node_id)
                            if obstacle is not None and not (
                                corridor.right <= obstacle.x
                                or obstacle.right <= corridor.x
                                or corridor.bottom <= obstacle.y
                                or obstacle.bottom <= corridor.y
                            ):
                                return True
                        return False

                    if {source_side, target_side} == {"north", "south"}:
                        center_offset = abs(target_center[0] - source_center[0])
                        if (
                            center_offset <= near_axis_tolerance
                            and len(normalized_axes) >= 3
                            and normalized_axes[0] == normalized_axes[-1] == "v"
                            and "h" in normalized_axes
                        ):
                            message = (
                                f"avoidable near-vertical dogleg: {edge_id} "
                                f"node-center offset={center_offset:g}px <= "
                                f"{near_axis_tolerance:g}px; align the chain"
                            )
                            self.warn(f"{message}; direct corridor contains an obstacle") if corridor_blocked(True) else self.fail(message)
                    elif {source_side, target_side} == {"east", "west"}:
                        center_offset = abs(target_center[1] - source_center[1])
                        if (
                            center_offset <= near_axis_tolerance
                            and len(normalized_axes) >= 3
                            and normalized_axes[0] == normalized_axes[-1] == "h"
                            and "v" in normalized_axes
                        ):
                            message = (
                                f"avoidable near-horizontal dogleg: {edge_id} "
                                f"node-center offset={center_offset:g}px <= "
                                f"{near_axis_tolerance:g}px; align the chain"
                            )
                            self.warn(f"{message}; direct corridor contains an obstacle") if corridor_blocked(False) else self.fail(message)

                def shortcut_segment_blocked(
                    first: tuple[float, float], last: tuple[float, float]
                ) -> bool:
                    if any(box is not None and label_id != edge_id and self.crosses_box(first, last, box)
                           for label_id, box in label_boxes.items()):
                        return True
                    for node_id in set(node_ids) | hierarchy_ids:
                        if node_id in {source_id, target_id}:
                            continue
                        obstacle = self.absolute_box(node_id)
                        if obstacle is None:
                            continue
                        style = self.styles.get(node_id, {})
                        if style.get("shape") == "singleArrow":
                            polygon = single_arrow_polygon(
                                obstacle.x, obstacle.y, obstacle.w, obstacle.h,
                                style.get("direction", "east"),
                                float(style.get("arrowWidth", 0.3)),
                                float(style.get("arrowSize", 0.2)),
                            )
                            if segment_intersects_polygon(first, last, polygon):
                                return True
                        elif (
                            self.crosses_box(first, last, obstacle)
                            or self.overlaps_box_boundary(first, last, obstacle)
                        ):
                            return True
                    for region_id in region_ids:
                        region_box = self.absolute_box(region_id)
                        if region_box is None:
                            continue
                        title_height = number(self.styles.get(region_id, {}).get("startSize"), 36.0)
                        title_box = Box(region_box.x, region_box.y, region_box.w, min(title_height, region_box.h))
                        if self.crosses_box(first, last, title_box):
                            return True
                    for other_id, other_points in edge_paths.items():
                        if other_id == edge_id:
                            continue
                        if any(
                            orthogonal_segments_conflict(first, last, other_first, other_last)
                            for other_first, other_last in zip(other_points, other_points[1:])
                        ):
                            return True
                    return False

                shortcut = avoidable_orthogonal_shortcut(points, shortcut_segment_blocked)
                if shortcut is not None:
                    start_index, end_index, candidate = shortcut
                    self.fail(
                        f"avoidable orthogonal staircase: {edge_id} segments "
                        f"{start_index}-{end_index} can use {len(candidate) - 1} legs"
                    )
            if (
                len(points) > 2
                and source_box is not None
                and self.is_rectangular_node(edge.get("source", ""))
                and self.segment(points[0], points[1])[0] == "d"
            ):
                self.fail(f"edge leaves rectangular source diagonally: {edge_id}")
            if (
                len(points) > 2
                and target_box is not None
                and self.is_rectangular_node(edge.get("target", ""))
                and self.segment(points[-2], points[-1])[0] == "d"
            ):
                self.fail(f"edge approaches rectangular target diagonally: {edge_id}")
            if source_box is not None and self.crosses_box(
                points[0], points[1], self.inset_box(source_box)
            ):
                self.fail(f"edge doubles back through source node: {edge_id}")
            if target_box is not None and self.crosses_box(
                points[-2], points[-1], self.inset_box(target_box)
            ):
                self.fail(f"edge approaches target through its interior: {edge_id}")
            for segment_index, (first, last) in enumerate(zip(points, points[1:])):
                if self.segment(first, last)[0] == "d":
                    # Draw.io projects fixed ports onto non-rectangular perimeters;
                    # the endpoint-to-waypoint segment may therefore be slightly
                    # diagonal in XML while the orthogonal renderer corrects it.
                    endpoint_segment = segment_index in {0, len(points) - 2}
                    if len(points) > 2 and not endpoint_segment:
                        self.warn(f"non-orthogonal explicit segment: {edge_id} {first} -> {last}")
                    continue
                for node_id in node_ids:
                    if node_id in {edge.get("source"), edge.get("target")}:
                        continue
                    box = self.absolute_box(node_id)
                    if box is not None and self.crosses_box(first, last, box):
                        self.fail(f"edge crosses unrelated node: {edge_id} / {node_id}")
                    elif box is not None and self.overlaps_box_boundary(first, last, box):
                        self.fail(f"edge overlaps unrelated node boundary: {edge_id} / {node_id}")

        allowed_crossings = configured_pairs(self.config.get("allowed_edge_crossings", []))
        if allowed_crossings:
            self.fail(
                "allowed_edge_crossings cannot prove visual separation; use line_jump_crossings "
                "with a rendered arc bridge"
            )
        raw_jump_crossings = self.config.get("line_jump_crossings", {})
        jump_crossings: dict[tuple[str, str], dict[str, Any]] = {}
        if not isinstance(raw_jump_crossings, dict):
            self.fail("line_jump_crossings must be an edge-pair-to-contract object")
            raw_jump_crossings = {}
        for raw_pair, contract in raw_jump_crossings.items():
            members = raw_pair.split("|") if isinstance(raw_pair, str) else []
            pair = pair_key(*members) if len(members) == 2 else None
            if pair is None or raw_pair != "|".join(pair) or pair[0] == pair[1]:
                self.fail(f"invalid canonical line-jump pair key: {raw_pair!r}")
                continue
            if not isinstance(contract, dict):
                self.fail(f"line-jump contract must be an object: {raw_pair}")
                continue
            jumper = contract.get("jumper")
            reason = contract.get("reason")
            style = contract.get("style")
            try:
                jump_size = float(contract.get("size"))
            except (TypeError, ValueError):
                jump_size = math.nan
            if jumper not in pair:
                self.fail(f"line-jump jumper must name one edge in {raw_pair}")
                continue
            if not isinstance(reason, str) or not reason.strip():
                self.fail(f"line-jump contract requires a non-empty reason: {raw_pair}")
                continue
            if style != "arc" or not math.isfinite(jump_size) or not 6 <= jump_size <= 32:
                self.fail(f"line-jump contract requires arc style and size within [6,32]: {raw_pair}")
                continue
            if any(member not in edge_paths for member in pair):
                self.fail(f"line-jump contract names a missing edge: {raw_pair}")
                continue
            xml_style = self.styles.get(jumper, {})
            if xml_style.get("jumpStyle") != "arc":
                self.fail(f"line-jump edge lacks jumpStyle=arc: {jumper}")
                continue
            try:
                xml_size = float(xml_style.get("jumpSize", "nan"))
            except ValueError:
                xml_size = math.nan
            if not math.isfinite(xml_size) or not math.isclose(xml_size, jump_size, abs_tol=0.01):
                self.fail(f"line-jump size drift: {jumper} ({xml_size!r} != {jump_size:g})")
                continue
            jump_crossings[pair] = {
                "jumper": jumper, "size": jump_size, "reason": reason.strip(),
            }
        contracted_jumpers = {contract["jumper"] for contract in jump_crossings.values()}
        for edge_id in edge_paths:
            jump_style = self.styles.get(edge_id, {}).get("jumpStyle")
            if jump_style not in {None, "", "none"} and edge_id not in contracted_jumpers:
                self.fail(f"unregistered line-jump style: {edge_id}")
        allowed_overlaps = configured_pairs(self.config.get("allowed_edge_overlaps", []))
        allowed_region_borders = configured_pairs(self.config.get("allowed_region_border_overlaps", []))
        shared_rail_sources = set(self.config.get("allowed_shared_rail_sources", []))

        for edge_id, points in edge_paths.items():
            for first, last in zip(points, points[1:]):
                for region_id in region_ids:
                    if pair_key(edge_id, region_id) in allowed_region_borders:
                        continue
                    region = self.absolute_box(region_id)
                    if region is not None and self.overlaps_box_boundary(first, last, region):
                        self.fail(f"edge rides on region boundary: {edge_id} / {region_id}")

        seen_jump_crossings: set[tuple[str, str]] = set()
        jump_counts: dict[str, int] = {}
        jump_pair_counts: dict[tuple[str, str], int] = {}
        for left_index, left_id in enumerate(edges):
            left = self.by_id[left_id]
            left_points = edge_paths[left_id]
            if len(left_points) < 2:
                continue
            for right_id in edges[left_index + 1 :]:
                right = self.by_id[right_id]
                right_points = edge_paths[right_id]
                if len(right_points) < 2:
                    continue
                pair = pair_key(left_id, right_id)
                shared_rail = (
                    left.get("source") == right.get("source")
                    and left.get("source") in shared_rail_sources
                )
                for lf, ll in zip(left_points, left_points[1:]):
                    la, lfix, llo, lhi = self.segment(lf, ll)
                    if la == "d" or math.isclose(llo, lhi):
                        continue
                    for rf, rl in zip(right_points, right_points[1:]):
                        ra, rfix, rlo, rhi = self.segment(rf, rl)
                        if ra == "d" or math.isclose(rlo, rhi):
                            continue
                        if la == ra and math.isclose(lfix, rfix):
                            overlap = min(lhi, rhi) - max(llo, rlo)
                            from junction_routes import shared_terminal_overlap
                            terminal_rail = shared_terminal_overlap(
                                left_id, right_id, lf, ll, rf, rl, junction_rails)
                            if overlap > 1 and not shared_rail and not terminal_rail and pair not in allowed_overlaps:
                                self.fail(f"edges overlap {overlap:g}px: {left_id} / {right_id}")
                        elif la != ra:
                            horizontal = (lfix, llo, lhi) if la == "h" else (rfix, rlo, rhi)
                            vertical = (lfix, llo, lhi) if la == "v" else (rfix, rlo, rhi)
                            point = (vertical[0], horizontal[0])
                            interior = (
                                horizontal[1] < point[0] < horizontal[2]
                                and vertical[1] < point[1] < vertical[2]
                            )
                            shared_nodes = {left.get("source"), left.get("target")} & {
                                right.get("source"), right.get("target")
                            }
                            endpoint = point in {left_points[0], left_points[-1]} and point in {
                                right_points[0], right_points[-1]
                            }
                            if interior and not (shared_nodes and endpoint):
                                jump = jump_crossings.get(pair)
                                if jump is None:
                                    self.fail(f"edges cross without junction at {point}: {left_id} / {right_id}")
                                    continue
                                jumper_segment = (lf, ll) if jump["jumper"] == left_id else (rf, rl)
                                crossed_segment = (rf, rl) if jump["jumper"] == left_id else (lf, ll)
                                clearance = jump["size"] * 1.25
                                if min(math.dist(point, endpoint) for endpoint in jumper_segment) < clearance:
                                    self.fail(
                                        f"line jump is too close to a bend or endpoint at {point}: "
                                        f"{left_id} / {right_id}"
                                    )
                                    continue
                                if min(math.dist(point, endpoint) for endpoint in crossed_segment) < clearance:
                                    self.fail(
                                        f"line jump crosses too close to the other edge endpoint at {point}: "
                                        f"{left_id} / {right_id}"
                                    )
                                    continue
                                seen_jump_crossings.add(pair)
                                jumper = jump["jumper"]
                                jump_counts[jumper] = jump_counts.get(jumper, 0) + 1
                                jump_pair_counts[pair] = jump_pair_counts.get(pair, 0) + 1

        for pair in sorted(set(jump_crossings) - seen_jump_crossings):
            self.fail(f"stale line-jump contract has no matching interior crossing: {' / '.join(pair)}")
        for pair, count in sorted(jump_pair_counts.items()):
            if count > 1:
                self.fail(
                    f"the same edge pair crosses {count} times despite a line jump: {' / '.join(pair)}; "
                    "reflow the routes"
                )
        try:
            maximum_jumps = int(self.config.get("maximum_line_jumps_per_edge", 3))
        except (TypeError, ValueError):
            maximum_jumps = -1
        if maximum_jumps < 1:
            self.fail("maximum_line_jumps_per_edge must be a positive integer")
        count_exceptions = self.config.get("line_jump_count_exceptions", {})
        if not isinstance(count_exceptions, dict):
            self.fail("line_jump_count_exceptions must be an edge-ID-to-reason object")
            count_exceptions = {}
        for edge_id, reason in count_exceptions.items():
            if edge_id not in jump_counts or not isinstance(reason, str) or not reason.strip():
                self.fail(f"stale or empty line-jump count exception: {edge_id}")
        for edge_id, count in jump_counts.items():
            if maximum_jumps >= 1 and count > maximum_jumps and edge_id not in count_exceptions:
                self.fail(
                    f"edge uses {count} line jumps (maximum {maximum_jumps}): {edge_id}; "
                    "reflow the lanes or record a narrow reason"
                )

        long_routes = set(self.config.get("allowed_long_routes", []))
        threshold = float(self.config.get("route_inflation_floor", 900))
        ratio = float(self.config.get("route_inflation_ratio", 4))
        for edge_id, points in edge_paths.items():
            if len(points) < 2 or edge_id in long_routes:
                continue
            length = sum(
                abs(last[0] - first[0]) + abs(last[1] - first[1])
                for first, last in zip(points, points[1:])
            )
            direct = abs(points[-1][0] - points[0][0]) + abs(points[-1][1] - points[0][1])
            bends = max(0, len(points) - 2)
            if direct and length > max(threshold, direct * ratio) and bends >= 3:
                self.fail(
                    f"route detour needs review: {edge_id} length={length:g}px "
                    f"direct={direct:g}px bends={bends}"
                )

    def check_hierarchy(self) -> None:
        anchors = self.config.get("hierarchy_anchors", {})
        detected = {
            cell_id for cell_id, cell in self.by_id.items()
            if cell.get("vertex") == "1"
            and (
                cell_id.startswith(("expand_", "expand:"))
                or self.styles[cell_id].get("shape") in {"singleArrow", "flexArrow"}
            )
        }
        ignored = set(self.config.get("unregistered_hierarchy_exclusions", []))
        for arrow_id in sorted(detected - set(anchors) - ignored):
            self.fail(f"unregistered hierarchy arrow: {arrow_id}")
        tolerance = float(self.config.get("hierarchy_tolerance", 1))
        minimum_thickness = float(self.config.get("minimum_hierarchy_arrow_thickness", 48))
        minimum_length = float(self.config.get("minimum_hierarchy_arrow_length", 48))
        try:
            maximum_straight_aspect = float(
                self.config.get("maximum_straight_hierarchy_arrow_aspect_ratio", 6.0)
            )
        except (TypeError, ValueError):
            self.fail("maximum_straight_hierarchy_arrow_aspect_ratio must be a positive number")
            return
        if maximum_straight_aspect <= 0:
            self.fail("maximum_straight_hierarchy_arrow_aspect_ratio must be a positive number")
            return
        aspect_exclusions = self.config.get("straight_hierarchy_arrow_aspect_exceptions", {})
        if not isinstance(aspect_exclusions, dict):
            self.fail("straight_hierarchy_arrow_aspect_exceptions must be an ID-to-reason object")
            return
        for arrow_id, reason in aspect_exclusions.items():
            if arrow_id not in anchors:
                self.fail(f"straight hierarchy-arrow aspect exception references missing anchor: {arrow_id}")
            if not isinstance(reason, str) or not reason.strip():
                self.fail(f"straight hierarchy-arrow aspect exception missing reason: {arrow_id}")
        region_ids, hierarchy_ids, ignored_ids = self.vertex_sets()
        arrow_polygons: dict[str, list[tuple[float, float]]] = {}
        for arrow_id, anchor in anchors.items():
            arrow = self.absolute_box(arrow_id)
            cell = self.by_id.get(arrow_id)
            semantic_parent_id = anchor.get("parent", "")
            attachment_mode = anchor.get("attachment_mode", "parent-node")
            attachment_id = anchor.get("attachment", semantic_parent_id)
            semantic_parent = self.absolute_box(semantic_parent_id)
            parent = self.absolute_box(attachment_id)
            child = self.absolute_box(anchor.get("child", ""))
            if arrow is None or semantic_parent is None or parent is None or child is None:
                self.fail(f"hierarchy anchor references missing geometry: {arrow_id}")
                continue
            if attachment_mode == "parent-node":
                if attachment_id != semantic_parent_id:
                    self.fail(f"parent-node hierarchy attachment differs from semantic parent: {arrow_id}")
            elif attachment_mode in {"owner-region-boundary", "target-signpost"}:
                owned = set(self.config.get("region_content_contracts", {}).get(attachment_id, []))
                if attachment_id not in region_ids or semantic_parent_id not in owned:
                    self.fail(f"hierarchy attachment region does not own semantic parent: {arrow_id}")
                anchor_label = anchor.get("anchor_label")
                visible_label = strip_markup(cell.get("value", "")) if cell is not None else ""
                if not isinstance(anchor_label, str) or not anchor_label.strip():
                    self.fail(f"region-owned hierarchy attachment lacks anchor label: {arrow_id}")
                elif anchor_label.casefold() not in visible_label.casefold():
                    self.fail(f"hierarchy arrow label does not name its semantic anchor: {arrow_id}")
            else:
                self.fail(f"invalid hierarchy attachment mode: {arrow_id} -> {attachment_mode!r}")
            style = self.styles.get(arrow_id, {})
            if cell is None or cell.get("vertex") != "1" or style.get("shape") not in {"singleArrow", "flexArrow"}:
                self.fail(f"hierarchy arrow is not a block-arrow vertex: {arrow_id}")
            fill = style.get("fillColor", "").lower()
            if fill not in {"#ffffff", "white"} or style.get("strokeColor", "").lower() in {"", "none"}:
                self.fail(f"hierarchy arrow is not white with a visible outline: {arrow_id}")
            direction = anchor.get("direction")
            style_direction = style.get("direction", "east")
            visual_direction = {"east": "right", "west": "left", "south": "down", "north": "up"}.get(style_direction)
            if visual_direction != direction:
                self.fail(
                    f"hierarchy visual direction disagrees with manifest: {arrow_id} "
                    f"({style_direction!r} != {direction!r})"
                )
            checks = {
                "right": (arrow.x, parent.right, arrow.right, child.x),
                "left": (arrow.right, parent.x, arrow.x, child.right),
                "down": (arrow.y, parent.bottom, arrow.bottom, child.y),
                "up": (arrow.bottom, parent.y, arrow.y, child.bottom),
            }
            if direction not in checks:
                self.fail(f"invalid hierarchy direction: {arrow_id} -> {direction!r}")
                continue
            length = arrow.h if direction in {"up", "down"} else arrow.w
            thickness = arrow.w if direction in {"up", "down"} else arrow.h
            if length + tolerance < minimum_length or thickness + tolerance < minimum_thickness:
                self.fail(
                    f"hierarchy arrow is too small: {arrow_id} "
                    f"length={length:g} thickness={thickness:g}"
                )
            if (
                style.get("shape") == "singleArrow"
                and thickness > 0
                and length / thickness > maximum_straight_aspect + 1e-6
                and arrow_id not in aspect_exclusions
            ):
                self.fail(
                    f"straight hierarchy arrow is cable-like: {arrow_id} "
                    f"aspect={length / thickness:.2f} > {maximum_straight_aspect:g}; "
                    "recompose the child on a nearer side or use a reviewed compact bent block arrow"
                )
            if direction in {"up", "down"}:
                parent_overlap = min(arrow.right, parent.right) - max(arrow.x, parent.x)
                child_overlap = min(arrow.right, child.right) - max(arrow.x, child.x)
                center = arrow.x + arrow.w / 2
                center_attached = parent.x - tolerance <= center <= parent.right + tolerance and child.x - tolerance <= center <= child.right + tolerance
            else:
                parent_overlap = min(arrow.bottom, parent.bottom) - max(arrow.y, parent.y)
                child_overlap = min(arrow.bottom, child.bottom) - max(arrow.y, child.y)
                center = arrow.y + arrow.h / 2
                center_attached = parent.y - tolerance <= center <= parent.bottom + tolerance and child.y - tolerance <= center <= child.bottom + tolerance
            if attachment_mode == "target-signpost":
                if child_overlap <= tolerance:
                    self.fail(f"hierarchy target signpost misses the child corridor: {arrow_id}")
                parent_center = (parent.x + parent.w / 2, parent.y + parent.h / 2)
                child_center = (child.x + child.w / 2, child.y + child.h / 2)
                points_toward_child = {
                    "right": child_center[0] > parent_center[0],
                    "left": child_center[0] < parent_center[0],
                    "down": child_center[1] > parent_center[1],
                    "up": child_center[1] < parent_center[1],
                }[direction]
                if not points_toward_child:
                    self.fail(f"hierarchy target signpost points away from its child: {arrow_id}")
            elif parent_overlap <= tolerance or child_overlap <= tolerance or not center_attached:
                self.fail(f"hierarchy arrow misses the attachment or child corridor: {arrow_id}")
            actual_tail, expected_tail, actual_tip, expected_tip = checks[direction]
            if attachment_mode != "target-signpost" and abs(actual_tail - expected_tail) > tolerance:
                self.fail(f"hierarchy tail detached: {arrow_id} ({actual_tail:g} != {expected_tail:g})")
            if abs(actual_tip - expected_tip) > tolerance:
                self.fail(f"hierarchy tip detached: {arrow_id} ({actual_tip:g} != {expected_tip:g})")
            if not strip_markup(self.by_id[arrow_id].get("value", "")):
                self.fail(f"hierarchy arrow missing label: {arrow_id}")
            if attachment_mode == "target-signpost":
                for region_id in region_ids - {anchor.get("child", "")}:
                    region = self.absolute_box(region_id)
                    if region is None:
                        continue
                    overlap_w = min(arrow.right, region.right) - max(arrow.x, region.x)
                    overlap_h = min(arrow.bottom, region.bottom) - max(arrow.y, region.y)
                    if overlap_w > tolerance and overlap_h > tolerance:
                        self.fail(f"hierarchy target signpost overlaps a region: {arrow_id} / {region_id}")
            arrow_polygon = None
            if style.get("shape") == "singleArrow" and visual_direction is not None:
                arrow_polygon = single_arrow_polygon(
                    arrow.x, arrow.y, arrow.w, arrow.h, style_direction,
                    float(style.get("arrowWidth", 0.3)), float(style.get("arrowSize", 0.2)),
                )
                arrow_polygons[arrow_id] = arrow_polygon
            for cell_id, other_cell in self.by_id.items():
                if (
                    other_cell.get("vertex") != "1"
                    or cell_id in hierarchy_ids | region_ids | ignored_ids
                    or cell_id in {semantic_parent_id, attachment_id, anchor.get("child")}
                ):
                    continue
                other = self.absolute_box(cell_id)
                if other is None:
                    continue
                if arrow_polygon is not None:
                    intersects = box_intersects_polygon(other.x, other.y, other.w, other.h, arrow_polygon)
                else:
                    overlap_w = min(arrow.right, other.right) - max(arrow.x, other.x)
                    overlap_h = min(arrow.bottom, other.bottom) - max(arrow.y, other.y)
                    intersects = overlap_w > tolerance and overlap_h > tolerance
                if intersects:
                    self.fail(f"hierarchy arrow crosses unrelated node: {arrow_id} / {cell_id}")
            for edge_id, edge_cell in self.by_id.items():
                if edge_cell.get("edge") != "1":
                    continue
                points = self.edge_points(edge_id)
                if arrow_polygon is not None:
                    intersects = any(
                        segment_intersects_polygon(first, last, arrow_polygon)
                        for first, last in zip(points, points[1:])
                    )
                else:
                    intersects = any(self.crosses_box(first, last, arrow) for first, last in zip(points, points[1:]))
                if intersects:
                    self.fail(f"hierarchy arrow crosses execution/relation edge: {arrow_id} / {edge_id}")
        polygon_ids = sorted(arrow_polygons)
        for index, left_id in enumerate(polygon_ids):
            for right_id in polygon_ids[index + 1:]:
                if polygons_intersect(arrow_polygons[left_id], arrow_polygons[right_id]):
                    self.fail(f"hierarchy arrows overlap: {left_id} / {right_id}")

    def run(self) -> dict[str, Any]:
        self.prepare()
        self.check_references()
        self.check_geometry_collections()
        self.check_edge_endpoint_clearance()
        self.check_required_and_text()
        self.check_semantic_styles()
        self.check_ports_and_expected_edges()
        self.check_edge_label_positions()
        self.check_fanout_shape_contracts()
        region_ids, hierarchy_ids, ignored_ids = self.vertex_sets()
        self.check_regions(region_ids)
        self.check_node_overlaps(region_ids, hierarchy_ids, ignored_ids)
        self.check_visual_clearances(region_ids, hierarchy_ids, ignored_ids)
        self.check_compact_execution_geometry(region_ids, hierarchy_ids, ignored_ids)
        self.check_semantic_coverage(region_ids, hierarchy_ids, ignored_ids)
        self.check_vertical_flow_contracts(region_ids)
        self.check_granularity_contracts(region_ids, hierarchy_ids, ignored_ids)
        self.check_typography_contract(region_ids, hierarchy_ids, ignored_ids)
        self.check_density_contract(region_ids)
        self.check_routes(region_ids, hierarchy_ids, ignored_ids)
        self.check_hierarchy()
        return {
            "name": self.name,
            "cells": len(self.by_id),
            "vertices": sum(cell.get("vertex") == "1" for cell in self.by_id.values()),
            "edges": sum(cell.get("edge") == "1" for cell in self.by_id.values()),
            "errors": self.errors,
            "warnings": self.warnings,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagram", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()

    manifest: dict[str, Any] = {}
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            print("drawio audit: FAIL\n- manifest schema_version must be 1")
            return 2

    try:
        pages = graph_pages(args.diagram)
    except (ET.ParseError, ValueError, OSError, zlib.error) as error:
        print(f"drawio audit: FAIL\n- {error}")
        return 2

    base_config = manifest.get("defaults", {})
    page_configs = manifest.get("pages", {})
    results = []
    for name, model in pages:
        config = merge_dict(base_config, page_configs.get("*", {}))
        config = merge_dict(config, page_configs.get(name, {}))
        results.append(PageAudit(name, model, config).run())

    digest = hashlib.sha256(args.diagram.read_bytes()).hexdigest()
    report = {
        "diagram": str(args.diagram),
        "sha256": digest,
        "pages": results,
        "errors": sum(len(result["errors"]) for result in results),
        "warnings": sum(len(result["warnings"]) for result in results),
    }
    report["error_summary"] = summarize_errors(
        [error for result in results for error in result["errors"]]
    )
    if args.json_report:
        args.json_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    status = "PASS" if report["errors"] == 0 else "FAIL"
    print(f"drawio audit: {status}")
    print(f"sha256: {digest}")
    for result in results:
        print(
            f"page {result['name']!r}: {result['cells']} cells, "
            f"{result['vertices']} vertices, {result['edges']} edges"
        )
    if report["errors"]:
        categories = ", ".join(
            f"{name}={count}" for name, count in report["error_summary"]["categories"].items()
        )
        roots = ", ".join(
            f"{edge_id}={count}" for edge_id, count in report["error_summary"]["root_edges"].items()
        )
        print(f"error categories: {categories}")
        print(f"most implicated edges: {roots or 'none'}")
    for result in results:
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
