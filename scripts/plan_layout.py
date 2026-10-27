#!/usr/bin/env python3
"""Plan global ELK geometry with validated precision and hierarchy refinement."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import unicodedata
from copy import deepcopy
from collections import defaultdict, deque
from pathlib import Path

from hierarchy_arrow_geometry import single_arrow_cell_area
from typography import resolve_typography, wrapped_label_ink
from validate_architecture_ir import load, validate
from view_projection import project_active_view


REGION_PAD = 42.0
REGION_GAP = 90.0
CANVAS_PAD = 40.0
HIERARCHY_ARROW_THICKNESS = 96.0
MIN_HIERARCHY_ARROW_THICKNESS = 48.0
MIN_HIERARCHY_ARROW_LENGTH = 48.0
MAX_HIERARCHY_ARROW_ASPECT_RATIO = 6.0
EXPANSION_GAP = 120.0
EXPANSION_REGION_GUTTER = 72.0
# A target signpost stands in the gap on the far side of its child. That reads
# as "the named parent expands into this child" only when some visible frame
# backs the tail; in open whitespace the same arrow reads as detached. When no
# other box sits within this distance of the signpost, the planner anchors the
# arrow at the owner instead (`source-signpost`).
SIGNPOST_GROUNDING_GAP = EXPANSION_REGION_GUTTER
HIERARCHY_SIDES = ("north", "east", "west", "south")
# Minimum arrow-edge to child-boundary distance along the corridor axis. A
# cross-section centered in a thin overlap band otherwise hugs the child's
# corner, which reads as "this arrow belongs to whatever sits there".
HIERARCHY_CORNER_MARGIN = 24.0
# Upper bound on hierarchy-label ink area over the visible singleArrow polygon
# when the label is painted on the arrow; above this the text swallows the
# shaft/head silhouette and the label moves beside the shaft instead.
HIERARCHY_LABEL_MAX_OCCLUSION = 0.45
HIERARCHY_LABEL_GAP = 12.0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic_anchor_label(node: dict, fallback: str = "") -> str:
    """Return the one-line module name a hierarchy arrow must carry.

    A Level-0 summary box lists its components on further lines, so only the
    primary first line identifies the module that owns the expansion.
    """
    lines = str(node.get("label", fallback)).replace("\\n", "\n").splitlines()
    return lines[0].strip() if lines and lines[0].strip() else fallback


def hierarchy_display_label(anchor_label: str, edge_label: str) -> str:
    """Compose the visible arrow text without repeating the anchor."""
    if not anchor_label:
        return edge_label
    if anchor_label.casefold() in edge_label.casefold():
        return edge_label
    if edge_label.casefold() in anchor_label.casefold():
        # "Vision Block x27" already names the "Vision Block" child.
        return anchor_label
    return f"{anchor_label} -> {edge_label}"


def _source_signpost_label(edge_label: str, anchor_label: str, child_title: str) -> str:
    """Name the target detail in an arrow whose tail sits on the owner."""
    if not child_title:
        return edge_label or anchor_label
    if anchor_label and anchor_label.casefold() in edge_label.casefold():
        start = edge_label.casefold().index(anchor_label.casefold())
        return edge_label[:start] + child_title + edge_label[start + len(anchor_label):]
    if child_title.casefold() in edge_label.casefold():
        return edge_label
    return f"{edge_label} -> {child_title}" if edge_label else child_title


def node_size(node: dict, font_size: float = 18.0) -> tuple[float, float]:
    """Estimate unwrapped label bounds in font units, including glyph padding."""
    font_size = float(font_size)
    if not math.isfinite(font_size) or font_size <= 0:
        raise ValueError("ordinary node font must be finite and positive")
    if node.get("kind") == "junction":
        diameter = round(font_size * 0.45, 2)
        return diameter, diameter
    lines = str(node.get("label", "")).replace("\\n", "\n").splitlines() or [""]

    def advance(char: str) -> float:
        if unicodedata.combining(char):
            return 0.0
        if unicodedata.east_asian_width(char) in {"W", "F"}:
            return 1.0
        if char in "ilI.,:;!|' `":
            return 0.3
        if char in "MW@%":
            return 0.95
        return 0.68 if char.isupper() else 0.58

    text_width = max(sum(advance(char) for char in line) for line in lines) * font_size
    width = max(3.0 * font_size, text_width + 1.8 * font_size)
    height = max(2.4 * font_size, len(lines) * 1.3 * font_size + font_size)
    if node.get("kind") in {"state", "cache"}:
        # Draw.io's fixed-size parallelogram reserves up to 20px on each end.
        width += 2.0 * max(20.0, font_size * 0.8)
    return round(width, 2), round(height, 2)


def region_title_layout(label: str, width: float, font_size: float = 20.0) -> dict:
    """Wrap the title to its content-derived region width, never widen the region."""
    font_size = float(font_size)
    if not math.isfinite(font_size) or font_size <= 0 or not math.isfinite(width) or width <= 32:
        raise ValueError("region title requires finite positive font and usable width")
    available = width - 32.0

    def measured(text: str) -> float:
        # Bold titles need extra advance beyond the regular-node estimate.
        return max(0.0, node_size({'label': text}, font_size)[0] - 1.8 * font_size) * 1.1

    lines = []
    for paragraph in str(label).replace('\\n', '\n').split('\n'):
        line = ''
        for word in paragraph.split():
            candidate = f'{line} {word}' if line else word
            if line and measured(candidate) > available:
                lines.append(line)
                line = ''
            if measured(word) <= available:
                line = f'{line} {word}' if line else word
                continue
            # Even a long identifier must wrap rather than resize execution content.
            for char in word:
                if line and measured(line + char) > available:
                    lines.append(line)
                    line = ''
                line += char
        lines.append(line)
    return {'text': '\n'.join(lines), 'line_count': len(lines),
            'font_size': font_size, 'available_width': round(available, 2),
            'header_height': round(8.0 + 1.3 * font_size * len(lines) + 12.0, 2)}




def _interval_overlap(first_lo: float, first_hi: float, second_lo: float, second_hi: float) -> tuple[float, float] | None:
    low, high = max(first_lo, second_lo), min(first_hi, second_hi)
    return (low, high) if high - low >= MIN_HIERARCHY_ARROW_THICKNESS else None


def _cross_center(
    low: float,
    high: float,
    thickness: float,
    child_low: float,
    child_high: float,
    margin: float = HIERARCHY_CORNER_MARGIN,
) -> float:
    """Cross-section center inside the overlap band, kept off the child's corner.

    Band centering alone hugs the child boundary when the parent/child overlap
    is a thin sliver at the child's edge. Prefer the band center, but keep at
    least `margin` of child boundary to each side of the arrow when the band
    allows; otherwise pull as far toward the child's center as the band
    permits so the arrow still reads as entering the child, not grazing it.
    """
    band_center = (low + high) / 2
    inset_lo = max(low + thickness / 2, child_low + margin + thickness / 2)
    inset_hi = min(high - thickness / 2, child_high - margin - thickness / 2)
    if inset_lo <= inset_hi:
        return min(max(band_center, inset_lo), inset_hi)
    child_center = (child_low + child_high) / 2
    return min(max(child_center, low + thickness / 2), high - thickness / 2)


def _root_region(region_id: str, regions: dict) -> str:
    while regions[region_id].get("parent") is not None:
        region_id = regions[region_id]["parent"]
    return region_id


def _move_region_tree(data: dict, layout: dict, root_id: str, x: float, y: float) -> None:
    """Move one top-level region without changing its compact internal geometry."""
    current = layout["regions"][root_id]
    dx, dy = x - current["x"], y - current["y"]
    regions = data["regions"]
    moved_regions = {
        region_id for region_id in regions
        if _root_region(region_id, regions) == root_id
    }
    for eid, route in layout.get('edges', {}).items():
        edge = data['edges'][eid]
        source_moved = data['nodes'][edge['source']]['region'] in moved_regions
        target_moved = data['nodes'][edge['target']]['region'] in moved_regions
        if source_moved != target_moved:
            raise ValueError('hierarchy translation cannot alter cross-component ordinary routes')
        if source_moved:
            route['waypoints'] = [[px + dx, py + dy] for px, py in route['waypoints']]
    for region_id in moved_regions:
        layout["regions"][region_id]["x"] += dx
        layout["regions"][region_id]["y"] += dy
    for node_id, node in data["nodes"].items():
        if node["region"] in moved_regions:
            layout["nodes"][node_id]["x"] += dx
            layout["nodes"][node_id]["y"] += dy


def _boxes_collide(first: dict, second: dict, gutter: float = 0.0) -> bool:
    return not (
        first["x"] + first["w"] + gutter <= second["x"]
        or second["x"] + second["w"] + gutter <= first["x"]
        or first["y"] + first["h"] + gutter <= second["y"]
        or second["y"] + second["h"] + gutter <= first["y"]
    )


def _side_positions(parent: dict, child: dict, side: str) -> list[tuple[float, float]]:
    """Enumerate centered and edge-aligned straight-corridor child slots."""
    if side in {"north", "south"}:
        low = parent["x"] - child["w"] + MIN_HIERARCHY_ARROW_THICKNESS
        high = parent["x"] + parent["w"] - MIN_HIERARCHY_ARROW_THICKNESS
        span = max(0.0, high - low)
        xs = [low + span * fraction for fraction in (0.5, 0.0, 1.0, 0.25, 0.75, 0.125, 0.375, 0.625, 0.875)]
        y = (
            parent["y"] - EXPANSION_GAP - child["h"]
            if side == "north"
            else parent["y"] + parent["h"] + EXPANSION_GAP
        )
        return [(x, y) for x in dict.fromkeys(round(value, 2) for value in xs)]
    low = parent["y"] - child["h"] + MIN_HIERARCHY_ARROW_THICKNESS
    high = parent["y"] + parent["h"] - MIN_HIERARCHY_ARROW_THICKNESS
    span = max(0.0, high - low)
    ys = [low + span * fraction for fraction in (0.5, 0.0, 1.0, 0.25, 0.75, 0.125, 0.375, 0.625, 0.875)]
    x = (
        parent["x"] - EXPANSION_GAP - child["w"]
        if side == "west"
        else parent["x"] + parent["w"] + EXPANSION_GAP
    )
    return [(x, y) for y in dict.fromkeys(round(value, 2) for value in ys)]


def _corridor_box(parent: dict, child: dict, side: str) -> dict | None:
    if side in {"north", "south"}:
        overlap = _interval_overlap(
            parent["x"], parent["x"] + parent["w"],
            child["x"], child["x"] + child["w"],
        )
        if overlap is None:
            return None
        low, high = overlap
        width = min(HIERARCHY_ARROW_THICKNESS, high - low)
        x = _cross_center(low, high, width, child["x"], child["x"] + child["w"]) - width / 2
        if side == "north":
            return {"x": x, "y": child["y"] + child["h"], "w": width, "h": parent["y"] - child["y"] - child["h"]}
        return {"x": x, "y": parent["y"] + parent["h"], "w": width, "h": child["y"] - parent["y"] - parent["h"]}
    overlap = _interval_overlap(
        parent["y"], parent["y"] + parent["h"],
        child["y"], child["y"] + child["h"],
    )
    if overlap is None:
        return None
    low, high = overlap
    height = min(HIERARCHY_ARROW_THICKNESS, high - low)
    y = _cross_center(low, high, height, child["y"], child["y"] + child["h"]) - height / 2
    if side == "west":
        return {"x": child["x"] + child["w"], "y": y, "w": parent["x"] - child["x"] - child["w"], "h": height}
    return {"x": parent["x"] + parent["w"], "y": y, "w": child["x"] - parent["x"] - parent["w"], "h": height}


def _signpost_box(child: dict, side: str) -> dict:
    """Short arrow in the gap on the parent-facing side of a placed child."""
    if side == "north":
        return {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) / 2, "y": child["y"] + child["h"], "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
    if side == "south":
        return {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) / 2, "y": child["y"] - EXPANSION_GAP, "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
    if side == "west":
        return {"x": child["x"] + child["w"], "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) / 2, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
    return {"x": child["x"] - EXPANSION_GAP, "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) / 2, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}


def _source_signpost_box(owner: dict, direction: str, position: float) -> dict:
    """Block arrow leaving the owning region toward the child's bearing.

    The tail sits on the owner boundary, so the arrow always has a visible
    source frame behind it. The tip stops one expansion gap away instead of
    pretending to reach a child that is thousands of pixels off.
    """
    if direction in {"north", "south"}:
        y = owner["y"] - EXPANSION_GAP if direction == "north" else owner["y"] + owner["h"]
        return {"x": position, "y": y, "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
    x = owner["x"] - EXPANSION_GAP if direction == "west" else owner["x"] + owner["w"]
    return {"x": x, "y": position, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}


def _signpost_axis_positions(owner: dict, node: dict, direction: str) -> list[float]:
    """Cross-axis slots on the owner edge, aligned with the parent block first."""
    span, along = ("w", "x") if direction in {"north", "south"} else ("h", "y")
    thickness = HIERARCHY_ARROW_THICKNESS
    low = owner[along]
    high = owner[along] + owner[span] - thickness
    if high < low:
        return [round(low, 2)]
    aligned = node[along] + node[span] / 2 - thickness / 2
    centred = owner[along] + owner[span] / 2 - thickness / 2
    steps = max(1, int((high - low) // 24))
    sweep = [low + (high - low) * index / steps for index in range(steps + 1)]
    sweep.sort(key=lambda value: abs(value - aligned))
    candidates = [value for value in [aligned, centred, *sweep] if low - 1e-6 <= value <= high + 1e-6]
    return list(dict.fromkeys(round(value, 2) for value in candidates))


def _backs_the_tail(box: dict, direction: str, other: dict, gap: float) -> bool:
    """True when `other` sits behind the tail of `box` on its cross-axis span.

    Content on the tip side, including the child's own nodes, does not count:
    it is what the arrow points at, not what the arrow comes from.
    """
    if direction == "north":
        behind = other["y"] - (box["y"] + box["h"])
        overlap = min(box["x"] + box["w"], other["x"] + other["w"]) - max(box["x"], other["x"])
    elif direction == "south":
        behind = box["y"] - (other["y"] + other["h"])
        overlap = min(box["x"] + box["w"], other["x"] + other["w"]) - max(box["x"], other["x"])
    elif direction == "east":
        behind = box["x"] - (other["x"] + other["w"])
        overlap = min(box["y"] + box["h"], other["y"] + other["h"]) - max(box["y"], other["y"])
    else:
        behind = other["x"] - (box["x"] + box["w"])
        overlap = min(box["y"] + box["h"], other["y"] + other["h"]) - max(box["y"], other["y"])
    return -1e-6 <= behind <= gap and overlap > 0


def _signpost_grounded(box: dict, direction: str, child_region_id: str,
                       region_boxes: dict, node_boxes: dict) -> bool:
    """True when visible geometry backs a target signpost's tail side.

    Without that backing the arrow stands in open whitespace: the reader can
    see neither its origin nor anything it belongs to.
    """
    boxes = [box_ for region_id, box_ in region_boxes.items() if region_id != child_region_id]
    boxes += list(node_boxes.values())
    return any(_backs_the_tail(box, direction, other, SIGNPOST_GROUNDING_GAP) for other in boxes)


def _source_signpost_slot(owner: dict, node: dict, child: dict, directions: list[str],
                          region_boxes: dict, node_boxes: dict,
                          ignore: set[str]) -> tuple[str, dict] | None:
    """First clear owner-edge slot in bearing order, or None."""
    gap = 8.0
    for direction in directions:
        for position in _signpost_axis_positions(owner, node, direction):
            box = _source_signpost_box(owner, direction, position)
            if any(region_id not in ignore and _boxes_collide(box, other, gap)
                   for region_id, other in region_boxes.items()):
                continue
            if any(_boxes_collide(box, other, gap) for other in node_boxes.values()):
                continue
            return direction, box
    return None


def _signpost_slots(side: str, parent: dict, source: dict, child: dict,
                    placed: list[dict], anchor: dict) -> list[tuple[float, float]]:
    """Child positions on one side of the owner, nearest first, for a signpost.

    Every slot stays beyond the owner on that side so the signpost still points
    from the owner toward the child. Slots also align with the semantic parent
    block itself, not only its owner region, so a module in the middle of a
    column can expand beside its own row. The last slots clear everything
    already placed, so a legal choice always exists.
    """
    anchor_x = anchor["x"] + anchor["w"] / 2 - child["w"] / 2
    anchor_y = anchor["y"] + anchor["h"] / 2 - child["h"] / 2
    gap, gutter = EXPANSION_GAP + 8.0, EXPANSION_REGION_GUTTER
    if side in {"north", "south"}:
        if side == "north":
            limit = source["y"] - EXPANSION_GAP - child["h"]
            beyond = [box["y"] - child["h"] - gap for box in placed if box["y"] - child["h"] - gap <= limit]
            outer = min(box["y"] for box in placed) - EXPANSION_GAP - child["h"]
        else:
            limit = source["y"] + source["h"] + EXPANSION_GAP
            beyond = [box["y"] + box["h"] + gap for box in placed if box["y"] + box["h"] + gap >= limit]
            outer = max(box["y"] + box["h"] for box in placed) + EXPANSION_GAP
        ys = [limit, *beyond, outer]
        xs = [anchor_x, *(x for x, _ in _side_positions(parent, child, side))]
        xs += [value for box in placed for value in (box["x"] + box["w"] + gutter, box["x"] - child["w"] - gutter)]
        return list(dict.fromkeys((round(x, 2), round(y, 2)) for y in ys for x in xs))
    if side == "west":
        limit = source["x"] - EXPANSION_GAP - child["w"]
        beyond = [box["x"] - child["w"] - gap for box in placed if box["x"] - child["w"] - gap <= limit]
        outer = min(box["x"] for box in placed) - EXPANSION_GAP - child["w"]
    else:
        limit = source["x"] + source["w"] + EXPANSION_GAP
        beyond = [box["x"] + box["w"] + gap for box in placed if box["x"] + box["w"] + gap >= limit]
        outer = max(box["x"] + box["w"] for box in placed) + EXPANSION_GAP
    xs = [limit, *beyond, outer]
    ys = [anchor_y, anchor["y"], anchor["y"] + anchor["h"] - child["h"],
          *(y for _, y in _side_positions(parent, child, side))]
    ys += [value for box in placed for value in (box["y"] + box["h"] + gutter, box["y"] - child["h"] - gutter)]
    return list(dict.fromkeys((round(x, 2), round(y, 2)) for x in xs for y in ys))


def _resolved_attachment(data: dict, edge: dict, side: str, mode_override: str | None = None) -> dict:
    declared = edge.get("visual_attachment") or {}
    if mode_override == "target-signpost":
        source_region = data["nodes"][edge["source"]]["region"]
        owner = declared.get("region") or _root_region(source_region, data["regions"])
        anchor_label = declared.get("anchor_label") or semantic_anchor_label(
            data["nodes"][edge["source"]], edge["source"]
        )
        label = str(edge.get("label", ""))
        return {
            "mode": "target-signpost", "id": owner, "side": side,
            "anchor_label": anchor_label,
            "display_label": hierarchy_display_label(anchor_label, label),
            "automatic": True,
        }
    if declared:
        return {
            "mode": declared.get("mode", "parent-node"),
            "id": declared.get("region", edge["source"]),
            "side": side,
            **({"anchor_label": declared["anchor_label"]} if declared.get("anchor_label") else {}),
            **({"display_label": declared["anchor_label"]} if declared.get("anchor_label") else {}),
        }
    source_region = data["nodes"][edge["source"]]["region"]
    owner = _root_region(source_region, data["regions"])
    anchor_label = semantic_anchor_label(data["nodes"][edge["source"]], edge["source"])
    label = str(edge.get("label", ""))
    return {
        "mode": "owner-region-boundary",
        "id": owner,
        "side": side,
        "anchor_label": anchor_label,
        "display_label": hierarchy_display_label(anchor_label, label),
        "automatic": True,
    }


def auto_place_expansion_regions(data: dict, layout: dict) -> None:
    """Place top-level hierarchy children around their semantic owners."""
    if data.get("project", {}).get("output_view") not in {"hierarchy-master", "paired"}:
        return
    if data.get("project", {}).get("auto_place_hierarchy_expansions", True) is False:
        return

    regions = data["regions"]
    # Only disconnected execution components may be translated for hollow arrows.
    # Connected global geometry belongs to ELK or the validated precision pass.
    if any(edge.get('kind') != 'expand' and
           _root_region(data['nodes'][edge['source']]['region'], regions) !=
           _root_region(data['nodes'][edge['target']]['region'], regions)
           for edge in data.get('edges', {}).values()):
        return
    top_regions = [region_id for region_id, region in regions.items() if region.get("parent") is None]
    expand_edges = [
        (edge_id, edge) for edge_id, edge in sorted(data.get("edges", {}).items())
        if edge.get("kind") == "expand"
    ]
    links: list[tuple[str, dict, str, str]] = []
    for edge_id, edge in expand_edges:
        source_root = _root_region(data["nodes"][edge["source"]]["region"], regions)
        child_region = data["nodes"][edge["target"]]["region"]
        child_root = _root_region(child_region, regions)
        if source_root != child_root and child_region == child_root:
            links.append((edge_id, edge, source_root, child_root))
    if not links:
        return

    outgoing: dict[str, list[tuple[str, dict, str]]] = defaultdict(list)
    incoming: dict[str, int] = defaultdict(int)
    for edge_id, edge, source_root, child_root in links:
        outgoing[source_root].append((edge_id, edge, child_root))
        incoming[child_root] += 1

    roots = sorted(
        (region_id for region_id in top_regions if incoming[region_id] == 0),
        key=lambda item: (regions[item].get("level", 99), regions[item].get("order", 0), item),
    )
    placed: set[str] = set()
    corridor_boxes: list[dict] = []
    attachments: dict[str, dict] = {}
    component_x = 0.0
    rivals = sorted({edge["source"] for _, edge in expand_edges})

    def occupied(candidate: dict, ignore: set[str]) -> bool:
        return any(
            root_id not in ignore
            and _boxes_collide(candidate, layout["regions"][root_id], EXPANSION_REGION_GUTTER)
            for root_id in placed
        )

    for component_root in roots:
        if component_root in placed:
            continue
        _move_region_tree(data, layout, component_root, component_x, 0.0)
        placed.add(component_root)
        queue = deque([component_root])
        while queue:
            source_root = queue.popleft()
            for edge_id, edge, child_root in outgoing.get(source_root, []):
                if child_root in placed:
                    continue
                declared = edge.get("visual_attachment") or {}
                if declared.get("mode") == "parent-node":
                    attachment_id = edge["source"]
                    parent_box = layout["nodes"][attachment_id]
                else:
                    attachment_id = declared.get("region") or source_root
                    parent_box = layout["regions"][attachment_id]
                child_box = layout["regions"][child_root]
                source_box = layout["regions"][source_root]
                preferred = declared.get("side") or edge.get("direction")
                preferred = {"up": "north", "down": "south", "left": "west", "right": "east"}.get(preferred, preferred)
                choices: list[tuple[tuple, str, float, float, dict]] = []
                rejected: dict[str, int] = defaultdict(int)
                for side_index, side in enumerate(HIERARCHY_SIDES):
                    positions = _side_positions(parent_box, child_box, side)
                    if side == "north":
                        positions = [(x, min(y, source_box["y"] - EXPANSION_GAP - child_box["h"])) for x, y in positions]
                    elif side == "south":
                        positions = [(x, max(y, source_box["y"] + source_box["h"] + EXPANSION_GAP)) for x, y in positions]
                    elif side == "west":
                        positions = [(min(x, source_box["x"] - EXPANSION_GAP - child_box["w"]), y) for x, y in positions]
                    else:
                        positions = [(max(x, source_box["x"] + source_box["w"] + EXPANSION_GAP), y) for x, y in positions]
                    for obstacle_id in placed:
                        if obstacle_id == source_root:
                            continue
                        obstacle = layout["regions"][obstacle_id]
                        if side in {"north", "south"}:
                            positions.extend([
                                (obstacle["x"] + obstacle["w"] + EXPANSION_REGION_GUTTER, positions[0][1]),
                                (obstacle["x"] - child_box["w"] - EXPANSION_REGION_GUTTER, positions[0][1]),
                            ])
                        else:
                            positions.extend([
                                (positions[0][0], obstacle["y"] + obstacle["h"] + EXPANSION_REGION_GUTTER),
                                (positions[0][0], obstacle["y"] - child_box["h"] - EXPANSION_REGION_GUTTER),
                            ])
                    positions = list(dict.fromkeys((round(x, 2), round(y, 2)) for x, y in positions))
                    for alignment_index, (x, y) in enumerate(positions):
                        candidate = {**child_box, "x": x, "y": y}
                        corridor = _corridor_box(parent_box, candidate, side)
                        if corridor is None or min(corridor["w"], corridor["h"]) < MIN_HIERARCHY_ARROW_THICKNESS:
                            rejected["corridor"] += 1
                            continue
                        corridor_length = max(corridor["w"], corridor["h"])
                        corridor_thickness = min(corridor["w"], corridor["h"])
                        if corridor_length / corridor_thickness > MAX_HIERARCHY_ARROW_ASPECT_RATIO:
                            rejected["cable-like-corridor"] += 1
                            continue
                        if occupied(candidate, set()):
                            rejected["region-collision"] += 1
                            continue
                        if any(_boxes_collide(corridor, box, 8.0) for box in corridor_boxes):
                            rejected["arrow-collision"] += 1
                            continue
                        if any(
                            root_id != source_root and _boxes_collide(corridor, layout["regions"][root_id], 0.0)
                            for root_id in placed
                        ):
                            rejected["arrow-region-collision"] += 1
                            continue
                        xs = [layout["regions"][item]["x"] for item in placed] + [candidate["x"]]
                        ys = [layout["regions"][item]["y"] for item in placed] + [candidate["y"]]
                        rights = [layout["regions"][item]["x"] + layout["regions"][item]["w"] for item in placed] + [candidate["x"] + candidate["w"]]
                        bottoms = [layout["regions"][item]["y"] + layout["regions"][item]["h"] for item in placed] + [candidate["y"] + candidate["h"]]
                        area = (max(rights) - min(xs)) * (max(bottoms) - min(ys))
                        if side in {"north", "south"}:
                            inset = min(
                                corridor["x"] - candidate["x"],
                                candidate["x"] + candidate["w"] - (corridor["x"] + corridor["w"]),
                            )
                        else:
                            inset = min(
                                corridor["y"] - candidate["y"],
                                candidate["y"] + candidate["h"] - (corridor["y"] + corridor["h"]),
                            )
                        score = (
                            0 if side == preferred else 1,
                            0 if inset >= HIERARCHY_CORNER_MARGIN else 1,
                            area, side_index, alignment_index,
                        )
                        choices.append((score, side, x, y, corridor))
                if not choices:
                    if declared.get("mode") == "parent-node":
                        raise ValueError(
                            f"expand relation {edge_id} has no collision-free macro slot for its "
                            f"explicit parent-node attachment; rejected={dict(rejected)}"
                        )
                    placed_boxes = [layout["regions"][item] for item in placed]
                    semantic_parent = layout["nodes"][edge["source"]]
                    signpost_choices: list[tuple[tuple, str, float, float, dict]] = []
                    for side_index, side in enumerate(HIERARCHY_SIDES):
                        for x, y in _signpost_slots(side, parent_box, source_box, child_box, placed_boxes,
                                                    semantic_parent):
                            candidate = {**child_box, "x": x, "y": y}
                            if occupied(candidate, set()):
                                continue
                            signpost = _signpost_box(candidate, side)
                            if any(_boxes_collide(signpost, box, 0.0) for box in placed_boxes):
                                continue
                            if any(_boxes_collide(signpost, box, 8.0) for box in corridor_boxes):
                                continue
                            # A reader traces a signpost back by eye: prefer slots with no
                            # region between it and the parent, then the nearest slot.
                            crossed = sum(
                                1 for box in placed_boxes
                                if not _contains(box, semantic_parent)
                                and _segment_box_length(_center(semantic_parent), _center(signpost), box) > 1.0
                            )
                            parent_gap = _box_gap(semantic_parent, signpost)
                            claimed = sum(
                                1 for other in rivals
                                if other != edge["source"]
                                and _root_region(data["nodes"][other]["region"], regions) in placed
                                and _box_gap(layout["nodes"][other], signpost) < parent_gap
                            )
                            score = (crossed, claimed, round(parent_gap, 1),
                                     0 if side == preferred else 1, side_index)
                            signpost_choices.append((score, side, x, y, signpost))
                    _, side, x, y, corridor = min(signpost_choices, key=lambda item: item[0])
                    _move_region_tree(data, layout, child_root, x, y)
                    placed.add(child_root)
                    corridor_boxes.append(corridor)
                    attachments[edge_id] = _resolved_attachment(data, edge, side, "target-signpost")
                    queue.append(child_root)
                    continue
                _, side, x, y, corridor = min(choices, key=lambda item: item[0])
                _move_region_tree(data, layout, child_root, x, y)
                placed.add(child_root)
                corridor_boxes.append(corridor)
                attachments[edge_id] = _resolved_attachment(data, edge, side)
                queue.append(child_root)

        component_right = max(layout["regions"][item]["x"] + layout["regions"][item]["w"] for item in placed)
        component_x = component_right + REGION_GAP * 2

    for region_id in top_regions:
        if region_id in placed:
            continue
        _move_region_tree(data, layout, region_id, component_x, 0.0)
        placed.add(region_id)
        component_x += layout["regions"][region_id]["w"] + REGION_GAP * 2

    min_x = min(layout["regions"][region_id]["x"] for region_id in top_regions)
    min_y = min(layout["regions"][region_id]["y"] for region_id in top_regions)
    for region_id in top_regions:
        _move_region_tree(
            data, layout, region_id,
            layout["regions"][region_id]["x"] - min_x + CANVAS_PAD,
            layout["regions"][region_id]["y"] - min_y + CANVAS_PAD,
        )
    layout["hierarchy_attachments"] = attachments


def hierarchy_attachment(edge_id: str, edge: dict, layout: dict) -> tuple[str, str, dict, dict]:
    """Resolve the physical arrow tail while preserving the semantic source node."""
    resolved = layout.get("hierarchy_attachments", {}).get(edge_id)
    attachment = resolved or edge.get("visual_attachment") or {}
    mode = attachment.get("mode", "parent-node")
    if mode in {"owner-region-boundary", "target-signpost", "source-signpost"}:
        attachment_id = attachment.get("id", attachment.get("region"))
        return mode, attachment_id, layout["regions"][attachment_id], attachment
    attachment_id = edge["source"]
    return "parent-node", attachment_id, layout["nodes"][attachment_id], attachment


def plan_hierarchy_arrows(data: dict, layout: dict) -> dict:
    """Derive straight, boundary-attached block arrows from final node/region boxes."""
    arrows: dict[str, dict] = {}
    node_boxes, region_boxes = layout.get("nodes", {}), layout.get("regions", {})
    for edge_id, edge in sorted(data.get("edges", {}).items()):
        if edge.get("kind") != "expand":
            continue
        source_id, target_id = edge["source"], edge["target"]
        child_region_id = data["nodes"][target_id]["region"]
        attachment_mode, attachment_id, parent, attachment = hierarchy_attachment(edge_id, edge, layout)
        child = region_boxes[child_region_id]
        # Signposts are centred first; _spread_signposts() then shares one child
        # edge only among the arrows that actually land on that edge.
        fraction = 0.5
        preferred_side = attachment.get("side")
        if attachment_mode == "target-signpost":
            if preferred_side == "north":
                box = {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) * fraction, "y": child["y"] + child["h"], "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
            elif preferred_side == "south":
                box = {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) * fraction, "y": child["y"] - EXPANSION_GAP, "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
            elif preferred_side == "west":
                box = {"x": child["x"] + child["w"], "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) * fraction, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
            elif preferred_side == "east":
                box = {"x": child["x"] - EXPANSION_GAP, "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) * fraction, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
            else:
                raise ValueError(f"expand relation {edge_id} target signpost lacks a valid direction")
            arrows[edge_id] = {
                **{key: round(value, 2) for key, value in box.items()},
                "direction": preferred_side, "parent": source_id,
                "attachment_mode": attachment_mode, "attachment_id": attachment_id,
                "child_region": child_region_id,
                "anchor_label": attachment["anchor_label"],
                "display_label": attachment["display_label"],
            }
            continue
        candidates: list[tuple[float, str, dict]] = []

        horizontal_overlap = _interval_overlap(parent["x"], parent["x"] + parent["w"], child["x"], child["x"] + child["w"])
        vertical_overlap = _interval_overlap(parent["y"], parent["y"] + parent["h"], child["y"], child["y"] + child["h"])
        if horizontal_overlap:
            low, high = horizontal_overlap
            thickness = min(HIERARCHY_ARROW_THICKNESS, high - low)
            x = _cross_center(low, high, thickness, child["x"], child["x"] + child["w"]) - thickness / 2
            up_gap = parent["y"] - (child["y"] + child["h"])
            down_gap = child["y"] - (parent["y"] + parent["h"])
            if up_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((up_gap, "north", {"x": x, "y": child["y"] + child["h"], "w": thickness, "h": up_gap}))
            if down_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((down_gap, "south", {"x": x, "y": parent["y"] + parent["h"], "w": thickness, "h": down_gap}))
        if vertical_overlap:
            low, high = vertical_overlap
            thickness = min(HIERARCHY_ARROW_THICKNESS, high - low)
            y = _cross_center(low, high, thickness, child["y"], child["y"] + child["h"]) - thickness / 2
            left_gap = parent["x"] - (child["x"] + child["w"])
            right_gap = child["x"] - (parent["x"] + parent["w"])
            if left_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((left_gap, "west", {"x": child["x"] + child["w"], "y": y, "w": left_gap, "h": thickness}))
            if right_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((right_gap, "east", {"x": parent["x"] + parent["w"], "y": y, "w": right_gap, "h": thickness}))

        # A legal overlap alone is not enough: a distant corridor becomes a cable
        # after compilation and must use the child-adjacent signpost fallback.
        candidates = [item for item in candidates
                      if max(item[2]["w"], item[2]["h"]) / min(item[2]["w"], item[2]["h"])
                      <= MAX_HIERARCHY_ARROW_ASPECT_RATIO]

        if not candidates:
            # No straight corridor. Do not fail the planner; keep the semantic
            # parent and place a registered signpost. Compile still rejects a
            # signpost that misses its anchor or covers another region.
            dx = (child["x"] + child["w"] / 2) - (parent["x"] + parent["w"] / 2)
            dy = (child["y"] + child["h"] / 2) - (parent["y"] + parent["h"] / 2)
            direction = ("east" if dx >= 0 else "west") if abs(dx) >= abs(dy) else ("south" if dy >= 0 else "north")
            if direction == "north":
                box = {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) * fraction, "y": child["y"] + child["h"], "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
            elif direction == "south":
                box = {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) * fraction, "y": child["y"] - EXPANSION_GAP, "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
            elif direction == "west":
                box = {"x": child["x"] + child["w"], "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) * fraction, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
            else:
                box = {"x": child["x"] - EXPANSION_GAP, "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) * fraction, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
            owner = attachment.get("region") or attachment.get("id") or data["nodes"][source_id]["region"]
            anchor = attachment.get("anchor_label") or semantic_anchor_label(
                data["nodes"][source_id], source_id
            )
            if not _signpost_grounded(box, direction, child_region_id, region_boxes, node_boxes):
                # The child-side gap is open canvas, so a target signpost would
                # float with nothing at its tail. Anchor the arrow at the owner
                # region instead and name the child detail it expands into;
                # only fall back to the target side when every owner edge is
                # obstructed.
                owner_box = region_boxes.get(owner)
                node_box = node_boxes.get(source_id)
                if owner_box is not None and node_box is not None:
                    opposite = {"north": "south", "south": "north", "east": "west", "west": "east"}
                    vertical = "north" if dy < 0 else "south"
                    horizontal = "east" if dx >= 0 else "west"
                    bearing = ([vertical, horizontal] if abs(dy) >= abs(dx) else [horizontal, vertical])
                    directions = [bearing[0], bearing[1], opposite[bearing[1]], opposite[bearing[0]]]
                    slot = _source_signpost_slot(
                        owner_box, node_box, child, directions,
                        region_boxes, node_boxes, {owner, child_region_id},
                    )
                    if slot is not None:
                        direction, box = slot
                        child_title = str(data["regions"].get(child_region_id, {}).get("label", ""))
                        arrows[edge_id] = {
                            **{key: round(value, 2) for key, value in box.items()},
                            "direction": direction, "parent": source_id,
                            "attachment_mode": "source-signpost", "attachment_id": owner,
                            "child_region": child_region_id, "anchor_label": anchor,
                            # The tail is attached to the owner, so the visible text
                            # must name where the arrow goes: swap the anchor name
                            # for the child's own title, keeping the edge's verb.
                            "display_label": _source_signpost_label(str(edge["label"]), anchor, child_title),
                        }
                        continue
            arrows[edge_id] = {**{key: round(value, 2) for key, value in box.items()}, "direction": direction,
                "parent": source_id, "attachment_mode": "target-signpost", "attachment_id": owner,
                "child_region": child_region_id, "anchor_label": anchor,
                "display_label": hierarchy_display_label(anchor, str(edge["label"]))}
            continue
        _, direction, box = min(
            candidates,
            key=lambda item: (0 if item[1] == preferred_side else 1, item[0], item[1]),
        )
        arrows[edge_id] = {
            **{key: round(value, 2) for key, value in box.items()},
            "direction": direction,
            "parent": source_id,
            "attachment_mode": attachment_mode,
            "attachment_id": attachment_id,
            "child_region": child_region_id,
            **({"anchor_label": attachment["anchor_label"]} if attachment.get("anchor_label") else {}),
            **({"display_label": attachment["display_label"]} if attachment.get("display_label") else {}),
        }
    _spread_signposts(arrows, region_boxes)
    _separate_signposts(arrows, region_boxes)
    finalize_hierarchy_labels(data, layout, arrows)
    return arrows


def _spread_signposts(arrows: dict, region_boxes: dict) -> None:
    """Share one anchor edge among the signposts that land on it.

    A direct corridor arrow onto a different side of the same anchor does not
    compete for a slot on this edge, so it must not shift this signpost away
    from the anchor's centre. Target signposts share their child's edge;
    source signposts share the owner region's edge.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for edge_id in sorted(arrows):
        arrow = arrows[edge_id]
        mode = arrow.get("attachment_mode")
        if mode == "target-signpost":
            key = (arrow["child_region"], arrow["direction"])
        elif mode == "source-signpost":
            key = (arrow["attachment_id"], arrow["direction"])
        else:
            continue
        groups.setdefault(key, []).append(edge_id)
    for (anchor_region, direction), edge_ids in groups.items():
        if len(edge_ids) < 2:
            continue
        anchor = region_boxes[anchor_region]
        for index, edge_id in enumerate(edge_ids):
            arrow = arrows[edge_id]
            fraction = 0.25 + 0.5 * index / (len(edge_ids) - 1)
            if direction in {"north", "south"}:
                arrow["x"] = round(anchor["x"] + (anchor["w"] - arrow["w"]) * fraction, 2)
            else:
                arrow["y"] = round(anchor["y"] + (anchor["h"] - arrow["h"]) * fraction, 2)


def _separate_signposts(arrows: dict, region_boxes: dict) -> None:
    """Slide a signpost along its anchor edge off any other hierarchy arrow.

    Direct arrows are fixed by their corridor, but a signpost only has to touch
    its anchor, so it can move along that edge. A child shared by two parents is
    where a signpost otherwise lands on the other parent's arrow.
    """
    gap = 8.0
    for edge_id in sorted(arrows):
        arrow = arrows[edge_id]
        mode = arrow.get("attachment_mode")
        if mode == "target-signpost":
            anchor = region_boxes[arrow["child_region"]]
            excluded = {arrow["child_region"]}
        elif mode == "source-signpost":
            anchor = region_boxes[arrow["attachment_id"]]
            excluded = {arrow["attachment_id"], arrow["child_region"]}
        else:
            continue
        others = [box for other_id, box in arrows.items() if other_id != edge_id]
        if not any(_boxes_collide(arrow, box, gap) for box in others):
            continue
        along = "x" if arrow["direction"] in {"north", "south"} else "y"
        span = "w" if along == "x" else "h"
        low, high = anchor[along], anchor[along] + anchor[span] - arrow[span]
        if high < low:
            continue
        steps = max(1, int((high - low) // 12))
        positions = sorted((low + (high - low) * index / steps for index in range(steps + 1)),
                           key=lambda value: abs(value - arrow[along]))
        for value in positions:
            candidate = {**arrow, along: round(value, 2)}
            if any(_boxes_collide(candidate, box, gap) for box in others):
                continue
            if any(region_id not in excluded and _boxes_collide(candidate, box, 0.0)
                   for region_id, box in region_boxes.items()):
                continue
            arrow[along] = candidate[along]
            break


def _attachment_band(arrow: dict, layout: dict) -> tuple[float, float] | None:
    """Overlap band constraining a direct arrow's cross-section growth."""
    if arrow.get("attachment_mode") in {"target-signpost", "source-signpost"}:
        return None
    boxes = layout["nodes"] if arrow.get("attachment_mode") == "parent-node" else layout["regions"]
    parent = boxes.get(arrow.get("attachment_id"))
    child = layout.get("regions", {}).get(arrow.get("child_region"))
    if parent is None or child is None:
        return None
    if arrow["direction"] in {"north", "south"}:
        return _interval_overlap(parent["x"], parent["x"] + parent["w"], child["x"], child["x"] + child["w"])
    return _interval_overlap(parent["y"], parent["y"] + parent["h"], child["y"], child["y"] + child["h"])


def _recenter_cross_section(arrow: dict, band: tuple[float, float] | None, layout: dict) -> None:
    if band is None:
        return
    child = layout["regions"][arrow["child_region"]]
    axis, span = ("x", "w") if arrow["direction"] in {"north", "south"} else ("y", "h")
    center = _cross_center(band[0], band[1], arrow[span], child[axis], child[axis] + child[span])
    arrow[axis] = round(center - arrow[span] / 2, 2)


def _narrow_for_corner(arrow: dict, band: tuple[float, float] | None, layout: dict) -> None:
    """Trim a label-free arrow's cross-section until the corner margin fits.

    A narrow parent/child overlap band cannot hold the default cross-section
    plus `HIERARCHY_CORNER_MARGIN` on both sides; centering alone then still
    grazes the child boundary corner. Only arrows whose label travels beside
    the shaft can give up thickness, so on-shape arrows are left untouched.
    """
    if band is None:
        return
    span = "w" if arrow["direction"] in {"north", "south"} else "h"
    available = round((band[1] - band[0]) - 2 * HIERARCHY_CORNER_MARGIN, 2)
    if available >= arrow[span] - 1e-6:
        return
    if available < MIN_HIERARCHY_ARROW_THICKNESS:
        return
    arrow[span] = available
    _recenter_cross_section(arrow, band, layout)


def _fits_on_shape(box: dict, direction: str, ink: tuple[float, float]) -> bool:
    ink_w, ink_h = ink
    if ink_w > 0.9 * box["w"] or ink_h > 0.9 * box["h"]:
        return False
    area = single_arrow_cell_area(box["w"], box["h"], direction)
    return (ink_w * ink_h) / max(area, 1.0) <= HIERARCHY_LABEL_MAX_OCCLUSION


def _place_beside(
    edge_id: str, arrow: dict, text: str, font_size: float, layout: dict,
    arrows: dict | None = None,
) -> None:
    """Move the label to the freer shaft flank as a plan-time offset.

    The offset is relative to the arrow box, so project-state corridor
    overrides keep label and arrow together. An east/west arrow crosses its
    corridor, so when the corridor is narrower than the label the label runs
    along the corridor instead: it rotates (`horizontal=0` at compile time)
    and stacks above or below the shaft inside the corridor width. Sibling
    arrows and already-placed companion cells count as obstacles, so two
    expand arrows in the same corridor cannot claim the same flank. A
    residual overlap is recorded as a finding for the author instead of
    failing layout silently.
    """
    direction = arrow["direction"]
    wrap_limit = min(max(arrow["w"], arrow["h"]) * 1.5, 320.0)
    # A flank that is narrower than the label can still hold it when the text
    # is re-wrapped shorter: try progressively tighter wraps, widest first so
    # an equally clean place never picks a needlessly thin label.
    wraps: list[float] = []
    for factor in (1.0, 0.8, 0.65, 0.5):
        wrap = max(80.0, max(24.0, wrap_limit) * factor)
        if all(abs(wrap - seen) > 1.0 for seen in wraps):
            wraps.append(wrap)
    candidates = []
    for wrap in wraps:
        ink_w, ink_h = wrapped_label_ink(text, font_size, wrap)
        box_w, box_h = ink_w + 8.0, ink_h + 8.0
        if direction in {"north", "south"}:
            for dx in (arrow["w"] + HIERARCHY_LABEL_GAP, -HIERARCHY_LABEL_GAP - box_w):
                for dy in ((arrow["h"] - box_h) / 2,
                           arrow["h"] + HIERARCHY_LABEL_GAP,
                           -HIERARCHY_LABEL_GAP - box_h):
                    candidates.append({
                        "dx": dx, "dy": dy, "rotated": False,
                        "ink": (ink_w, ink_h), "box": (box_w, box_h), "wrap": wrap,
                    })
            continue
        candidates.extend([
            {"dx": (arrow["w"] - box_w) / 2, "dy": arrow["h"] + HIERARCHY_LABEL_GAP,
             "rotated": False, "ink": (ink_w, ink_h), "box": (box_w, box_h), "wrap": wrap},
            {"dx": (arrow["w"] - box_w) / 2, "dy": -HIERARCHY_LABEL_GAP - box_h,
             "rotated": False, "ink": (ink_w, ink_h), "box": (box_w, box_h), "wrap": wrap},
        ])
        # The corridor of an east/west arrow is vertical, so a rotated label
        # is the only fit when the corridor is narrower than the wrapped ink.
        # Lines stack across the corridor once rotated.
        rot_box_w, rot_box_h = ink_h + 8.0, ink_w + 8.0
        for dy in (arrow["h"] + HIERARCHY_LABEL_GAP, -HIERARCHY_LABEL_GAP - rot_box_h):
            candidates.append({
                "dx": (arrow["w"] - rot_box_w) / 2, "dy": dy,
                "rotated": True, "ink": (ink_w, ink_h), "box": (rot_box_w, rot_box_h),
                "wrap": wrap,
            })
    if direction not in {"north", "south"}:
        # A single unwrapped line is the last resort for blocks whose wrapped
        # cross-section still would not fit the corridor.
        single_w, single_h = wrapped_label_ink(text, font_size, 1e9)
        if single_w > max(wrapped_label_ink(text, font_size, w)[0] for w in wraps) + 0.01:
            rot_box_w, rot_box_h = single_h + 8.0, single_w + 8.0
            for dy in (arrow["h"] + HIERARCHY_LABEL_GAP, -HIERARCHY_LABEL_GAP - rot_box_h):
                candidates.append({
                    "dx": (arrow["w"] - rot_box_w) / 2, "dy": dy,
                    "rotated": True, "ink": (single_w, single_h), "box": (rot_box_w, rot_box_h),
                    "wrap": 1e9,
                })
    obstacles = list(layout.get("regions", {}).values()) + list(layout.get("nodes", {}).values())
    siblings = arrows if arrows is not None else layout.get("hierarchy_arrows", {})
    for other_id, other in siblings.items():
        if other_id == edge_id:
            continue
        obstacles.append({"x": other["x"], "y": other["y"], "w": other["w"], "h": other["h"]})
        ink = other.get("label_ink")
        offset = other.get("label_offset")
        if other.get("label_placement") != "beside" or not ink or not offset:
            continue
        if other.get("label_rotated"):
            other_w, other_h = ink[1] + 8.0, ink[0] + 8.0
        else:
            other_w, other_h = ink[0] + 8.0, ink[1] + 8.0
        obstacles.append({
            "x": other["x"] + offset[0], "y": other["y"] + offset[1],
            "w": other_w, "h": other_h,
        })

    def overlap_area(candidate: dict) -> float:
        bw, bh = candidate["box"]
        box = {"x": arrow["x"] + candidate["dx"], "y": arrow["y"] + candidate["dy"], "w": bw, "h": bh}
        return sum(
            max(0.0, min(box["x"] + bw, other["x"] + other["w"]) - max(box["x"], other["x"]))
            * max(0.0, min(box["y"] + bh, other["y"] + other["h"]) - max(box["y"], other["y"]))
            for other in obstacles
        )

    best = min(enumerate(candidates), key=lambda item: (overlap_area(item[1]), item[0]))[1]
    arrow["label_placement"] = "beside"
    arrow["label_offset"] = [round(best["dx"], 2), round(best["dy"], 2)]
    arrow["label_ink"] = list(best["ink"])
    if best["rotated"]:
        arrow["label_rotated"] = True
        # The renderer rotates one text block, so the compiler needs the same
        # wrap width the ink estimate used to emit matching explicit breaks.
        arrow["label_wrap"] = round(best["wrap"], 2)
    if overlap_area(best) > 0:
        arrow["placement_warning"] = (
            f"expand relation {edge_id} beside-label overlaps other geometry; "
            "adjust the corridor or register an occlusion exception"
        )


def finalize_hierarchy_labels(data: dict, layout: dict, arrows: dict | None = None) -> None:
    """Decide each arrow's label placement after corridor geometry is final.

    The declared policy comes from project.typography.hierarchy_label_placement
    (auto | on-shape | beside). auto keeps the label on the arrow when the
    wrapped ink stays inside the occlusion budget — growing the cross-section
    within the corridor band when that rescues on-shape placement — and moves
    the label to a free shaft flank otherwise, so the arrow silhouette stays
    readable. Forced on-shape keeps the grown arrow even above the budget;
    the rendered audit then requires an explicit occlusion exception.
    """
    typography = resolve_typography(data.get("project", {}).get("typography"))
    font_size = float(typography["hierarchy_label_font"])
    policy = typography["hierarchy_label_placement"]
    arrows = layout.get("hierarchy_arrows", {}) if arrows is None else arrows
    for edge_id in sorted(arrows):
        arrow = arrows[edge_id]
        edge = data.get("edges", {}).get(edge_id, {})
        child_label = data.get("regions", {}).get(arrow.get("child_region"), {}).get("label", "")
        text = str(arrow.get("display_label") or edge.get("label") or f"expand {child_label}")
        text = text.replace("\\n", "\n")
        direction = arrow["direction"]
        band = _attachment_band(arrow, layout)
        thickness_key = "w" if direction in {"north", "south"} else "h"
        thicknesses = [arrow[thickness_key]]
        if band is not None:
            for grown in (128.0, 160.0, 192.0, 256.0):
                if grown > arrow[thickness_key] and grown - 1 <= band[1] - band[0]:
                    thicknesses.append(min(grown, band[1] - band[0]))
        chosen: float | None = None
        if policy in {"auto", "on-shape"}:
            for thickness in thicknesses:
                wrap = thickness if direction in {"north", "south"} else arrow["w"] - 2 * HIERARCHY_LABEL_GAP
                ink = wrapped_label_ink(text, font_size, max(24.0, wrap))
                if _fits_on_shape({**arrow, thickness_key: thickness}, direction, ink):
                    chosen = thickness
                    break
        if chosen is not None or policy == "on-shape":
            arrow[thickness_key] = round(chosen if chosen is not None else thicknesses[-1], 2)
            _recenter_cross_section(arrow, band, layout)
            arrow["label_placement"] = "on-shape"
            continue
        _narrow_for_corner(arrow, band, layout)
        _place_beside(edge_id, arrow, text, font_size, layout, arrows)


def hierarchy_corridor_findings(data: dict, layout: dict) -> list[str]:
    """Report direct arrows that hug the child's corner or have residual label overlap."""
    findings: list[str] = []
    regions = layout.get("regions", {})
    for edge_id, arrow in sorted(layout.get("hierarchy_arrows", {}).items()):
        if arrow.get("attachment_mode") not in {"target-signpost", "source-signpost"}:
            child = regions.get(arrow.get("child_region"))
            if child is not None:
                if arrow["direction"] in {"north", "south"}:
                    inset = min(arrow["x"] - child["x"], child["x"] + child["w"] - (arrow["x"] + arrow["w"]))
                else:
                    inset = min(arrow["y"] - child["y"], child["y"] + child["h"] - (arrow["y"] + arrow["h"]))
                if inset + 1 < HIERARCHY_CORNER_MARGIN:
                    findings.append(
                        f"{edge_id}: arrow hugs the child boundary corner "
                        f"(inset {inset:.1f}px < {HIERARCHY_CORNER_MARGIN:g}px); "
                        "widen the overlap band or move the child region"
                    )
        if arrow.get("placement_warning"):
            findings.append(arrow["placement_warning"])
    return findings


def _center(box: dict) -> tuple[float, float]:
    return box["x"] + box["w"] / 2, box["y"] + box["h"] / 2


def _contains(outer: dict, inner: dict) -> bool:
    return (outer["x"] - 1 <= inner["x"] and outer["y"] - 1 <= inner["y"]
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + 1
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + 1)


def _segment_box_length(start: tuple[float, float], end: tuple[float, float], box: dict) -> float:
    """Length of the straight segment that lies inside an axis-aligned box."""
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    low, high = 0.0, 1.0
    for delta, origin, minimum, maximum in (
        (dx, x0, box["x"], box["x"] + box["w"]),
        (dy, y0, box["y"], box["y"] + box["h"]),
    ):
        if abs(delta) < 1e-9:
            if origin < minimum or origin > maximum:
                return 0.0
            continue
        first, last = (minimum - origin) / delta, (maximum - origin) / delta
        if first > last:
            first, last = last, first
        low, high = max(low, first), min(high, last)
        if low >= high:
            return 0.0
    return (high - low) * math.hypot(dx, dy)


def _box_gap(first: dict, second: dict) -> float:
    gap_x = max(0.0, max(first["x"], second["x"]) - min(first["x"] + first["w"], second["x"] + second["w"]))
    gap_y = max(0.0, max(first["y"], second["y"]) - min(first["y"] + first["h"], second["y"] + second["h"]))
    return math.hypot(gap_x, gap_y)


def hierarchy_attribution_findings(data: dict, layout: dict) -> list[str]:
    """Report target signposts a reader would not trace back to their parent.

    A signpost is legal without touching its parent, so compile and audit pass
    it. These findings catch the two ways it still reads as orphaned: other
    regions sit between the parent and the signpost, or another expandable
    module is nearer to the signpost than the registered parent.
    """
    findings: list[str] = []
    nodes, regions = layout.get("nodes", {}), layout.get("regions", {})
    expandable = {
        edge["source"] for edge in data.get("edges", {}).values() if edge.get("kind") == "expand"
    }
    for edge_id, arrow in sorted(layout.get("hierarchy_arrows", {}).items()):
        if arrow.get("attachment_mode") != "target-signpost":
            continue
        parent_id = arrow.get("parent")
        parent = nodes.get(parent_id)
        if parent is None:
            continue
        child_id = arrow.get("child_region")
        name = arrow.get("anchor_label") or parent_id
        start, end = _center(parent), _center(arrow)
        crossed = sorted(
            region_id for region_id, box in regions.items()
            if region_id != child_id
            and not _contains(box, parent) and not _contains(box, arrow)
            and _segment_box_length(start, end, box) > 1.0
        )
        if crossed:
            findings.append(
                f"{edge_id}: signpost {name!r} is separated from its parent by regions {crossed}; "
                "move the child region beside the parent"
            )
        parent_gap = _box_gap(parent, arrow)
        nearer = sorted(
            (round(_box_gap(nodes[other], arrow), 1), other)
            for other in expandable
            if other != parent_id and other in nodes and _box_gap(nodes[other], arrow) < parent_gap
        )
        if nearer:
            gap, other = nearer[0]
            other_name = semantic_anchor_label(data["nodes"].get(other, {}), other)
            findings.append(
                f"{edge_id}: signpost {name!r} is nearer to expandable module {other_name!r} "
                f"({gap:g}px) than to its parent ({round(parent_gap, 1):g}px)"
            )
    return findings


def apply_hierarchy_arrow_overrides(layout: dict, state: dict | None) -> None:
    """Apply project-owned corridor adjustments after automatic arrow derivation."""
    if not state:
        return
    overrides = state.get("layout_overrides", {}).get("hierarchy_arrows", {})
    for edge_id, override in overrides.items():
        if edge_id in layout["hierarchy_arrows"] and isinstance(override, dict):
            layout["hierarchy_arrows"][edge_id] = _merge_fields(
                layout["hierarchy_arrows"][edge_id], override
            )


def _merge_fields(original: dict, override: dict) -> dict:
    result = dict(original)
    result.update(override)
    return result


def plan(
    data: dict,
    architecture_sha256: str,
    previous_layout: dict | None = None,
    state: dict | None = None,
    defer_hierarchy_arrows: bool = False,
    layout_engine: str = "elk-compound",
) -> dict:
    if layout_engine not in {"elk", "elk-compound"}:
        raise ValueError(
            f"unsupported layout engine {layout_engine!r}; native has been removed; "
            "use global ELK (omit the legacy engine option)"
        )
    from compound_layout import plan_compound
    return plan_compound(
        project_active_view(data), architecture_sha256, state,
        defer_hierarchy_arrows, previous_layout,
    )


def main() -> int:
    from semantic_gate import add_gate_arguments, cli_gate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--previous-layout", type=Path)
    parser.add_argument("--state", type=Path)
    # Compatibility only: both old spellings select the sole global backend.
    parser.add_argument("--layout-engine", choices=("elk", "elk-compound"), default="elk-compound", help=argparse.SUPPRESS)
    parser.add_argument(
        "--defer-hierarchy-arrows",
        action="store_true",
        help="emit provisional geometry for a project refiner; refresh arrows before compilation",
    )
    add_gate_arguments(parser, include_state=False)
    args = parser.parse_args()
    if not cli_gate(args):
        return 3
    data = load(args.architecture)
    errors = validate(data, args.architecture.parent)
    if errors:
        print("layout: FAIL; architecture IR is invalid")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    previous = json.loads(args.previous_layout.read_text(encoding="utf-8")) if args.previous_layout else None
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state and args.state.is_file() else None
    try:
        output = plan(
            data, digest(args.architecture), previous, state,
            defer_hierarchy_arrows=args.defer_hierarchy_arrows,
            layout_engine=args.layout_engine,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"layout: FAIL ({error})")
        return 1
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        f"layout: GENERATED; strict/visual audits pending ({len(output['nodes'])} nodes, {len(output['edges'])} edges, "
        f"{len(output['hierarchy_arrows'])} hierarchy arrows)"
    )
    for finding in hierarchy_attribution_findings(data, output):
        print(f"WARNING: hierarchy attribution: {finding}")
    for finding in hierarchy_corridor_findings(data, output):
        print(f"WARNING: hierarchy corridor: {finding}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
