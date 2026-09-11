#!/usr/bin/env python3
"""Run ELK Layered on a focused graph and emit Draw.io-compatible geometry.

This adapter deliberately accepts a small layout problem instead of architecture.json.
View projection remains a separate concern and can later feed this stable boundary.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
import subprocess
import tempfile
import time
from itertools import product
from copy import deepcopy
from pathlib import Path

from validate_architecture_ir import edge_display_label
from visual_edge_labels import visual_edge_label
from straight_route_refinement import refine_straight_routes
from focused_layout_quality import candidate_quality
from layout_progress import progress


VALID_DIRECTIONS = {"UP", "DOWN", "LEFT", "RIGHT"}
VALID_SIDES = {"north", "south", "east", "west"}
BOUNDARY_TOLERANCE = 1.1
NEAR_AXIS_SNAP = 12.0
ENGINE_TIMEOUT_SECONDS = 45


def _port_sort_key(item: tuple[str, int, str, str]) -> tuple:
    side, order, edge_id, role = item
    # ELK enumerates ports clockwise; our orders increase left-to-right/top-to-bottom.
    return ({"north": 0, "east": 1, "south": 2, "west": 3}[side],
            -order if side in {"south", "west"} else order, edge_id, role)


def _default_sides(direction: str) -> tuple[str, str]:
    return {
        "UP": ("north", "south"),
        "DOWN": ("south", "north"),
        "LEFT": ("west", "east"),
        "RIGHT": ("east", "west"),
    }[direction]


def load_problem(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("direction", "UP") not in VALID_DIRECTIONS:
        errors.append(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, dict) or not nodes:
        errors.append("nodes must be a non-empty object")
        nodes = {}
    if not isinstance(edges, dict):
        errors.append("edges must be an object")
        edges = {}
    for node_id, node in nodes.items():
        if node.get("port_constraints", "FIXED_ORDER") not in {"FIXED_ORDER", "FIXED_SIDE"}:
            errors.append(f"node {node_id}.port_constraints must be FIXED_ORDER or FIXED_SIDE")
        for field in ("w", "h"):
            value = node.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                errors.append(f"node {node_id}.{field} must be a positive finite number")
    for edge_id, edge in edges.items():
        if edge.get("source") not in nodes:
            errors.append(f"edge {edge_id} has unknown source {edge.get('source')!r}")
        if edge.get("target") not in nodes:
            errors.append(f"edge {edge_id} has unknown target {edge.get('target')!r}")
        if edge.get("source") == edge.get("target"):
            errors.append(f"edge {edge_id} is a self-loop; focused operator flow must expand it")
        for field in ("source_side", "target_side"):
            if field in edge and edge[field] not in VALID_SIDES:
                errors.append(f"edge {edge_id}.{field} must be one of {sorted(VALID_SIDES)}")
        for field in ("source_order", "target_order"):
            if field in edge and not isinstance(edge[field], int):
                errors.append(f"edge {edge_id}.{field} must be an integer")
        label = edge.get("label")
        if label is not None:
            if not isinstance(label, dict) or set(label) != {"text", "w", "h"}:
                errors.append(f"edge {edge_id}.label must be exactly a {{text, w, h}} object")
            else:
                if not isinstance(label["text"], str) or not label["text"].strip():
                    errors.append(f"edge {edge_id}.label.text must be a non-empty string")
                for field in ("w", "h"):
                    value = label[field]
                    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                        errors.append(f"edge {edge_id}.label.{field} must be a positive finite number")
    if errors:
        raise ValueError("invalid ELK layout problem:\n  " + "\n  ".join(errors))
    return data


def elk_graph(problem: dict) -> dict:
    spacing = problem.get("spacing", {})
    options = {
        "elk.algorithm": "layered",
        "elk.direction": problem.get("direction", "UP"),
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": str(float(spacing.get("node", 64))),
        "elk.layered.spacing.nodeNodeBetweenLayers": str(float(spacing.get("layer", 96))),
        "elk.spacing.edgeNode": str(float(spacing.get("edge_node", 28))),
        "elk.layered.spacing.edgeNodeBetweenLayers": str(float(spacing.get("edge_node", 28))),
        "elk.spacing.edgeEdge": str(float(spacing.get("edge", 18))),
        "elk.layered.spacing.edgeEdgeBetweenLayers": str(float(spacing.get("edge", 18))),
        "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
        "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
        "elk.layered.nodePlacement.bk.fixedAlignment": "BALANCED",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
        "elk.layered.mergeEdges": "false",
        "elk.layered.unnecessaryBendpoints": "true",
        "elk.padding": "[top=24,left=24,bottom=24,right=24]",
    }
    options.update({str(key): str(value) for key, value in problem.get("elk_options", {}).items()})
    default_source_side, default_target_side = _default_sides(problem.get("direction", "UP"))
    ports: dict[str, list[tuple[str, int, str, str]]] = defaultdict(list)
    for edge_id, edge in problem["edges"].items():
        ports[edge["source"]].append(
            (edge.get("source_side", default_source_side), edge.get("source_order", 0), edge_id, "source")
        )
        ports[edge["target"]].append(
            (edge.get("target_side", default_target_side), edge.get("target_order", 0), edge_id, "target")
        )
    side_names = {"north": "NORTH", "south": "SOUTH", "east": "EAST", "west": "WEST"}

    return {
        "id": problem.get("id", "focused-view"),
        "layoutOptions": options,
        "children": [
            {
                "id": node_id,
                "width": float(node["w"]),
                "height": float(node["h"]),
                "layoutOptions": {"elk.portConstraints": node.get("port_constraints", "FIXED_ORDER")},
                "ports": [
                    {
                        "id": f"{node_id}:{role}:{edge_id}",
                        "width": 0,
                        "height": 0,
                        "layoutOptions": {"elk.port.side": side_names[side]},
                    }
                    for side, _, edge_id, role in sorted(
                        ports[node_id], key=_port_sort_key
                    )
                ],
            }
            for node_id, node in problem["nodes"].items()
        ],
        "edges": [
            {
                "id": edge_id,
                "sources": [f"{edge['source']}:source:{edge_id}"],
                "targets": [f"{edge['target']}:target:{edge_id}"],
                "layoutOptions": {
                    "elk.layered.priority.direction": str(edge.get("direction_priority", 0)),
                    "elk.layered.priority.straightness": str(edge.get("straightness_priority", 0)),
                },
                **(
                    {
                        "labels": [
                            {
                                "id": f"{edge_id}:label",
                                "text": edge["label"]["text"],
                                "width": float(edge["label"]["w"]),
                                "height": float(edge["label"]["h"]),
                            }
                        ]
                    }
                    if edge.get("label")
                    else {}
                ),
            }
            for edge_id, edge in problem["edges"].items()
        ],
    }


def problem_from_region(data: dict, region_id: str, sizes: dict[str, tuple[float, float]]) -> dict:
    """Project one region's direct ordinary graph into the ELK adapter schema."""
    region = data["regions"][region_id]
    node_ids = [node_id for node_id, node in data["nodes"].items() if node["region"] == region_id]
    node_set = set(node_ids)
    edges = {
        edge_id: edge
        for edge_id, edge in data.get("edges", {}).items()
        if edge.get("kind") != "expand"
        and edge.get("source") in node_set
        and edge.get("target") in node_set
    }
    lane_candidates: dict[str, list[int]] = defaultdict(list)
    for lane_index, sequence in enumerate(region.get("operator_sequences", [])):
        for node_id in sequence.get("nodes", []):
            if node_id in node_set:
                lane_candidates[node_id].append(lane_index)
    lane = {node_id: min(lane_candidates.get(node_id, [0])) for node_id in node_ids}
    edge_font = float(data.get("project", {}).get("typography", {}).get("edge_label_font", 14))
    multi_write_state = any(
        data["nodes"][nid].get("kind") in {"state", "cache"}
        and sum(edge["target"] == nid for edge in edges.values()) >= 3
        for nid in node_ids
    )
    branched = any(
        sum(edge["source"] == node_id for edge in edges.values()) > 1
        or sum(edge["target"] == node_id for edge in edges.values()) > 1
        or data["nodes"][node_id].get("kind") in {"state", "cache"}
        for node_id in node_ids
    )
    projected_edges: dict[str, dict] = {}
    sequence_pairs = {pair for sequence in region.get("operator_sequences", [])
                      for pair in zip(sequence.get("nodes", []), sequence.get("nodes", [])[1:])}
    for edge_id, edge in edges.items():
        source, target = edge["source"], edge["target"]
        item: dict = {
            "source": source,
            "target": target,
            "source_order": lane[target],
            "target_order": lane[source],
            "direction_priority": 1000 if (source, target) in sequence_pairs else 0,
            "straightness_priority": (
                1000 if (source, target) in sequence_pairs
                and sum(other["source"] == source for other in edges.values()) == 1
                and sum(other["target"] == target for other in edges.values()) > 1
                else 10 if (source, target) in sequence_pairs else 0
            ),
        }
        source_kind = data["nodes"][source].get("kind")
        target_kind = data["nodes"][target].get("kind")
        if source_kind in {"cache", "state"} and target_kind not in {"cache", "state"}:
            item.update({"source_side": "west", "target_side": "east"})
        elif target_kind in {"cache", "state"} and source_kind not in {"cache", "state"}:
            item.update({"source_side": "east", "target_side": "west"})
        label = visual_edge_label(edge, edge_id=edge_id).strip()
        if label:
            lines = label.splitlines()
            item["label"] = {
                "text": label,
                "w": max(48.0, max(len(line) for line in lines) * edge_font * 0.58 + 12.0),
                "h": max(20.0, len(lines) * edge_font * 1.25 + 6.0),
            }
        projected_edges[edge_id] = item
    return {
        "schema_version": 1,
        "id": region_id,
        "direction": "UP",
        "operator_sequences": deepcopy(region.get("operator_sequences", [])),
        "ordinary_node_font": float(data.get("project", {}).get("typography", {}).get("ordinary_node_font", 18)),
        "edge_label_font": edge_font,
        "alignment_candidates": ["LEFTUP", "RIGHTUP", "LEFTDOWN", "RIGHTDOWN", "BALANCED"],
        "placement_candidates": ["BRANDES_KOEPF", "NETWORK_SIMPLEX"] if len(node_ids) >= 24 else ["BRANDES_KOEPF"],
        "elk_options": {
            "elk.layered.considerModelOrder.strategy": "NONE",
            "elk.layered.crossingMinimization.greedySwitch.type": "TWO_SIDED",
            "elk.layered.thoroughness": "16",
        },
        "spacing": {
            "node": 64,
            # Center labels occupy an ELK dummy layer, so this gap occurs twice.
            "layer": max(48, edge_font * 2.4) if branched else max(36, edge_font * 1.8),
            "edge_node": max(24, edge_font * 1.8),
            # Several state-write shelves need room for independent crossings.
            "edge": max(16, edge_font * (2.8 if multi_write_state else 1.1)),
        },
        "nodes": {
            # Sequence membership is not an ordering contract on shared ports.
            node_id: {"w": sizes[node_id][0], "h": sizes[node_id][1], "port_constraints": "FIXED_SIDE"}
            for node_id in node_ids
        },
        "edges": projected_edges,
    }


def _point(value: dict) -> tuple[float, float]:
    return float(value["x"]), float(value["y"])


def _port_from_point(box: dict, point: tuple[float, float], expected_side: str, edge_id: str) -> dict:
    x, y = point
    if not all(math.isfinite(value) for value in point):
        raise ValueError(f"ELK edge {edge_id} returned a non-finite endpoint {point}")
    boundary = {
        "west": box["x"],
        "east": box["x"] + box["w"],
        "north": box["y"],
        "south": box["y"] + box["h"],
    }[expected_side]
    distance = abs((x if expected_side in {"west", "east"} else y) - boundary)
    if distance > BOUNDARY_TOLERANCE:
        raise ValueError(
            f"ELK edge {edge_id} endpoint is {distance:.3f}px away from its declared "
            f"{expected_side} boundary"
        )
    position = (
        (y - box["y"]) / box["h"]
        if expected_side in {"west", "east"}
        else (x - box["x"]) / box["w"]
    )
    if not math.isfinite(position) or not 0.0 <= position <= 1.0:
        raise ValueError(
            f"ELK edge {edge_id} returned out-of-range {expected_side} port position {position}"
        )
    # Preserve enough precision that reconstructing a boundary endpoint does not
    # create a visible diagonal stub before the first orthogonal bend.
    return {"side": expected_side, "position": round(position, 6)}


def _drop_collinear(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    clean: list[tuple[float, float]] = []
    for point in points:
        if clean and math.isclose(point[0], clean[-1][0], abs_tol=0.01) and math.isclose(
            point[1], clean[-1][1], abs_tol=0.01
        ):
            continue
        clean.append(point)
        while len(clean) >= 3:
            first, middle, last = clean[-3:]
            vertical = math.isclose(first[0], middle[0], abs_tol=0.01) and math.isclose(
                middle[0], last[0], abs_tol=0.01
            )
            horizontal = math.isclose(first[1], middle[1], abs_tol=0.01) and math.isclose(
                middle[1], last[1], abs_tol=0.01
            )
            forward = ((middle[0] - first[0]) * (last[0] - middle[0])
                       + (middle[1] - first[1]) * (last[1] - middle[1])) >= 0
            if not ((vertical or horizontal) and forward):
                break
            clean.pop(-2)
    return clean


def _segment_hits_box(first: tuple[float, float], second: tuple[float, float], box: dict) -> bool:
    epsilon = 0.01
    left, right = box["x"] + epsilon, box["x"] + box["w"] - epsilon
    top, bottom = box["y"] + epsilon, box["y"] + box["h"] - epsilon
    if math.isclose(first[0], second[0], abs_tol=epsilon):
        low, high = sorted((first[1], second[1]))
        return left < first[0] < right and max(low, top) < min(high, bottom)
    if math.isclose(first[1], second[1], abs_tol=epsilon):
        low, high = sorted((first[0], second[0]))
        return top < first[1] < bottom and max(low, left) < min(high, right)
    return True


def _port_point(box: dict, port: dict) -> tuple[float, float]:
    if port["side"] == "north":
        return box["x"] + box["w"] * port["position"], box["y"]
    if port["side"] == "south":
        return box["x"] + box["w"] * port["position"], box["y"] + box["h"]
    if port["side"] == "west":
        return box["x"], box["y"] + box["h"] * port["position"]
    return box["x"] + box["w"], box["y"] + box["h"] * port["position"]


def _validate_endpoint_direction(points: list[tuple[float, float]], source_side: str,
                                 target_side: str, edge_id: str) -> None:
    normal = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
    for name, side, boundary, outside in (
        ("source", source_side, points[0], points[1]),
        ("target", target_side, points[-1], points[-2]),
    ):
        dx, dy = outside[0] - boundary[0], outside[1] - boundary[1]
        nx, ny = normal[side]
        if abs(dx * ny - dy * nx) > 0.01 or dx * nx + dy * ny <= 0:
            raise ValueError(f"ELK edge {edge_id} has non-normal or inward {name} approach")


def _snap_near_axis_route(
    points: list[tuple[float, float]],
    source_box: dict,
    target_box: dict,
    source_side: str,
    target_side: str,
    unrelated_boxes: list[dict],
) -> list[tuple[float, float]]:
    """Remove a tiny ELK dogleg when one clear straight corridor exists."""
    start, end = points[0], points[-1]
    if source_side in {"north", "south"} and target_side in {"north", "south"}:
        if abs(start[0] - end[0]) > NEAR_AXIS_SNAP:
            return points
        low = max(source_box["x"], target_box["x"])
        high = min(source_box["x"] + source_box["w"], target_box["x"] + target_box["w"])
        if low > high:
            return points
        axis = min(high, max(low, (start[0] + end[0]) / 2))
        candidate = [(axis, start[1]), (axis, end[1])]
    elif source_side in {"east", "west"} and target_side in {"east", "west"}:
        if abs(start[1] - end[1]) > NEAR_AXIS_SNAP:
            return points
        low = max(source_box["y"], target_box["y"])
        high = min(source_box["y"] + source_box["h"], target_box["y"] + target_box["h"])
        if low > high:
            return points
        axis = min(high, max(low, (start[1] + end[1]) / 2))
        candidate = [(start[0], axis), (end[0], axis)]
    else:
        return points
    if any(_segment_hits_box(candidate[0], candidate[1], box) for box in unrelated_boxes):
        return points
    return candidate


def _label_offsets(anchor, normal, label, elk_offset, obstacles, other_routes, cached_spans=None):
    """Search bounded transverse free-space boundaries, without clamping ELK."""
    axis = 0 if abs(normal[0]) > 0.5 else 1
    half = float(label["width"] if axis == 0 else label["height"]) / 2 + 8
    origin, sign = anchor[axis], normal[axis]
    candidates = {0.0, -160.0, 160.0}
    if math.isfinite(elk_offset) and abs(elk_offset) <= 160:
        candidates.add(elk_offset)
    spans = cached_spans
    if spans is None:
        spans = [(box["x"], box["x"] + box["w"]) if axis == 0
                 else (box["y"], box["y"] + box["h"]) for box in obstacles]
        spans.extend((min(a[axis], b[axis]), max(a[axis], b[axis]))
                     for route in other_routes for a, b in zip(route, route[1:]))
    for low, high in spans:
        for coordinate in (low - half - 1, high + half + 1):
            offset = (coordinate - origin) * sign
            if math.isfinite(offset) and abs(offset) <= 160:
                candidates.add(offset)
    return sorted(candidates, key=lambda value: (abs(value), value))


def _label_position(
    edge_id: str,
    points: list[tuple[float, float]],
    label: dict,
    padding: float,
    obstacles: list[dict] | None = None,
    other_routes: list[list[tuple[float, float]]] | None = None,
    minimum_flank: float = 12.0,
) -> tuple[dict, dict]:
    numeric = [float(label[key]) for key in ("x", "y", "width", "height")]
    if not all(math.isfinite(value) for value in [*numeric, padding]):
        raise ValueError(f"ELK edge {edge_id} returned a non-finite label box")
    if numeric[2] <= 0 or numeric[3] <= 0:
        raise ValueError(f"ELK edge {edge_id} returned a non-positive label size")
    elk_center = (
        float(label["x"]) + float(label["width"]) / 2 + padding,
        float(label["y"]) + float(label["height"]) / 2 + padding,
    )
    lengths = [math.dist(first, second) for first, second in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 0:
        raise ValueError(f"ELK edge {edge_id} has zero route length")
    best = None
    traversed = 0.0
    other_segments = [(a, b) for route in other_routes or [] for a, b in zip(route, route[1:])]
    spans_by_axis = [
        [(box[pos], box[pos] + box[size]) for box in obstacles or []]
        + [(min(a[axis], b[axis]), max(a[axis], b[axis])) for a, b in other_segments]
        for axis, pos, size in ((0, 'x', 'w'), (1, 'y', 'h'))
    ]
    for (first, second), length in zip(zip(points, points[1:]), lengths):
        if length <= 0:
            continue
        dx, dy = second[0] - first[0], second[1] - first[1]
        if not (math.isclose(dx, 0.0, abs_tol=0.01) or math.isclose(dy, 0.0, abs_tol=0.01)):
            traversed += length
            continue
        along_label = float(label["height"] if math.isclose(dx, 0.0, abs_tol=0.01) else label["width"])
        # Reserve visible line beyond the renderer's padded label background.
        margin = along_label / 2 + minimum_flank + 8.0
        if length < 2 * margin:
            traversed += length
            continue
        raw_fraction = (
            ((elk_center[0] - first[0]) * dx + (elk_center[1] - first[1]) * dy)
            / (length * length)
        )
        fraction = min(1.0 - margin / length, max(margin / length, raw_fraction))
        # Search the legal straight segment, not just the nearest point to ELK's label.
        fractions = [fraction, 0.5, margin / length, 1.0 - margin / length]
        fractions.extend(margin / length + i / 16 * (1 - 2 * margin / length) for i in range(17))
        for fraction in fractions:
            anchor = (first[0] + fraction * dx, first[1] + fraction * dy)
            # mxGraph's positive relative y uses (dy,-dx), not (-dy,dx).
            nx, ny = dy / length, -dx / length
            elk_offset = (elk_center[0] - anchor[0]) * nx + (elk_center[1] - anchor[1]) * ny
            offsets = _label_offsets(anchor, (nx, ny), label, elk_offset,
                                     obstacles or [], other_routes or [],
                                     spans_by_axis[0 if abs(nx) > 0.5 else 1])
            for offset in offsets:
                if best is not None and (offset != 0, abs(offset)) > best[0][:2]:
                    break
                center = (anchor[0] + offset * nx, anchor[1] + offset * ny)
                rank = (offset != 0, abs(offset), math.dist(elk_center, center))
                # A candidate that cannot replace the winner needs no collision scan.
                if best is not None and rank >= best[0]:
                    continue
                box = {"x": center[0] - float(label["width"]) / 2 - 8,
                       "y": center[1] - float(label["height"]) / 2 - 8,
                       "w": float(label["width"]) + 16, "h": float(label["height"]) + 16}
                if any(box["x"] < other["x"] + other["w"] and other["x"] < box["x"] + box["w"]
                       and box["y"] < other["y"] + other["h"] and other["y"] < box["y"] + box["h"]
                       for other in obstacles or []):
                    continue
                if any(_segment_hits_box(a, b, box) for a, b in other_segments):
                    continue
                if any(_segment_hits_box(a, b, box) for a, b in zip(points, points[1:])
                       if (a, b) != (first, second)):
                    continue
                along = traversed + fraction * length
                # Any legal on-route placement outranks a displaced label.
                rank = (offset != 0, abs(offset), math.dist(elk_center, center))
                candidate = (rank, along, center, offset)
                if best is None or rank < best[0]:
                    best = candidate
        traversed += length
    if best is None:
        raise ValueError(
            f"ELK edge {edge_id} has no straight segment long enough for its label and endpoint flanks"
        )
    _, along, center, offset = best
    relative_x = 2.0 * along / total - 1.0
    if not -1.0 <= relative_x <= 1.0:
        raise ValueError(f"ELK edge {edge_id} returned unsupported label position x={relative_x}")
    return (
        {"x": round(relative_x, 6), "y": round(offset, 6)},
        {
            "x": round(center[0] - float(label["width"]) / 2, 2),
            "y": round(center[1] - float(label["height"]) / 2, 2),
            "w": float(label["width"]),
            "h": float(label["height"]),
        },
    )


def convert_result(problem: dict, result: dict) -> dict:
    engine = result.get("_modelSketcherLayoutEngine")
    if not isinstance(engine, dict) or engine.get("name") != "elk-layered" or not engine.get("elkjsVersion"):
        raise ValueError("ELK result is missing reproducible engine/version metadata")
    padding = float(problem.get("canvas_padding", 24))
    boxes = {
        node["id"]: {
            "x": float(node["x"]) + padding,
            "y": float(node["y"]) + padding,
            "w": float(node["width"]),
            "h": float(node["height"]),
        }
        for node in result.get("children", [])
    }
    raw_edges = {edge["id"]: edge for edge in result.get("edges", [])}
    routes: dict[str, dict] = {}
    label_boxes: dict[str, dict] = {}
    default_source_side, default_target_side = _default_sides(problem.get("direction", "UP"))
    declarations = {key: {**item,
                         "source_side": item.get("source_side", default_source_side),
                         "target_side": item.get("target_side", default_target_side)}
                    for key, item in problem["edges"].items()}
    raw_paths = {}
    for edge_id, declared in declarations.items():
        sections = raw_edges.get(edge_id, {}).get("sections", [])
        if len(sections) != 1:
            raise ValueError(f"ELK edge {edge_id} must return exactly one routed section")
        section = sections[0]
        points = _drop_collinear([
            tuple(value + padding for value in _point(point))
            for point in [section["startPoint"], *section.get("bendPoints", []), section["endPoint"]]
        ])
        for endpoint, index in (("source", 0), ("target", -1)):
            _port_from_point(boxes[declared[endpoint]], points[index], declared[endpoint + "_side"], edge_id)
        _validate_endpoint_direction(points, declared["source_side"], declared["target_side"], edge_id)
        raw_paths[edge_id] = points
    refined_paths = refine_straight_routes(
        boxes, declarations, raw_paths,
        node_clearance=float(problem.get("spacing", {}).get("edge_node", 28)),
        preserve_existing_crossings=True,
    )
    progress(f'label placement: RUNNING ({len(problem["edges"])} edges)')
    for edge_index, (edge_id, declared) in enumerate(problem["edges"].items(), 1):
        edge = raw_edges.get(edge_id)
        sections = edge.get("sections", []) if edge else []
        if len(sections) != 1:
            raise ValueError(f"ELK edge {edge_id} must return exactly one routed section")
        section = sections[0]
        start = tuple(value + padding for value in _point(section["startPoint"]))
        end = tuple(value + padding for value in _point(section["endPoint"]))
        points = [start]
        points.extend(tuple(value + padding for value in _point(point)) for point in section.get("bendPoints", []))
        points.append(end)
        points = _drop_collinear(points)
        source_side = declared.get("source_side", default_source_side)
        target_side = declared.get("target_side", default_target_side)
        points = refined_paths[edge_id]
        route = {
            "source_port": _port_from_point(
                boxes[declared["source"]],
                points[0],
                source_side,
                edge_id,
            ),
            "target_port": _port_from_point(
                boxes[declared["target"]],
                points[-1],
                target_side,
                edge_id,
            ),
            "waypoints": [[round(x, 2), round(y, 2)] for x, y in points[1:-1]],
        }
        if declared.get("label"):
            labels = edge.get("labels", [])
            if len(labels) != 1:
                raise ValueError(f"ELK edge {edge_id} must return exactly one label box")
            route["label_position"], label_boxes[edge_id] = _label_position(
                edge_id, points, labels[0], padding,
                [*boxes.values(), *label_boxes.values()],
                [path for other_id, path in refined_paths.items() if other_id != edge_id],
                minimum_flank=max(12.0, 1.1 * float(problem.get("edge_label_font", 20))),
            )
            label_box = label_boxes[edge_id]
            for node_id, box in boxes.items():
                if not (
                    label_box["x"] + label_box["w"] <= box["x"]
                    or box["x"] + box["w"] <= label_box["x"]
                    or label_box["y"] + label_box["h"] <= box["y"]
                    or box["y"] + box["h"] <= label_box["y"]
                ):
                    raise ValueError(f"ELK edge {edge_id} centered label overlaps node {node_id}")
        routes[edge_id] = route
        if edge_index % 25 == 0 or edge_index == len(problem['edges']):
            progress(f'label placement: {edge_index}/{len(problem["edges"])}')
    for edge_id, declared in problem["edges"].items():
        route = routes[edge_id]
        points = [
            _port_point(boxes[declared["source"]], route["source_port"]),
            *[tuple(point) for point in route["waypoints"]],
            _port_point(boxes[declared["target"]], route["target_port"]),
        ]
        _validate_endpoint_direction(points, route["source_port"]["side"], route["target_port"]["side"], edge_id)
        for node_id, box in boxes.items():
            if any(_segment_hits_box(first, second, box) for first, second in zip(points, points[1:])):
                raise ValueError(f"ELK edge {edge_id} penetrates node {node_id}")
    for label_id, label_box in label_boxes.items():
        for other_id, other_box in label_boxes.items():
            if other_id <= label_id:
                continue
            if (label_box["x"] < other_box["x"] + other_box["w"]
                    and other_box["x"] < label_box["x"] + label_box["w"]
                    and label_box["y"] < other_box["y"] + other_box["h"]
                    and other_box["y"] < label_box["y"] + label_box["h"]):
                raise ValueError(f"ELK labels overlap: {label_id} / {other_id}")
        for edge_id, declared in problem["edges"].items():
            if edge_id == label_id:
                continue
            route = routes[edge_id]
            points = [_port_point(boxes[declared["source"]], route["source_port"]),
                      *[tuple(point) for point in route["waypoints"]],
                      _port_point(boxes[declared["target"]], route["target_port"])]
            if any(_segment_hits_box(a, b, label_box) for a, b in zip(points, points[1:])):
                raise ValueError(f"ELK edge {edge_id} crosses label {label_id}")
    extents = [*boxes.values(), *label_boxes.values()]
    extents.extend({"x": x, "y": y, "w": 0, "h": 0}
                   for route in routes.values() for x, y in route["waypoints"])
    width = max((box["x"] + box["w"] for box in extents), default=0) + padding
    height = max((box["y"] + box["h"] for box in extents), default=0) + padding
    return {
        "schema_version": 1,
        "engine": engine,
        "view_id": problem.get("id", "focused-view"),
        "canvas": {"width": math.ceil(width), "height": math.ceil(height)},
        "nodes": boxes,
        "edges": routes,
        "edge_label_boxes": label_boxes,
    }


def _layout_once(problem: dict, runner: Path, node: str) -> dict:
    graph = elk_graph(problem)
    with tempfile.TemporaryDirectory(prefix="model-sketcher-elk-") as temp_dir:
        temp = Path(temp_dir)
        input_path = temp / "input.json"
        result_path = temp / "result.json"
        input_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
        subprocess.run(
            [node, str(runner), str(input_path), str(result_path)],
            check=True,
            env=os.environ.copy(),
            timeout=ENGINE_TIMEOUT_SECONDS,
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
    return convert_result(problem, result)


def layout_problem(problem: dict, runner: Path, node: str) -> dict:
    alignments = problem.get("alignment_candidates")
    if alignments is None:
        return _layout_once(problem, runner, node)
    valid = {"LEFTUP", "RIGHTUP", "LEFTDOWN", "RIGHTDOWN", "BALANCED"}
    if (not isinstance(alignments, list) or not alignments or len(alignments) > 5
            or len(set(alignments)) != len(alignments) or any(item not in valid for item in alignments)):
        raise ValueError("alignment_candidates must contain one to five distinct supported alignments")
    placements = problem.get("placement_candidates", ["BRANDES_KOEPF"])
    if (not isinstance(placements, list) or not placements or len(placements) > 2
            or any(item not in {"BRANDES_KOEPF", "NETWORK_SIMPLEX"} for item in placements)):
        raise ValueError("placement_candidates must contain supported ELK node placement engines")
    attempts, candidates = [], []
    started = time.monotonic()
    for placement, alignment in product(placements, alignments):
        if time.monotonic() - started > ENGINE_TIMEOUT_SECONDS:
            raise ValueError("bounded ELK candidate selection exceeded its time budget")
        candidate_problem = deepcopy(problem)
        candidate_problem.setdefault("elk_options", {}).update({
            "elk.layered.nodePlacement.bk.fixedAlignment": alignment,
            "elk.layered.nodePlacement.favorStraightEdges": "true",
            "elk.layered.nodePlacement.strategy": placement,
        })
        try:
            layout = _layout_once(candidate_problem, runner, node)
        except ValueError as error:
            attempts.append({"alignment": alignment, "placement": placement, "adapter_error": str(error)})
            continue
        quality = candidate_quality(candidate_problem, layout)
        attempts.append({"alignment": alignment, "placement": placement, **quality})
        candidates.append((quality["score"], len(candidates), alignment, layout, placement))
    if not candidates:
        raise ValueError("all bounded ELK candidates failed: " + "; ".join(
            f"{item['alignment']}: {item.get('adapter_error')}" for item in attempts))
    _, _, selected, layout, placement = min(candidates, key=lambda item: (item[0], item[1]))
    layout["engine"]["candidate_selection"] = {"selected_alignment": selected,
                                              "selected_placement": placement, "attempts": attempts}
    if all(candidate[0][0] > 0 for candidate in candidates):
        from isolated_line_jumps import plan_isolated_line_jumps
        layout = plan_isolated_line_jumps(problem, layout)
    return layout


def run(problem_path: Path, output_path: Path, runner: Path, node: str) -> dict:
    problem = load_problem(problem_path)
    output = layout_problem(problem, runner, node)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--node", default="node")
    parser.add_argument("--runner", type=Path, default=Path(__file__).with_name("elk_runner.cjs"))
    args = parser.parse_args()
    try:
        output = run(args.problem, args.output, args.runner, args.node)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"ELK layout: FAIL ({error})")
        return 1
    print(
        f"ELK layout: GENERATED; strict/visual audits pending ({len(output['nodes'])} nodes, {len(output['edges'])} edges, "
        f"canvas {output['canvas']['width']}x{output['canvas']['height']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
