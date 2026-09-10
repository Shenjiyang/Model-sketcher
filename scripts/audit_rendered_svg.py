#!/usr/bin/env python3
"""Audit geometry from an SVG exported by the official Draw.io renderer."""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from audit_drawio import (
    avoidable_orthogonal_shortcut,
    graph_pages,
    merge_dict,
    orthogonal_segments_conflict,
    parse_style,
)
from hierarchy_arrow_geometry import box_intersects_polygon, segment_intersects_polygon, single_arrow_polygon

try:
    from PIL import Image
except ImportError:  # The standard-library decoder below keeps the skill self-contained.
    Image = None


SVG = "{http://www.w3.org/2000/svg}"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
PATH_TOKEN = re.compile(rf"[A-Za-z]|{NUMBER}")
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.x

    @property
    def height(self) -> float:
        return self.bottom - self.y

    def grown(self, amount: float) -> "Box":
        return Box(self.x - amount, self.y - amount, self.right + amount, self.bottom + amount)


@dataclass
class RenderedCell:
    cell_id: str
    label_boxes: list[Box]
    shape_boxes: list[Box]
    route_points: list[tuple[float, float]]
    arrow_boxes: list[Box]
    route_curve_count: int = 0

    @property
    def label_box(self) -> Box | None:
        return union_boxes(self.label_boxes)

    @property
    def shape_box(self) -> Box | None:
        return union_boxes(self.shape_boxes)


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def number(value: str | None, default: float = 0.0) -> float:
    return float(value) if value not in {None, ""} else default


def union_boxes(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return Box(
        min(box.x for box in boxes),
        min(box.y for box in boxes),
        max(box.right for box in boxes),
        max(box.bottom for box in boxes),
    )


def boxes_intersect(left: Box, right: Box, clearance: float = 0.0) -> bool:
    left = left.grown(clearance)
    return (
        min(left.right, right.right) - max(left.x, right.x) > 0.5
        and min(left.bottom, right.bottom) - max(left.y, right.y) > 0.5
    )


def intersection_box(left: Box, right: Box) -> Box | None:
    result = Box(
        max(left.x, right.x), max(left.y, right.y),
        min(left.right, right.right), min(left.bottom, right.bottom),
    )
    return result if result.width > 0 and result.height > 0 else None


def material_overlap(left: Box, right: Box, minimum_depth: float, minimum_ratio: float) -> bool:
    overlap = intersection_box(left, right)
    if overlap is None or min(overlap.width, overlap.height) < minimum_depth:
        return False
    smaller_area = min(left.width * left.height, right.width * right.height)
    return smaller_area > 0 and overlap.width * overlap.height / smaller_area >= minimum_ratio


def overflow_amount(outer: Box, inner: Box) -> float:
    return max(
        outer.x - inner.x, outer.y - inner.y,
        inner.right - outer.right, inner.bottom - outer.bottom, 0.0,
    )


def contains(outer: Box, inner: Box, tolerance: float) -> bool:
    return (
        inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.right <= outer.right + tolerance
        and inner.bottom <= outer.bottom + tolerance
    )


def point_in_box(point: tuple[float, float], box: Box, margin: float = 0.5) -> bool:
    x, y = point
    return box.x + margin < x < box.right - margin and box.y + margin < y < box.bottom - margin


def segment_intersects_box(
    start: tuple[float, float], end: tuple[float, float], box: Box, margin: float = 0.5
) -> bool:
    """Liang-Barsky segment/rectangle intersection against the box interior."""
    box = Box(box.x + margin, box.y + margin, box.right - margin, box.bottom - margin)
    if box.width <= 0 or box.height <= 0:
        return False
    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - box.x, box.right - x0, y0 - box.y, box.bottom - y0)
    low, high = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-9:
            if qi < 0:
                return False
            continue
        ratio = qi / pi
        if pi < 0:
            low = max(low, ratio)
        else:
            high = min(high, ratio)
        if low > high:
            return False
    return high > 0 and low < 1


def element_box(element: ET.Element) -> Box | None:
    tag = local_name(element)
    if tag in {"rect", "image"}:
        x, y = number(element.get("x")), number(element.get("y"))
        return Box(x, y, x + number(element.get("width")), y + number(element.get("height")))
    if tag == "circle":
        cx, cy, radius = number(element.get("cx")), number(element.get("cy")), number(element.get("r"))
        return Box(cx - radius, cy - radius, cx + radius, cy + radius)
    if tag == "ellipse":
        cx, cy = number(element.get("cx")), number(element.get("cy"))
        rx, ry = number(element.get("rx")), number(element.get("ry"))
        return Box(cx - rx, cy - ry, cx + rx, cy + ry)
    if tag == "line":
        xs = [number(element.get("x1")), number(element.get("x2"))]
        ys = [number(element.get("y1")), number(element.get("y2"))]
        return Box(min(xs), min(ys), max(xs), max(ys))
    if tag in {"polygon", "polyline"}:
        values = [float(item) for item in re.findall(NUMBER, element.get("points", ""))]
        points = list(zip(values[::2], values[1::2]))
        return points_box(points)
    if tag == "path":
        return points_box(path_points(element.get("d", ""), include_controls=True))
    return None


def png_ink_box(data: bytes) -> Box | None:
    """Return the non-transparent pixel bounds of an 8-bit PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if Image is not None:
        with Image.open(io.BytesIO(data)) as image:
            alpha = image.convert("RGBA").getchannel("A")
            bounds = alpha.getbbox()
        return Box(*bounds) if bounds else None
    offset = 8
    width = height = color_type = bit_depth = 0
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    channels = {4: 2, 6: 4}.get(color_type)
    if not width or not height or bit_depth != 8 or channels is None:
        return None
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    rows: list[bytearray] = []
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        previous = rows[-1] if rows else bytearray(stride)
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 255
            elif filter_type == 2:
                row[index] = (row[index] + above) & 255
            elif filter_type == 3:
                row[index] = (row[index] + ((left + above) // 2)) & 255
            elif filter_type == 4:
                estimate = left + above - upper_left
                pa, pb, pc = abs(estimate - left), abs(estimate - above), abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else above if pb <= pc else upper_left
                row[index] = (row[index] + predictor) & 255
            elif filter_type != 0:
                return None
        rows.append(row)
    alpha_index = channels - 1
    left, top, right, bottom = width, height, -1, -1
    for y, row in enumerate(rows):
        for x in range(width):
            if row[x * channels + alpha_index] != 0:
                left, top = min(left, x), min(top, y)
                right, bottom = max(right, x), max(bottom, y)
    if right < 0:
        return None
    return Box(left, top, right + 1, bottom + 1)


def rendered_image_box(element: ET.Element, trim_transparency: bool) -> Box | None:
    box = element_box(element)
    href = element.get(XLINK_HREF, "")
    if box is None or not trim_transparency or not href.startswith("data:image/png;base64,"):
        return box
    try:
        raw = base64.b64decode(href.split(",", 1)[1])
        ink = png_ink_box(raw)
    except (ValueError, zlib.error, struct.error):
        return box
    if ink is None:
        return box
    width, height = struct.unpack(">II", raw[16:24])
    return Box(
        box.x + ink.x * box.width / width,
        box.y + ink.y * box.height / height,
        box.x + ink.right * box.width / width,
        box.y + ink.bottom * box.height / height,
    )


def points_box(points: list[tuple[float, float]]) -> Box | None:
    if not points:
        return None
    return Box(
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def path_points(data: str, include_controls: bool = False) -> list[tuple[float, float]]:
    """Return points from common Draw.io path commands; curves include controls for bounds."""
    tokens = PATH_TOKEN.findall(data)
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
    result: list[tuple[float, float]] = []
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = current
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command.upper() == "Z":
                current = start
                result.append(current)
                command = ""
                continue
        if not command or command.upper() not in arity:
            break
        count = arity[command.upper()]
        if index + count > len(tokens):
            break
        values = [float(item) for item in tokens[index : index + count]]
        index += count
        relative = command.islower()
        upper = command.upper()
        x0, y0 = current
        if upper in {"M", "L", "T"}:
            point = (values[0] + x0, values[1] + y0) if relative else (values[0], values[1])
            current = point
            result.append(point)
            if upper == "M":
                start = point
                command = "l" if relative else "L"
        elif upper == "H":
            current = (values[0] + x0 if relative else values[0], y0)
            result.append(current)
        elif upper == "V":
            current = (x0, values[0] + y0 if relative else values[0])
            result.append(current)
        elif upper in {"C", "S", "Q"}:
            pairs = list(zip(values[::2], values[1::2]))
            if relative:
                pairs = [(x + x0, y + y0) for x, y in pairs]
            current = pairs[-1]
            result.extend(pairs if include_controls else [current])
        elif upper == "A":
            endpoint = (values[5] + x0, values[6] + y0) if relative else (values[5], values[6])
            current = endpoint
            result.append(endpoint)
            if include_controls:
                rx, ry = abs(values[0]), abs(values[1])
                result.extend([(endpoint[0] - rx, endpoint[1] - ry), (endpoint[0] + rx, endpoint[1] + ry)])
    return result


def straight_runs(points):
    """Merge renderer split points, retaining real turns and reversals."""
    result = []
    for point in points:
        if len(result) >= 2:
            a, b = result[-2:]
            vertical = abs(a[0]-b[0]) <= .75 and abs(b[0]-point[0]) <= .75
            horizontal = abs(a[1]-b[1]) <= .75 and abs(b[1]-point[1]) <= .75
            axis = 1 if vertical else 0
            if (vertical or horizontal) and (b[axis]-a[axis])*(point[axis]-b[axis]) > 0:
                result.pop()
        result.append(point)
    return list(zip(result, result[1:]))


def owned_elements(group: ET.Element) -> Iterator[tuple[ET.Element, bool]]:
    """Yield descendants owned by one cell, excluding nested data-cell-id groups."""
    def visit(element: ET.Element, in_label_switch: bool) -> Iterator[tuple[ET.Element, bool]]:
        for child in element:
            if child is not group and child.get("data-cell-id"):
                continue
            child_label_switch = in_label_switch or local_name(child) == "switch"
            yield child, child_label_switch
            yield from visit(child, child_label_switch)

    yield from visit(group, False)


def rendered_cells(svg: Path, trim_label_ids: set[str] | None = None) -> dict[str, RenderedCell]:
    root = ET.parse(svg).getroot()
    result: dict[str, RenderedCell] = {}
    for group in root.iter(f"{SVG}g"):
        cell_id = group.get("data-cell-id")
        if not cell_id or cell_id in result:
            continue
        labels: list[Box] = []
        shapes: list[Box] = []
        route_points: list[tuple[float, float]] = []
        route_curve_count = 0
        arrows: list[Box] = []
        for element, in_label_switch in owned_elements(group):
            tag = local_name(element)
            if tag == "image" and in_label_switch:
                box = rendered_image_box(element, cell_id in (trim_label_ids or set()))
                if box and box.width > 0 and box.height > 0:
                    labels.append(box)
                continue
            if in_label_switch or tag not in {"rect", "circle", "ellipse", "line", "polygon", "polyline", "path"}:
                continue
            box = element_box(element)
            if box is None:
                continue
            style = element.get("style", "")
            if tag == "path" and "stroke:" in style and "fill:" not in style:
                points = path_points(element.get("d", ""))
                points = [
                    point for index, point in enumerate(points)
                    if index == 0 or math.dist(point, points[index - 1]) > 0.5
                ]
                if len(points) >= 2 and not route_points:
                    route_points = points
                    route_curve_count = len(
                        re.findall(r"[ACQSTacqst]", element.get("d", ""))
                    )
                    continue
            if tag == "path" and "fill:" in style and "stroke:" in style:
                arrows.append(box)
            else:
                shapes.append(box)
        result[cell_id] = RenderedCell(
            cell_id, labels, shapes, route_points, arrows, route_curve_count
        )
    return result


def exception_keys(config: dict[str, Any], name: str) -> set[str]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an ID-to-reason object")
    bad = [key for key, reason in value.items() if not isinstance(reason, str) or not reason.strip()]
    if bad:
        raise ValueError(f"{name} has empty reasons: {', '.join(bad)}")
    return set(value)


def pair_key(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def page_config(manifest: dict[str, Any], page_name: str) -> dict[str, Any]:
    config = merge_dict({}, manifest.get("defaults", {}))
    pages = manifest.get("pages", {})
    config = merge_dict(config, pages.get("*", {}))
    config = merge_dict(config, pages.get(page_name, {}))
    rendered_config = dict(config.get("rendered_svg_audit", {}))
    rendered_config.setdefault("minimum_route_node_clearance", config.get("minimum_route_node_clearance", 0.0))
    return rendered_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagram", type=Path)
    parser.add_argument("svg", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    manifest: dict[str, Any] = {}
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    pages = graph_pages(args.diagram)
    if len(pages) != 1:
        print("rendered SVG audit: FAIL\nERROR: one SVG per Draw.io page is required")
        return 1
    page_name, model = pages[0]
    config = page_config(manifest, page_name)
    clearance = float(config.get("minimum_clearance", 2.0))
    route_node_clearance = float(config.get("minimum_route_node_clearance", 0.0))
    if not math.isfinite(route_node_clearance) or route_node_clearance < 0:
        print("rendered SVG audit: FAIL\nERROR: minimum_route_node_clearance must be finite and non-negative")
        return 1
    # Absorb only sub-pixel rasterization fringe. Visible ink outside a node is
    # a layout defect, not a warning that can be accepted visually.
    fit_tolerance = float(config.get("label_fit_tolerance", 0.5))
    endpoint_margin = float(config.get("endpoint_interior_margin", 2.0))
    overlap_depth = float(config.get("material_overlap_depth", 3.0))
    overlap_ratio = float(config.get("material_overlap_ratio", 0.08))
    # Text remains unreadable at overlap ratios that are harmless for large
    # filled shapes. Audit label ink with its own stricter thresholds.
    label_overlap_depth = float(config.get("label_overlap_depth", 2.0))
    label_overlap_ratio = float(config.get("label_overlap_ratio", 0.01))
    ignored = exception_keys(config, "ignored_cells")
    allowed_label_pairs = exception_keys(config, "allowed_label_overlaps")
    allowed_label_node = exception_keys(config, "allowed_label_node_overlaps")
    allowed_edge_text = exception_keys(config, "allowed_edge_text_crossings")
    allowed_edge_node = exception_keys(config, "allowed_edge_node_crossings")
    allowed_outside = exception_keys(config, "allowed_labels_outside_nodes")
    allowed_bends = exception_keys(config, "allowed_label_at_bends")
    allowed_label_distances = exception_keys(config, "allowed_edge_label_distances")
    allowed_arrow_overlap = exception_keys(config, "allowed_label_arrow_overlaps")
    allowed_endpoint_reentry = exception_keys(config, "allowed_endpoint_reentries")
    route_quality_exclusions = exception_keys(config, "route_quality_exclusions")
    route_degree_exclusions = exception_keys(config, "route_degree_exclusions")
    raw_line_jumps = config.get("line_jump_crossings", {})
    configured_near_axis_tolerance = config.get("near_axis_dogleg_tolerance")
    configured_backtrack_floor = config.get("minimum_route_backtrack")

    source_cells = {cell.get("id", ""): cell for cell in model.iter("mxCell")}
    styles = {cell_id: parse_style(cell.get("style", "")) for cell_id, cell in source_cells.items()}
    vertices = {cell_id for cell_id, cell in source_cells.items() if cell.get("vertex") == "1"}
    edges = {cell_id for cell_id, cell in source_cells.items() if cell.get("edge") == "1"}
    incoming_count: dict[str, int] = {}
    outgoing_count: dict[str, int] = {}
    for edge_id in edges:
        edge_style = styles[edge_id]
        relation_only = (
            edge_id in route_degree_exclusions
            or (
                float(edge_style.get("strokeWidth", 1)) >= 3
                and "endFill=0" in source_cells[edge_id].get("style", "").split(";")
            )
        )
        if relation_only:
            continue
        source_id = source_cells[edge_id].get("source", "")
        target_id = source_cells[edge_id].get("target", "")
        outgoing_count[source_id] = outgoing_count.get(source_id, 0) + 1
        incoming_count[target_id] = incoming_count.get(target_id, 0) + 1

    def endpoint_side(edge_id: str, prefix: str) -> str | None:
        style = styles[edge_id]
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
    regions = {cell_id for cell_id in vertices if styles[cell_id].get("container") == "1"}
    text_only = {
        cell_id
        for cell_id in vertices
        if styles[cell_id].get("text") == "1" and styles[cell_id].get("strokeColor") in {None, "none"}
    }
    # Vertex labels normally have transparent padding; trim it to visible glyph ink.
    # Edge-label backgrounds remain untrimmed because their white box occludes routes.
    rendered = rendered_cells(args.svg, vertices)
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw_line_jumps, dict):
        errors.append("line_jump_crossings must be an edge-pair-to-contract object")
        raw_line_jumps = {}
    declared_jump_counts: dict[str, int] = {}
    for pair, contract in raw_line_jumps.items():
        if not isinstance(contract, dict) or not isinstance(contract.get("jumper"), str):
            errors.append(f"invalid rendered line-jump contract: {pair!r}")
            continue
        jumper = contract["jumper"]
        declared_jump_counts[jumper] = declared_jump_counts.get(jumper, 0) + 1
    for jumper, expected_count in declared_jump_counts.items():
        item = rendered.get(jumper)
        if jumper not in edges or item is None:
            errors.append(f"rendered line-jump edge is missing: {jumper}")
        elif item.route_curve_count < expected_count:
            errors.append(
                f"rendered arc bridges missing: {jumper} has {item.route_curve_count}, "
                f"expected at least {expected_count}"
            )
    try:
        maximum_label_distance = float(config.get("maximum_edge_label_distance", 64.0))
    except (TypeError, ValueError):
        maximum_label_distance = 64.0
        errors.append("maximum_edge_label_distance must be a positive finite number")
    if not math.isfinite(maximum_label_distance) or maximum_label_distance <= 0:
        errors.append("maximum_edge_label_distance must be a positive finite number")
        maximum_label_distance = 64.0
    try:
        minimum_visible_label_flank = float(config.get("minimum_visible_edge_label_flank", 12.0))
        minimum_edge_label_route_clearance = float(config.get("minimum_edge_label_route_clearance", 2.0))
    except (TypeError, ValueError):
        minimum_visible_label_flank = 12.0
        minimum_edge_label_route_clearance = 2.0
        errors.append("rendered edge-label clearance thresholds must be numeric")
    if not math.isfinite(minimum_visible_label_flank) or minimum_visible_label_flank < 0:
        errors.append("minimum_visible_edge_label_flank must be a finite non-negative number")
        minimum_visible_label_flank = 12.0
    if not math.isfinite(minimum_edge_label_route_clearance) or minimum_edge_label_route_clearance < 0:
        errors.append("minimum_edge_label_route_clearance must be a finite non-negative number")
        minimum_edge_label_route_clearance = 2.0
    for name, ids in (
        ("route_quality_exclusions", route_quality_exclusions),
        ("route_degree_exclusions", route_degree_exclusions),
        ("allowed_edge_label_distances", allowed_label_distances),
    ):
        for unknown_id in sorted(ids - edges):
            errors.append(f"{name} references a missing edge: {unknown_id}")

    for cell_id in vertices | edges:
        if cell_id in ignored:
            continue
        source = source_cells[cell_id]
        if source.get("value", "").strip() and (cell_id not in rendered or not rendered[cell_id].label_boxes):
            warnings.append(f"rendered label geometry unavailable: {cell_id}")

    # Rendered label must fit the visible node, not merely its XML estimate.
    for cell_id in vertices - regions - text_only - ignored:
        item = rendered.get(cell_id)
        if not item or not item.label_box or not item.shape_box or cell_id in allowed_outside:
            continue
        overflow = overflow_amount(item.shape_box, item.label_box)
        if overflow > fit_tolerance:
            errors.append(f"rendered label exceeds its node by {overflow:.1f}px: {cell_id}")
        elif overflow > 0:
            warnings.append(f"rendered label reaches its node boundary ({overflow:.1f}px): {cell_id}")

    labeled = {cell_id: item.label_box for cell_id, item in rendered.items() if item.label_box and cell_id not in ignored}
    ordinary_labels = {
        cell_id: labeled[cell_id]
        for cell_id in vertices - regions - text_only
        if cell_id in labeled
    }
    edge_labels = {cell_id: labeled[cell_id] for cell_id in edges if cell_id in labeled}
    region_labels = {cell_id: labeled[cell_id] for cell_id in regions if cell_id in labeled}
    labeled_ids = sorted(set(ordinary_labels) | set(edge_labels) | set(region_labels))
    for index, left_id in enumerate(labeled_ids):
        for right_id in labeled_ids[index + 1 :]:
            if pair_key(left_id, right_id) in allowed_label_pairs:
                continue
            if not material_overlap(
                labeled[left_id], labeled[right_id],
                label_overlap_depth, label_overlap_ratio,
            ):
                continue
            # An edge-label/node-label collision is reported against the node shape below.
            if (left_id in edges and right_id in vertices) or (right_id in edges and left_id in vertices):
                continue
            if left_id in regions and right_id in regions:
                continue
            errors.append(f"rendered labels overlap: {left_id} / {right_id}")

    blockers = {
        cell_id: item.shape_box
        for cell_id, item in rendered.items()
        if cell_id in vertices - regions - text_only - ignored and item.shape_box
    }
    hierarchy_polygons = {
        cell_id: single_arrow_polygon(
            box.x, box.y, box.width, box.height,
            styles[cell_id].get("direction", "east"),
            float(styles[cell_id].get("arrowWidth", 0.3)),
            float(styles[cell_id].get("arrowSize", 0.2)),
        )
        for cell_id, box in blockers.items()
        if styles[cell_id].get("shape") == "singleArrow"
    }
    for label_id, label_box in {**edge_labels, **region_labels}.items():
        for node_id, node_box in blockers.items():
            if label_id == node_id or pair_key(label_id, node_id) in allowed_label_node:
                continue
            if node_id in hierarchy_polygons:
                overlaps = box_intersects_polygon(
                    label_box.x, label_box.y, label_box.width, label_box.height,
                    hierarchy_polygons[node_id],
                )
            else:
                overlaps = material_overlap(label_box, node_box, overlap_depth, overlap_ratio)
            if not overlaps:
                continue
            endpoints = {
                source_cells[label_id].get("source", ""),
                source_cells[label_id].get("target", ""),
            } if label_id in edges else set()
            relation = "source/target node" if node_id in endpoints else "unrelated node"
            errors.append(f"rendered {label_id} label overlaps {relation}: {node_id}")

    for edge_id in edges - ignored:
        item = rendered.get(edge_id)
        if not item or len(item.route_points) < 2:
            continue
        source = source_cells[edge_id].get("source", "")
        target = source_cells[edge_id].get("target", "")
        segments = list(zip(item.route_points, item.route_points[1:]))
        if edge_id not in route_quality_exclusions:
            axes: list[str] = []
            for start, end in segments:
                if math.isclose(start[0], end[0], abs_tol=0.75):
                    axes.append("v")
                elif math.isclose(start[1], end[1], abs_tol=0.75):
                    axes.append("h")
                else:
                    axes.append("d")
            source_side = endpoint_side(edge_id, "exit")
            target_side = endpoint_side(edge_id, "entry")
            source_axis = expected_axis(source_side)
            target_axis = expected_axis(target_side)
            source_shape = styles.get(source, {}).get("shape", "rectangle")
            target_shape = styles.get(target, {}).get("shape", "rectangle")
            source_rectangular = source_shape in {"", "rectangle"}
            target_rectangular = target_shape in {"", "rectangle"}
            if source in blockers and source_rectangular and source_axis is not None and axes[0] != source_axis:
                errors.append(
                    f"rendered route leaves endpoint tangentially: {edge_id} "
                    f"({source_side} port, first segment={axes[0]})"
                )
            if target in blockers and target_rectangular and target_axis is not None and axes[-1] != target_axis:
                errors.append(
                    f"rendered route approaches endpoint tangentially: {edge_id} "
                    f"({target_side} port, last segment={axes[-1]})"
                )
            for index in range(1, len(item.route_points) - 1):
                if axes[index - 1] != axes[index] or axes[index] not in {"h", "v"}:
                    continue
                before, middle, after = item.route_points[index - 1 : index + 2]
                if axes[index] == "h":
                    first_delta = middle[0] - before[0]
                    second_delta = after[0] - middle[0]
                else:
                    first_delta = middle[1] - before[1]
                    second_delta = after[1] - middle[1]
                if first_delta * second_delta < 0:
                    source_box = blockers.get(source)
                    target_box = blockers.get(target)
                    backtrack_floor = (
                        float(configured_backtrack_floor)
                        if configured_backtrack_floor is not None
                        else max(
                            2.0,
                            min(source_box.height, target_box.height) * 0.05
                            if source_box and target_box
                            else 2.0,
                        )
                    )
                    reversal = min(abs(first_delta), abs(second_delta))
                    message = f"rendered route backtracks {reversal:g}px: {edge_id} at {middle}"
                    if reversal > backtrack_floor:
                        errors.append(message)
                    else:
                        warnings.append(f"subpixel/short {message}")

            source_box = blockers.get(source)
            target_box = blockers.get(target)
            single_chain = outgoing_count.get(source) == 1 and incoming_count.get(target) == 1
            normalized_axes: list[str] = []
            for axis in axes:
                if not normalized_axes or normalized_axes[-1] != axis:
                    normalized_axes.append(axis)
            near_axis_tolerance = (
                float(configured_near_axis_tolerance)
                if configured_near_axis_tolerance is not None
                else min(source_box.height, target_box.height) * 0.75
                if source_box and target_box
                else 0.0
            )
            def rendered_direct_port_blocked(vertical: bool, coordinate: float) -> bool:
                if not source_box or not target_box:
                    return False
                if vertical:
                    first = (coordinate, min(source_box.bottom, target_box.bottom))
                    last = (coordinate, max(source_box.y, target_box.y))
                else:
                    first = (min(source_box.right, target_box.right), coordinate)
                    last = (max(source_box.x, target_box.x), coordinate)
                if first == last:
                    return False
                for node_id, node_box in blockers.items():
                    if node_id in {source, target}:
                        continue
                    if node_id in hierarchy_polygons:
                        if segment_intersects_polygon(first, last, hierarchy_polygons[node_id]):
                            return True
                    elif segment_intersects_box(first, last, node_box.grown(route_node_clearance)):
                        return True
                for label_id, label_box in labeled.items():
                    if label_id not in {edge_id, source, target} and segment_intersects_box(first, last, label_box):
                        return True
                for other_id in edges - ignored - {edge_id}:
                    other = rendered.get(other_id)
                    if not other or len(other.route_points) < 2:
                        continue
                    if any(
                        orthogonal_segments_conflict(first, last, other_first, other_last)
                        for other_first, other_last in zip(other.route_points, other.route_points[1:])
                    ):
                        return True
                return False

            port_alignable = False
            if source_rectangular and target_rectangular and source_box and target_box:
                if (
                    {source_side, target_side} == {"north", "south"}
                    and len(normalized_axes) >= 3
                    and normalized_axes[0] == normalized_axes[-1] == "v"
                    and "h" in normalized_axes
                ):
                    overlap_left = max(source_box.x, target_box.x)
                    overlap_right = min(source_box.right, target_box.right)
                    if overlap_right - overlap_left > 2:
                        coordinate = min(
                            max((target_box.x + target_box.right) / 2, overlap_left + 1),
                            overlap_right - 1,
                        )
                        port_alignable = True
                        message = (
                            f"rendered avoidable vertical port-alignment dogleg: {edge_id}; "
                            "endpoint spans overlap"
                        )
                        warnings.append(f"{message}; direct corridor contains an obstacle") if rendered_direct_port_blocked(True, coordinate) else errors.append(message)
                elif (
                    {source_side, target_side} == {"east", "west"}
                    and len(normalized_axes) >= 3
                    and normalized_axes[0] == normalized_axes[-1] == "h"
                    and "v" in normalized_axes
                ):
                    overlap_top = max(source_box.y, target_box.y)
                    overlap_bottom = min(source_box.bottom, target_box.bottom)
                    if overlap_bottom - overlap_top > 2:
                        coordinate = min(
                            max((target_box.y + target_box.bottom) / 2, overlap_top + 1),
                            overlap_bottom - 1,
                        )
                        port_alignable = True
                        message = (
                            f"rendered avoidable horizontal port-alignment dogleg: {edge_id}; "
                            "endpoint spans overlap"
                        )
                        warnings.append(f"{message}; direct corridor contains an obstacle") if rendered_direct_port_blocked(False, coordinate) else errors.append(message)

            def rendered_corridor_blocked(vertical: bool) -> bool:
                if not source_box or not target_box:
                    return False
                source_center = (
                    (source_box.x + source_box.right) / 2,
                    (source_box.y + source_box.bottom) / 2,
                )
                target_center = (
                    (target_box.x + target_box.right) / 2,
                    (target_box.y + target_box.bottom) / 2,
                )
                if vertical:
                    corridor = Box(
                        min(source_center[0], target_center[0]) - 1,
                        min(source_box.bottom, target_box.bottom),
                        max(source_center[0], target_center[0]) + 1,
                        max(source_box.y, target_box.y),
                    )
                else:
                    corridor = Box(
                        min(source_box.right, target_box.right),
                        min(source_center[1], target_center[1]) - 1,
                        max(source_box.x, target_box.x),
                        max(source_center[1], target_center[1]) + 1,
                    )
                if corridor.width <= 0 or corridor.height <= 0:
                    return False
                return any(
                    node_id not in {source, target} and boxes_intersect(corridor, node_box)
                    for node_id, node_box in blockers.items()
                )

            if (
                single_chain
                and not port_alignable
                and source_rectangular
                and target_rectangular
                and source_box
                and target_box
                and len(normalized_axes) >= 3
                and normalized_axes[0] == normalized_axes[-1] == "v"
                and "h" in normalized_axes
            ):
                center_offset = abs(
                    (source_box.x + source_box.right) / 2
                    - (target_box.x + target_box.right) / 2
                )
                if center_offset <= near_axis_tolerance:
                    message = (
                        f"rendered avoidable near-vertical dogleg: {edge_id} "
                        f"node-center offset={center_offset:g}px"
                    )
                    warnings.append(f"{message}; direct corridor contains an obstacle") if rendered_corridor_blocked(True) else errors.append(message)
            elif (
                single_chain
                and source_rectangular
                and target_rectangular
                and source_box
                and target_box
                and len(normalized_axes) >= 3
                and normalized_axes[0] == normalized_axes[-1] == "h"
                and "v" in normalized_axes
            ):
                center_offset = abs(
                    (source_box.y + source_box.bottom) / 2
                    - (target_box.y + target_box.bottom) / 2
                )
                if center_offset <= near_axis_tolerance:
                    message = (
                        f"rendered avoidable near-horizontal dogleg: {edge_id} "
                        f"node-center offset={center_offset:g}px"
                    )
                    warnings.append(f"{message}; direct corridor contains an obstacle") if rendered_corridor_blocked(False) else errors.append(message)

            def rendered_shortcut_blocked(
                first: tuple[float, float], last: tuple[float, float]
            ) -> bool:
                for node_id, node_box in blockers.items():
                    if node_id in {source, target}:
                        continue
                    if node_id in hierarchy_polygons:
                        if segment_intersects_polygon(first, last, hierarchy_polygons[node_id]):
                            return True
                    elif segment_intersects_box(first, last, node_box.grown(route_node_clearance)):
                        return True
                for label_id, label_box in labeled.items():
                    if label_id not in {edge_id, source, target} and segment_intersects_box(first, last, label_box):
                        return True
                for other_id in edges - ignored - {edge_id}:
                    other = rendered.get(other_id)
                    if not other or len(other.route_points) < 2:
                        continue
                    if any(
                        orthogonal_segments_conflict(first, last, other_first, other_last)
                        for other_first, other_last in zip(other.route_points, other.route_points[1:])
                    ):
                        return True
                return False

            shortcut = avoidable_orthogonal_shortcut(
                item.route_points, rendered_shortcut_blocked, tolerance=0.75
            )
            if shortcut is not None:
                start_index, end_index, candidate = shortcut
                errors.append(
                    f"rendered avoidable orthogonal staircase: {edge_id} segments "
                    f"{start_index}-{end_index} can use {len(candidate) - 1} legs"
                )
        if edge_id not in allowed_endpoint_reentry:
            source_box = blockers.get(source)
            target_box = blockers.get(target)
            if source_box and (
                segment_intersects_box(*segments[0], source_box, margin=endpoint_margin)
                or any(
                    segment_intersects_box(*segment, source_box, margin=endpoint_margin)
                    for segment in segments[1:]
                )
            ):
                errors.append(f"rendered edge enters or re-enters source node: {edge_id} / {source}")
            if target_box and (
                segment_intersects_box(*segments[-1], target_box, margin=endpoint_margin)
                or any(
                    segment_intersects_box(*segment, target_box, margin=endpoint_margin)
                    for segment in segments[:-1]
                )
            ):
                errors.append(f"rendered edge enters target before its terminal approach: {edge_id} / {target}")
        for node_id, node_box in blockers.items():
            if node_id in {source, target} or pair_key(edge_id, node_id) in allowed_edge_node:
                continue
            if node_id in hierarchy_polygons:
                intersects = any(
                    segment_intersects_polygon(start, end, hierarchy_polygons[node_id])
                    for start, end in segments
                )
            else:
                intersects = any(segment_intersects_box(start, end, node_box) for start, end in segments)
            if intersects:
                errors.append(f"rendered edge crosses unrelated node: {edge_id} / {node_id}")
        for label_id, label_box in region_labels.items():
            if pair_key(edge_id, label_id) in allowed_edge_text:
                continue
            if any(segment_intersects_box(start, end, label_box) for start, end in segments):
                errors.append(f"rendered edge crosses region-title text: {edge_id} / {label_id}")
        for label_id, label_box in edge_labels.items():
            if label_id == edge_id or pair_key(edge_id, label_id) in allowed_edge_text:
                continue
            if any(
                segment_intersects_box(
                    start, end, label_box.grown(minimum_edge_label_route_clearance), margin=0.0
                )
                for start, end in segments
            ):
                errors.append(
                    f"rendered edge crosses or crowds unrelated edge label: "
                    f"{edge_id} / {label_id}"
                )
        for label_id in sorted(text_only):
            label_box = labeled.get(label_id)
            if not label_box or pair_key(edge_id, label_id) in allowed_edge_text:
                continue
            if any(segment_intersects_box(start, end, label_box) for start, end in segments):
                warnings.append(f"rendered edge crosses annotation text: {edge_id} / {label_id}")
        own_label = item.label_box
        if own_label:
            if edge_id not in allowed_label_distances and segments and not any(
                segment_intersects_box(start, end, own_label.grown(maximum_label_distance), margin=0.0)
                for start, end in segments
            ):
                errors.append(
                    f"rendered edge label is detached from its route by more than "
                    f"{maximum_label_distance:g}px: {edge_id}"
                )
            if any(boxes_intersect(own_label, arrow_box) for arrow_box in item.arrow_boxes):
                if edge_id not in allowed_arrow_overlap:
                    errors.append(f"rendered edge label overlaps its arrowhead: {edge_id}")
            elif any(boxes_intersect(own_label, arrow_box, clearance) for arrow_box in item.arrow_boxes):
                warnings.append(f"rendered edge label is within {clearance:g}px of its arrowhead: {edge_id}")
            if edge_id not in allowed_bends:
                label_covers_bend = False
                for index, point in enumerate(item.route_points[1:-1], start=1):
                    before = item.route_points[index - 1]
                    after = item.route_points[index + 1]
                    incoming_vertical = math.isclose(before[0], point[0], abs_tol=0.75)
                    outgoing_vertical = math.isclose(point[0], after[0], abs_tol=0.75)
                    incoming_horizontal = math.isclose(before[1], point[1], abs_tol=0.75)
                    outgoing_horizontal = math.isclose(point[1], after[1], abs_tol=0.75)
                    actual_bend = (
                        incoming_vertical and outgoing_horizontal
                    ) or (
                        incoming_horizontal and outgoing_vertical
                    )
                    if actual_bend and point_in_box(point, own_label, margin=1.5):
                        label_covers_bend = True
                        break
                if label_covers_bend:
                    errors.append(f"rendered edge label contains a route bend: {edge_id}")
            hosting_segments: list[tuple[float, float]] = []
            for start, end in straight_runs(item.route_points):
                if not segment_intersects_box(start, end, own_label, margin=0.0):
                    continue
                if math.isclose(start[0], end[0], abs_tol=0.75):
                    low, high = sorted((start[1], end[1]))
                    before = max(0.0, own_label.y - low)
                    after = max(0.0, high - own_label.bottom)
                    hosting_segments.append((before, after))
                elif math.isclose(start[1], end[1], abs_tol=0.75):
                    low, high = sorted((start[0], end[0]))
                    before = max(0.0, own_label.x - low)
                    after = max(0.0, high - own_label.right)
                    hosting_segments.append((before, after))
            if len(hosting_segments) == 1:
                before, after = hosting_segments[0]
                if min(before, after) + 1e-6 < minimum_visible_label_flank:
                    errors.append(
                        f"rendered edge label leaves an unreadably short visible flank: "
                        f"{edge_id} ({before:g}px, {after:g}px; "
                        f"minimum={minimum_visible_label_flank:g}px)"
                    )

    # Clearance without intersection is useful for review but is not a deterministic failure.
    for edge_id, edge_box in edge_labels.items():
        for node_id, node_box in blockers.items():
            if boxes_intersect(edge_box, node_box, clearance) and not boxes_intersect(edge_box, node_box):
                warnings.append(f"rendered {edge_id} label is within {clearance:g}px of node: {node_id}")

    errors = sorted(set(errors))
    warnings = sorted(set(warnings))
    status = "FAIL" if errors else "WARN" if warnings else "PASS"
    print(f"rendered SVG audit: {status}")
    print(f"page '{page_name}': {len(rendered)} rendered cell groups, {len(labeled)} labels")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
