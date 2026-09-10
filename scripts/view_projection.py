#!/usr/bin/env python3
"""Select one reader-facing view from a complete canonical architecture IR."""

from __future__ import annotations

from copy import deepcopy


def active_view(data: dict) -> str | None:
    project = data.get("project", {})
    contract = data.get("view_projection_contract", {})
    view_id = project.get("semantic_view") if isinstance(project, dict) else None
    views = contract.get("views", {}) if isinstance(contract, dict) else {}
    return view_id if view_id in views else None


def project_layout_view(data: dict, layout: dict | None) -> dict:
    """Honor the layout's explicit view without rewriting canonical evidence."""
    if layout is None or "semantic_view" not in layout:
        return project_active_view(data)
    view_id = layout["semantic_view"]
    declared = data.get("view_projection_contract", {}).get("views", {})
    if not isinstance(view_id, str) or view_id not in declared:
        raise ValueError(f"layout declares unknown semantic view {view_id!r}")
    materialized = data.get("projection_materialization", {}).get("view")
    if materialized is not None and materialized != view_id:
        raise ValueError("layout view differs from materialized projection; use canonical IR")
    selected = deepcopy(data)
    selected.setdefault("project", {})["semantic_view"] = view_id
    return project_active_view(selected)


def project_active_view(data: dict) -> dict:
    """Return a visual slice while leaving the caller's canonical IR untouched."""
    view_id = active_view(data)
    if view_id is None:
        return data
    if data.get("projection_materialization", {}).get("view") == view_id:
        return deepcopy(data)
    if data.get("projection_materialization"):
        raise ValueError("select another view from canonical IR, not a materialized projection")
    result = deepcopy(data)
    regions = {
        item_id: item for item_id, item in result.get("regions", {}).items()
        if view_id in item.get("views", [])
    }
    nodes = {
        item_id: item for item_id, item in result.get("nodes", {}).items()
        if view_id in item.get("views", []) and item.get("region") in regions
    }
    edges = {
        item_id: item for item_id, item in result.get("edges", {}).items()
        if view_id in item.get("views", [])
        and item.get("source") in nodes and item.get("target") in nodes
    }
    tensor_pairs = {(edge.get("source"), edge.get("target"))
                    for edge in edges.values() if edge.get("kind") == "tensor"}
    for region in regions.values():
        sequences = []
        for sequence in region.get("operator_sequences", []):
            visible = [node_id for node_id in sequence.get("nodes", []) if node_id in nodes]
            runs = []
            for node_id in visible:
                if not runs or (runs[-1][-1], node_id) not in tensor_pairs:
                    runs.append([])
                runs[-1].append(node_id)
            for index, run in enumerate(runs):
                projected = dict(sequence)
                projected["nodes"] = run
                projected["projection"] = {
                    "canonical_sequence_id": sequence["id"],
                    "complete": len(runs) == 1 and run == sequence.get("nodes", []),
                }
                if len(runs) > 1:
                    projected["id"] = f"{sequence['id']}::projection-part-{index + 1}"
                sequences.append(projected)
        region["operator_sequences"] = sequences
    result["regions"], result["nodes"], result["edges"] = regions, nodes, edges
    result["repetitions"] = [
        item for item in result.get("repetitions", [])
        if item.get("region") in regions and item.get("target") in nodes
    ]
    result["execution_fusions"] = [
        item for item in result.get("execution_fusions", [])
        if all(node_id in nodes for node_id in item.get("operators", []))
        and item.get("owner_region") in regions
        and (not item.get("implementation_node") or item.get("implementation_node") in nodes)
    ]
    result["detail_information_gain_contracts"] = {
        edge_id: item for edge_id, item in result.get("detail_information_gain_contracts", {}).items()
        if edge_id in edges and item.get("parent_region") in regions and item.get("child_region") in regions
    }
    result["runtime_variant_contracts"] = {
        region_id: item for region_id, item in result.get("runtime_variant_contracts", {}).items()
        if region_id in regions
    }
    result["state_lifecycle_contracts"] = {
        node_id: item for node_id, item in result.get("state_lifecycle_contracts", {}).items()
        if node_id in nodes
    }
    _project_nested_contracts(result, data, view_id)
    result["projection_materialization"] = {"view": view_id}
    return result


def _project_nested_contracts(result: dict, canonical: dict, view_id: str) -> None:
    """Scope visual contracts; retain hidden evidence as non-visual references."""
    regions, nodes, edges = result["regions"], result["nodes"], result["edges"]
    external = result.setdefault("external_canonical_references", {})
    result["cross_level_interface_contracts"] = {
        edge_id: item for edge_id, item in result.get("cross_level_interface_contracts", {}).items()
        if edge_id in edges and edges[edge_id].get("kind") == "expand"
    }
    for edge_id, contract in result["cross_level_interface_contracts"].items():
        hidden = {}
        if contract.get("display_node") and contract["display_node"] not in nodes:
            hidden["display_node"] = contract.pop("display_node")
            hidden["display_text"] = contract.pop("display_text", "")
        consumers = contract.get("output_consumers", [])
        if any(node not in nodes for node in consumers):
            hidden["output_consumers"] = [node for node in consumers if node not in nodes]
            contract["output_consumers"] = [node for node in consumers if node in nodes]
        if hidden:
            external.setdefault("cross_level_interfaces", {})[edge_id] = hidden

    for name in ("operator_display_contract", "operator_naming_review"):
        if name in result:
            result[name]["reviewed_region_ids"] = [
                rid for rid in result[name].get("reviewed_region_ids", [])
                if rid in regions and regions[rid].get("granularity") == "operator-detail"
            ]
    overview = result.get("overview_contract", {})
    level0 = [rid for rid in overview.get("level0_region_ids", []) if rid in regions]
    if not level0:
        result["overview_contract"] = {}
    else:
        overview["level0_region_ids"] = level0
        overview["spine_nodes"] = [nid for nid in overview.get("spine_nodes", []) if nid in nodes]
        overview["facets"] = {
            key: [nid for nid in ids if nid in nodes]
            for key, ids in overview.get("facets", {}).items()
            if any(nid in nodes for nid in ids)
        }
        components = []
        for component in overview.get("signature_components", []):
            for field in ("level0_nodes", "level1_nodes"):
                component[field] = [nid for nid in component.get(field, []) if nid in nodes]
            if component.get("level0_nodes"):
                components.append(component)
        overview["signature_components"] = components
    template = result.get("template_coverage_contract", {})
    template_regions = {}
    for rid, entries in template.get("regions", {}).items():
        if rid not in regions:
            continue
        complete = {
            s["projection"]["canonical_sequence_id"]
            for s in regions[rid].get("operator_sequences", [])
            if s["projection"]["complete"]
        }
        visible_entries = []
        for entry in entries:
            if entry.get("sequence_id") in complete:
                entry["level0_nodes"] = [nid for nid in entry.get("level0_nodes", []) if nid in nodes]
                visible_entries.append(entry)
        if visible_entries:
            template_regions[rid] = visible_entries
    if template_regions:
        template["regions"] = template_regions
    else:
        result["template_coverage_contract"] = {}

    for rid, contract in result.get("runtime_variant_contracts", {}).items():
        complete = {
            s["projection"]["canonical_sequence_id"]
            for s in regions[rid].get("operator_sequences", [])
            if s["projection"]["complete"]
        }
        variants = contract.get("variants", [])
        retained = [v for v in variants if v.get("sequence_ids") and set(v["sequence_ids"]) <= complete]
        excluded = [v for v in variants if v not in retained]
        contract["variants"] = retained
        contract["shared_state_nodes"] = [nid for nid in contract.get("shared_state_nodes", []) if nid in nodes]
        contract["projection_selection"] = {
            "view": view_id,
            "canonical_status": contract.get("status"),
            "selected_variant_ids": [v["id"] for v in retained],
            "excluded_variant_ids": [v["id"] for v in excluded],
            "complete_sequence_ids": sorted(complete),
        }
        if excluded:
            external.setdefault("runtime_variants", {})[rid] = excluded

    for state_id, contract in result.get("state_lifecycle_contracts", {}).items():
        hidden = {}
        for field in ("writers", "readers"):
            retained, excluded = [], []
            for item in contract.get(field, []):
                operation, edge_id = item.get("operation"), item.get("edge")
                if operation not in nodes or edge_id not in edges:
                    excluded.append(item)
                    continue
                edge = edges[edge_id]
                expected = (operation, state_id) if field == "writers" else (state_id, operation)
                if (edge.get("source"), edge.get("target")) != expected:
                    raise ValueError(f"state {state_id} {field} edge {edge_id} has invalid direction")
                retained.append(item)
            contract[field] = retained
            if excluded:
                hidden[field] = excluded
        if hidden:
            external.setdefault("state_lifecycles", {})[state_id] = hidden
            contract["projection_selection"] = {
                "view": view_id, "external_reference": state_id,
                "external_writer_count": len(hidden.get("writers", [])),
                "external_reader_count": len(hidden.get("readers", [])),
            }

    visible_fusions = {fusion["id"] for fusion in result.get("execution_fusions", [])}
    canonical_fusions = {fusion["id"]: fusion for fusion in canonical.get("execution_fusions", [])}
    for node_id, node in nodes.items():
        contract = node.get("implementation_contract", {})
        if "logical_members" in contract:
            members = contract["logical_members"]
            if (not isinstance(members, list)
                    or any(not isinstance(nid, str) for nid in members)):
                raise ValueError(f"node {node_id} logical_members must be a node ID list")
            canonical_nodes = canonical.get("nodes", {})
            missing_members = [nid for nid in members if nid not in canonical_nodes]
            if missing_members:
                raise ValueError(f"node {node_id} references unknown canonical logical members {missing_members}")
            hidden_members = [nid for nid in members if nid not in nodes]
            contract["logical_members"] = [nid for nid in members if nid in nodes]
            if hidden_members:
                contract["external_logical_members"] = hidden_members
                for nid in hidden_members:
                    external.setdefault("logical_members", {})[nid] = deepcopy(canonical_nodes[nid])
        hidden = [fid for fid in contract.get("implements", []) if fid not in visible_fusions]
        if not hidden:
            continue
        missing = [fid for fid in hidden if fid not in canonical_fusions]
        if missing:
            raise ValueError(f"node {node_id} references unknown canonical fusions {missing}")
        contract["implements"] = [fid for fid in contract["implements"] if fid in visible_fusions]
        contract["external_implements"] = hidden
        for fid in hidden:
            external.setdefault("execution_fusions", {})[fid] = deepcopy(canonical_fusions[fid])
