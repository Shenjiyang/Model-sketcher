#!/usr/bin/env python3
"""Plan deterministic branch-aware geometry, with optional incremental preservation."""

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
from plan_layout_elk import layout_problem, problem_from_region


NODE_H = 64.0
CHAR_W = 9.5
MIN_NODE_W = 128.0
PAD_X = 38.0
REGION_PAD = 42.0
TITLE_H = 44.0
ITEM_GAP = 170.0
LANE_GAP = 86.0
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


def _detail_grid(region: dict, owned: list[str], nodes: dict, edges: dict, sizes: dict) -> tuple[dict, float, float]:
    """Assign DAG depth bottom-to-top and declared sequences to horizontal lanes."""
    lane_candidates: dict[str, list[int]] = defaultdict(list)
    for lane_index, sequence in enumerate(region.get("operator_sequences", [])):
        for node_id in sequence["nodes"]:
            lane_candidates[node_id].append(lane_index)
    lane = {node_id: min(lane_candidates.get(node_id, [0])) for node_id in owned}
    successors: dict[str, list[str]] = {item: [] for item in owned}
    indegree = {item: 0 for item in owned}
    owned_set = set(owned)
    for edge in edges.values():
        source, target = edge["source"], edge["target"]
        if source in owned_set and target in owned_set:
            successors[source].append(target)
            indegree[target] += 1
    queue = deque(sorted((item for item in owned if indegree[item] == 0), key=lambda item: (nodes[item].get("order", 0), item)))
    depth = {item: 0 for item in owned}
    visited: list[str] = []
    while queue:
        source = queue.popleft()
        visited.append(source)
        for target in sorted(successors[source], key=lambda item: (nodes[item].get("order", 0), item)):
            depth[target] = max(depth[target], depth[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(visited) != len(owned):
        depth = {item: index for index, item in enumerate(owned)}

    depths, lanes = sorted(set(depth.values())), sorted(set(lane.values()))
    lane_width = {column: max(sizes[item][0] for item in owned if lane[item] == column) for column in lanes}
    depth_height = {row: max(sizes[item][1] for item in owned if depth[item] == row) for row in depths}
    lane_x: dict[int, float] = {}
    cursor = 0.0
    for column in lanes:
        lane_x[column] = cursor
        cursor += lane_width[column] + LANE_GAP
    inner_w = cursor - LANE_GAP if lanes else MIN_NODE_W
    depth_y: dict[int, float] = {}
    cursor = 0.0
    for row in reversed(depths):
        depth_y[row] = cursor
        cursor += depth_height[row] + ITEM_GAP
    inner_h = cursor - ITEM_GAP if depths else NODE_H
    offsets = {
        item: {
            "x": lane_x[lane[item]] + (lane_width[lane[item]] - sizes[item][0]) / 2,
            "y": depth_y[depth[item]] + (depth_height[depth[item]] - sizes[item][1]) / 2,
        }
        for item in owned
    }
    return offsets, inner_w, inner_h


def _elk_detail_grid(data: dict, region_id: str, sizes: dict) -> tuple[dict, float, float, dict]:
    problem = problem_from_region(data, region_id, sizes)
    result = layout_problem(problem, Path(__file__).with_name("elk_runner.cjs"), "node")
    boxes = result["nodes"]
    content = [*boxes.values(), *result.get("edge_label_boxes", {}).values()]
    content.extend({"x": x, "y": y, "w": 0, "h": 0}
                   for route in result["edges"].values() for x, y in route["waypoints"])
    min_x = min(box["x"] for box in content)
    min_y = min(box["y"] for box in content)
    offsets = {
        node_id: {"x": box["x"] - min_x, "y": box["y"] - min_y}
        for node_id, box in boxes.items()
    }
    inner_w = max(box["x"] + box["w"] for box in content) - min_x
    inner_h = max(box["y"] + box["h"] for box in content) - min_y
    return offsets, inner_w, inner_h, result


def _port_xy(box: dict, port: dict) -> tuple[float, float]:
    side, position = port["side"], port["position"]
    if side == "east":
        return box["x"] + box["w"], box["y"] + box["h"] * position
    if side == "west":
        return box["x"], box["y"] + box["h"] * position
    if side == "north":
        return box["x"] + box["w"] * position, box["y"]
    return box["x"] + box["w"] * position, box["y"] + box["h"]


def _route_edges(edges: dict, boxes: dict) -> dict:
    choices: dict[str, tuple[str, str]] = {}
    for edge_id, edge in sorted(edges.items()):
        source, target = boxes[edge["source"]], boxes[edge["target"]]
        source_cy, target_cy = source["y"] + source["h"] / 2, target["y"] + target["h"] / 2
        if target["x"] >= source["x"] + source["w"] + 20:
            if target_cy > source_cy + NODE_H:
                choices[edge_id] = ("south", "west")
            elif target_cy < source_cy - NODE_H:
                choices[edge_id] = ("east", "south")
            else:
                choices[edge_id] = ("east", "west")
        elif target["y"] >= source["y"] + source["h"] + 20:
            choices[edge_id] = ("south", "north")
        else:
            choices[edge_id] = ("north", "south")

    source_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    target_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for edge_id, edge in edges.items():
        source_side, target_side = choices[edge_id]
        source_groups[(edge["source"], source_side)].append(edge_id)
        target_groups[(edge["target"], target_side)].append(edge_id)
    source_ports: dict[str, dict] = {}
    target_ports: dict[str, dict] = {}
    for (_, side), ids in source_groups.items():
        for index, edge_id in enumerate(sorted(ids)):
            source_ports[edge_id] = {"side": side, "position": round((index + 1) / (len(ids) + 1), 4)}
    for (_, side), ids in target_groups.items():
        for index, edge_id in enumerate(sorted(ids)):
            target_ports[edge_id] = {"side": side, "position": round((index + 1) / (len(ids) + 1), 4)}

    routes: dict[str, dict] = {}
    for edge_id, edge in sorted(edges.items()):
        source, target = boxes[edge["source"]], boxes[edge["target"]]
        source_port, target_port = source_ports[edge_id], target_ports[edge_id]
        sx, sy = _port_xy(source, source_port)
        tx, ty = _port_xy(target, target_port)
        source_side, target_side = source_port["side"], target_port["side"]
        if source_side == "east" and target_side == "west":
            if math.isclose(sy, ty, abs_tol=1.0):
                points = []
            else:
                rank = sorted(source_groups[(edge["source"], source_side)]).index(edge_id)
                mid = min(tx - 24.0, sx + 28.0 + 12.0 * rank)
                points = [[round(mid, 2), round(sy, 2)], [round(mid, 2), round(ty, 2)]]
        elif source_side == "south" and target_side == "west":
            corridor_y = max(sy + 28.0, ty)
            points = [[round(sx, 2), round(corridor_y, 2)], [round(tx - 24.0, 2), round(corridor_y, 2)], [round(tx - 24.0, 2), round(ty, 2)]]
        elif source_side == "east" and target_side == "south":
            rank = sorted(source_groups[(edge["source"], source_side)]).index(edge_id)
            corridor_x, corridor_y = sx + 28.0 + rank * 16.0, ty + 28.0 + rank * 16.0
            points = [[round(corridor_x, 2), round(sy, 2)], [round(corridor_x, 2), round(corridor_y, 2)], [round(tx, 2), round(corridor_y, 2)]]
        else:
            mid_y = round((sy + ty) / 2, 2)
            points = [[round(sx, 2), mid_y], [round(tx, 2), mid_y]]
        routes[edge_id] = {"source_port": source_port, "target_port": target_port, "waypoints": points}
    return routes


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


def _apply_incremental(layout: dict, previous: dict | None, state: dict | None, node_regions: dict[str, str]) -> None:
    if not previous or not state:
        return
    change_set = state.get("change_set") or {}
    affected = set(change_set.get("affected_regions", layout["regions"]))
    policies = state.get("region_policies", {})
    preserved: list[str] = []
    for region_id, box in list(layout["regions"].items()):
        policy_value = policies.get(region_id, "adaptive")
        policy = policy_value.get("policy", "adaptive") if isinstance(policy_value, dict) else policy_value
        old_region = previous.get("regions", {}).get(region_id)
        if old_region is None:
            continue
        if policy == "frozen" or region_id not in affected:
            layout["regions"][region_id] = dict(old_region)
            for node_id, owner in node_regions.items():
                if owner == region_id and node_id in previous.get("nodes", {}) and node_id in layout["nodes"]:
                    layout["nodes"][node_id] = dict(previous["nodes"][node_id])
            preserved.append(region_id)
        elif policy == "preserve":
            dx, dy = old_region["x"] - box["x"], old_region["y"] - box["y"]
            layout["regions"][region_id]["x"], layout["regions"][region_id]["y"] = old_region["x"], old_region["y"]
            for node_id, owner in node_regions.items():
                if owner == region_id and node_id in layout["nodes"]:
                    layout["nodes"][node_id]["x"] += dx
                    layout["nodes"][node_id]["y"] += dy
    for section in ("regions", "nodes"):
        for item_id, override in state.get("layout_overrides", {}).get(section, {}).items():
            if item_id in layout[section] and isinstance(override, dict):
                layout[section][item_id] = _merge_fields(layout[section][item_id], override)
    layout["incremental"] = {"mode": change_set.get("mode", "unspecified"), "preserved_regions": sorted(preserved)}


def plan(
    data: dict,
    architecture_sha256: str,
    previous_layout: dict | None = None,
    state: dict | None = None,
    defer_hierarchy_arrows: bool = False,
    layout_engine: str = "native",
) -> dict:
    if layout_engine not in {"native", "elk", "elk-compound"}:
        raise ValueError(f"unknown layout engine {layout_engine!r}")
    data = project_active_view(data)
    needs_compound = any(
        edge.get('kind') != 'expand' and (
            data['nodes'][edge['source']]['region'] != data['nodes'][edge['target']]['region']
            or not data['regions'][data['nodes'][edge['source']]['region']].get('operator_sequences')
        ) for edge in data.get('edges', {}).values()
    )
    if layout_engine == 'elk-compound' or (layout_engine == 'elk' and needs_compound):
        from compound_layout import plan_compound
        return plan_compound(data, architecture_sha256, state, defer_hierarchy_arrows, previous_layout)
    regions, nodes, edges = data["regions"], data["nodes"], data.get("edges", {})
    children: dict[str | None, list[str]] = {None: []}
    for region_id, region in regions.items():
        children.setdefault(region.get("parent"), []).append(region_id)
        children.setdefault(region_id, [])
    for ids in children.values():
        ids.sort(key=lambda item: (regions[item].get("order", 0), item))
    direct_nodes: dict[str, list[str]] = {item: [] for item in regions}
    for node_id, node in nodes.items():
        direct_nodes[node["region"]].append(node_id)
    for ids in direct_nodes.values():
        ids.sort(key=lambda item: (nodes[item].get("order", 0), item))

    ordinary_font = data.get("project", {}).get("typography", {}).get("ordinary_node_font", 18)
    region_pad = max(REGION_PAD, float(ordinary_font) * 2.0)
    node_sizes = {item: node_size(node, ordinary_font) for item, node in nodes.items()}
    sizes: dict[str, tuple[float, float]] = {}
    grids: dict[str, dict] = {}
    grid_extents: dict[str, tuple[float, float]] = {}
    node_extents: dict[str, tuple[float, float]] = {}
    elk_results: dict[str, dict] = {}
    region_titles: dict[str, dict] = {}
    title_font = data.get('project', {}).get('typography', {}).get('region_title_font', 20)

    def grouped_extent(items: list[tuple[float, float]], direction: str) -> tuple[float, float]:
        if not items:
            return 0.0, 0.0
        if direction == "row":
            return sum(item[0] for item in items) + ITEM_GAP * (len(items) - 1), max(item[1] for item in items)
        return max(item[0] for item in items), sum(item[1] for item in items) + ITEM_GAP * (len(items) - 1)

    def measure(region_id: str) -> tuple[float, float]:
        child_sizes = [measure(child) for child in children[region_id]]
        region = regions[region_id]
        if region.get("operator_sequences") and direct_nodes[region_id]:
            if layout_engine == "elk":
                offsets, inner_w, inner_h, elk_results[region_id] = _elk_detail_grid(
                    data, region_id, node_sizes
                )
            else:
                offsets, inner_w, inner_h = _detail_grid(
                    region, direct_nodes[region_id], nodes, edges, node_sizes
                )
            grids[region_id], grid_extents[region_id] = offsets, (inner_w, inner_h)
        else:
            inner_w, inner_h = grouped_extent(
                [node_sizes[item] for item in direct_nodes[region_id]], "column"
            )
            node_extents[region_id] = (inner_w, inner_h)
        child_w, child_h = grouped_extent(child_sizes, region.get("child_direction", "row"))
        if child_sizes:
            inner_w = max(inner_w, child_w)
            inner_h = inner_h + (REGION_GAP if direct_nodes[region_id] else 0.0) + child_h
        if not direct_nodes[region_id] and not child_sizes:
            inner_w, inner_h = MIN_NODE_W, NODE_H
        width = inner_w + region_pad * 2
        region_titles[region_id] = region_title_layout(region['label'], width, title_font)
        sizes[region_id] = (width, inner_h + region_pad * 2 + region_titles[region_id]['header_height'])
        return sizes[region_id]

    for root in children[None]:
        measure(root)
    region_boxes: dict[str, dict] = {}
    node_boxes: dict[str, dict] = {}

    def place(region_id: str, x: float, y: float) -> None:
        width, height = sizes[region_id]
        region_boxes[region_id] = {"x": x, "y": y, "w": width, "h": height}
        origin_x, origin_y = x + region_pad, y + region_pad + region_titles[region_id]['header_height']
        if region_id in grids:
            for node_id, offset in grids[region_id].items():
                width_n, height_n = node_sizes[node_id]
                node_boxes[node_id] = {"x": origin_x + offset["x"], "y": origin_y + offset["y"], "w": width_n, "h": height_n}
            node_height = grid_extents[region_id][1]
        else:
            cursor_y = origin_y
            for node_id in direct_nodes[region_id]:
                width_n, height_n = node_sizes[node_id]
                node_boxes[node_id] = {"x": origin_x, "y": cursor_y, "w": width_n, "h": height_n}
                cursor_y += height_n + ITEM_GAP
            node_height = node_extents.get(region_id, (0.0, 0.0))[1]

        child_x = origin_x
        child_y = origin_y + node_height + (REGION_GAP if direct_nodes[region_id] and children[region_id] else 0.0)
        child_direction = regions[region_id].get("child_direction", "row")
        for child in children[region_id]:
            place(child, child_x, child_y)
            if child_direction == "row":
                child_x += sizes[child][0] + ITEM_GAP
            else:
                child_y += sizes[child][1] + ITEM_GAP

    root_y = CANVAS_PAD
    for root in children[None]:
        place(root, CANVAS_PAD, root_y)
        root_y += sizes[root][1] + REGION_GAP

    layout = {
        "schema_version": 3,
        "architecture_sha256": architecture_sha256,
        **({"semantic_view": data["project"]["semantic_view"]}
           if data.get("project", {}).get("semantic_view") else {}),
        "canvas": {},
        "regions": region_boxes,
        "region_titles": region_titles,
        "nodes": node_boxes,
        "edges": {},
        "hierarchy_arrows": {},
        "hierarchy_attachments": {},
    }
    auto_place_expansion_regions(data, layout)
    _apply_incremental(layout, previous_layout, state, {item: node["region"] for item, node in nodes.items()})
    ordinary_edges = {edge_id: edge for edge_id, edge in edges.items() if edge.get("kind") != "expand"}
    layout["edges"] = _route_edges(ordinary_edges, layout["nodes"]) if layout_engine == 'native' else {}
    if layout_engine == "elk":
        for region_id, result in elk_results.items():
            if not result["edges"]:
                continue
            translations = {
                (
                    round(layout["nodes"][node_id]["x"] - result["nodes"][node_id]["x"], 6),
                    round(layout["nodes"][node_id]["y"] - result["nodes"][node_id]["y"], 6),
                )
                for node_id in result["nodes"]
            }
            if len(translations) != 1:
                raise ValueError(
                    f"ELK region {region_id} was deformed by per-node incremental overrides; "
                    "reflow the region or remove those overrides"
                )
            dx, dy = next(iter(translations))
            for edge_id, route in result["edges"].items():
                translated = deepcopy(route)
                translated["waypoints"] = [
                    [round(x + dx, 2), round(y + dy, 2)]
                    for x, y in route["waypoints"]
                ]
                layout["edges"][edge_id] = translated
        if set(layout['edges']) != set(ordinary_edges):
            raise ValueError('ELK coverage incomplete; refusing native routing fallback')
    if state:
        for edge_id, override in state.get("layout_overrides", {}).get("edges", {}).items():
            if edge_id in layout["edges"] and isinstance(override, dict):
                layout["edges"][edge_id] = _merge_fields(layout["edges"][edge_id], override)
    if not defer_hierarchy_arrows:
        layout["hierarchy_arrows"] = plan_hierarchy_arrows(data, layout)
        apply_hierarchy_arrow_overrides(layout, state)
    max_right = max([box["x"] + box["w"] for box in layout["regions"].values()] + [800.0])
    max_bottom = max([box["y"] + box["h"] for box in layout["regions"].values()] + [600.0])
    layout["canvas"] = {"width": math.ceil(max_right + CANVAS_PAD), "height": math.ceil(max_bottom + CANVAS_PAD)}
    if layout_engine == "elk":
        versions = {result["engine"]["elkjsVersion"] for result in elk_results.values()}
        if len(versions) != 1:
            raise ValueError(f"ELK regions reported inconsistent engine versions: {sorted(versions)}")
        layout["layout_engine"] = {
            "name": "hybrid-elk-layered",
            "elkjs_version": next(iter(versions)),
            "elk_region_ids": sorted(elk_results),
            "macro_engine": "model-sketcher-native",
            "elk_edge_ids": sorted(layout['edges']),
            "native_routed_edge_ids": [],
            "region_candidate_selection": {
                region_id: result["engine"].get("candidate_selection", {})
                for region_id, result in elk_results.items()
            },
        }
    from junction_routes import normalize_junctions
    return normalize_junctions(data, layout)


def main() -> int:
    from semantic_gate import add_gate_arguments, cli_gate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--previous-layout", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--layout-engine", choices=("native", "elk", "elk-compound"), default="native")
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
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
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
