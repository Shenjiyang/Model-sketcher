#!/usr/bin/env python3
"""Validate an independent topology review against current IR, ASCII, and evidence bytes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from topology_review_common import (
    RECONSTRUCTION_REVIEW_CHECKS,
    REVIEW_TRIGGERS,
    SEMANTIC_REVIEW_CHECKS,
    SOURCE_INVENTORY_KINDS,
    is_concrete_text,
    resolve_evidence_path,
    semantic_json_sha256,
    review_payload_sha256,
    sha256,
)
from render_topology_contract import render
from validate_architecture_ir import load, validate


def checked_string_list(value: object, *, allow_empty: bool = False) -> list[str] | None:
    if not isinstance(value, list) or (not allow_empty and not value):
        return None
    if not all(isinstance(item, str) and item.strip() for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return value


def concrete_string_list(value: object, *, allow_empty: bool = False) -> bool:
    values = checked_string_list(value, allow_empty=allow_empty)
    return values is not None and all(is_concrete_text(item) for item in values)


def validate_identity(review: dict, errors: list[str]) -> None:
    builder_id, reviewer_id = review.get("builder_id"), review.get("reviewer_id")
    for field, value in (("builder_id", builder_id), ("reviewer_id", reviewer_id)):
        if not isinstance(value, str) or len(value.strip()) < 6 or value.startswith("replace-"):
            errors.append(f"topology review {field} is missing or still a placeholder")
    if isinstance(builder_id, str) and builder_id == reviewer_id:
        errors.append("topology reviewer must be independent from the builder")
    attestation = review.get("reviewer_attestation")
    required = {
        "independent_from_builder",
        "source_inventory_created_before_ir_comparison",
        "did_not_edit_semantic_inputs",
    }
    if not isinstance(attestation, dict) or set(attestation) != required:
        errors.append("topology reviewer attestations must contain exactly the required fields")
    elif any(attestation.get(key) is not True for key in required):
        errors.append("topology reviewer attestations must all be true")


def validate_source_artifacts(
    architecture: Path,
    data: dict,
    review: dict,
    errors: list[str],
) -> dict[str, dict]:
    evidence = {
        item.get("id"): item for item in data.get("evidence", []) if isinstance(item, dict)
    }
    artifacts = review.get("source_artifacts")
    actual: dict[str, dict] = {}
    if not isinstance(artifacts, list):
        errors.append("topology review source_artifacts must be a list")
        artifacts = []
    for index, artifact in enumerate(artifacts):
        prefix = f"source_artifacts[{index}]"
        if not isinstance(artifact, dict):
            errors.append(f"{prefix} must be an object")
            continue
        evidence_id = artifact.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id not in evidence or evidence_id in actual:
            errors.append(f"{prefix}.evidence_id is unknown or duplicate")
            continue
        actual[evidence_id] = artifact
        expected = evidence[evidence_id]
        for field in ("role", "path", "revision"):
            if artifact.get(field) != expected.get(field):
                errors.append(f"{prefix}.{field} disagrees with architecture evidence")
        source = resolve_evidence_path(architecture, expected["path"])
        if artifact.get("sha256") != sha256(source):
            errors.append(f"{prefix} is stale: source SHA-256 changed")
    if set(actual) != set(evidence):
        errors.append(
            "topology review must bind every architecture evidence source; "
            f"missing={sorted(set(evidence) - set(actual))}, "
            f"extra={sorted(set(actual) - set(evidence))}"
        )
    return evidence


def validate_source_inventory(
    data: dict,
    review: dict,
    evidence: dict[str, dict],
    errors: list[str],
) -> dict[str, dict]:
    coverage_paths = {
        item["id"]: item
        for item in data.get("source_coverage", {}).get("paths", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    inventory = review.get("independent_source_inventory")
    if not isinstance(inventory, dict):
        errors.append("independent_source_inventory must be an object")
        return coverage_paths
    if inventory.get("status") != "pass":
        errors.append("independent_source_inventory.status must be pass")
    if not concrete_string_list(inventory.get("findings")):
        errors.append("independent_source_inventory.findings must contain concrete non-placeholder observations")
    blockers = inventory.get("blocking_findings")
    if checked_string_list(blockers, allow_empty=True) is None:
        errors.append("independent_source_inventory.blocking_findings must be a duplicate-free string list")
    elif blockers:
        errors.append("independent_source_inventory has unresolved blocking findings")

    paths = inventory.get("paths")
    actual_paths: dict[str, dict] = {}
    if not isinstance(paths, list):
        errors.append("independent_source_inventory.paths must be a list")
        paths = []
    for index, path in enumerate(paths):
        prefix = f"independent_source_inventory.paths[{index}]"
        if not isinstance(path, dict):
            errors.append(f"{prefix} must be an object")
            continue
        path_id = path.get("path_id")
        if not isinstance(path_id, str) or path_id not in coverage_paths or path_id in actual_paths:
            errors.append(f"{prefix}.path_id is unknown or duplicate")
            continue
        actual_paths[path_id] = path
        expected = coverage_paths[path_id]
        if path.get("evidence_id") != expected.get("evidence"):
            errors.append(f"{prefix}.evidence_id disagrees with source coverage")
        if path.get("source") != expected.get("source"):
            errors.append(f"{prefix}.source disagrees with source coverage")
        if checked_string_list(path.get("entrypoints")) is None:
            errors.append(f"{prefix}.entrypoints must be a non-empty duplicate-free string list")
        if path.get("closure_status") != "complete":
            errors.append(f"{prefix}.closure_status must be complete")
        if not concrete_string_list(path.get("findings")):
            errors.append(f"{prefix}.findings must contain concrete non-placeholder observations")

        callees = path.get("material_callees")
        if not isinstance(callees, list):
            errors.append(f"{prefix}.material_callees must be a list")
            callees = []
        seen_callees: set[tuple[str, str, str]] = set()
        for callee_index, callee in enumerate(callees):
            callee_prefix = f"{prefix}.material_callees[{callee_index}]"
            if not isinstance(callee, dict):
                errors.append(f"{callee_prefix} must be an object")
                continue
            evidence_id = callee.get("evidence_id")
            key = (str(evidence_id), str(callee.get("symbol")), str(callee.get("source")))
            if key in seen_callees:
                errors.append(f"{callee_prefix} duplicates a material callee")
            seen_callees.add(key)
            if not isinstance(evidence_id, str) or evidence_id not in evidence:
                errors.append(f"{callee_prefix}.evidence_id must name a pinned evidence source")
            if not isinstance(callee.get("symbol"), str) or not callee["symbol"].strip():
                errors.append(f"{callee_prefix}.symbol is required")
            if not isinstance(callee.get("source"), str) or not callee["source"].strip():
                errors.append(f"{callee_prefix}.source is required")

        expected_operation_ids = {
            operation.get("id") for operation in expected.get("operations", [])
            if isinstance(operation, dict) and isinstance(operation.get("id"), str)
        }
        mapped_operation_ids: list[str] = []
        operations = path.get("operations")
        if not isinstance(operations, list) or not operations:
            errors.append(f"{prefix}.operations must contain the independent source observations")
            operations = []
        seen_observation_ids: set[str] = set()
        for op_index, operation in enumerate(operations):
            op_prefix = f"{prefix}.operations[{op_index}]"
            if not isinstance(operation, dict):
                errors.append(f"{op_prefix} must be an object")
                continue
            observation_id = operation.get("id")
            if not isinstance(observation_id, str) or not observation_id.strip() or observation_id in seen_observation_ids:
                errors.append(f"{op_prefix}.id is missing or duplicate")
            else:
                seen_observation_ids.add(observation_id)
            if not isinstance(operation.get("kind"), str) or operation["kind"] not in SOURCE_INVENTORY_KINDS:
                errors.append(f"{op_prefix}.kind is invalid")
            if not is_concrete_text(operation.get("label"), minimum=8):
                errors.append(f"{op_prefix}.label must be concrete and non-placeholder")
            if not isinstance(operation.get("source"), str) or not operation["source"].strip():
                errors.append(f"{op_prefix}.source is required")
            operation_evidence = operation.get("evidence_id")
            if not isinstance(operation_evidence, str) or operation_evidence not in evidence or evidence[operation_evidence].get("role") not in {
                "canonical-model", "inference-implementation"
            }:
                errors.append(f"{op_prefix}.evidence_id must name executable pinned evidence")
            if operation.get("comparison") != "matched":
                errors.append(f"{op_prefix}.comparison must be matched before review can pass")
            mapped = checked_string_list(operation.get("source_operation_ids"))
            if mapped is None:
                errors.append(f"{op_prefix}.source_operation_ids must be non-empty and duplicate-free")
            else:
                mapped_operation_ids.extend(mapped)
                unknown = sorted(set(mapped) - expected_operation_ids)
                if unknown:
                    errors.append(f"{op_prefix} maps unknown source operation IDs: {unknown}")
        if len(mapped_operation_ids) != len(set(mapped_operation_ids)):
            errors.append(f"{prefix} maps at least one source operation more than once")
        if set(mapped_operation_ids) != expected_operation_ids:
            errors.append(
                f"{prefix} must reconcile every source operation exactly; "
                f"missing={sorted(expected_operation_ids - set(mapped_operation_ids))}, "
                f"extra={sorted(set(mapped_operation_ids) - expected_operation_ids)}"
            )
    if set(actual_paths) != set(coverage_paths):
        errors.append(
            "independent source inventory must cover every source path exactly; "
            f"missing={sorted(set(coverage_paths) - set(actual_paths))}, "
            f"extra={sorted(set(actual_paths) - set(coverage_paths))}"
        )
    return coverage_paths


def validate_semantic_review(
    data: dict,
    review: dict,
    evidence: dict[str, dict],
    coverage_paths: dict[str, dict],
    errors: list[str],
) -> None:
    expected_regions = set(data["regions"])
    expected_paths = set(coverage_paths)
    semantic = review.get("semantic_review")
    if not isinstance(semantic, dict):
        errors.append("semantic_review must be an object")
        return
    if semantic.get("status") != "pass" or semantic.get("method") != "independent-source-first":
        errors.append("semantic_review requires pass via independent-source-first")
    reviewed_paths = checked_string_list(semantic.get("reviewed_path_ids"))
    reviewed_regions = checked_string_list(semantic.get("reviewed_region_ids"))
    if reviewed_paths is None or set(reviewed_paths) != expected_paths:
        errors.append("semantic_review.reviewed_path_ids must match source paths exactly without duplicates")
    if reviewed_regions is None or set(reviewed_regions) != expected_regions:
        errors.append("semantic_review.reviewed_region_ids must match regions exactly without duplicates")

    valid_scope_refs = (
        {f"path:{item}" for item in expected_paths}
        | {f"region:{item}" for item in expected_regions}
        | {f"evidence:{item}" for item in evidence}
    )
    by_level = {
        level: {region_id for region_id, region in data["regions"].items() if region.get("level") == level}
        for level in range(4)
    }
    detail_regions = {
        region_id for region_id, region in data["regions"].items()
        if region.get("granularity") in {"operator-detail", "implementation-detail"}
    }
    state_regions = {
        node.get("region") for node in data["nodes"].values()
        if isinstance(node, dict) and node.get("kind") in {"cache", "state"}
    }
    expected_check_regions = {
        "user-request-coverage": expected_regions,
        "model-overview": by_level[0],
        "template-families": by_level[0] | by_level[1],
        "logical-operator-coverage": detail_regions,
        "branch-and-merge-coverage": expected_regions,
        "tensor-shape-closure": expected_regions,
        "runtime-variant-coverage": by_level[2] | by_level[3],
        "state-lifecycle-coverage": state_regions,
        "source-operation-closure": expected_regions,
        "evidence-status": expected_regions,
        "terminology-and-granularity": expected_regions,
    }
    results = semantic.get("results")
    result_checks: list[str] = []
    covered_scopes: set[str] = set()
    if not isinstance(results, list):
        errors.append("semantic_review.results must be a list")
        results = []
    for index, result in enumerate(results):
        prefix = f"semantic_review.results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{prefix} must be an object")
            continue
        check = result.get("check")
        valid_check = isinstance(check, str) and check in SEMANTIC_REVIEW_CHECKS
        if isinstance(check, str):
            result_checks.append(check)
        if not valid_check:
            errors.append(f"{prefix}.check is invalid")
        if result.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        scopes = checked_string_list(result.get("scope_refs"))
        if scopes is None or any(scope not in valid_scope_refs for scope in scopes):
            errors.append(f"{prefix}.scope_refs must be valid, non-empty, and duplicate-free")
        else:
            covered_scopes.update(scopes)
            applicable_regions = expected_check_regions.get(check, set()) if valid_check else set()
            required_for_check = {f"path:{item}" for item in expected_paths} | {
                f"region:{item}" for item in applicable_regions
            }
            if not required_for_check.issubset(scopes):
                errors.append(
                    f"{prefix}.scope_refs omit required per-check scopes: "
                    f"{sorted(required_for_check - set(scopes))}"
                )
        refs = checked_string_list(result.get("evidence_refs"))
        if refs is None or any(ref not in evidence for ref in refs):
            errors.append(f"{prefix}.evidence_refs must name pinned evidence")
        else:
            required_path_evidence = {
                path.get("evidence") for path in coverage_paths.values()
                if isinstance(path.get("evidence"), str)
            }
            if not required_path_evidence.issubset(refs):
                errors.append(f"{prefix}.evidence_refs must cover every reviewed path's evidence")
            if check == "evidence-status" and set(refs) != set(evidence):
                errors.append(f"{prefix}.evidence_refs must cover every pinned evidence source")
        if not is_concrete_text(result.get("finding")):
            errors.append(f"{prefix}.finding must be concrete and non-placeholder")
    if set(result_checks) != SEMANTIC_REVIEW_CHECKS or len(result_checks) != len(SEMANTIC_REVIEW_CHECKS):
        errors.append("semantic_review.results must contain every required check exactly once")
    required_scopes = {f"path:{item}" for item in expected_paths} | {
        f"region:{item}" for item in expected_regions
    }
    if not required_scopes.issubset(covered_scopes):
        errors.append(f"semantic_review.results do not cover scopes: {sorted(required_scopes - covered_scopes)}")

    region_results = semantic.get("region_results")
    actual_regions: list[str] = []
    if not isinstance(region_results, list):
        errors.append("semantic_review.region_results must be a list")
        region_results = []
    for index, result in enumerate(region_results):
        prefix = f"semantic_review.region_results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{prefix} must be an object")
            continue
        region_id = result.get("region_id")
        valid_region = isinstance(region_id, str) and region_id in expected_regions
        if isinstance(region_id, str):
            actual_regions.append(region_id)
        if not valid_region:
            errors.append(f"{prefix}.region_id is unknown")
        if result.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        path_ids = checked_string_list(result.get("source_path_ids"))
        applicable = {
            path_id for path_id, path in coverage_paths.items()
            if valid_region and region_id in path.get("regions", [])
        }
        if path_ids is None or set(path_ids) != applicable or not applicable:
            errors.append(f"{prefix}.source_path_ids must exactly name every source path covering this region")
        if not is_concrete_text(result.get("finding")):
            errors.append(f"{prefix}.finding must be concrete and non-placeholder")
    if set(actual_regions) != expected_regions or len(actual_regions) != len(expected_regions):
        errors.append("semantic_review.region_results must cover every region exactly once")

    if not concrete_string_list(semantic.get("findings")):
        errors.append("semantic_review.findings must contain concrete non-placeholder observations")
    blockers = semantic.get("blocking_findings")
    if checked_string_list(blockers, allow_empty=True) is None:
        errors.append("semantic_review.blocking_findings must be a duplicate-free string list")
    elif blockers:
        errors.append("semantic_review has unresolved blocking findings")


def validate_reconstruction_review(data: dict, review: dict, errors: list[str]) -> None:
    regions = data["regions"]
    expected_regions = set(regions)
    nodes = set(data["nodes"])
    edges = set(data.get("edges", {}))
    sequences = {
        f"{region_id}/{sequence['id']}"
        for region_id, region in regions.items()
        for sequence in region.get("operator_sequences", [])
        if isinstance(sequence, dict) and isinstance(sequence.get("id"), str)
    }
    project_id = data.get("project", {}).get("id", "project")
    valid_contract_refs = (
        {f"project:{project_id}"}
        | {f"region:{item}" for item in expected_regions}
        | {f"node:{item}" for item in nodes}
        | {f"edge:{item}" for item in edges}
        | {f"sequence:{item}" for item in sequences}
    )
    by_level = {
        level: {region_id for region_id, region in regions.items() if region.get("level") == level}
        for level in range(4)
    }
    expected_check_regions = {
        "standalone-level0": by_level[0],
        "complete-level1": by_level[1],
        "detail-sequence-reconstructable": by_level[2] | by_level[3],
        "cross-level-traceability": expected_regions,
        "ambiguity-free-state-and-branches": expected_regions,
        "no-informationless-detail": by_level[2] | by_level[3],
    }
    sequence_refs_by_region = {
        region_id: {
            f"sequence:{region_id}/{sequence['id']}"
            for sequence in region.get("operator_sequences", [])
            if isinstance(sequence, dict) and isinstance(sequence.get("id"), str)
        }
        for region_id, region in regions.items()
    }
    tensor_edges = {
        edge_id: edge for edge_id, edge in data.get("edges", {}).items()
        if isinstance(edge, dict) and edge.get("kind") == "tensor"
    }
    tensor_degree: dict[str, tuple[int, int]] = {}
    for node_id in nodes:
        tensor_degree[node_id] = (
            sum(edge.get("target") == node_id for edge in tensor_edges.values()),
            sum(edge.get("source") == node_id for edge in tensor_edges.values()),
        )
    structural_nodes = {
        node_id for node_id, node in data["nodes"].items()
        if node.get("kind") in {"cache", "state"}
        or max(tensor_degree.get(node_id, (0, 0))) > 1
    }
    structural_refs_by_region: dict[str, set[str]] = {region_id: set() for region_id in regions}
    for node_id in structural_nodes:
        region_id = data["nodes"][node_id].get("region")
        if region_id in structural_refs_by_region:
            structural_refs_by_region[region_id].add(f"node:{node_id}")
            structural_refs_by_region[region_id].update(
                f"edge:{edge_id}" for edge_id, edge in tensor_edges.items()
                if edge.get("source") == node_id or edge.get("target") == node_id
            )
    expand_refs = {
        f"edge:{edge_id}" for edge_id, edge in data.get("edges", {}).items()
        if isinstance(edge, dict) and edge.get("kind") == "expand"
    }

    def required_reconstruction_refs(check: object, applicable_regions: set[str]) -> set[str]:
        refs = {f"region:{region_id}" for region_id in applicable_regions}
        if check in {
            "standalone-level0", "complete-level1", "detail-sequence-reconstructable",
            "no-informationless-detail",
        }:
            for region_id in applicable_regions:
                refs.update(sequence_refs_by_region[region_id])
        if check == "cross-level-traceability":
            refs.update(expand_refs)
        if check == "ambiguity-free-state-and-branches":
            for region_id in applicable_regions:
                refs.update(structural_refs_by_region[region_id])
        return refs

    reconstruction = review.get("reconstruction_review")
    if not isinstance(reconstruction, dict):
        errors.append("reconstruction_review must be an object")
        return
    if reconstruction.get("status") != "pass" or reconstruction.get("method") != "ascii-reconstruction-review":
        errors.append("reconstruction_review requires pass via ascii-reconstruction-review")
    reviewed_regions = checked_string_list(reconstruction.get("reviewed_region_ids"))
    if reviewed_regions is None or set(reviewed_regions) != expected_regions:
        errors.append("reconstruction_review.reviewed_region_ids must match regions exactly without duplicates")

    results = reconstruction.get("results")
    result_checks: list[str] = []
    if not isinstance(results, list):
        errors.append("reconstruction_review.results must be a list")
        results = []
    for index, result in enumerate(results):
        prefix = f"reconstruction_review.results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{prefix} must be an object")
            continue
        check = result.get("check")
        valid_check = isinstance(check, str) and check in RECONSTRUCTION_REVIEW_CHECKS
        if isinstance(check, str):
            result_checks.append(check)
        if not valid_check:
            errors.append(f"{prefix}.check is invalid")
        if result.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        region_ids = checked_string_list(result.get("region_ids"), allow_empty=True)
        applicable_regions = expected_check_regions.get(check, set()) if valid_check else set()
        if region_ids is None or set(region_ids) != applicable_regions:
            errors.append(f"{prefix}.region_ids must exactly cover the regions applicable to this check")
        refs = checked_string_list(result.get("contract_refs"))
        if refs is None or any(ref not in valid_contract_refs for ref in refs):
            errors.append(f"{prefix}.contract_refs must name valid ASCII contract IDs")
        elif not required_reconstruction_refs(check, applicable_regions).issubset(refs):
            missing = sorted(required_reconstruction_refs(check, applicable_regions) - set(refs))
            errors.append(f"{prefix}.contract_refs omit required reconstruction contracts: {missing}")
        if not is_concrete_text(result.get("finding")):
            errors.append(f"{prefix}.finding must be concrete and non-placeholder")
    if set(result_checks) != RECONSTRUCTION_REVIEW_CHECKS or len(result_checks) != len(RECONSTRUCTION_REVIEW_CHECKS):
        errors.append("reconstruction_review.results must contain every required check exactly once")

    region_results = reconstruction.get("region_results")
    actual_regions: list[str] = []
    if not isinstance(region_results, list):
        errors.append("reconstruction_review.region_results must be a list")
        region_results = []
    for index, result in enumerate(region_results):
        prefix = f"reconstruction_review.region_results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{prefix} must be an object")
            continue
        region_id = result.get("region_id")
        valid_region = isinstance(region_id, str) and region_id in expected_regions
        if isinstance(region_id, str):
            actual_regions.append(region_id)
        if not valid_region:
            errors.append(f"{prefix}.region_id is unknown")
        if result.get("status") != "pass" or result.get("reconstructable") is not True:
            errors.append(f"{prefix} must pass with reconstructable=true")
        refs = checked_string_list(result.get("contract_refs"))
        required_refs = (
            {f"region:{region_id}"}
            | sequence_refs_by_region.get(region_id, set())
            | structural_refs_by_region.get(region_id, set())
        ) if valid_region else set()
        if (
            refs is None or not valid_region or any(ref not in valid_contract_refs for ref in refs)
            or not required_refs.issubset(refs)
        ):
            errors.append(f"{prefix}.contract_refs must include its region, sequences, and branch/state contracts")
        if not is_concrete_text(result.get("finding")):
            errors.append(f"{prefix}.finding must be concrete and non-placeholder")
    if set(actual_regions) != expected_regions or len(actual_regions) != len(expected_regions):
        errors.append("reconstruction_review.region_results must cover every region exactly once")

    if not concrete_string_list(reconstruction.get("findings")):
        errors.append("reconstruction_review.findings must contain concrete non-placeholder observations")
    blockers = reconstruction.get("blocking_findings")
    if checked_string_list(blockers, allow_empty=True) is None:
        errors.append("reconstruction_review.blocking_findings must be a duplicate-free string list")
    elif blockers:
        errors.append("reconstruction_review has unresolved blocking findings")


def validate_review(
    architecture: Path,
    topology: Path,
    review_path: Path,
    *,
    require_receipt: bool = True,
) -> list[str]:
    from semantic_gate import validate_delivery_scope
    errors: list[str] = []
    try:
        data = load(architecture)
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"cannot read topology review inputs: {error}"]
    architecture_errors = validate(data, architecture.parent, require_files=True)
    architecture_errors.extend(validate_delivery_scope(data))
    if architecture_errors:
        return [f"architecture IR invalid for topology review: {error}" for error in architecture_errors]
    if not isinstance(review, dict) or review.get("schema_version") != 3:
        return ["topology review schema_version must be 3; regenerate the review artifact"]
    receipt = review.get("review_receipt")
    if require_receipt:
        if not isinstance(receipt, dict):
            errors.append("topology review is not finalized: review_receipt is missing")
        elif set(receipt) != {"mechanism", "payload_sha256"}:
            errors.append("topology review receipt contains unsupported fields")
        else:
            if receipt.get("mechanism") != "model-sketcher-controlled-finalizer-v1":
                errors.append("topology review receipt mechanism is invalid")
            if receipt.get("payload_sha256") != review_payload_sha256(review):
                errors.append("topology review receipt is stale: completed review was edited after finalization")
    if review.get("review_scope") != "semantic-topology":
        errors.append("topology review_scope must be semantic-topology")
    if not isinstance(review.get("trigger"), str) or review["trigger"] not in REVIEW_TRIGGERS:
        errors.append("topology review trigger is invalid")
    if review.get("architecture_semantic_sha256") != semantic_json_sha256(data):
        errors.append("topology review is stale: architecture semantic SHA-256 changed")
    try:
        topology_digest = sha256(topology)
        topology_text = topology.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"cannot read ASCII topology contract: {error}")
    else:
        if review.get("topology_contract_sha256") != topology_digest:
            errors.append("topology review is stale: ASCII topology SHA-256 changed")
        if topology_text != render(data):
            errors.append("ASCII topology contract is not the canonical generated output for this architecture")

    validate_identity(review, errors)
    evidence = validate_source_artifacts(architecture, data, review, errors)
    coverage_paths = validate_source_inventory(data, review, evidence, errors)
    validate_semantic_review(data, review, evidence, coverage_paths, errors)
    validate_reconstruction_review(data, review, errors)
    from semantic_consistency import validate_expectations
    errors.extend(validate_expectations(data, review, architecture))
    if review.get("verdict") != "pass":
        errors.append("topology review verdict must be pass")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("topology_contract", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    errors = validate_review(args.architecture, args.topology_contract, args.review)
    if errors:
        print("topology review audit: FAIL")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"topology review audit: PASS ({args.review})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
