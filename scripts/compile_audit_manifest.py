#!/usr/bin/env python3
"""Derive the machine-owned structural portion of a Draw.io audit manifest from architecture IR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compile_drawio import (
    edge_label_coordinates,
    line_jump_contracts,
    port_coordinates,
    validate_fusion_boundary_geometry,
    validate_hierarchy_arrow_geometry,
)
from semantic_palette import (
    SEMANTIC_GLYPHS,
    SEMANTIC_PALETTE,
    TP_PARTITION_MODIFIER,
    resolve_visual_class,
    semantic_glyph,
)
from validate_architecture_ir import load, validate
from view_projection import project_active_view, project_layout_view
from fusion_presentation import execution_fusion_ledger, fusion_presentation
from visual_edge_labels import visual_edge_label
from junction_routes import rail_contracts, rail_markers


LEGEND_ENTRIES = (
    "conditional", "tensor-op", "vector-op", "io-op", "tp-partition",
    "communication", "composite-op", "residual-op", "cache",
)


def build_manifest(data: dict, layout: dict | None = None) -> dict:
    data = project_layout_view(data, layout or {})
    rails = rail_contracts(data, layout) if layout else {}
    markers = rail_markers(rails)
    ordinary_font = float(
        data.get("project", {}).get("typography", {}).get("ordinary_node_font", 18)
    )
    edge_label_font = float(
        data.get("project", {}).get("typography", {}).get("edge_label_font", ordinary_font * 0.75)
    )
    region_ids = [f"region:{item}" for item in data["regions"]]
    node_ids = [f"node:{item}" for item in data["nodes"]]
    ordinary_edges = {
        edge_id: edge for edge_id, edge in data.get("edges", {}).items()
        if edge.get("kind") != "expand"
    }
    expand_edges = {
        edge_id: edge for edge_id, edge in data.get("edges", {}).items()
        if edge.get("kind") == "expand"
    }
    edge_ids = [f"edge:{item}" for item in ordinary_edges]
    arrow_ids = [f"expand:{item}" for item in expand_edges]
    fusion_policy = fusion_presentation(data)
    fusion_boundary_ids = fusion_policy["boundary_ids"]
    legend_ids = ["legend:title"] + [f"legend:{item}" for item in LEGEND_ENTRIES]
    region_parents = {
        f"region:{region_id}": f"region:{region['parent']}"
        for region_id, region in data["regions"].items() if region.get("parent") is not None
    }
    region_content = {f"region:{region_id}": [] for region_id in data["regions"]}
    for node_id, node in data["nodes"].items():
        cursor = node["region"]
        while cursor is not None:
            region_content[f"region:{cursor}"].append(f"node:{node_id}")
            cursor = data["regions"][cursor].get("parent")
    expected_edges = {
        f"edge:{edge_id}": {"source": f"node:{edge['source']}", "target": f"node:{edge['target']}"}
        for edge_id, edge in ordinary_edges.items()
    }
    expected_ports: dict[str, dict[str, float | str]] = {}
    expected_label_positions: dict[str, dict[str, float]] = {}
    line_jump_crossings: dict[str, dict[str, object]] = {}
    if layout is not None:
        jump_contracts, jump_errors = line_jump_contracts(data, layout)
        if jump_errors:
            raise ValueError("; ".join(jump_errors))
        for edge_id in ordinary_edges:
            route = layout["edges"][edge_id]
            source_x, source_y = port_coordinates(route["source_port"])
            target_x, target_y = port_coordinates(route["target_port"])
            source_side = (
                route["source_port"]
                if isinstance(route["source_port"], str) else route["source_port"]["side"]
            )
            target_side = (
                route["target_port"]
                if isinstance(route["target_port"], str) else route["target_port"]["side"]
            )
            expected_ports[f"edge:{edge_id}"] = {
                "exitX": source_x, "exitY": source_y,
                "entryX": target_x, "entryY": target_y,
                "exitSide": source_side, "entrySide": target_side,
            }
            if route.get("label_position") is not None:
                label_x, label_y = edge_label_coordinates(route["label_position"])
                expected_label_positions[f"edge:{edge_id}"] = {"x": label_x, "y": label_y}
        for jumper, contract in jump_contracts.items():
            for crossed, reason in contract["crossings"].items():
                pair = "|".join(sorted((f"edge:{jumper}", f"edge:{crossed}")))
                line_jump_crossings[pair] = {
                    "jumper": f"edge:{jumper}",
                    "style": contract["style"],
                    "size": contract["size"],
                    "reason": reason,
                }
    if (expand_edges or fusion_boundary_ids) and layout is None:
        raise ValueError("layout is required to generate hierarchy anchors or fusion boundaries")
    if layout is not None:
        geometry_errors = (
            validate_hierarchy_arrow_geometry(data, layout)
            + validate_fusion_boundary_geometry(data, layout)
        )
        if geometry_errors:
            raise ValueError("; ".join(geometry_errors))
    audit_direction = {"north": "up", "south": "down", "west": "left", "east": "right"}
    hierarchy_anchors = {
        f"expand:{edge_id}": {
            "parent": f"node:{edge['source']}",
            "attachment_mode": layout["hierarchy_arrows"][edge_id]["attachment_mode"],
            "attachment": (
                f"region:{layout['hierarchy_arrows'][edge_id]['attachment_id']}"
                if layout["hierarchy_arrows"][edge_id]["attachment_mode"] in {"owner-region-boundary", "target-signpost"}
                else f"node:{layout['hierarchy_arrows'][edge_id]['attachment_id']}"
            ),
            "child": f"region:{data['nodes'][edge['target']]['region']}",
            "direction": audit_direction[layout["hierarchy_arrows"][edge_id]["direction"]],
            **(
                {"anchor_label": layout["hierarchy_arrows"][edge_id]["anchor_label"]}
                if layout["hierarchy_arrows"][edge_id].get("attachment_mode") in {"owner-region-boundary", "target-signpost"}
                else {}
            ),
        }
        for edge_id, edge in expand_edges.items()
    }
    node_semantics = {
        f"node:{node_id}": {
            "kind": node["kind"],
            "evidence": ", ".join(node["evidence"]),
            "semantic_layer": node.get("semantic_layer"),
            "views": node.get("views", []),
            **(
                {"operator_classification": node["operator_contract"]["classification"]}
                if isinstance(node.get("operator_contract"), dict)
                and node["operator_contract"].get("classification")
                else {}
            ),
            **(
                {"op_type": node["operator_contract"]["op_type"]}
                if isinstance(node.get("operator_contract"), dict)
                and node["operator_contract"].get("op_type")
                else {}
            ),
            **(
                {"shape_rule": node["operator_contract"]["shape_rule"]}
                if isinstance(node.get("operator_contract"), dict)
                and node["operator_contract"].get("shape_rule")
                else {}
            ),
            **(
                {"semantic_role": node["operator_contract"]["semantic_role"]}
                if isinstance(node.get("operator_contract"), dict)
                and node["operator_contract"].get("semantic_role")
                else {}
            ),
            **(
                {"source_symbols": node["operator_contract"]["source_symbols"]}
                if isinstance(node.get("operator_contract"), dict)
                and node["operator_contract"].get("source_symbols")
                else {}
            ),
            **(
                {"visual_class": resolve_visual_class(node)}
                if resolve_visual_class(node) is not None else {}
            ),
            "visual_modifiers": node.get("visual_modifiers", []),
        }
        for node_id, node in data["nodes"].items()
    }
    granularity = {
        f"region:{region_id}": {
            "mode": region["granularity"],
            "level": region.get("level"),
            "allowed_composites": {
                f"node:{node_id}": {
                    "classification": "expanded-elsewhere",
                    "evidence": ", ".join(node["evidence"]),
                    "detail_target": f"region:{node['operator_contract']['detail_region']}",
                    "reason": node["operator_contract"]["reason"],
                }
                for node_id, node in data["nodes"].items()
                if node.get("region") == region_id
                and isinstance(node.get("operator_contract"), dict)
                and node["operator_contract"].get("classification") == "expanded-elsewhere"
            },
            "node_exclusions": {},
        }
        for region_id, region in data["regions"].items()
    }
    vertical_flow = {
        f"region:{region_id}": {
            "direction": "bottom-to-top",
            "sequences": [
                {
                    "id": sequence["id"],
                    "nodes": [f"node:{node_id}" for node_id in sequence["nodes"]],
                }
                for sequence in region.get("operator_sequences", [])
            ],
        }
        for region_id, region in data["regions"].items()
    }
    return {
        "schema_version": 1,
        "generated_from": "architecture.json; merge workflow_contract and human review records before final delivery",
        "defaults": {
            "layout_engine": (
                layout.get("layout_engine", {"name": "v4-native"})
                if layout is not None else {"name": "unmaterialized"}
            ),
            "require_fixed_ports": True,
            "require_port_geometry_contracts": layout is not None,
            "expected_ports": expected_ports,
            "require_registered_edge_label_positions": layout is not None,
            "expected_edge_label_positions": expected_label_positions,
            "line_jump_crossings": line_jump_crossings,
            "junction_rails": rails,
            "junction_rail_markers": markers,
            "maximum_line_jumps_per_edge": 3,
            "line_jump_count_exceptions": {},
            "require_semantic_coverage": True,
            "require_granularity_contracts": True,
            "require_logical_operator_contracts": data.get("project", {}).get("require_logical_operator_contracts") is True,
            "require_source_coverage": data.get("project", {}).get("require_source_coverage") is True,
            "require_view_projection_contracts": data.get("project", {}).get("require_view_projection_contracts") is True,
            "semantic_view": data.get("project", {}).get("semantic_view"),
            "view_projection_contract": data.get("view_projection_contract", {}),
            "external_canonical_references": data.get("external_canonical_references", {}),
            "require_reader_facing_labels": data.get("project", {}).get("require_logical_operator_contracts") is True,
            "require_overview_contract": True,
            "overview_contract": data.get("overview_contract", {}),
            "require_template_coverage_contract": True,
            "template_coverage_contract": data.get("template_coverage_contract", {}),
            "require_cross_level_interface_contracts": True,
            "cross_level_interface_contracts": data.get("cross_level_interface_contracts", {}),
            "require_operator_display_contract": True,
            "operator_display_contract": data.get("operator_display_contract", {}),
            "require_detail_information_gain_contracts": True,
            "detail_information_gain_contracts": data.get("detail_information_gain_contracts", {}),
            "require_runtime_variant_contracts": True,
            "runtime_variant_contracts": data.get("runtime_variant_contracts", {}),
            "require_state_lifecycle_contracts": True,
            "state_lifecycle_contracts": data.get("state_lifecycle_contracts", {}),
            "require_semantic_style_contract": True,
            "require_semantic_glyph_contract": True,
            "require_vertical_flow_contracts": True,
            "regions": region_ids,
            "region_parents": region_parents,
            "region_content_contracts": region_content,
            "hierarchy_anchors": hierarchy_anchors,
            "required_cells": region_ids + node_ids + edge_ids + arrow_ids + fusion_boundary_ids + legend_ids + list(markers),
            "execution_fusion_ledger": execution_fusion_ledger(data),
            "fusion_presentation_policy": fusion_policy,
            "expected_edges": expected_edges,
            "expected_edge_labels": {
                f"edge:{edge_id}": visual_edge_label(edge, edge_id=edge_id)
                for edge_id, edge in data["edges"].items() if edge.get("kind") != "expand"
            },
            "node_semantics": node_semantics,
            "semantic_style_contract": {
                "profile": "dpsk-v4-original",
                "palette": SEMANTIC_PALETTE,
                "tp_partition_modifier": TP_PARTITION_MODIFIER,
                "glyphs": SEMANTIC_GLYPHS,
                "nodes": {
                    f"node:{node_id}": {
                        "visual_class": resolve_visual_class(node),
                        "visual_modifiers": node.get("visual_modifiers", []),
                        "glyph": semantic_glyph(node),
                    }
                    for node_id, node in data["nodes"].items()
                    if node.get("kind") != "junction"
                },
                "legend_title": "legend:title",
                "legend_entries": {item: f"legend:{item}" for item in LEGEND_ENTRIES},
                "legend_glyphs": {
                    item: ("storage" if item == "cache" else "operator")
                    for item in LEGEND_ENTRIES if item != "tp-partition"
                },
            },
            "semantic_coverage_exclusions": fusion_boundary_ids + legend_ids,
            "ignore_geometry": fusion_boundary_ids + legend_ids + list(markers),
            "granularity_contracts": granularity,
            "vertical_flow_contracts": vertical_flow,
            "maximum_vertical_flow_lateral_gap_ratio": 4.0,
            "minimum_vertical_flow_lateral_gap_allowance": 240,
            "vertical_flow_lateral_gap_exclusions": {},
            "minimum_node_gutter": round(max(16.0, ordinary_font * 0.9), 2),
            "node_gutter_exclusions": {},
            "minimum_route_node_clearance": round(max(16.0, ordinary_font * 1.2), 2),
            "route_node_clearance_exclusions": {},
            "minimum_route_region_boundary_clearance": round(max(24.0, ordinary_font * 2.0), 2),
            "route_region_clearance_exclusions": {},
            "require_compact_execution_geometry": True,
            # Top includes the generated title header; the other sides contain padding only.
            "maximum_region_content_slack": {
                "left": round(max(120.0, ordinary_font * 6.0), 2),
                "right": round(max(120.0, ordinary_font * 6.0), 2),
                "top": round(max(160.0, ordinary_font * 6.0), 2),
                "bottom": round(max(120.0, ordinary_font * 6.0), 2),
            },
            "region_side_slack_exceptions": {},
            "maximum_parallel_lane_gap": round(max(120.0, ordinary_font * 6.0), 2),
            "parallel_lane_gap_exceptions": {},
            "maximum_straight_hierarchy_arrow_aspect_ratio": 6.0,
            "straight_hierarchy_arrow_aspect_exceptions": {},
            "density_contract": {
                "minimum_region_content_width_ratio": 0.35,
                "minimum_region_content_height_ratio": 0.35,
                "maximum_trailing_right_ratio": 0.30,
                "maximum_trailing_bottom_ratio": 0.30,
                "maximum_horizontal_region_gap": 240,
                "maximum_vertical_region_gap": 180,
                "minimum_perpendicular_overlap_ratio": 0.25,
                "minimum_internal_void_area_ratio": 0.12,
                "minimum_internal_void_width_ratio": 0.30,
                "minimum_internal_void_height_ratio": 0.20,
                "internal_void_grid_size": 40,
                "internal_void_node_padding": 12,
                "region_exceptions": {},
                "gap_exceptions": {},
            },
            "rendered_svg_audit": {
                "line_jump_crossings": line_jump_crossings,
                "ignored_cells": {
                    **{mid: "Generated shared-terminal junction marker; exact position and glyph audited statically."
                       for mid in markers},
                    **{
                    cell_id: "Generated fusion boundary; ownership and membership are validated before compilation."
                    for cell_id in fusion_boundary_ids
                    },
                },
                "allowed_label_overlaps": {}, "allowed_label_node_overlaps": {},
                "allowed_edge_text_crossings": {}, "allowed_edge_node_crossings": {},
                "allowed_labels_outside_nodes": {}, "allowed_label_at_bends": {},
                "allowed_edge_label_distances": {},
                "maximum_edge_label_distance": 64,
                "minimum_visible_edge_label_flank": round(max(10.0, edge_label_font * 1.1), 2),
                "minimum_edge_label_route_clearance": round(max(2.0, edge_label_font * 0.2), 2),
            },
        },
        "render": {"overview_width": 2560, "detail_width": 4800, "detail_regions": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--layout", type=Path)
    args = parser.parse_args()
    data = load(args.architecture)
    errors = validate(data, args.architecture.parent)
    if errors:
        print("audit manifest: FAIL; architecture IR is invalid")
        return 1
    layout = json.loads(args.layout.read_text(encoding="utf-8")) if args.layout else None
    try:
        manifest = build_manifest(data, layout)
    except ValueError as error:
        print(f"audit manifest: FAIL; {error}")
        return 1
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"audit manifest: PASS ({args.output})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
