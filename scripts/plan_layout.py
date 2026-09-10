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
HIERARCHY_SIDES = ("north", "east", "west", "south")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        x = (low + high - width) / 2
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
    y = (low + high - height) / 2
    if side == "west":
        return {"x": child["x"] + child["w"], "y": y, "w": parent["x"] - child["x"] - child["w"], "h": height}
    return {"x": parent["x"] + parent["w"], "y": y, "w": child["x"] - parent["x"] - parent["w"], "h": height}


def _resolved_attachment(data: dict, edge: dict, side: str, mode_override: str | None = None) -> dict:
    declared = edge.get("visual_attachment") or {}
    if mode_override == "target-signpost":
        source_region = data["nodes"][edge["source"]]["region"]
        owner = declared.get("region") or _root_region(source_region, data["regions"])
        source_label = str(data["nodes"][edge["source"]].get("label", edge["source"])).replace("\\n", "\n").splitlines()[0]
        anchor_label = declared.get("anchor_label") or source_label
        label = str(edge.get("label", ""))
        return {
            "mode": "target-signpost", "id": owner, "side": side,
            "anchor_label": anchor_label,
            "display_label": label if anchor_label.casefold() in label.casefold() else f"{anchor_label} -> {label}",
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
    source_label = str(data["nodes"][edge["source"]].get("label", edge["source"])).replace("\\n", "\n").splitlines()[0]
    label = str(edge.get("label", ""))
    return {
        "mode": "owner-region-boundary",
        "id": owner,
        "side": side,
        "anchor_label": source_label,
        "display_label": label if source_label.casefold() in label.casefold() else f"{source_label} -> {label}",
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
                        score = (0 if side == preferred else 1, area, side_index, alignment_index)
                        choices.append((score, side, x, y, corridor))
                if not choices:
                    if declared.get("mode") == "parent-node":
                        raise ValueError(
                            f"expand relation {edge_id} has no collision-free macro slot for its "
                            f"explicit parent-node attachment; rejected={dict(rejected)}"
                        )
                    placed_boxes = [layout["regions"][item] for item in placed]
                    bounds = {
                        "left": min(box["x"] for box in placed_boxes),
                        "right": max(box["x"] + box["w"] for box in placed_boxes),
                        "top": min(box["y"] for box in placed_boxes),
                        "bottom": max(box["y"] + box["h"] for box in placed_boxes),
                    }
                    signpost_choices: list[tuple[tuple, str, float, float, dict]] = []
                    for side_index, side in enumerate(HIERARCHY_SIDES):
                        if side in {"north", "south"}:
                            x = parent_box["x"] + (parent_box["w"] - child_box["w"]) / 2
                            y = (
                                bounds["top"] - EXPANSION_GAP - child_box["h"]
                                if side == "north" else bounds["bottom"] + EXPANSION_GAP
                            )
                        else:
                            x = (
                                bounds["left"] - EXPANSION_GAP - child_box["w"]
                                if side == "west" else bounds["right"] + EXPANSION_GAP
                            )
                            y = parent_box["y"] + (parent_box["h"] - child_box["h"]) / 2
                        candidate = {**child_box, "x": x, "y": y}
                        if side == "north":
                            signpost = {"x": x + (child_box["w"] - HIERARCHY_ARROW_THICKNESS) / 2, "y": y + child_box["h"], "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
                        elif side == "south":
                            signpost = {"x": x + (child_box["w"] - HIERARCHY_ARROW_THICKNESS) / 2, "y": y - EXPANSION_GAP, "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
                        elif side == "west":
                            signpost = {"x": x + child_box["w"], "y": y + (child_box["h"] - HIERARCHY_ARROW_THICKNESS) / 2, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
                        else:
                            signpost = {"x": x - EXPANSION_GAP, "y": y + (child_box["h"] - HIERARCHY_ARROW_THICKNESS) / 2, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
                        xs = [box["x"] for box in placed_boxes] + [candidate["x"]]
                        ys = [box["y"] for box in placed_boxes] + [candidate["y"]]
                        rights = [box["x"] + box["w"] for box in placed_boxes] + [candidate["x"] + candidate["w"]]
                        bottoms = [box["y"] + box["h"] for box in placed_boxes] + [candidate["y"] + candidate["h"]]
                        area = (max(rights) - min(xs)) * (max(bottoms) - min(ys))
                        score = (0 if side == preferred else 1, area, side_index)
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
    if mode in {"owner-region-boundary", "target-signpost"}:
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
        preferred_side = attachment.get("side")
        if attachment_mode == "target-signpost":
            if preferred_side == "north":
                box = {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) / 2, "y": child["y"] + child["h"], "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
            elif preferred_side == "south":
                box = {"x": child["x"] + (child["w"] - HIERARCHY_ARROW_THICKNESS) / 2, "y": child["y"] - EXPANSION_GAP, "w": HIERARCHY_ARROW_THICKNESS, "h": EXPANSION_GAP}
            elif preferred_side == "west":
                box = {"x": child["x"] + child["w"], "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) / 2, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
            elif preferred_side == "east":
                box = {"x": child["x"] - EXPANSION_GAP, "y": child["y"] + (child["h"] - HIERARCHY_ARROW_THICKNESS) / 2, "w": EXPANSION_GAP, "h": HIERARCHY_ARROW_THICKNESS}
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
            x = (low + high - thickness) / 2
            up_gap = parent["y"] - (child["y"] + child["h"])
            down_gap = child["y"] - (parent["y"] + parent["h"])
            if up_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((up_gap, "north", {"x": x, "y": child["y"] + child["h"], "w": thickness, "h": up_gap}))
            if down_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((down_gap, "south", {"x": x, "y": parent["y"] + parent["h"], "w": thickness, "h": down_gap}))
        if vertical_overlap:
            low, high = vertical_overlap
            thickness = min(HIERARCHY_ARROW_THICKNESS, high - low)
            y = (low + high - thickness) / 2
            left_gap = parent["x"] - (child["x"] + child["w"])
            right_gap = child["x"] - (parent["x"] + parent["w"])
            if left_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((left_gap, "west", {"x": child["x"] + child["w"], "y": y, "w": left_gap, "h": thickness}))
            if right_gap >= MIN_HIERARCHY_ARROW_LENGTH:
                candidates.append((right_gap, "east", {"x": parent["x"] + parent["w"], "y": y, "w": right_gap, "h": thickness}))

        if not candidates:
            raise ValueError(
                f"expand relation {edge_id} has no straight hierarchy-arrow corridor from "
                f"{attachment_mode}:{attachment_id} to region:{child_region_id}; "
                "reflow the regions or change the declared attachment side before compiling"
            )
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
    return arrows


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
            "use global ELK (elk-compound)"
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
    parser.add_argument("--layout-engine", choices=("elk", "elk-compound"), default="elk-compound")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
