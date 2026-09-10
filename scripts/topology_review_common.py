#!/usr/bin/env python3
"""Shared schema and digest helpers for topology review artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


SEMANTIC_REVIEW_CHECKS = {
    "user-request-coverage",
    "model-overview",
    "template-families",
    "logical-operator-coverage",
    "branch-and-merge-coverage",
    "tensor-shape-closure",
    "runtime-variant-coverage",
    "state-lifecycle-coverage",
    "source-operation-closure",
    "evidence-status",
    "terminology-and-granularity",
    "view-projection-boundary",
}

RECONSTRUCTION_REVIEW_CHECKS = {
    "standalone-level0",
    "complete-level1",
    "detail-sequence-reconstructable",
    "cross-level-traceability",
    "ambiguity-free-state-and-branches",
    "no-informationless-detail",
}

REVIEW_TRIGGERS = {
    "cold-start",
    "semantic-revision",
    "source-revision",
    "requested-recheck",
}

SOURCE_INVENTORY_KINDS = {
    "interface", "operator", "branch", "merge", "call", "state-read", "state-write", "output"
}

PLACEHOLDER_TEXT = re.compile(
    r"\b(?:replace(?: me| with)?|todo|tbd|pending|not yet reviewed|review has not run|"
    r"fill (?:this|me|in)|lorem ipsum)\b",
    re.IGNORECASE,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic_architecture_view(value: object) -> object:
    """Remove compiler-owned visual choices that do not change model topology."""
    data = deepcopy(value)
    if not isinstance(data, dict):
        return data
    project = data.get("project")
    if isinstance(project, dict):
        project.pop("typography", None)
        project.pop("semantic_view", None)
    data.pop("operator_naming_review", None)
    regions = data.get("regions")
    if isinstance(regions, dict):
        for region in regions.values():
            if isinstance(region, dict):
                region.pop("child_direction", None)
                region.pop("order", None)
    nodes = data.get("nodes")
    if isinstance(nodes, dict):
        for node in nodes.values():
            if isinstance(node, dict):
                node.pop("order", None)
                for key in tuple(node):
                    if key.startswith("visual_"):
                        node.pop(key)
    edges = data.get("edges")
    if isinstance(edges, dict):
        for edge in edges.values():
            if isinstance(edge, dict):
                edge.pop("visual_attachment", None)
                if edge.get("kind") == "expand":
                    edge.pop("direction", None)

    def strip_review_metadata(contract: object) -> None:
        if not isinstance(contract, dict):
            return
        for key in ("status", "method", "checks", "findings"):
            contract.pop(key, None)

    for name in ("overview_contract", "template_coverage_contract", "operator_display_contract"):
        strip_review_metadata(data.get(name))
    coverage = data.get("source_coverage")
    if isinstance(coverage, dict):
        coverage.pop("reconciliation", None)
    for name in ("detail_information_gain_contracts", "state_lifecycle_contracts"):
        contracts = data.get(name)
        if isinstance(contracts, dict):
            for contract in contracts.values():
                strip_review_metadata(contract)
    runtime_contracts = data.get("runtime_variant_contracts")
    if isinstance(runtime_contracts, dict):
        for contract in runtime_contracts.values():
            if isinstance(contract, dict):
                for key in ("method", "checks", "findings"):
                    contract.pop(key, None)
    return data


def semantic_json_sha256(value: object) -> str:
    payload = json.dumps(
        semantic_architecture_view(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_evidence_path(architecture: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (architecture.parent / path).resolve()


def is_concrete_text(value: object, minimum: int = 20) -> bool:
    return (
        isinstance(value, str)
        and len(value.strip()) >= minimum
        and PLACEHOLDER_TEXT.search(value) is None
    )
