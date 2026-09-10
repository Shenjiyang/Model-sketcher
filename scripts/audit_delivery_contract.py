#!/usr/bin/env python3
"""Fail closed when a Draw.io architecture project omits delivery evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from audit_topology_review import validate_review
from view_projection import project_layout_view
from fusion_presentation import validate_fusion_presentation


DETAIL_PATTERN = re.compile(r"\b(?:LEVEL\s+[23][A-Z]?|FLOPS?|OPERATOR(?:-DETAIL)?)\b", re.I)
VALID_MODES = {"module-summary", "operator-detail", "implementation-detail"}
VALID_SOURCE_ROLES = {
    "checkpoint-config", "canonical-model", "official-report",
    "inference-implementation", "supporting-analysis",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def resolve_project_file(manifest_path: Path, value: object, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        fail(errors, f"workflow_contract.{field} must name a non-empty project file")
        return None
    path = (manifest_path.parent / value).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        fail(errors, f"workflow_contract.{field} is missing or empty: {path}")
    return path


def validate_manifest(diagram: Path, manifest_path: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, [f"cannot read manifest: {error}"]

    defaults = manifest.get("defaults")
    if not isinstance(defaults, dict):
        return manifest, ["manifest.defaults must be an object"]

    workflow = manifest.get("workflow_contract")
    if not isinstance(workflow, dict):
        fail(errors, "top-level workflow_contract is required for strict delivery")
        workflow = {}

    if workflow.get("output_view") not in {"hierarchy-master", "end-to-end-dataflow", "paired"}:
        fail(errors, "workflow_contract.output_view must be hierarchy-master, end-to-end-dataflow, or paired")
    resolve_project_file(manifest_path, workflow.get("evidence_file"), "evidence_file", errors)
    architecture_path = resolve_project_file(
        manifest_path, workflow.get("architecture_file"), "architecture_file", errors
    )
    topology_path = resolve_project_file(
        manifest_path, workflow.get("topology_contract_file"), "topology_contract_file", errors
    )
    topology_review_path = resolve_project_file(
        manifest_path, workflow.get("topology_review_file"), "topology_review_file", errors
    )
    resolve_project_file(manifest_path, workflow.get("shape_ledger_file"), "shape_ledger_file", errors)
    if all(
        path is not None and path.is_file()
        for path in (architecture_path, topology_path, topology_review_path)
    ):
        errors.extend(validate_review(architecture_path, topology_path, topology_review_path))

    projected = None
    if architecture_path is not None and architecture_path.is_file() and defaults.get("semantic_view"):
        try:
            projected = project_layout_view(json.loads(architecture_path.read_text()),
                                            {"semantic_view": defaults["semantic_view"]})
        except (ValueError, KeyError, TypeError) as error:
            fail(errors, f"cannot materialize declared delivery view: {error}")
        if projected is not None:
            errors.extend(validate_fusion_presentation(projected, defaults))
            for field in ("cross_level_interface_contracts", "operator_display_contract",
                          "runtime_variant_contracts", "state_lifecycle_contracts",
                          "external_canonical_references"):
                if defaults.get(field, {}) != projected.get(field, {}):
                    fail(errors, f"defaults.{field} differs from the canonical reader-view projection")

    evidence_sources = workflow.get("evidence_sources")
    if not isinstance(evidence_sources, list) or len(evidence_sources) < 2:
        fail(errors, "workflow_contract.evidence_sources must contain at least two versioned sources")
    else:
        source_roles: set[str] = set()
        for index, source in enumerate(evidence_sources):
            if not isinstance(source, dict) or not source.get("path") or not source.get("claims"):
                fail(errors, f"workflow_contract.evidence_sources[{index}] requires path and claims")
                continue
            source_path = Path(source["path"])
            if not source_path.is_absolute():
                source_path = (manifest_path.parent / source_path).resolve()
            if not source_path.is_file():
                fail(errors, f"workflow_contract.evidence_sources[{index}] does not exist: {source_path}")
            if "revision" not in source:
                fail(errors, f"workflow_contract.evidence_sources[{index}] requires revision (use 'unknown' explicitly)")
            role = source.get("role")
            if role not in VALID_SOURCE_ROLES:
                fail(errors, f"workflow_contract.evidence_sources[{index}] has invalid or missing role: {role!r}")
            else:
                source_roles.add(role)
        if "checkpoint-config" not in source_roles:
            fail(errors, "evidence_sources requires a checkpoint-config source")
        if not source_roles.intersection({"canonical-model", "inference-implementation"}):
            fail(errors, "evidence_sources requires executable model evidence")

    if defaults.get("require_granularity_contracts") is not True:
        fail(errors, "defaults.require_granularity_contracts must be true")
    if defaults.get("require_logical_operator_contracts") is not True:
        fail(errors, "defaults.require_logical_operator_contracts must be true")
    if defaults.get("require_source_coverage") is not True:
        fail(errors, "defaults.require_source_coverage must be true")
    if defaults.get("require_view_projection_contracts") is not True:
        fail(errors, "defaults.require_view_projection_contracts must be true")
    if not isinstance(defaults.get("semantic_view"), str) or not defaults["semantic_view"].strip():
        fail(errors, "defaults.semantic_view must name the compiled reader-view projection")
    if not isinstance(defaults.get("view_projection_contract"), dict):
        fail(errors, "defaults.view_projection_contract must be an object")
    elif defaults.get("semantic_view") not in defaults["view_projection_contract"].get("views", {}):
        fail(errors, "defaults.semantic_view must exist in defaults.view_projection_contract.views")
    if defaults.get("require_reader_facing_labels") is not True:
        fail(errors, "defaults.require_reader_facing_labels must be true")
    summary_contracts = (
        "overview_contract",
        "template_coverage_contract",
        "cross_level_interface_contracts",
        "operator_display_contract",
        "detail_information_gain_contracts",
        "runtime_variant_contracts",
        "state_lifecycle_contracts",
    )
    for field in summary_contracts:
        if defaults.get(f"require_{field}") is not True:
            fail(errors, f"defaults.require_{field} must be true")
        if not isinstance(defaults.get(field), dict):
            fail(errors, f"defaults.{field} must be an object")

    hierarchy_anchors = defaults.get("hierarchy_anchors", {})
    cross_level = defaults.get("cross_level_interface_contracts", {})
    if isinstance(hierarchy_anchors, dict) and isinstance(cross_level, dict):
        expected_expand_ids = {
            anchor_id.removeprefix("expand:") for anchor_id in hierarchy_anchors
        }
        if set(cross_level) != expected_expand_ids:
            fail(
                errors,
                "defaults.cross_level_interface_contracts must match hierarchy_anchors exactly; "
                f"missing={sorted(expected_expand_ids - set(cross_level))}, "
                f"extra={sorted(set(cross_level) - expected_expand_ids)}",
            )
        for edge_id, contract in cross_level.items():
            if not isinstance(contract, dict):
                fail(errors, f"defaults.cross_level_interface_contracts.{edge_id} must be an object")
                continue
            for field in ("parent_shape", "child_shape", "mapping", "status"):
                if not isinstance(contract.get(field), str) or not contract[field].strip():
                    fail(errors, f"defaults.cross_level_interface_contracts.{edge_id}.{field} is required")
            evidence = contract.get("evidence")
            if not isinstance(evidence, list) or not evidence or not all(
                isinstance(item, str) and item.strip() for item in evidence
            ):
                fail(errors, f"defaults.cross_level_interface_contracts.{edge_id}.evidence is required")
    if defaults.get("require_port_geometry_contracts") is not True:
        fail(errors, "defaults.require_port_geometry_contracts must be true")
    if not isinstance(defaults.get("expected_ports"), dict):
        fail(errors, "defaults.expected_ports must be an object")
    if defaults.get("require_registered_edge_label_positions") is not True:
        fail(errors, "defaults.require_registered_edge_label_positions must be true")
    if not isinstance(defaults.get("expected_edge_label_positions"), dict):
        fail(errors, "defaults.expected_edge_label_positions must be an object")
    if defaults.get("require_semantic_style_contract") is not True:
        fail(errors, "defaults.require_semantic_style_contract must be true")
    if not isinstance(defaults.get("semantic_style_contract"), dict):
        fail(errors, "defaults.semantic_style_contract must be an object")
    if defaults.get("require_semantic_glyph_contract") is not True:
        fail(errors, "defaults.require_semantic_glyph_contract must be true")
    if defaults.get("require_semantic_coverage") is not True:
        fail(errors, "defaults.require_semantic_coverage must be true")
    if defaults.get("require_compact_execution_geometry") is not True:
        fail(errors, "defaults.require_compact_execution_geometry must be true")

    regions = defaults.get("regions", [])
    contracts = defaults.get("granularity_contracts", {})
    if not isinstance(regions, list) or not regions:
        fail(errors, "defaults.regions must declare the visible ownership regions")
    if not isinstance(contracts, dict):
        fail(errors, "defaults.granularity_contracts must be an object")
        contracts = {}

    # The static auditor checks the actual labels. This contract-level check
    # prevents an empty contract registry from being accepted before parsing.
    for region_id, contract in contracts.items():
        if not isinstance(contract, dict) or contract.get("mode") not in VALID_MODES:
            fail(errors, f"invalid granularity contract mode: {region_id}")
        elif not isinstance(contract.get("level"), int) or contract["level"] < 0:
            fail(errors, f"granularity contract requires a non-negative level: {region_id}")

    expected_detail_expands = {
        anchor_id.removeprefix("expand:") for anchor_id, anchor in hierarchy_anchors.items()
        if isinstance(anchor, dict)
        and contracts.get(anchor.get("child"), {}).get("level") in {2, 3}
    }
    gains = defaults.get("detail_information_gain_contracts", {})
    if set(gains) != expected_detail_expands:
        fail(errors, "defaults.detail_information_gain_contracts must match Level 2/3 hierarchy anchors exactly")
    elif any(
        not isinstance(contract, dict)
        or contract.get("status") != "pass"
        or contract.get("method") != "parent-child-delta-review"
        or not contract.get("new_information")
        for contract in gains.values()
    ):
        fail(errors, "every detail information gain contract must record a non-empty reviewed delta")
    else:
        for edge_id, contract in gains.items():
            if not isinstance(contract.get("parent_region"), str) or not isinstance(contract.get("child_region"), str):
                fail(errors, f"detail information gain {edge_id} requires parent_region and child_region")
            if not all(
                isinstance(item, dict)
                and isinstance(item.get("kind"), str)
                and isinstance(item.get("summary"), str) and item["summary"].strip()
                and isinstance(item.get("nodes"), list) and item["nodes"]
                and isinstance(item.get("evidence"), list) and item["evidence"]
                for item in contract["new_information"]
            ):
                fail(errors, f"detail information gain {edge_id} has an incomplete delta record")

    expected_runtime_regions = {
        region_id.removeprefix("region:") for region_id, contract in contracts.items()
        if isinstance(contract, dict) and contract.get("mode") == "implementation-detail"
    }
    runtime = defaults.get("runtime_variant_contracts", {})
    if set(runtime) != expected_runtime_regions:
        fail(errors, "defaults.runtime_variant_contracts must match implementation-detail regions exactly")
    else:
        for region_id, contract in runtime.items():
            if not isinstance(contract, dict) or contract.get("status") not in {"pass", "not-applicable"}:
                fail(errors, f"runtime variant {region_id} has an invalid status")
                continue
            verified_selection = (projected is not None
                                  and contract == projected.get("runtime_variant_contracts", {}).get(region_id)
                                  and contract.get("projection_selection", {}).get("view") == defaults.get("semantic_view"))
            if contract["status"] == "pass" and (
                contract.get("method") != "source-branch-review"
                or not isinstance(contract.get("variants"), list)
                or (len(contract["variants"]) < 2 and not verified_selection)
                or not contract.get("source_discriminators")
            ):
                fail(errors, f"runtime variant {region_id} lacks reviewed branch mappings")
            if contract["status"] == "not-applicable" and not contract.get("reason"):
                fail(errors, f"runtime variant {region_id} not-applicable requires a reason")
            if not contract.get("evidence") or not contract.get("findings"):
                fail(errors, f"runtime variant {region_id} requires evidence and findings")

    semantics = defaults.get("node_semantics", {})
    expected_state_nodes = {
        node_id.removeprefix("node:") for node_id, semantic in semantics.items()
        if isinstance(semantic, dict) and semantic.get("kind") in {"cache", "state"}
    } if isinstance(semantics, dict) else set()
    lifecycles = defaults.get("state_lifecycle_contracts", {})
    if set(lifecycles) != expected_state_nodes:
        fail(errors, "defaults.state_lifecycle_contracts must match cache/state nodes exactly")
    else:
        for node_id, contract in lifecycles.items():
            if not isinstance(contract, dict):
                fail(errors, f"state lifecycle {node_id} must be an object")
                continue
            if contract.get("status") != "pass" or contract.get("method") != "state-lifecycle-review":
                fail(errors, f"state lifecycle {node_id} lacks a passing lifecycle review")
            for field in ("storage_shape", "layout", "dtype", "scope", "lifetime"):
                if not isinstance(contract.get(field), str) or not contract[field].strip():
                    fail(errors, f"state lifecycle {node_id}.{field} is required")
            external_state = {}
            if (projected is not None
                    and contract == projected.get("state_lifecycle_contracts", {}).get(node_id)):
                external_state = projected.get("external_canonical_references", {}).get("state_lifecycles", {}).get(node_id, {})
            if not contract.get("writers") and not contract.get("initial_state_reason") and not external_state.get("writers"):
                fail(errors, f"state lifecycle {node_id} requires writers or initial_state_reason")
            if not contract.get("readers") and not contract.get("output_state_reason") and not external_state.get("readers"):
                fail(errors, f"state lifecycle {node_id} requires readers or output_state_reason")
            if not contract.get("evidence"):
                fail(errors, f"state lifecycle {node_id}.evidence is required")

    hierarchy_view = workflow.get("output_view") in {"hierarchy-master", "paired"}
    level0_regions = {
        region_id.removeprefix("region:")
        for region_id, contract in contracts.items()
        if isinstance(contract, dict) and contract.get("level") == 0
    }
    overview = defaults.get("overview_contract")
    if hierarchy_view:
        if not level0_regions:
            fail(errors, "hierarchy/paired delivery requires at least one Level 0 region")
        if not isinstance(overview, dict) or not overview:
            fail(errors, "hierarchy/paired delivery requires a non-empty defaults.overview_contract")
        elif overview.get("status") != "pass" or overview.get("method") != "standalone-reader-review":
            fail(errors, "defaults.overview_contract requires pass via standalone-reader-review")
        elif set(overview.get("level0_region_ids", [])) != level0_regions:
            fail(errors, "defaults.overview_contract.level0_region_ids must match Level 0 regions exactly")

    vertical_flow = defaults.get("vertical_flow_contracts", {})
    sequenced_level1 = {
        region_id.removeprefix("region:")
        for region_id, contract in contracts.items()
        if isinstance(contract, dict)
        and contract.get("level") == 1
        and isinstance(vertical_flow, dict)
        and isinstance(vertical_flow.get(region_id), dict)
        and vertical_flow[region_id].get("sequences")
    }
    template = defaults.get("template_coverage_contract")
    if sequenced_level1:
        if not isinstance(template, dict) or not template:
            fail(errors, "sequenced Level 1 delivery requires a non-empty defaults.template_coverage_contract")
        elif template.get("status") != "pass" or template.get("method") != "template-family-review":
            fail(errors, "defaults.template_coverage_contract requires pass via template-family-review")
        elif set(template.get("regions", {})) != sequenced_level1:
            fail(errors, "defaults.template_coverage_contract.regions must match sequenced Level 1 regions exactly")

    has_operator_detail = any(
        isinstance(contract, dict) and contract.get("mode") == "operator-detail"
        for contract in contracts.values()
    )
    if has_operator_detail and not defaults.get("operator_display_contract"):
        fail(errors, "operator-detail delivery requires a non-empty defaults.operator_display_contract")
    elif has_operator_detail:
        display = defaults["operator_display_contract"]
        expected_operator_regions = {
            region_id.removeprefix("region:")
            for region_id, contract in contracts.items()
            if isinstance(contract, dict) and contract.get("mode") == "operator-detail"
        }
        if display.get("status") != "pass" or display.get("method") != "reader-shape-parameter-review":
            fail(errors, "defaults.operator_display_contract requires pass via reader-shape-parameter-review")
        elif set(display.get("reviewed_region_ids", [])) != expected_operator_regions:
            fail(errors, "defaults.operator_display_contract.reviewed_region_ids must match operator-detail regions exactly")

    if workflow.get("contains_detail_regions") is True and not contracts:
        fail(errors, "detail regions are declared but granularity_contracts is empty")

    render = manifest.get("render")
    if not isinstance(render, dict):
        fail(errors, "top-level render contract is required")
    else:
        details = render.get("detail_regions")
        if not isinstance(details, list) or len(details) < 2:
            fail(errors, "render.detail_regions must declare at least two manual-review regions")
        for key in ("overview_width", "detail_width"):
            if not isinstance(render.get(key), int) or render[key] <= 0:
                fail(errors, f"render.{key} must be a positive integer")

    if diagram.stem not in manifest_path.stem:
        fail(errors, "diagram and manifest stems do not match")
    return manifest, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagram", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rendered-svg", type=Path)
    args = parser.parse_args()

    _, errors = validate_manifest(args.diagram, args.manifest)
    if errors:
        print("delivery contract audit: FAIL")
        for error in errors:
            print(f"ERROR: {error}")
        return 2

    scripts = Path(__file__).resolve().parent
    static = subprocess.run(
        [sys.executable, str(scripts / "audit_drawio.py"), str(args.diagram), "--manifest", str(args.manifest)],
        check=False,
    )
    if static.returncode:
        print("delivery contract audit: FAIL (static audit)")
        return static.returncode

    if args.rendered_svg is not None:
        rendered = subprocess.run(
            [sys.executable, str(scripts / "audit_rendered_svg.py"), str(args.diagram), str(args.rendered_svg), "--manifest", str(args.manifest)],
            check=False,
        )
        if rendered.returncode:
            print("delivery contract audit: FAIL (rendered geometry)")
            return rendered.returncode

    print("delivery contract audit: PASS")
    if args.rendered_svg is None:
        print("NOTE: official Draw.io rendered geometry and manual visual review remain pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
