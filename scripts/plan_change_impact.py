#!/usr/bin/env python3
"""Compute a conservative region-level change set between two architecture IR revisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_architecture_ir import load, validate


POLICIES = {"preserve", "adaptive", "derived", "frozen"}


def validate_state(state: dict, architecture: dict) -> list[str]:
    errors: list[str] = []
    from layout_intents import validate_hints
    try:
        validate_hints(architecture, state.get('layout_hints'), projected=False)
    except ValueError as error:
        errors.append(str(error))
    regions, nodes, edges = architecture.get("regions", {}), architecture.get("nodes", {}), architecture.get("edges", {})
    ordinary_edges = {edge_id: edge for edge_id, edge in edges.items() if edge.get("kind") != "expand"}
    hierarchy_arrows = {edge_id: edge for edge_id, edge in edges.items() if edge.get("kind") == "expand"}
    for region_id, value in state.get("region_policies", {}).items():
        if region_id not in regions:
            errors.append(f"region policy names unknown region {region_id!r}")
            continue
        policy = value.get("policy") if isinstance(value, dict) else value
        if policy not in POLICIES:
            errors.append(f"region {region_id} has invalid stability policy {policy!r}")
    allowed_fields = {
        "regions": {"x", "y", "w", "h"},
        "nodes": {"x", "y", "w", "h"},
        "edges": {"source_port", "target_port", "waypoints"},
        "hierarchy_arrows": {"x", "y", "w", "h"},
    }
    known = {
        "regions": regions, "nodes": nodes, "edges": ordinary_edges,
        "hierarchy_arrows": hierarchy_arrows,
    }
    for section, overrides in state.get("layout_overrides", {}).items():
        if section not in allowed_fields:
            errors.append(f"unknown layout override section {section!r}")
            continue
        if not isinstance(overrides, dict):
            errors.append(f"layout_overrides.{section} must be an object")
            continue
        for item_id, override in overrides.items():
            if item_id not in known[section]:
                errors.append(f"layout override names unknown {section[:-1]} {item_id!r}")
            if not isinstance(override, dict):
                errors.append(f"layout override {section}.{item_id} must be an object")
            else:
                unexpected = set(override) - allowed_fields[section]
                if unexpected:
                    errors.append(f"layout override {section}.{item_id} has invalid fields {sorted(unexpected)}")
    return errors


def changed_ids(old: dict, new: dict, section: str) -> set[str]:
    before = old.get(section, {})
    after = new.get(section, {})
    return {item for item in set(before) | set(after) if before.get(item) != after.get(item)}


def policy_for(state: dict, region_id: str) -> str:
    value = state.get("region_policies", {}).get(region_id, "adaptive")
    if isinstance(value, dict):
        value = value.get("policy", "adaptive")
    return value if value in POLICIES else "adaptive"


def analyze(old: dict, new: dict, state: dict | None = None) -> dict:
    state = state or {}
    changed_nodes = changed_ids(old, new, "nodes")
    changed_edges = changed_ids(old, new, "edges")
    changed_regions = changed_ids(old, new, "regions")
    old_project, new_project = old.get("project", {}), new.get("project", {})
    project_fields = sorted(key for key in set(old_project) | set(new_project) if old_project.get(key) != new_project.get(key))
    global_project_changed = old_project.get("output_view") != new_project.get("output_view")

    affected_nodes = set(changed_nodes)
    all_edges = {**old.get("edges", {}), **new.get("edges", {})}
    changed = True
    while changed:
        changed = False
        for edge in all_edges.values():
            if not isinstance(edge, dict):
                continue
            if edge.get("source") in affected_nodes and edge.get("target") not in affected_nodes:
                affected_nodes.add(edge.get("target"))
                changed = True

    affected_regions = set(changed_regions)
    for node_id in affected_nodes:
        for document in (new, old):
            node = document.get("nodes", {}).get(node_id)
            if isinstance(node, dict) and node.get("region"):
                affected_regions.add(node["region"])
    for edge_id in changed_edges:
        edge = new.get("edges", {}).get(edge_id) or old.get("edges", {}).get(edge_id)
        if isinstance(edge, dict):
            for endpoint in (edge.get("source"), edge.get("target")):
                node = new.get("nodes", {}).get(endpoint) or old.get("nodes", {}).get(endpoint)
                if isinstance(node, dict) and node.get("region"):
                    affected_regions.add(node["region"])

    regions = {**old.get("regions", {}), **new.get("regions", {})}
    for region_id in list(affected_regions):
        cursor = region_id
        while cursor in regions and isinstance(regions[cursor], dict):
            parent = regions[cursor].get("parent")
            if parent is None:
                break
            affected_regions.add(parent)
            cursor = parent

    all_region_ids = set(old.get("regions", {})) | set(new.get("regions", {}))
    blockers = [
        f"region {region_id} is frozen but was invalidated"
        for region_id in sorted(affected_regions) if policy_for(state, region_id) == "frozen"
    ]

    structural = bool(changed_edges or changed_regions or set(old.get("nodes", {})) != set(new.get("nodes", {})))
    if global_project_changed:
        mode = "full-rebuild"
        affected_regions = all_region_ids
    elif structural:
        mode = "regional-reflow"
    elif changed_nodes or project_fields:
        mode = "patch"
    else:
        mode = "no-op"
    return {
        "schema_version": 1,
        "mode": mode,
        "requested_changes": {
            "nodes": sorted(changed_nodes), "edges": sorted(changed_edges), "regions": sorted(changed_regions),
            "project_fields": project_fields,
        },
        "affected_nodes": sorted(item for item in affected_nodes if item is not None),
        "affected_regions": sorted(affected_regions),
        "preserved_regions": sorted(all_region_ids - affected_regions),
        "region_policies": {region_id: policy_for(state, region_id) for region_id in sorted(all_region_ids)},
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_architecture", type=Path)
    parser.add_argument("new_architecture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    old, new = load(args.old_architecture), load(args.new_architecture)
    errors = validate(new, args.new_architecture.parent)
    if errors:
        print("change impact: FAIL; new architecture IR is invalid")
        return 1
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state and args.state.is_file() else {}
    state_errors = validate_state(state, new)
    if state_errors:
        print("change impact: FAIL; project state is invalid")
        for error in state_errors:
            print(f"ERROR: {error}")
        return 1
    result = analyze(old, new, state)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if result["blockers"]:
        print("change impact: BLOCKED")
        for blocker in result["blockers"]:
            print(f"ERROR: {blocker}")
        return 2
    print(f"change impact: PASS ({result['mode']}; {len(result['affected_regions'])} affected regions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
