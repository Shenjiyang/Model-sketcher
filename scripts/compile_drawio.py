#!/usr/bin/env python3
"""Compile architecture IR plus deterministic layout into editable Draw.io XML."""

from __future__ import annotations

import argparse
import heapq
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from semantic_palette import (
    SEMANTIC_PALETTE,
    TP_PARTITION_MODIFIER,
    resolve_visual_class,
    semantic_glyph,
    semantic_style,
)
from validate_architecture_ir import edge_display_label, load, validate
from view_projection import project_active_view, project_layout_view
from fusion_presentation import visible_fusion_boundaries
from plan_layout import region_title_layout
from visual_edge_labels import visual_edge_label
from junction_routes import rail_contracts, rail_markers


NODE_STYLES = {
    "junction": "ellipse;aspect=fixed;fillColor=#000000;strokeColor=#000000;",
}
LEGEND_ORDER = (
    "conditional", "tensor-op", "vector-op", "io-op", "tp-partition",
    "communication", "composite-op", "residual-op", "cache",
)
HIERARCHY_ARROW_STYLE = (
    "shape=singleArrow;arrowWidth=0.52;arrowSize=0.38;whiteSpace=wrap;html=1;"
    "fillColor=#FFFFFF;strokeColor=#555555;strokeWidth=1.8;fontStyle=1;"
)
FUSION_BOUNDARY_STYLE = (
    "rounded=0;dashed=1;dashPattern=6 4;whiteSpace=wrap;html=1;fillColor=none;"
    "strokeColor=#777777;strokeWidth=1.5;fontStyle=1;align=left;"
    "verticalAlign=top;spacingTop=4;spacingLeft=6;"
)
PORTS = {
    "east": (1, 0.5), "west": (0, 0.5), "north": (0.5, 0), "south": (0.5, 1),
}
MAX_EDGE_LABEL_OFFSET = 160.0
MIN_LINE_JUMP_SIZE = 6.0
MAX_LINE_JUMP_SIZE = 32.0


def port_coordinates(value: str | dict) -> tuple[float, float]:
    if isinstance(value, str):
        if value not in PORTS:
            raise ValueError(f"invalid port side: {value!r}")
        return PORTS[value]
    if not isinstance(value, dict):
        raise ValueError("port must be a side string or {side, position} object")
    side = value.get("side")
    try:
        position = float(value.get("position", 0.5))
    except (TypeError, ValueError) as error:
        raise ValueError(f"port position must be numeric, got {value.get('position')!r}") from error
    if not math.isfinite(position) or not 0.0 <= position <= 1.0:
        raise ValueError(f"port position must be within [0,1], got {position}")
    if side == "east":
        return 1.0, position
    if side == "west":
        return 0.0, position
    if side == "north":
        return position, 0.0
    if side == "south":
        return position, 1.0
    raise ValueError(f"invalid port side: {side!r}")


def edge_label_coordinates(value: object) -> tuple[float, float]:
    """Validate Draw.io edge-label relative position and perpendicular offset."""
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError("label_position must be exactly an {x, y} object")
    try:
        x, y = float(value["x"]), float(value["y"])
    except (TypeError, ValueError) as error:
        raise ValueError("label_position x and y must be numeric") from error
    if not math.isfinite(x) or not -1.0 <= x <= 1.0:
        raise ValueError(f"label_position.x must be finite and within [-1,1], got {x}")
    if not math.isfinite(y) or abs(y) > MAX_EDGE_LABEL_OFFSET:
        raise ValueError(
            f"label_position.y must be finite and within [-{MAX_EDGE_LABEL_OFFSET:g},{MAX_EDGE_LABEL_OFFSET:g}], got {y}"
        )
    return x, y


def line_jump_contracts(data: dict, layout: dict) -> tuple[dict[str, dict], list[str]]:
    """Validate optional, layout-only arc bridges and return them by jumper edge."""
    ordinary = {
        edge_id for edge_id, edge in data.get("edges", {}).items()
        if edge.get("kind") != "expand"
    }
    contracts: dict[str, dict] = {}
    errors: list[str] = []
    declared_pairs: set[tuple[str, str]] = set()
    for edge_id in sorted(ordinary):
        route = layout.get("edges", {}).get(edge_id, {})
        contract = route.get("line_jump") if isinstance(route, dict) else None
        if contract is None:
            continue
        if not isinstance(contract, dict) or set(contract) != {"style", "size", "crossings"}:
            errors.append(
                f"edge {edge_id} line_jump must be exactly a {{style, size, crossings}} object"
            )
            continue
        if contract.get("style") != "arc":
            errors.append(f"edge {edge_id} line_jump.style must be 'arc'")
        try:
            size = float(contract.get("size"))
        except (TypeError, ValueError):
            size = math.nan
        if not math.isfinite(size) or not MIN_LINE_JUMP_SIZE <= size <= MAX_LINE_JUMP_SIZE:
            errors.append(
                f"edge {edge_id} line_jump.size must be finite and within "
                f"[{MIN_LINE_JUMP_SIZE:g},{MAX_LINE_JUMP_SIZE:g}]"
            )
        crossings = contract.get("crossings")
        if not isinstance(crossings, dict) or not crossings:
            errors.append(f"edge {edge_id} line_jump.crossings must be a non-empty edge-ID-to-reason object")
            continue
        clean_crossings: dict[str, str] = {}
        for other_id, reason in crossings.items():
            if other_id not in ordinary or other_id == edge_id:
                errors.append(f"edge {edge_id} line jump names invalid crossed edge {other_id!r}")
                continue
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"edge {edge_id} line jump over {other_id} requires a non-empty reason")
                continue
            pair = tuple(sorted((edge_id, other_id)))
            if pair in declared_pairs:
                errors.append(f"line-jump pair {pair[0]} / {pair[1]} is declared more than once")
                continue
            declared_pairs.add(pair)
            clean_crossings[other_id] = reason.strip()
        if clean_crossings and math.isfinite(size):
            contracts[edge_id] = {"style": "arc", "size": size, "crossings": clean_crossings}

    # The XML order must agree with which line visually bridges over the other.
    dependencies = {edge_id: set() for edge_id in ordinary}
    for jumper, contract in contracts.items():
        dependencies[jumper].update(contract["crossings"])
    remaining = {edge_id: set(items) for edge_id, items in dependencies.items()}
    ready = [edge_id for edge_id, items in remaining.items() if not items]
    heapq.heapify(ready)
    emitted: set[str] = set()
    while ready:
        edge_id = heapq.heappop(ready)
        if edge_id in emitted:
            continue
        emitted.add(edge_id)
        for candidate, items in remaining.items():
            if edge_id in items:
                items.remove(edge_id)
                if not items:
                    heapq.heappush(ready, candidate)
    if len(emitted) != len(ordinary):
        errors.append("line-jump over/under declarations contain a cycle")
    return contracts, errors


def ordered_ordinary_edges(data: dict, contracts: dict[str, dict]) -> list[tuple[str, dict]]:
    """Render crossed edges before the edge whose arc bridge passes over them."""
    ordinary = {
        edge_id: edge for edge_id, edge in data.get("edges", {}).items()
        if edge.get("kind") != "expand"
    }
    dependencies = {
        edge_id: set(contracts.get(edge_id, {}).get("crossings", {}))
        for edge_id in ordinary
    }
    ready = [edge_id for edge_id, items in dependencies.items() if not items]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        edge_id = heapq.heappop(ready)
        ordered.append(edge_id)
        for candidate, items in dependencies.items():
            if edge_id in items:
                items.remove(edge_id)
                if not items:
                    heapq.heappush(ready, candidate)
    if len(ordered) != len(ordinary):
        raise ValueError("line-jump over/under declarations contain a cycle")
    return [(edge_id, ordinary[edge_id]) for edge_id in ordered]


def architecture_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry(parent: ET.Element, box: dict) -> None:
    ET.SubElement(parent, "mxGeometry", {
        "x": str(box["x"]), "y": str(box["y"]), "width": str(box["w"]), "height": str(box["h"]), "as": "geometry"
    })


def legend_origin(layout: dict) -> tuple[float, float]:
    boxes = list(layout.get("regions", {}).values()) + list(layout.get("nodes", {}).values())
    if not boxes:
        return 40.0, 40.0
    return min(float(box["x"]) for box in boxes), max(float(box["y"] + box["h"]) for box in boxes) + 64.0


def add_semantic_legend(root: ET.Element, layout: dict, font_size: int) -> None:
    """Add one fixed two-row Legend using the original DPSK V4 palette."""
    origin_x, origin_y = legend_origin(layout)
    title = ET.SubElement(root, "mxCell", {
        "id": "legend:title", "value": "Legend / 图例",
        "style": f"text;html=1;strokeColor=none;fillColor=none;align=left;fontStyle=1;fontSize={font_size};",
        "vertex": "1", "parent": "1",
    })
    geometry(title, {"x": origin_x, "y": origin_y, "w": 150, "h": 28})
    swatch_w, swatch_h, gap_x, gap_y = 122, 36, 12, 12
    for index, entry in enumerate(LEGEND_ORDER):
        row = 0 if index < 5 else 1
        column = index if row == 0 else index - 5
        x = origin_x + column * (swatch_w + gap_x)
        y = origin_y + 34 + row * (swatch_h + gap_y)
        if entry == "tp-partition":
            modifier = TP_PARTITION_MODIFIER
            label = modifier["label"]
            style = (
                "rounded=1;arcSize=6;whiteSpace=wrap;html=1;"
                f"fillColor={modifier['legend_fillColor']};strokeColor={modifier['legend_strokeColor']};"
                f"fontColor={modifier['fontColor']};dashed={modifier['legend_dashed']};"
            )
        else:
            label = SEMANTIC_PALETTE[entry]["label"]
            style = semantic_style(entry, glyph="storage" if entry == "cache" else "operator")
        cell = ET.SubElement(root, "mxCell", {
            "id": f"legend:{entry}", "value": label,
            "style": style + f"fontSize={font_size};", "vertex": "1", "parent": "1",
        })
        geometry(cell, {"x": x, "y": y, "w": swatch_w, "h": swatch_h})


def fusion_boundary_box(fusion: dict, layout: dict) -> dict:
    members = [layout["nodes"][node_id] for node_id in fusion["operators"]]
    left = min(box["x"] for box in members) - 16
    top = min(box["y"] for box in members) - 32
    right = max(box["x"] + box["w"] for box in members) + 16
    bottom = max(box["y"] + box["h"] for box in members) + 16
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def validate_fusion_boundary_geometry(data: dict, layout: dict) -> list[str]:
    """Keep generated fusion boundaries owned, contained, and semantically exclusive."""
    errors: list[str] = []
    for fusion in visible_fusion_boundaries(data):
        fusion_id = fusion.get("id", "<unknown>")
        try:
            boundary = fusion_boundary_box(fusion, layout)
            owner = layout["regions"][fusion["owner_region"]]
        except (KeyError, TypeError, ValueError):
            errors.append(f"fusion {fusion_id} references missing boundary geometry")
            continue
        if (
            boundary["x"] < owner["x"]
            or boundary["y"] < owner["y"]
            or boundary["x"] + boundary["w"] > owner["x"] + owner["w"]
            or boundary["y"] + boundary["h"] > owner["y"] + owner["h"]
        ):
            errors.append(f"fusion {fusion_id} boundary escapes owner region {fusion['owner_region']}")
        members = set(fusion["operators"])
        for node_id, box in layout.get("nodes", {}).items():
            if node_id in members or data.get("nodes", {}).get(node_id, {}).get("region") != fusion.get("owner_region"):
                continue
            overlap_width = min(
                boundary["x"] + boundary["w"], box["x"] + box["w"]
            ) - max(boundary["x"], box["x"])
            overlap_height = min(
                boundary["y"] + boundary["h"], box["y"] + box["h"]
            ) - max(boundary["y"], box["y"])
            if overlap_width > 0 and overlap_height > 0:
                errors.append(f"fusion {fusion_id} boundary intersects non-member node {node_id}")
    return errors


def validate_detail_flow_geometry(data: dict, layout: dict) -> list[str]:
    """Ensure every declared block sequence keeps strict bottom-to-top flow."""
    errors: list[str] = []
    boxes = layout.get("nodes", {})
    for region_id, region in data.get("regions", {}).items():
        for sequence in region.get("operator_sequences", []):
            path = sequence.get("nodes", [])
            for source, target in zip(path, path[1:]):
                if source not in boxes or target not in boxes:
                    continue
                source_center = boxes[source]["y"] + boxes[source]["h"] / 2
                target_center = boxes[target]["y"] + boxes[target]["h"] / 2
                if target_center >= source_center:
                    errors.append(
                        f"region {region_id} sequence {sequence.get('id')!r} "
                        f"does not rise bottom-to-top: {source} -> {target}"
                    )
    return sorted(set(errors))


def validate_hierarchy_arrow_geometry(data: dict, layout: dict) -> list[str]:
    """Require one large, boundary-attached arrow vertex for every expand relation."""
    errors: list[str] = []
    expand_edges = {
        edge_id: edge for edge_id, edge in data.get("edges", {}).items()
        if edge.get("kind") == "expand"
    }
    arrows = layout.get("hierarchy_arrows", {})
    if not isinstance(arrows, dict):
        return ["layout.hierarchy_arrows must be an object"]
    if set(arrows) != set(expand_edges):
        errors.append(
            "layout hierarchy-arrow IDs do not match expand relations: "
            f"expected={sorted(expand_edges)} actual={sorted(arrows)}"
        )
        return errors
    node_boxes, region_boxes = layout.get("nodes", {}), layout.get("regions", {})
    for edge_id, edge in expand_edges.items():
        arrow = arrows[edge_id]
        child_region_id = data["nodes"][edge["target"]]["region"]
        declared_attachment = edge.get("visual_attachment") or {}
        attachment_mode = arrow.get("attachment_mode")
        attachment_id = arrow.get("attachment_id")
        if declared_attachment:
            declared_mode = declared_attachment.get("mode", "parent-node")
            declared_id = (
                declared_attachment.get("region")
                if declared_mode == "owner-region-boundary" else edge["source"]
            )
            mode_matches = attachment_mode == declared_mode or (
                declared_mode == "owner-region-boundary" and attachment_mode == "target-signpost"
            )
            if not mode_matches or attachment_id != declared_id:
                errors.append(f"expand relation {edge_id} resolved attachment differs from its explicit IR contract")
        elif attachment_mode == "parent-node":
            if attachment_id != edge["source"]:
                errors.append(f"expand relation {edge_id} parent-node attachment is not its semantic parent")
        elif attachment_mode in {"owner-region-boundary", "target-signpost"}:
            source_region = data["nodes"][edge["source"]]["region"]
            cursor = source_region
            owners: set[str] = set()
            while cursor is not None:
                owners.add(cursor)
                cursor = data["regions"][cursor].get("parent")
            if attachment_id not in owners:
                errors.append(f"expand relation {edge_id} automatic egress does not own its semantic parent")
            anchor_label = arrow.get("anchor_label")
            if not isinstance(anchor_label, str) or not anchor_label.strip():
                errors.append(f"expand relation {edge_id} automatic egress lacks an anchor label")
            elif anchor_label.casefold() not in str(arrow.get("display_label") or edge.get("label", "")).casefold():
                errors.append(f"expand relation {edge_id} expansion label does not name its automatic egress")
        else:
            errors.append(f"expand relation {edge_id} has invalid resolved attachment mode")
        parent = (
            region_boxes.get(attachment_id)
            if attachment_mode in {"owner-region-boundary", "target-signpost"}
            else node_boxes.get(attachment_id)
        )
        child = region_boxes.get(child_region_id)
        if parent is None or child is None or not isinstance(arrow, dict):
            errors.append(f"expand relation {edge_id} references missing hierarchy geometry")
            continue
        if (
            arrow.get("parent") != edge["source"]
            or arrow.get("child_region") != child_region_id
        ):
            errors.append(f"expand relation {edge_id} hierarchy metadata does not match its endpoints")
        try:
            x, y, width, height = (float(arrow[key]) for key in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            errors.append(f"expand relation {edge_id} has invalid hierarchy-arrow box")
            continue
        if width < 48 or height < 48:
            errors.append(f"expand relation {edge_id} hierarchy arrow is too small ({width:g}x{height:g})")
        direction = arrow.get("direction")
        checks = {
            "east": (x, parent["x"] + parent["w"], x + width, child["x"]),
            "west": (x + width, parent["x"], x, child["x"] + child["w"]),
            "south": (y, parent["y"] + parent["h"], y + height, child["y"]),
            "north": (y + height, parent["y"], y, child["y"] + child["h"]),
        }
        if direction not in checks:
            errors.append(f"expand relation {edge_id} has invalid hierarchy direction {direction!r}")
            continue
        if direction in {"north", "south"}:
            parent_overlap = min(x + width, parent["x"] + parent["w"]) - max(x, parent["x"])
            child_overlap = min(x + width, child["x"] + child["w"]) - max(x, child["x"])
            center = x + width / 2
            center_attached = parent["x"] - 1 <= center <= parent["x"] + parent["w"] + 1 and child["x"] - 1 <= center <= child["x"] + child["w"] + 1
        else:
            parent_overlap = min(y + height, parent["y"] + parent["h"]) - max(y, parent["y"])
            child_overlap = min(y + height, child["y"] + child["h"]) - max(y, child["y"])
            center = y + height / 2
            center_attached = parent["y"] - 1 <= center <= parent["y"] + parent["h"] + 1 and child["y"] - 1 <= center <= child["y"] + child["h"] + 1
        if attachment_mode == "target-signpost":
            if child_overlap <= 1:
                errors.append(f"expand relation {edge_id} target signpost misses the child corridor")
            parent_center = (parent["x"] + parent["w"] / 2, parent["y"] + parent["h"] / 2)
            child_center = (child["x"] + child["w"] / 2, child["y"] + child["h"] / 2)
            points_toward_child = {
                "east": child_center[0] > parent_center[0],
                "west": child_center[0] < parent_center[0],
                "south": child_center[1] > parent_center[1],
                "north": child_center[1] < parent_center[1],
            }[direction]
            if not points_toward_child:
                errors.append(f"expand relation {edge_id} target signpost points away from its child")
            for region_id, region in region_boxes.items():
                if region_id == child_region_id:
                    continue
                overlap_w = min(x + width, region["x"] + region["w"]) - max(x, region["x"])
                overlap_h = min(y + height, region["y"] + region["h"]) - max(y, region["y"])
                if overlap_w > 1 and overlap_h > 1:
                    errors.append(f"expand relation {edge_id} target signpost overlaps region {region_id}")
        elif parent_overlap <= 1 or child_overlap <= 1 or not center_attached:
            errors.append(f"expand relation {edge_id} hierarchy arrow misses the attachment or child corridor")
        actual_tail, expected_tail, actual_tip, expected_tip = checks[direction]
        if attachment_mode != "target-signpost" and abs(actual_tail - expected_tail) > 1:
            errors.append(f"expand relation {edge_id} hierarchy tail is detached")
        if abs(actual_tip - expected_tip) > 1:
            errors.append(f"expand relation {edge_id} hierarchy tip is detached")
    return errors


def compile_diagram(data: dict, layout: dict) -> ET.ElementTree:
    data = project_layout_view(data, layout)
    jump_contracts, jump_errors = line_jump_contracts(data, layout)
    if jump_errors:
        raise ValueError("; ".join(jump_errors))
    geometry_errors = (
        validate_detail_flow_geometry(data, layout)
        + validate_hierarchy_arrow_geometry(data, layout)
        + validate_fusion_boundary_geometry(data, layout)
    )
    if geometry_errors:
        raise ValueError("; ".join(geometry_errors))
    typography = data.get("project", {}).get("typography", {})
    ordinary_font = int(typography.get("ordinary_node_font", 18))
    edge_font = int(typography.get("edge_label_font", 14))
    annotation_font = int(typography.get("annotation_font", edge_font))
    region_font = int(typography.get("region_title_font", 20))
    hierarchy_font = int(typography.get("hierarchy_label_font", 20))

    rails = rail_contracts(data, layout)
    if rails != layout.get('junction_rails', {}):
        raise ValueError('junction rail registry missing or stale; regenerate layout')
    mxfile = ET.Element("mxfile", {"host": "codex", "version": "1", "compressed": "false"})
    diagram = ET.SubElement(mxfile, "diagram", {"id": "compiled", "name": data["project"]["title"]})
    model = ET.SubElement(diagram, "mxGraphModel", {"dx": "1200", "dy": "800", "grid": "1", "gridSize": "10", "page": "0"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    depth_cache: dict[str, int] = {}
    def depth(region_id: str) -> int:
        if region_id not in depth_cache:
            parent = data["regions"][region_id].get("parent")
            depth_cache[region_id] = 0 if parent is None else depth(parent) + 1
        return depth_cache[region_id]

    for region_id in sorted(data["regions"], key=lambda item: (depth(item), data["regions"][item].get("order", 0), item)):
        region = data["regions"][region_id]
        title = region_title_layout(region['label'], layout['regions'][region_id]['w'], region_font)
        cell = ET.SubElement(root, "mxCell", {
            "id": f"region:{region_id}", "value": title['text'],
            "style": f"container=1;html=1;rounded=0;whiteSpace=wrap;fillColor=none;strokeColor=#666666;dashed=1;dashPattern=8 4;align=left;verticalAlign=top;spacingLeft=14;spacingTop=8;fontSize={region_font};fontStyle=1;",
            "vertex": "1", "parent": "1",
        })
        geometry(cell, layout["regions"][region_id])

    for fusion in visible_fusion_boundaries(data):
        label = str(fusion.get("label") or f"Fused execution: {fusion['id']}")
        cell = ET.SubElement(root, "mxCell", {
            "id": f"fusion:{fusion['id']}", "value": label.replace("\\n", "\n"),
            "style": FUSION_BOUNDARY_STYLE + f"fontSize={annotation_font};", "vertex": "1", "parent": "1",
        })
        geometry(cell, fusion_boundary_box(fusion, layout))

    for node_id, node in sorted(data["nodes"].items(), key=lambda item: (item[1].get("order", 0), item[0])):
        visual_class = resolve_visual_class(node)
        style = (
            NODE_STYLES["junction"]
            if node["kind"] == "junction"
            else semantic_style(
                visual_class,
                node.get("visual_modifiers", []),
                semantic_glyph(node),
            )
        )
        cell = ET.SubElement(root, "mxCell", {
            "id": f"node:{node_id}", "value": str(node["label"]).replace("\\n", "\n"),
            "style": style + f"fontSize={ordinary_font};", "vertex": "1", "parent": "1",
        })
        geometry(cell, layout["nodes"][node_id])

    add_semantic_legend(root, layout, annotation_font)

    for edge_id, edge in sorted(data.get("edges", {}).items()):
        if edge.get("kind") != "expand":
            continue
        arrow = layout["hierarchy_arrows"][edge_id]
        child_region_id = arrow["child_region"]
        label = str(arrow.get("display_label") or edge.get("label") or f"expand {data['regions'][child_region_id]['label']}")
        cell = ET.SubElement(root, "mxCell", {
            "id": f"expand:{edge_id}", "value": label.replace("\\n", "\n"),
            "style": HIERARCHY_ARROW_STYLE + f"fontSize={hierarchy_font};direction={arrow['direction']};",
            "vertex": "1", "parent": "1",
        })
        geometry(cell, arrow)

    for edge_id, edge in ordered_ordinary_edges(data, jump_contracts):
        route = layout["edges"][edge_id]
        sx, sy = port_coordinates(route["source_port"])
        tx, ty = port_coordinates(route["target_port"])
        dashed = "1" if edge["kind"] in {"uses", "injects", "reuses"} else "0"
        end_arrow = "block" if edge["kind"] == "tensor" else "open"
        if data['nodes'][edge['target']].get('kind') == 'junction':
            end_arrow = 'none'
        style = (
            "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;jettySize=auto;html=1;"
            f"rounded=0;strokeWidth=2;dashed={dashed};endArrow={end_arrow};endFill=1;"
            f"exitX={sx};exitY={sy};exitDx=0;exitDy=0;entryX={tx};entryY={ty};entryDx=0;entryDy=0;fontSize={edge_font};"
        )
        if edge_id in jump_contracts:
            style += f"jumpStyle=arc;jumpSize={jump_contracts[edge_id]['size']:g};"
        cell = ET.SubElement(root, "mxCell", {
            "id": f"edge:{edge_id}", "value": visual_edge_label(edge, edge_id=edge_id), "style": style,
            "edge": "1", "parent": "1", "source": f"node:{edge['source']}", "target": f"node:{edge['target']}",
        })
        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        label_position = route.get("label_position")
        if label_position is not None:
            label_x, label_y = edge_label_coordinates(label_position)
            geo.set("x", str(label_x))
            geo.set("y", str(label_y))
        if route["waypoints"]:
            array = ET.SubElement(geo, "Array", {"as": "points"})
            for x, y in route["waypoints"]:
                ET.SubElement(array, "mxPoint", {"x": str(x), "y": str(y)})
    for marker_id, box in rail_markers(rails).items():
        cell = ET.SubElement(root, 'mxCell', {
            'id': marker_id, 'value': '', 'style': NODE_STYLES['junction'],
            'vertex': '1', 'parent': '1',
        })
        geometry(cell, box)
    return ET.ElementTree(mxfile)


def main() -> int:
    from semantic_gate import add_gate_arguments, cli_gate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("layout", type=Path)
    parser.add_argument("output", type=Path)
    add_gate_arguments(parser)
    args = parser.parse_args()
    if not cli_gate(args):
        return 3
    data = load(args.architecture)
    errors = validate(data, args.architecture.parent)
    if errors:
        print("compile: FAIL; architecture IR is invalid")
        return 1
    data = project_active_view(data)
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    if layout.get("architecture_sha256") != architecture_digest(args.architecture):
        print("compile: FAIL; layout is stale for this architecture IR")
        return 1
    ordinary_edges = {
        edge_id for edge_id, edge in data.get("edges", {}).items() if edge.get("kind") != "expand"
    }
    expand_edges = {
        edge_id for edge_id, edge in data.get("edges", {}).items() if edge.get("kind") == "expand"
    }
    expected = {
        "regions": set(data["regions"]), "nodes": set(data["nodes"]),
        "edges": ordinary_edges, "hierarchy_arrows": expand_edges,
    }
    for section, ids in expected.items():
        if set(layout.get(section, {})) != ids:
            print(f"compile: FAIL; layout {section} IDs do not match architecture IR")
            return 1
    _, line_jump_errors = line_jump_contracts(data, layout)
    geometry_errors = (
        validate_detail_flow_geometry(data, layout)
        + validate_hierarchy_arrow_geometry(data, layout)
        + line_jump_errors
    )
    if geometry_errors:
        print("compile: FAIL; detail flow geometry violates the architecture contract")
        for error in geometry_errors:
            print(f"ERROR: {error}")
        return 1
    try:
        tree = compile_diagram(data, layout)
    except ValueError as error:
        print(f"compile: FAIL; {error}")
        return 1
    ET.indent(tree, space="  ")
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"compile: PASS ({args.output})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
