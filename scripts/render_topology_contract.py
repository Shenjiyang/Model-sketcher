#!/usr/bin/env python3
"""Render a deterministic, reviewable ASCII topology contract from architecture IR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_architecture_ir import edge_display_label, load, validate


def ordered(mapping: dict, definitions: dict) -> list[str]:
    del definitions
    return sorted(mapping)


def render(data: dict) -> str:
    regions: dict[str, dict] = data["regions"]
    nodes: dict[str, dict] = data["nodes"]
    edges: dict[str, dict] = data.get("edges", {})
    children: dict[str | None, list[str]] = {None: []}
    for region_id, region in regions.items():
        children.setdefault(region.get("parent"), []).append(region_id)
        children.setdefault(region_id, [])
    for parent, ids in children.items():
        children[parent] = ordered(ids, regions)

    edge_by_pair: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for edge_id, edge in edges.items():
        edge_by_pair.setdefault((edge["source"], edge["target"]), []).append((edge_id, edge))

    lines = [
        "ASCII TOPOLOGY CONTRACT",
        "=======================",
        f"project: {data['project'].get('id', '')}",
        f"title: {data['project'].get('title', '')}",
        f"view: {data['project'].get('output_view', '')}",
        "delivery_scope: " + json.dumps(data['project'].get('delivery_scope'), sort_keys=True),
        "request_contract: " + json.dumps(data['project'].get('request_contract'), sort_keys=True),
        "",
        "EVIDENCE",
        "--------",
    ]
    for item in sorted(data.get("evidence", []), key=lambda value: value["id"]):
        lines.append(f"[{item['id']}] {item['role']} @ {item['revision']} :: {item['path']}")

    projections = data.get("view_projection_contract")
    lines.extend(["", "VIEW PROJECTIONS", "----------------"])
    if not isinstance(projections, dict):
        lines.append("not-enabled")
    else:
        for view_id, view in sorted(projections.get("views", {}).items()):
            lines.append(f"[{view_id}] {view['kind']} :: {view['purpose']}")
        for entity_kind, collection in (
            ("region", regions), ("node", nodes), ("edge", edges)
        ):
            for entity_id, entity in sorted(collection.items()):
                lines.append(
                    f"{entity_kind}[{entity_id}]: layer={entity.get('semantic_layer', '')} "
                    f":: views={','.join(sorted(entity.get('views', [])))}"
                )

    lines.extend(["", "SHAPE SYMBOLS", "-------------"])
    symbols = data.get("shape_symbols", {})
    if symbols:
        for symbol, meaning in sorted(symbols.items()):
            if isinstance(meaning, dict):
                meaning = meaning.get("meaning", "")
            lines.append(f"[{symbol}] {meaning}")
    else:
        lines.append("not-enabled")

    overview = data.get("overview_contract")
    lines.extend(["", "LEVEL 0 STANDALONE SYNOPSIS", "---------------------------"])
    if not isinstance(overview, dict):
        lines.append("not-applicable")
    else:
        lines.append(f"spine: {' -> '.join(overview['spine_nodes'])}")
        for facet, mapped in sorted(overview["facets"].items()):
            mapped_ids = [mapped] if isinstance(mapped, str) else mapped
            lines.append(f"facet[{facet}]: {','.join(mapped_ids)}")
        for component in sorted(overview["signature_components"], key=lambda value: value["id"]):
            lines.append(
                f"signature[{component['id']}]: {component['display_text']} "
                f":: level0={','.join(component['level0_nodes'])} "
                f":: level1={','.join(component.get('level1_nodes', [])) or '(none)'}"
            )

    templates = data.get("template_coverage_contract")
    lines.extend(["", "LEVEL 1 TEMPLATE COVERAGE", "-------------------------"])
    if not isinstance(templates, dict):
        lines.append("not-applicable")
    else:
        for region_id, entries in sorted(templates["regions"].items()):
            for entry in sorted(entries, key=lambda value: value["sequence_id"]):
                lines.append(
                    f"[{region_id}/{entry['sequence_id']}] {entry['summary']} "
                    f":: level0={','.join(entry['level0_nodes'])}"
                )

    interfaces = data.get("cross_level_interface_contracts")
    lines.extend(["", "CROSS-LEVEL INTERFACE CLOSURE", "-----------------------------"])
    if not isinstance(interfaces, dict) or not interfaces:
        lines.append("not-applicable")
    else:
        for edge_id, contract in sorted(interfaces.items()):
            visible = ""
            if contract.get("display_node"):
                visible = f" :: visible={contract['display_node']}:{contract['display_text']}"
            lines.append(
                f"[{edge_id}] {contract['parent_shape']} -> {contract['child_shape']} "
                f":: mapping={contract['mapping']} :: status={contract['status']}{visible}"
            )

    display = data.get("operator_display_contract")
    lines.extend(["", "OPERATOR DISPLAY CONTRACT", "-------------------------"])
    if not isinstance(display, dict):
        lines.append("not-applicable")
    else:
        lines.append(f"activation_shapes: {display['activation_shape_placement']}")
        lines.append(f"parameter_shapes: {display['parameter_shape_placement']}")
        lines.append(f"source_symbols: {display['source_symbol_placement']}")
        lines.append(f"reviewed_regions: {','.join(sorted(display['reviewed_region_ids']))}")

    gains = data.get("detail_information_gain_contracts")
    lines.extend(["", "DETAIL INFORMATION GAIN", "-----------------------"])
    if not isinstance(gains, dict) or not gains:
        lines.append("not-applicable")
    else:
        for edge_id, contract in sorted(gains.items()):
            lines.append(
                f"[{edge_id}] {contract['parent_region']} -> {contract['child_region']}"
            )
            for item in sorted(
                contract["new_information"],
                key=lambda value: (value["kind"], value["summary"], tuple(value["nodes"])),
            ):
                lines.append(
                    f"  + {item['kind']}: {item['summary']} :: nodes={','.join(item['nodes'])}"
                )

    variants = data.get("runtime_variant_contracts")
    lines.extend(["", "RUNTIME VARIANT COVERAGE", "------------------------"])
    if not isinstance(variants, dict) or not variants:
        lines.append("not-applicable")
    else:
        for region_id, contract in sorted(variants.items()):
            lines.append(f"[{region_id}] status={contract['status']}")
            if contract["status"] == "not-applicable":
                lines.append(f"  reason: {contract['reason']}")
                continue
            lines.append(f"  discriminators: {'; '.join(sorted(contract['source_discriminators']))}")
            for variant in sorted(contract["variants"], key=lambda value: value["id"]):
                lines.append(
                    f"  <{variant['id']}> sequences={','.join(sorted(variant['sequence_ids']))}"
                )
            lines.append(
                f"  shared_state: {','.join(sorted(contract.get('shared_state_nodes', []))) or '(none)'}"
            )

    lifecycles = data.get("state_lifecycle_contracts")
    lines.extend(["", "STATE / CACHE LIFECYCLES", "------------------------"])
    if not isinstance(lifecycles, dict) or not lifecycles:
        lines.append("not-applicable")
    else:
        for node_id, contract in sorted(lifecycles.items()):
            lines.append(
                f"[{node_id}] {contract['storage_shape']} :: layout={contract['layout']} "
                f":: dtype={contract['dtype']} :: scope={contract['scope']} :: lifetime={contract['lifetime']}"
            )
            for role in ("writers", "readers"):
                records = contract.get(role, [])
                if records:
                    for record in sorted(records, key=lambda value: (value["operation"], value["edge"])):
                        lines.append(
                            f"  {role[:-1]}: {record['operation']} via {record['edge']} "
                            f":: addressing={','.join(sorted(record['addressing']))}"
                        )
                else:
                    alternative = "initial_state_reason" if role == "writers" else "output_state_reason"
                    lines.append(f"  {role[:-1]}: {contract.get(alternative, '(none)')}")

    coverage = data.get("source_coverage")
    lines.extend(["", "SOURCE OPERATION COVERAGE", "-------------------------"])
    if not isinstance(coverage, dict):
        lines.append("not-enabled")
    else:
        lines.append(f"scope: {coverage['scope']}")
        lines.append(f"canonical_sources: {','.join(sorted(coverage.get('canonical_source_ids', []))) or '(none)'}")
        for path in sorted(coverage["paths"], key=lambda value: value["id"]):
            lines.append(f"<{path['id']}> evidence={path['evidence']} :: {path['source']}")
            lines.append(f"  regions: {','.join(sorted(path['regions']))}")
            for operation in sorted(path["operations"], key=lambda value: value["id"]):
                target = ""
                if "node" in operation:
                    target = f" -> node:{operation['node']}"
                elif "region" in operation:
                    target = f" -> region:{operation['region']}"
                reason = f" :: {operation['reason']}" if operation.get("reason") else ""
                lines.append(
                    f"  [{operation['id']}] {operation['label']} :: {operation['status']}{target}"
                    f" :: {operation['source']}{reason}"
                )

    lines.extend(["", "OWNERSHIP TREE", "--------------"])

    def emit_tree(region_id: str, prefix: str, last: bool) -> None:
        branch = "`-- " if last else "+-- "
        region = regions[region_id]
        level = f"L{region['level']}" if "level" in region else "L?"
        lines.append(f"{prefix}{branch}{region_id} [{level}; {region['granularity']}] :: {region['label']}")
        next_prefix = prefix + ("    " if last else "|   ")
        items = children[region_id]
        for index, child in enumerate(items):
            emit_tree(child, next_prefix, index == len(items) - 1)

    roots = children[None]
    for index, root in enumerate(roots):
        emit_tree(root, "", index == len(roots) - 1)

    for region_id in ordered(regions, regions):
        region = regions[region_id]
        owned = [item for item, node in nodes.items() if node["region"] == region_id]
        owned = ordered(owned, nodes)
        lines.extend([
            "",
            f"REGION {region_id}",
            "-" * (7 + len(region_id)),
            f"label: {region['label']}",
            f"level: {region.get('level', 'unspecified')}",
            f"granularity: {region['granularity']}",
            f"layout_axis: {region.get('direction', 'column')}",
            f"flow_direction: {region.get('flow_direction', 'unspecified')}",
            "nodes:",
        ])
        for node_id in owned:
            node = nodes[node_id]
            evidence = ",".join(sorted(node["evidence"]))
            operator_contract = node.get("operator_contract", {})
            classification = operator_contract.get("classification")
            role = f"; operator={classification}" if classification else ""
            if operator_contract.get("op_type"):
                role += f"; op_type={operator_contract['op_type']}"
            if operator_contract.get("semantic_role"):
                role += f"; semantic_role={operator_contract['semantic_role']}"
            if operator_contract.get("source_symbols"):
                role += f"; source_symbols={','.join(sorted(operator_contract['source_symbols']))}"
            if operator_contract.get("shape_rule"):
                role += f"; shape_rule={operator_contract['shape_rule']}"
            lines.append(f"  [{node_id}] {node['kind']}{role} :: {node['label']} :: evidence={evidence}")
            for parameter_shape in sorted(node.get("parameter_shapes", [])):
                lines.append(f"    parameter-shape: {parameter_shape}")
            if node.get("parameterless_reason"):
                lines.append(f"    parameterless: {node['parameterless_reason']}")
            if operator_contract.get("shape_equation"):
                lines.append(f"    shape-equation: {operator_contract['shape_equation']}")
            if operator_contract.get("decomposition_path"):
                lines.append(
                    "    decomposition-path: " + " -> ".join(operator_contract["decomposition_path"])
                )
            for output in sorted(
                operator_contract.get("packed_outputs", []),
                key=lambda value: (value["name"], value["edge"]),
            ):
                lines.append(
                    f"    packed-output: {output['name']} {output['shape']} "
                    f"via edge:{output['edge']} -> node:{output['consumer']}"
                )
            if classification == "expanded-elsewhere":
                lines.append(
                    f"    expanded-detail: region:{operator_contract['detail_region']} "
                    f":: {operator_contract['reason']}"
                )
            if operator_contract.get("op_type") == "custom":
                lines.append(
                    "    custom-definition: "
                    f"{operator_contract['definition']} :: formula={operator_contract['formula']} "
                    f":: atomicity={operator_contract['atomicity_reason']}"
                )

        for node_id in sorted(owned):
            implementation = nodes[node_id].get("implementation_contract")
            if implementation:
                lines.append(f"  implementation-contract: node:{node_id} :: " + json.dumps(implementation, sort_keys=True))

        loop = region.get("loop_contract")
        if loop:
            lines.append("indexed_loop_contract:")
            lines.append(f"  domain: {loop['domain']}")
            lines.append("  step-inputs: " + ", ".join(f"node:{nid}" for nid in sorted(loop['step_inputs'])))
            lines.append(f"  state-input: node:{loop['state_input']}")
            lines.append(f"  state-output: node:{loop['state_output']}")
            lines.append(f"  feedback: {loop['feedback']}")
            lines.append(f"  output-assembly: node:{loop['output_assembly']}")
            lines.append(f"  physical-execution: {loop['physical_execution']}")
            lines.append(f"  source: {loop['source']} :: evidence={','.join(sorted(loop['evidence']))}")

        sequences = region.get("operator_sequences", [])
        consumed_edges: set[str] = set()
        if sequences:
            lines.append("operator_sequences:")
            for sequence in sorted(sequences, key=lambda value: value["id"]):
                lines.append(f"  <{sequence['id']}>")
                path = sequence["nodes"]
                lines.append(f"    [{path[0]}]")
                for source, target in zip(path, path[1:]):
                    matches = sorted(
                        (
                            (edge_id, edge) for edge_id, edge in edge_by_pair[(source, target)]
                            if edge["kind"] == "tensor"
                        ),
                        key=lambda item: item[0],
                    )
                    consumed_edges.update(edge_id for edge_id, _ in matches)
                    transitions = "; ".join(
                        f"{edge_id}: {edge_display_label(edge) or 'tensor'}"
                        for edge_id, edge in matches
                    )
                    lines.append(f"      --({transitions})--> [{target}]")
        else:
            lines.append("operator_sequences: not-required-for-single-block-region")

        related = [
            (edge_id, edge) for edge_id, edge in sorted(edges.items())
            if edge_id not in consumed_edges and (edge["source"] in owned or edge["target"] in owned)
        ]
        lines.append("additional_relations:")
        if not related:
            lines.append("  (none)")
        for edge_id, edge in related:
            label = edge_display_label(edge)
            lines.append(
                f"  ({edge_id}) [{edge['source']}] --{edge['kind']}:{label}--> [{edge['target']}]"
            )

    lines.extend(["", "REPETITION BOUNDARIES", "---------------------"])
    repetitions = data.get("repetitions", [])
    if not repetitions:
        lines.append("(none)")
    for repetition in sorted(
        repetitions,
        key=lambda value: (value["region"], value["target"], str(value["count"])),
    ):
        lines.append(
            f"[region:{repetition['region']}/node:{repetition['target']}] x{repetition['count']}"
        )

    lines.extend(["", "EXECUTION FUSIONS", "-----------------"])
    fusions = data.get("execution_fusions", [])
    if not fusions:
        lines.append("(none)")
    for fusion in sorted(fusions, key=lambda value: value["id"]):
        evidence = ",".join(fusion.get("evidence", []))
        members = " -> ".join(fusion.get("operators", []))
        lines.append(
            f"[{fusion['id']}] {fusion['label']} :: {members} :: topology={fusion['topology']} "
            f":: visualization={fusion['visualization']} :: evidence={evidence} :: {fusion['source']}"
        )

    unresolved = data.get("unresolved_claims", [])
    lines.extend(["", "UNRESOLVED CLAIMS", "-----------------"])
    if unresolved:
        for item in sorted(unresolved, key=lambda value: json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)):
            lines.append(f"- {item if isinstance(item, str) else item.get('claim', item)}")
    else:
        lines.append("(none)")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = load(args.architecture)
    errors = validate(data, args.architecture.parent)
    if errors:
        print("ASCII topology contract: FAIL; architecture IR is invalid")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    args.output.write_text(render(data), encoding="utf-8")
    print(f"ASCII topology contract: PASS ({args.output})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
