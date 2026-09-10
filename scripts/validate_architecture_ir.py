#!/usr/bin/env python3
"""Validate the semantic architecture IR before any diagram geometry is made."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from semantic_palette import (
    SEMANTIC_PALETTE,
    VISUAL_MODIFIERS,
    allowed_visual_classes,
    resolve_visual_class,
)


ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
VIEWS = {"hierarchy-master", "end-to-end-dataflow", "paired"}
KINDS = {"module", "operator", "interface", "cache", "state", "junction"}
EDGE_KINDS = {"tensor", "expand", "uses", "injects", "reuses"}
GRANULARITIES = {"module-summary", "operator-detail", "implementation-detail"}
FLOW_DIRECTIONS = {"left-to-right", "right-to-left", "top-to-bottom", "bottom-to-top"}
HIERARCHY_ATTACHMENT_MODES = {"parent-node", "owner-region-boundary"}
HIERARCHY_SIDES = {"north", "south", "east", "west"}
EVIDENCE_ROLES = {"checkpoint-config", "canonical-model", "official-report", "inference-implementation", "supporting-analysis"}
SOURCE_COVERAGE_SCOPES = {"complete-hierarchy", "selected-paths"}
SOURCE_OPERATION_STATUSES = {
    "visible-node",
    "source-confirmed-fusion",
    "fused-execution-group",
    "expanded-in-region",
    "out-of-scope",
    "unresolved",
}
SEMANTIC_LAYERS = {
    "model-algorithm", "inference-execution", "backend-implementation", "shared-interface"
}
PROJECTION_KINDS = {
    "algorithm-master", "operator-flops", "inference-runtime", "backend-runtime"
}
PROJECTION_REQUIRED_CHECKS = {
    "canonical-entity-disposition",
    "algorithm-backend-separation",
    "model-semantics-retained",
    "runtime-variant-placement",
}
BACKEND_ONLY_LABEL = re.compile(
    r"\b(?:dcp|paged[- ](?:cache|attention)|flash(?:attention|infer)|deepgemm|triton|"
    r"(?:cuda|triton|fused|hardware)[- ]kernel|backend|nccl|block[- ]table|fallback)\b",
    re.IGNORECASE,
)
OPERATOR_CLASSIFICATIONS = {
    "atomic-operator",
    "view-transform",
    "packed-parameterized-op",
    "expanded-elsewhere",
}
OPERATOR_TYPES = {
    "rmsnorm", "layernorm", "normalization", "linear", "convolution", "embedding",
    "split", "chunk", "slice", "unbind", "concatenate", "reshape", "view", "transpose",
    "permute", "repeat", "broadcast", "gather", "scatter", "rope", "positional-transform",
    "matmul", "scale", "mask", "softmax", "sigmoid", "silu", "gelu", "activation",
    "multiply", "add", "subtract", "divide", "power", "sqrt", "exp", "log", "clamp",
    "where", "reduce", "sum", "mean", "max", "topk", "sort", "routing", "dispatch", "combine",
    "pooling", "dropout", "scan", "cumsum", "index", "pad", "sample", "loss",
    "cache-read", "cache-write", "cache-update", "state-update", "all-to-all", "all-reduce",
    "cast", "load", "store", "format-conversion", "einsum",
    "all-gather", "reduce-scatter", "quantize", "dequantize", "custom",
}
SHAPE_RULES = {"preserve", "transform", "multi-input", "multi-output", "stateful", "custom"}
OP_TYPE_SHAPE_RULES = {
    "linear": {"transform"}, "convolution": {"transform"}, "embedding": {"transform"},
    "reshape": {"transform"}, "view": {"transform"}, "transpose": {"transform"},
    "permute": {"transform"}, "repeat": {"transform"}, "broadcast": {"transform"},
    "split": {"multi-output"}, "chunk": {"multi-output"}, "unbind": {"multi-output"},
    "slice": {"transform", "multi-output"}, "concatenate": {"multi-input"},
    "matmul": {"multi-input"}, "multiply": {"multi-input"}, "add": {"multi-input"},
    "subtract": {"multi-input"}, "divide": {"multi-input"}, "where": {"multi-input"},
    "cache-read": {"stateful"}, "cache-write": {"stateful"}, "cache-update": {"stateful"},
    "state-update": {"stateful"},
    "load": {"transform", "stateful"}, "store": {"stateful"},
}
UNPACK_OPERATOR_TYPES = {"split", "chunk", "slice", "unbind"}
PARAMETERIZED_OPERATOR_TYPES = {
    "linear", "convolution", "embedding", "rmsnorm", "layernorm", "normalization"
}
TENSOR_SHAPE_STATUSES = {
    "code-confirmed",
    "config-confirmed",
    "report-confirmed",
    "inferred",
    "backend-dependent",
    "unknown",
}
SHAPE_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
SHAPE_EQUATION_SEPARATOR = re.compile(r"<->|->|→")
COMPOSITE_OPERATOR_TERMS = re.compile(
    r"\b(?:rmsnorm|layernorm|linear|projection|conv(?:olution)?|reshape|transpose|permute|"
    r"view|split|chunk|slice|unbind|concat(?:enate)?|repeat|broadcast|matmul|scale|mask|"
    r"softmax|sigmoid|silu|gelu|activation|multiply|add|subtract|divide|reduce|top[- ]?k|"
    r"dispatch|combine|cache[- ]?(?:read|write|update)|state[- ]?update|"
    r"all[- ]?to[- ]?all|all[- ]?reduce|quantize|dequantize)\b",
    re.IGNORECASE,
)
OPERATOR_TERM_FAMILIES = {
    "rmsnorm": "normalization", "layernorm": "normalization",
    "linear": "projection", "projection": "projection",
    "conv": "convolution", "convolution": "convolution",
    "reshape": "shape-view", "view": "shape-view",
    "transpose": "permutation", "permute": "permutation",
    "split": "unpack", "chunk": "unpack", "slice": "unpack", "unbind": "unpack",
    "concat": "concatenate", "concatenate": "concatenate",
    "repeat": "repeat", "broadcast": "broadcast", "matmul": "matmul", "scale": "scale", "mask": "mask",
    "softmax": "softmax", "sigmoid": "activation", "silu": "activation",
    "gelu": "activation", "activation": "activation", "topk": "topk",
    "multiply": "multiply", "add": "add", "subtract": "subtract", "divide": "divide",
    "dispatch": "dispatch", "combine": "combine", "reduce": "reduce",
    "cacheread": "cache-read", "cachewrite": "cache-write", "cacheupdate": "cache-update",
    "stateupdate": "state-update",
    "alltoall": "all-to-all", "allreduce": "all-reduce",
    "quantize": "quantize", "dequantize": "dequantize",
}
SEMANTIC_ROLE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SOURCE_IDENTIFIER_IN_LABEL = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")
OPAQUE_PRIMARY_LABEL = re.compile(
    r"^(?:[A-Za-z0-9.-]+\s+)?(?:core|kernel|backend|process|operation|op)$",
    re.IGNORECASE,
)
OPERATOR_LABEL_SHAPE = re.compile(
    r"\[[^\]\n]*(?:,|→|->)[^\]\n]*\]|\b\d+\s*(?:→|->)\s*\d+\b"
)
OVERVIEW_REQUIRED_FACETS = {"input", "backbone", "output"}
OVERVIEW_REQUIRED_CHECKS = {
    "standalone-model-identity",
    "heterogeneous-backbone-summary",
    "model-level-branch-coverage",
    "output-readout-coverage",
}
TEMPLATE_REQUIRED_CHECKS = {
    "distinct-template-families",
    "complete-template-paths",
    "level0-summary-mapping",
}
DISPLAY_REQUIRED_CHECKS = {
    "operator-names",
    "activation-shapes-on-edges",
    "parameter-shapes-outside-blocks",
    "source-symbols-outside-primary-label",
}
DETAIL_INFORMATION_KINDS = {
    "logical-decomposition", "runtime-variant", "state-lifecycle", "kernel-fusion",
    "communication", "physical-layout", "dtype-or-quantization", "addressing-or-indexing",
}
OP_TYPE_DISPLAY_TERMS = {
    "rmsnorm": (r"\brmsnorm\b",),
    "layernorm": (r"\blayernorm\b",),
    "linear": (r"\b(?:linear|projection|project|output head|lm head)\b",),
    "convolution": (r"\bconv(?:olution)?(?:1d|2d|3d)?\b",),
    "split": (r"\b(?:split|unpack)\b",),
    "chunk": (r"\bchunk\b",),
    "concatenate": (r"\b(?:concat(?:enate)?|merge)\b",),
    "reshape": (r"\b(?:reshape|flatten|unflatten|squeeze|unsqueeze|merge heads?)\b",),
    "transpose": (r"\btranspose\b",),
    "permute": (r"\bpermute\b",),
    "repeat": (r"\brepeat\b",),
    "matmul": (r"\b(?:matmul|matrix multiply|dot product)\b",),
    "einsum": (r"\beinsum\b",),
    "softmax": (r"\bsoftmax\b",),
    "sigmoid": (r"\bsigmoid\b",),
    "silu": (r"\b(?:silu|swish)\b",),
    "gelu": (r"\bgelu\b",),
    "multiply": (r"\b(?:multiply|product|gate)\b",),
    "add": (r"\b(?:add|sum|residual)\b",),
    "topk": (r"\btop[- ]?k\b",),
    "dispatch": (r"\bdispatch\b",),
    "combine": (r"\b(?:combine|merge|reduce)\b",),
    "scan": (r"\b(?:scan|recurren(?:t|ce)|delta rule)\b",),
    "cache-read": (r"\bcache read\b",),
    "cache-write": (r"\bcache write\b",),
    "cache-update": (r"\bcache update\b",),
    "state-update": (r"\bstate update\b",),
    "all-to-all": (r"\ball[- ]to[- ]all\b",),
    "all-reduce": (r"\ball[- ]reduce\b",),
    "all-gather": (r"\ball[- ]gather\b",),
    "reduce-scatter": (r"\breduce[- ]scatter\b",),
}


def primary_reader_label(node: dict) -> str:
    """Return the reader-facing first line, excluding optional technical detail."""
    return str(node.get("label", "")).splitlines()[0].strip()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("top-level value must be an object")
    return value


def edge_display_label(edge: dict) -> str:
    """Render one display label from the structured tensor contract when present."""
    tensor = edge.get("tensor")
    if isinstance(tensor, dict):
        name = str(tensor.get("name", "")).strip()
        shape = str(tensor.get("shape", "")).strip()
        return " ".join(part for part in (name, shape) if part)
    return str(edge.get("label", ""))


def tensor_edges_for_node(edges: dict, node_id: str) -> tuple[list[str], list[str]]:
    incoming = [
        edge_id for edge_id, edge in edges.items()
        if isinstance(edge, dict) and edge.get("kind") == "tensor" and edge.get("target") == node_id
    ]
    outgoing = [
        edge_id for edge_id, edge in edges.items()
        if isinstance(edge, dict) and edge.get("kind") == "tensor" and edge.get("source") == node_id
    ]
    return sorted(incoming), sorted(outgoing)


def connected_member_subgraph(edges: dict, members: set[str], transparent: set[str] | None = None) -> bool:
    if not members:
        return False
    traversal_nodes = members | (transparent or set())
    adjacency = {item: set() for item in traversal_nodes}
    for edge in edges.values():
        if not isinstance(edge, dict) or edge.get("kind") != "tensor":
            continue
        source, target = edge.get("source"), edge.get("target")
        if source in traversal_nodes and target in traversal_nodes:
            adjacency[source].add(target)
            adjacency[target].add(source)
    pending = [next(iter(members))]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency[current] - seen)
    return members <= seen


def validate_view_projection_contract(
    data: dict, regions: dict, nodes: dict, edges: dict
) -> list[str]:
    """Validate one complete semantic ledger's disposition into reader-facing views."""
    errors: list[str] = []
    project = data.get("project", {})
    required = isinstance(project, dict) and project.get("require_view_projection_contracts") is True
    contract = data.get("view_projection_contract")
    if not required and contract is None:
        return errors
    if not isinstance(contract, dict):
        return ["project.require_view_projection_contracts is true but view_projection_contract is missing"]
    if contract.get("status") != "pass":
        errors.append("view_projection_contract.status must be pass")
    if contract.get("method") != "canonical-ir-projection-review":
        errors.append("view_projection_contract.method must be canonical-ir-projection-review")
    checks = contract.get("checks")
    if not isinstance(checks, list) or not PROJECTION_REQUIRED_CHECKS.issubset(set(checks)):
        errors.append(
            f"view_projection_contract.checks must include {sorted(PROJECTION_REQUIRED_CHECKS)}"
        )
    if not non_empty_string_list(contract.get("findings")):
        errors.append("view_projection_contract.findings must be a non-empty string list")

    views = contract.get("views")
    if not isinstance(views, dict) or not views:
        errors.append("view_projection_contract.views must be a non-empty object")
        views = {}
    view_kinds: dict[str, str] = {}
    for view_id, view in views.items():
        prefix = f"view_projection_contract.views.{view_id}"
        if not isinstance(view_id, str) or not ID.fullmatch(view_id):
            errors.append(f"{prefix} has an invalid view id")
        if not isinstance(view, dict):
            errors.append(f"{prefix} must be an object")
            continue
        kind = view.get("kind")
        if kind not in PROJECTION_KINDS:
            errors.append(f"{prefix}.kind is invalid: {kind!r}")
        else:
            view_kinds[view_id] = kind
        if not isinstance(view.get("purpose"), str) or not view["purpose"].strip():
            errors.append(f"{prefix}.purpose is required")
    if "algorithm-master" not in set(view_kinds.values()):
        errors.append("view_projection_contract requires an algorithm-master view")

    active_view = project.get("semantic_view") if isinstance(project, dict) else None
    if active_view not in views:
        errors.append("project.semantic_view must name a declared view projection")

    memberships: dict[str, tuple[str, set[str]]] = {}
    collections = (("region", regions), ("node", nodes), ("edge", edges))
    for entity_kind, collection in collections:
        for entity_id, entity in collection.items():
            prefix = f"{entity_kind} {entity_id}"
            if not isinstance(entity, dict):
                continue
            layer = entity.get("semantic_layer")
            if layer not in SEMANTIC_LAYERS:
                errors.append(f"{prefix}.semantic_layer is missing or invalid")
            entity_views = entity.get("views")
            if not isinstance(entity_views, list) or not entity_views or any(
                not isinstance(view_id, str) for view_id in entity_views
            ):
                errors.append(f"{prefix}.views must be a non-empty list of declared view IDs")
                member_views: set[str] = set()
            else:
                member_views = set(entity_views)
                if len(member_views) != len(entity_views):
                    errors.append(f"{prefix}.views contains duplicates")
                unknown = sorted(member_views - set(views))
                if unknown:
                    errors.append(f"{prefix}.views names unknown projections: {unknown}")
            memberships[f"{entity_kind}:{entity_id}"] = (str(layer), member_views)

            kinds = {view_kinds.get(view_id) for view_id in member_views}
            if layer == "model-algorithm" and "algorithm-master" not in kinds:
                errors.append(f"{prefix} is model-algorithm but is absent from every algorithm-master view")
            if layer in {"inference-execution", "backend-implementation"} and "algorithm-master" in kinds:
                errors.append(f"{prefix} leaks {layer} detail into an algorithm-master view")
            if layer == "backend-implementation" and "backend-runtime" not in kinds:
                errors.append(f"{prefix} is backend-implementation but has no backend-runtime disposition")
            if layer == "inference-execution" and not kinds.intersection({"inference-runtime", "backend-runtime"}):
                errors.append(f"{prefix} is inference-execution but has no runtime-view disposition")

    for region_id, region in regions.items():
        if not isinstance(region, dict):
            continue
        region_views = memberships.get(f"region:{region_id}", ("", set()))[1]
        parent = region.get("parent")
        if parent is not None:
            parent_views = memberships.get(f"region:{parent}", ("", set()))[1]
            missing = sorted(region_views - parent_views)
            if missing:
                errors.append(f"region {region_id}.views are absent from parent {parent}: {missing}")
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        node_views = memberships.get(f"node:{node_id}", ("", set()))[1]
        region_views = memberships.get(f"region:{node.get('region')}", ("", set()))[1]
        missing = sorted(node_views - region_views)
        if missing:
            errors.append(f"node {node_id}.views are absent from owner region {node.get('region')}: {missing}")
        if (
            node.get("kind") in {"operator", "module"}
            and memberships.get(f"node:{node_id}", ("", set()))[0] == "model-algorithm"
            and BACKEND_ONLY_LABEL.search(primary_reader_label(node))
        ):
            errors.append(
                f"node {node_id} uses a backend-specific label but is classified model-algorithm"
            )
    for edge_id, edge in edges.items():
        if not isinstance(edge, dict):
            continue
        edge_views = memberships.get(f"edge:{edge_id}", ("", set()))[1]
        source_views = memberships.get(f"node:{edge.get('source')}", ("", set()))[1]
        target_views = memberships.get(f"node:{edge.get('target')}", ("", set()))[1]
        missing = sorted(edge_views - source_views.intersection(target_views))
        if missing:
            errors.append(f"edge {edge_id}.views lack both visible endpoints in: {missing}")

    present_layers = {layer for layer, _ in memberships.values()}
    present_kinds = set(view_kinds.values())
    if "inference-execution" in present_layers and "inference-runtime" not in present_kinds:
        errors.append("inference-execution entities require an inference-runtime view")
    if "backend-implementation" in present_layers and "backend-runtime" not in present_kinds:
        errors.append("backend-implementation entities require a backend-runtime view")
    return errors


def operator_families_in_label(label: str) -> set[str]:
    """Return distinct logical operation families named by a node label."""
    families: set[str] = set()
    for term in COMPOSITE_OPERATOR_TERMS.findall(label):
        key = re.sub(r"[- ]", "", term.lower())
        families.add(OPERATOR_TERM_FAMILIES.get(key, key))
    return families


def region_owns_region(regions: dict, owner_id: str, region_id: str) -> bool:
    """Return true when owner_id is region_id or one of its ownership ancestors."""
    cursor: str | None = region_id
    seen: set[str] = set()
    while cursor is not None and cursor not in seen:
        if cursor == owner_id:
            return True
        seen.add(cursor)
        region = regions.get(cursor)
        cursor = region.get("parent") if isinstance(region, dict) else None
    return False


def non_empty_string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def validate_hierarchy_summary_contracts(
    data: dict,
    project: dict,
    regions: dict,
    nodes: dict,
    edges: dict,
    evidence_ids: set[str],
) -> list[str]:
    """Validate reader-first Level 0/1 coverage and cross-level shape closure."""
    errors: list[str] = []
    if project.get("output_view") not in {"hierarchy-master", "paired"}:
        return errors

    level0_regions = {
        region_id for region_id, region in regions.items()
        if isinstance(region, dict) and region.get("level") == 0
    }
    level0_nodes = {
        node_id for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("region") in level0_regions
    }
    if level0_regions:
        contract = data.get("overview_contract")
        if not isinstance(contract, dict):
            errors.append("overview_contract is required when a hierarchy view contains Level 0")
        else:
            if contract.get("status") != "pass":
                errors.append("overview_contract.status must be pass")
            if contract.get("method") != "standalone-reader-review":
                errors.append("overview_contract.method must be standalone-reader-review")
            declared_regions = contract.get("level0_region_ids")
            if not isinstance(declared_regions, list) or set(declared_regions) != level0_regions:
                errors.append("overview_contract.level0_region_ids must match all Level 0 regions exactly")
            spine = contract.get("spine_nodes")
            if not isinstance(spine, list) or len(spine) < 2 or len(set(spine)) != len(spine):
                errors.append("overview_contract.spine_nodes must contain at least two unique Level 0 nodes")
                spine = []
            elif any(node_id not in level0_nodes for node_id in spine):
                errors.append("overview_contract.spine_nodes must contain only Level 0 nodes")
            else:
                tensor_pairs = {
                    (edge.get("source"), edge.get("target"))
                    for edge in edges.values() if isinstance(edge, dict) and edge.get("kind") == "tensor"
                }
                for source, target in zip(spine, spine[1:]):
                    if (source, target) not in tensor_pairs:
                        errors.append(f"overview spine lacks tensor edge {source} -> {target}")

            facets = contract.get("facets")
            if not isinstance(facets, dict) or not OVERVIEW_REQUIRED_FACETS.issubset(facets):
                errors.append(
                    "overview_contract.facets must include input, backbone, and output"
                )
            else:
                for facet, mapped in facets.items():
                    mapped_ids = [mapped] if isinstance(mapped, str) else mapped
                    if not non_empty_string_list(mapped_ids) or any(
                        node_id not in level0_nodes for node_id in mapped_ids
                    ):
                        errors.append(f"overview facet {facet!r} must map to visible Level 0 nodes")

            components = contract.get("signature_components")
            covered_level1: set[str] = set()
            component_ids: set[str] = set()
            if not isinstance(components, list) or not components:
                errors.append("overview_contract.signature_components must be non-empty")
                components = []
            for index, component in enumerate(components):
                prefix = f"overview_contract.signature_components[{index}]"
                if not isinstance(component, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                component_id = component.get("id")
                if not isinstance(component_id, str) or not ID.fullmatch(component_id) or component_id in component_ids:
                    errors.append(f"{prefix}.id is invalid or duplicate")
                else:
                    component_ids.add(component_id)
                display_text = component.get("display_text")
                mapped_level0 = component.get("level0_nodes")
                if not isinstance(display_text, str) or not display_text.strip():
                    errors.append(f"{prefix}.display_text is required")
                if not non_empty_string_list(mapped_level0) or any(
                    node_id not in level0_nodes for node_id in mapped_level0
                ):
                    errors.append(f"{prefix}.level0_nodes must name visible Level 0 nodes")
                    mapped_level0 = []
                elif display_text.strip().casefold() not in " ".join(
                    str(nodes[node_id].get("label", "")) for node_id in mapped_level0
                ).casefold():
                    errors.append(f"{prefix}.display_text is not visible in its mapped Level 0 nodes")
                mapped_level1 = component.get("level1_nodes", [])
                if not isinstance(mapped_level1, list) or any(
                    node_id not in nodes or regions.get(nodes[node_id].get("region"), {}).get("level") != 1
                    for node_id in mapped_level1
                ):
                    errors.append(f"{prefix}.level1_nodes must name Level 1 nodes")
                else:
                    covered_level1.update(mapped_level1)
                refs = component.get("evidence")
                if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs):
                    errors.append(f"{prefix}.evidence must cite known evidence IDs")

            expanded_level1 = {
                edge.get("source") for edge in edges.values()
                if isinstance(edge, dict) and edge.get("kind") == "expand"
                and edge.get("source") in nodes
                and regions.get(nodes[edge["source"]].get("region"), {}).get("level") == 1
            }
            missing_signatures = sorted(expanded_level1 - covered_level1)
            if missing_signatures:
                errors.append(
                    "Level 1 expanded signature components are absent from the Level 0 synopsis: "
                    f"{missing_signatures}"
                )
            checks = contract.get("checks")
            if not isinstance(checks, list) or not OVERVIEW_REQUIRED_CHECKS.issubset(set(checks)):
                errors.append(f"overview_contract.checks must include {sorted(OVERVIEW_REQUIRED_CHECKS)}")
            if not non_empty_string_list(contract.get("findings")):
                errors.append("overview_contract.findings must be a non-empty string list")

    level1_sequences = {
        region_id: {
            sequence.get("id") for sequence in region.get("operator_sequences", [])
            if isinstance(sequence, dict) and isinstance(sequence.get("id"), str)
        }
        for region_id, region in regions.items()
        if isinstance(region, dict) and region.get("level") == 1 and region.get("operator_sequences")
    }
    if level1_sequences:
        contract = data.get("template_coverage_contract")
        if not isinstance(contract, dict):
            errors.append("template_coverage_contract is required for Level 1 template sequences")
        else:
            if contract.get("status") != "pass" or contract.get("method") != "template-family-review":
                errors.append("template_coverage_contract requires status pass and method template-family-review")
            coverage = contract.get("regions")
            if not isinstance(coverage, dict) or set(coverage) != set(level1_sequences):
                errors.append("template_coverage_contract.regions must match sequenced Level 1 regions exactly")
                coverage = {}
            for region_id, expected_sequences in level1_sequences.items():
                entries = coverage.get(region_id, [])
                if not isinstance(entries, list):
                    errors.append(f"template coverage for region {region_id} must be a list")
                    continue
                actual_sequences: list[str] = []
                for index, entry in enumerate(entries):
                    prefix = f"template_coverage_contract.regions.{region_id}[{index}]"
                    if not isinstance(entry, dict):
                        errors.append(f"{prefix} must be an object")
                        continue
                    sequence_id = entry.get("sequence_id")
                    actual_sequences.append(sequence_id)
                    summary = entry.get("summary")
                    summary_nodes = entry.get("level0_nodes")
                    if not isinstance(summary, str) or not summary.strip():
                        errors.append(f"{prefix}.summary is required")
                    if not non_empty_string_list(summary_nodes) or any(
                        node_id not in level0_nodes for node_id in summary_nodes
                    ):
                        errors.append(f"{prefix}.level0_nodes must name visible Level 0 nodes")
                    elif summary.strip().casefold() not in " ".join(
                        str(nodes[node_id].get("label", "")) for node_id in summary_nodes
                    ).casefold():
                        errors.append(f"{prefix}.summary is not visible in its mapped Level 0 nodes")
                    refs = entry.get("evidence")
                    if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs):
                        errors.append(f"{prefix}.evidence must cite known evidence IDs")
                if set(actual_sequences) != expected_sequences or len(actual_sequences) != len(expected_sequences):
                    errors.append(f"template coverage for region {region_id} must map every sequence exactly once")
            checks = contract.get("checks")
            if not isinstance(checks, list) or not TEMPLATE_REQUIRED_CHECKS.issubset(set(checks)):
                errors.append(f"template_coverage_contract.checks must include {sorted(TEMPLATE_REQUIRED_CHECKS)}")
            if not non_empty_string_list(contract.get("findings")):
                errors.append("template_coverage_contract.findings must be a non-empty string list")

    expand_edges = {
        edge_id: edge for edge_id, edge in edges.items()
        if isinstance(edge, dict) and edge.get("kind") == "expand"
    }
    if expand_edges:
        contracts = data.get("cross_level_interface_contracts")
        if not isinstance(contracts, dict) or set(contracts) != set(expand_edges):
            actual = set(contracts) if isinstance(contracts, dict) else set()
            errors.append(
                "cross_level_interface_contracts must map every expand relation exactly; "
                f"missing={sorted(set(expand_edges) - actual)}, "
                f"extra={sorted(actual - set(expand_edges))}"
            )
            contracts = contracts if isinstance(contracts, dict) else {}
        for edge_id, edge in expand_edges.items():
            contract = contracts.get(edge_id)
            if not isinstance(contract, dict):
                continue
            parent_shape, child_shape = contract.get("parent_shape"), contract.get("child_shape")
            for field, shape in (("parent_shape", parent_shape), ("child_shape", child_shape)):
                if not isinstance(shape, str) or not shape.strip():
                    errors.append(f"cross-level interface {edge_id}.{field} is required")
            mapping = contract.get("mapping")
            if not isinstance(mapping, str) or not mapping.strip():
                errors.append(f"cross-level interface {edge_id}.mapping is required")
            elif parent_shape != child_shape and mapping.strip().casefold() == "identity":
                errors.append(f"cross-level interface {edge_id} changes shape but declares identity mapping")
            elif parent_shape == child_shape and mapping.strip().casefold() != "identity":
                errors.append(f"cross-level interface {edge_id} preserves shape and must declare identity mapping")
            if parent_shape != child_shape:
                display_node = contract.get("display_node")
                display_text = contract.get("display_text")
                source_region = nodes.get(edge.get("source"), {}).get("region")
                target_region = nodes.get(edge.get("target"), {}).get("region")
                if (
                    display_node not in nodes
                    or nodes[display_node].get("region") not in {source_region, target_region}
                    or not isinstance(display_text, str)
                    or not display_text.strip()
                    or display_text.casefold() not in str(nodes.get(display_node, {}).get("label", "")).casefold()
                ):
                    errors.append(
                        f"cross-level interface {edge_id} shape mapping must be visible on a parent/child boundary node"
                    )
            if contract.get("status") not in TENSOR_SHAPE_STATUSES - {"unknown"}:
                errors.append(f"cross-level interface {edge_id}.status is invalid")
            refs = contract.get("evidence")
            if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs):
                errors.append(f"cross-level interface {edge_id}.evidence must cite known evidence IDs")
    return errors


def validate_detail_runtime_state_contracts(
    data: dict,
    regions: dict,
    nodes: dict,
    edges: dict,
    evidence_ids: set[str],
) -> list[str]:
    """Reject decorative detail regions and incomplete runtime/state stories."""
    errors: list[str] = []
    expand_edges = {
        edge_id: edge for edge_id, edge in edges.items()
        if isinstance(edge, dict)
        and edge.get("kind") == "expand"
        and regions.get(nodes.get(edge.get("target"), {}).get("region"), {}).get("level") in {2, 3}
    }
    gains = data.get("detail_information_gain_contracts")
    if expand_edges:
        if not isinstance(gains, dict) or set(gains) != set(expand_edges):
            actual = set(gains) if isinstance(gains, dict) else set()
            errors.append(
                "detail_information_gain_contracts must map every Level 2/3 expansion exactly; "
                f"missing={sorted(set(expand_edges) - actual)}, extra={sorted(actual - set(expand_edges))}"
            )
            gains = gains if isinstance(gains, dict) else {}
        for edge_id, edge in expand_edges.items():
            contract = gains.get(edge_id)
            if not isinstance(contract, dict):
                continue
            parent_region = nodes.get(edge.get("source"), {}).get("region")
            child_region = nodes.get(edge.get("target"), {}).get("region")
            if contract.get("parent_region") != parent_region:
                errors.append(f"detail information gain {edge_id}.parent_region must be {parent_region!r}")
            if contract.get("child_region") != child_region:
                errors.append(f"detail information gain {edge_id}.child_region must be {child_region!r}")
            if contract.get("status") != "pass" or contract.get("method") != "parent-child-delta-review":
                errors.append(
                    f"detail information gain {edge_id} requires status pass via parent-child-delta-review"
                )
            items = contract.get("new_information")
            if not isinstance(items, list) or not items:
                errors.append(f"detail information gain {edge_id}.new_information must be non-empty")
                items = []
            for index, item in enumerate(items):
                prefix = f"detail_information_gain_contracts.{edge_id}.new_information[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                if item.get("kind") not in DETAIL_INFORMATION_KINDS:
                    errors.append(f"{prefix}.kind is invalid")
                if not isinstance(item.get("summary"), str) or not item["summary"].strip():
                    errors.append(f"{prefix}.summary is required")
                item_nodes = item.get("nodes")
                if not non_empty_string_list(item_nodes) or any(
                    node_id not in nodes
                    or not region_owns_region(regions, child_region, nodes[node_id].get("region"))
                    for node_id in item_nodes or []
                ):
                    errors.append(f"{prefix}.nodes must name visible nodes owned by the child detail region")
                refs = item.get("evidence")
                if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs or []):
                    errors.append(f"{prefix}.evidence must cite known evidence IDs")
            if not non_empty_string_list(contract.get("findings")):
                errors.append(f"detail information gain {edge_id}.findings must be a non-empty string list")

    implementation_regions = {
        region_id: region for region_id, region in regions.items()
        if isinstance(region, dict) and region.get("granularity") == "implementation-detail"
    }
    runtime_contracts = data.get("runtime_variant_contracts")
    if implementation_regions:
        if not isinstance(runtime_contracts, dict) or set(runtime_contracts) != set(implementation_regions):
            actual = set(runtime_contracts) if isinstance(runtime_contracts, dict) else set()
            errors.append(
                "runtime_variant_contracts must map every implementation-detail region exactly; "
                f"missing={sorted(set(implementation_regions) - actual)}, "
                f"extra={sorted(actual - set(implementation_regions))}"
            )
            runtime_contracts = runtime_contracts if isinstance(runtime_contracts, dict) else {}
        for region_id, region in implementation_regions.items():
            contract = runtime_contracts.get(region_id)
            if not isinstance(contract, dict):
                continue
            status = contract.get("status")
            if status == "not-applicable":
                if not isinstance(contract.get("reason"), str) or not contract["reason"].strip():
                    errors.append(f"runtime variant {region_id}.reason is required when not-applicable")
            elif status == "pass":
                if contract.get("method") != "source-branch-review":
                    errors.append(f"runtime variant {region_id}.method must be source-branch-review")
                if not non_empty_string_list(contract.get("source_discriminators")):
                    errors.append(f"runtime variant {region_id}.source_discriminators must be non-empty")
                variants = contract.get("variants")
                if not isinstance(variants, list) or len(variants) < 2:
                    errors.append(f"runtime variant {region_id}.variants must contain at least two distinct paths")
                    variants = []
                available_sequences = {
                    item.get("id") for item in region.get("operator_sequences", []) if isinstance(item, dict)
                }
                variant_ids: list[str] = []
                covered_sequences: set[str] = set()
                for index, variant in enumerate(variants):
                    prefix = f"runtime_variant_contracts.{region_id}.variants[{index}]"
                    if not isinstance(variant, dict):
                        errors.append(f"{prefix} must be an object")
                        continue
                    variant_ids.append(variant.get("id"))
                    sequence_ids = variant.get("sequence_ids")
                    if not non_empty_string_list(sequence_ids) or any(
                        sequence_id not in available_sequences for sequence_id in sequence_ids or []
                    ):
                        errors.append(f"{prefix}.sequence_ids must name region operator_sequences")
                    else:
                        covered_sequences.update(sequence_ids)
                    refs = variant.get("evidence")
                    if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs or []):
                        errors.append(f"{prefix}.evidence must cite known evidence IDs")
                if len(set(variant_ids)) != len(variant_ids) or any(
                    not isinstance(item, str) or not ID.fullmatch(item) for item in variant_ids
                ):
                    errors.append(f"runtime variant {region_id} has invalid or duplicate variant IDs")
                if covered_sequences != available_sequences:
                    errors.append(
                        f"runtime variant {region_id} must cover every region operator_sequence; "
                        f"missing={sorted(available_sequences - covered_sequences)}, "
                        f"extra={sorted(covered_sequences - available_sequences)}"
                    )
            else:
                errors.append(f"runtime variant {region_id}.status must be pass or not-applicable")
            shared = contract.get("shared_state_nodes", [])
            if not isinstance(shared, list) or any(
                node_id not in nodes or nodes[node_id].get("kind") not in {"cache", "state"}
                for node_id in shared
            ):
                errors.append(f"runtime variant {region_id}.shared_state_nodes must name cache/state nodes")
            refs = contract.get("evidence")
            if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs or []):
                errors.append(f"runtime variant {region_id}.evidence must cite known evidence IDs")
            if not non_empty_string_list(contract.get("findings")):
                errors.append(f"runtime variant {region_id}.findings must be a non-empty string list")

    state_nodes = {
        node_id: node for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("kind") in {"cache", "state"}
    }
    lifecycles = data.get("state_lifecycle_contracts")
    if state_nodes:
        if not isinstance(lifecycles, dict) or set(lifecycles) != set(state_nodes):
            actual = set(lifecycles) if isinstance(lifecycles, dict) else set()
            errors.append(
                "state_lifecycle_contracts must map every cache/state node exactly; "
                f"missing={sorted(set(state_nodes) - actual)}, extra={sorted(actual - set(state_nodes))}"
            )
            lifecycles = lifecycles if isinstance(lifecycles, dict) else {}
        sequence_state_nodes = {
            node_id
            for region in regions.values() if isinstance(region, dict)
            for sequence in region.get("operator_sequences", []) if isinstance(sequence, dict)
            for node_id in sequence.get("nodes", []) if node_id in state_nodes
        }
        for node_id in sorted(sequence_state_nodes):
            errors.append(
                f"state node {node_id} must use a side lane and cannot appear in operator_sequences"
            )
        for node_id, node in state_nodes.items():
            contract = lifecycles.get(node_id)
            if not isinstance(contract, dict):
                continue
            if contract.get("status") != "pass" or contract.get("method") != "state-lifecycle-review":
                errors.append(f"state lifecycle {node_id} requires status pass via state-lifecycle-review")
            for field in ("storage_shape", "layout", "dtype", "scope", "lifetime"):
                if not isinstance(contract.get(field), str) or not contract[field].strip():
                    errors.append(f"state lifecycle {node_id}.{field} is required")
            for role, expected_direction in (("writers", "write"), ("readers", "read")):
                records = contract.get(role)
                alternative = "initial_state_reason" if role == "writers" else "output_state_reason"
                if not isinstance(records, list):
                    errors.append(f"state lifecycle {node_id}.{role} must be a list")
                    records = []
                if not records and (
                    not isinstance(contract.get(alternative), str) or not contract[alternative].strip()
                ):
                    errors.append(f"state lifecycle {node_id} requires {role} or {alternative}")
                for index, record in enumerate(records):
                    prefix = f"state_lifecycle_contracts.{node_id}.{role}[{index}]"
                    if not isinstance(record, dict):
                        errors.append(f"{prefix} must be an object")
                        continue
                    operation, edge_id = record.get("operation"), record.get("edge")
                    edge = edges.get(edge_id)
                    if operation not in nodes or nodes.get(operation, {}).get("kind") != "operator":
                        errors.append(f"{prefix}.operation must name an operator node")
                    if not isinstance(edge, dict) or edge.get("kind") != "tensor":
                        errors.append(f"{prefix}.edge must name a tensor edge")
                    elif expected_direction == "write" and (edge.get("source"), edge.get("target")) != (operation, node_id):
                        errors.append(f"{prefix}.edge must connect writer operation -> state")
                    elif expected_direction == "read" and (edge.get("source"), edge.get("target")) != (node_id, operation):
                        errors.append(f"{prefix}.edge must connect state -> reader operation")
                    if not non_empty_string_list(record.get("addressing")):
                        errors.append(f"{prefix}.addressing must be a non-empty string list")
            refs = contract.get("evidence")
            if not non_empty_string_list(refs) or any(ref not in evidence_ids for ref in refs or []):
                errors.append(f"state lifecycle {node_id}.evidence must cite known evidence IDs")
    return errors


def validate_loop_contracts(data: dict, regions: dict, nodes: dict) -> list[str]:
    """Validate explicit indexed-loop boundaries, without proving recurrence algebra."""
    errors = []
    evidence_ids = {e.get("id") for e in data.get("evidence", []) if isinstance(e, dict)}
    for rid, region in regions.items():
        if not isinstance(region, dict) or "loop_contract" not in region:
            continue
        contract = region["loop_contract"]
        prefix = f"region {rid}.loop_contract"
        if not isinstance(contract, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("domain", "feedback", "physical_execution", "source"):
            if not isinstance(contract.get(field), str) or not contract[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        refs = contract.get("evidence")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in evidence_ids for ref in refs)):
            errors.append(f"{prefix}.evidence must name known evidence IDs")
        inputs = contract.get("step_inputs")
        if (not isinstance(inputs, list) or not inputs
                or any(not isinstance(nid, str) for nid in inputs)):
            errors.append(f"{prefix}.step_inputs must be a non-empty node ID list")
            inputs = []
        elif len(set(inputs)) != len(inputs):
            errors.append(f"{prefix}.step_inputs must not contain duplicates")
        references = [("step_inputs", nid) for nid in inputs]
        references += [(field, contract.get(field)) for field in (
            "state_input", "state_output", "output_assembly")]
        for field, nid in references:
            if not isinstance(nid, str) or nid not in nodes or nodes[nid].get("region") != rid:
                errors.append(f"{prefix}.{field} must name a node owned by {rid}")
                continue
            node = nodes[nid]
            if field in {"state_input", "state_output"} and node.get("kind") not in {"state", "cache"}:
                errors.append(f"{prefix}.{field} must name a persistent state/cache boundary")
            if field == "output_assembly" and node.get("kind") != "operator":
                errors.append(f"{prefix}.output_assembly must name an operator")
            for view in region.get("views", []):
                if view not in node.get("views", []):
                    errors.append(f"{prefix} loses {field} node {nid} in view {view}")
        sequence_nodes = {
            nid for seq in region.get("operator_sequences", []) if isinstance(seq, dict)
            for nid in seq.get("nodes", []) if isinstance(nid, str)
        }
        for field, nid in references:
            if field in {"step_inputs", "output_assembly"} and isinstance(nid, str) and nid not in sequence_nodes:
                errors.append(f"{prefix}.{field} node {nid} is absent from operator_sequences")
    return errors


def validate(data: dict, base: Path, require_files: bool = False) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    project = data.get("project")
    if not isinstance(project, dict) or project.get("output_view") not in VIEWS:
        errors.append("project.output_view must be hierarchy-master, end-to-end-dataflow, or paired")
    if isinstance(project, dict) and "require_source_coverage" in project and not isinstance(project["require_source_coverage"], bool):
        errors.append("project.require_source_coverage must be a boolean")
    if isinstance(project, dict) and "require_view_projection_contracts" in project and not isinstance(
        project["require_view_projection_contracts"], bool
    ):
        errors.append("project.require_view_projection_contracts must be a boolean")
    if isinstance(project, dict) and "require_logical_operator_contracts" in project and not isinstance(
        project["require_logical_operator_contracts"], bool
    ):
        errors.append("project.require_logical_operator_contracts must be a boolean")
    require_logical_contracts = (
        isinstance(project, dict) and project.get("require_logical_operator_contracts") is True
    )

    evidence = data.get("evidence")
    evidence_ids: set[str] = set()
    evidence_by_id: dict[str, dict] = {}
    roles: set[str] = set()
    if not isinstance(evidence, list) or len(evidence) < 2:
        errors.append("evidence must contain at least two sources")
        evidence = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not ID.fullmatch(item_id):
            errors.append(f"evidence[{index}].id is invalid")
        elif item_id in evidence_ids:
            errors.append(f"duplicate evidence id: {item_id}")
        else:
            evidence_ids.add(item_id)
            evidence_by_id[item_id] = item
        role = item.get("role")
        if role not in EVIDENCE_ROLES:
            errors.append(f"evidence[{index}].role is invalid: {role!r}")
        else:
            roles.add(role)
        if not item.get("revision"):
            errors.append(f"evidence[{index}].revision is required; use 'unknown' explicitly")
        source_path = item.get("path")
        if not isinstance(source_path, str) or not source_path:
            errors.append(f"evidence[{index}].path is required")
        elif require_files and not (base / source_path).resolve().is_file():
            errors.append(f"evidence[{index}] file does not exist: {(base / source_path).resolve()}")
    if "checkpoint-config" not in roles:
        errors.append("evidence requires a checkpoint-config source")
    if not roles.intersection({"canonical-model", "inference-implementation"}):
        errors.append("evidence requires executable model evidence")

    regions = data.get("regions")
    if not isinstance(regions, dict) or not regions:
        errors.append("regions must be a non-empty object")
        regions = {}
    for region_id, region in regions.items():
        if not ID.fullmatch(region_id):
            errors.append(f"invalid region id: {region_id!r}")
        if not isinstance(region, dict):
            errors.append(f"region {region_id} must be an object")
            continue
        parent = region.get("parent")
        if parent is not None and parent not in regions:
            errors.append(f"region {region_id} has missing parent {parent!r}")
        if region.get("direction") != "column":
            errors.append(f"region {region_id}.direction must be column for vertical block flow")
        if region.get("child_direction", "row") not in {"row", "column"}:
            errors.append(f"region {region_id}.child_direction must be row or column")
        granularity = region.get("granularity")
        if granularity not in GRANULARITIES:
            errors.append(f"region {region_id}.granularity is missing or invalid")
        flow_direction = region.get("flow_direction")
        if flow_direction is not None and flow_direction not in FLOW_DIRECTIONS:
            errors.append(f"region {region_id}.flow_direction is invalid: {flow_direction!r}")
        if flow_direction != "bottom-to-top":
            errors.append(f"region {region_id}.flow_direction must be bottom-to-top")
        if not isinstance(region.get("level"), int) or region["level"] not in {0, 1, 2, 3}:
            errors.append(f"region {region_id}.level must be one of 0, 1, 2, or 3")
    for start in regions:
        seen: set[str] = set()
        cursor: str | None = start
        while cursor is not None:
            if cursor in seen:
                errors.append(f"region ownership cycle includes {cursor}")
                break
            seen.add(cursor)
            value = regions.get(cursor)
            cursor = value.get("parent") if isinstance(value, dict) else None

    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        errors.append("nodes must be a non-empty object")
        nodes = {}
    for node_id, node in nodes.items():
        if not ID.fullmatch(node_id):
            errors.append(f"invalid node id: {node_id!r}")
        if not isinstance(node, dict):
            errors.append(f"node {node_id} must be an object")
            continue
        if node.get("kind") not in KINDS:
            errors.append(f"node {node_id}.kind is invalid")
        if node.get("region") not in regions:
            errors.append(f"node {node_id} has missing region {node.get('region')!r}")
        refs = node.get("evidence")
        if not isinstance(refs, list) or not refs:
            errors.append(f"node {node_id} must cite at least one evidence id")
        else:
            for ref in refs:
                if ref not in evidence_ids:
                    errors.append(f"node {node_id} cites unknown evidence {ref!r}")

        visual_class = node.get("visual_class")
        if visual_class is not None and visual_class not in SEMANTIC_PALETTE:
            errors.append(f"node {node_id}.visual_class is invalid: {visual_class!r}")
        elif visual_class is not None and visual_class not in allowed_visual_classes(node):
            errors.append(
                f"node {node_id}.visual_class {visual_class!r} conflicts with its kind/op_type; "
                f"allowed={sorted(allowed_visual_classes(node))}"
            )
        elif node.get("kind") != "junction" and resolve_visual_class(node) is None:
            errors.append(f"node {node_id} has no resolvable semantic visual class")
        inferred_class = resolve_visual_class({key: value for key, value in node.items() if key != "visual_class"})
        if visual_class is not None and visual_class != inferred_class and (
            not isinstance(node.get("visual_class_reason"), str) or not node["visual_class_reason"].strip()
        ):
            errors.append(
                f"node {node_id}.visual_class overrides inferred {inferred_class!r} and requires visual_class_reason"
            )
        modifiers = node.get("visual_modifiers", [])
        if not isinstance(modifiers, list) or any(modifier not in VISUAL_MODIFIERS for modifier in modifiers):
            errors.append(
                f"node {node_id}.visual_modifiers must be a list drawn from {sorted(VISUAL_MODIFIERS)}"
            )
        elif len(set(modifiers)) != len(modifiers):
            errors.append(f"node {node_id}.visual_modifiers contains duplicates")
        if "tp-partition" in modifiers and node.get("kind") in {"cache", "state", "junction"}:
            errors.append(f"node {node_id} cannot apply tp-partition to kind {node.get('kind')!r}")
        if "tp-partition" in modifiers and (
            not isinstance(node.get("visual_modifier_reason"), str) or not node["visual_modifier_reason"].strip()
        ):
            errors.append(f"node {node_id} tp-partition requires visual_modifier_reason")

        region = regions.get(node.get("region"), {})
        if require_logical_contracts and region.get("granularity") == "operator-detail" and node.get("kind") not in {
            "interface", "cache", "state", "junction"
        }:
            contract = node.get("operator_contract")
            if not isinstance(contract, dict):
                errors.append(f"operator-detail node {node_id} requires operator_contract")
                continue
            classification = contract.get("classification")
            if classification not in OPERATOR_CLASSIFICATIONS:
                errors.append(f"operator-detail node {node_id} has invalid operator classification {classification!r}")
                continue
            semantic_role = contract.get("semantic_role")
            if not isinstance(semantic_role, str) or not SEMANTIC_ROLE.fullmatch(semantic_role):
                errors.append(
                    f"operator-detail node {node_id}.operator_contract.semantic_role "
                    "must be a lower-kebab reader-facing role"
                )
            source_symbols = contract.get("source_symbols")
            if not isinstance(source_symbols, list) or not source_symbols or any(
                not isinstance(symbol, str) or not symbol.strip() for symbol in source_symbols
            ):
                errors.append(
                    f"operator-detail node {node_id}.operator_contract.source_symbols "
                    "must be a non-empty list of exact source symbols"
                )
            primary_label = primary_reader_label(node)
            if not primary_label:
                errors.append(f"operator-detail node {node_id} requires a reader-facing label")
            else:
                if SOURCE_IDENTIFIER_IN_LABEL.search(primary_label):
                    errors.append(
                        f"operator-detail node {node_id} primary label contains a source identifier; "
                        "move it to source_symbols or a secondary line"
                    )
                if OPAQUE_PRIMARY_LABEL.fullmatch(primary_label):
                    errors.append(
                        f"operator-detail node {node_id} primary label is opaque; name the mathematical "
                        "operation or model-specific algorithm role"
                    )
            if OPERATOR_LABEL_SHAPE.search(str(node.get("label", ""))):
                errors.append(
                    f"operator-detail node {node_id} label contains an activation or parameter shape; "
                    "put activation shapes on tensor edges and parameters in structured annotations"
                )
            if node.get("kind") == "module" and classification != "expanded-elsewhere":
                errors.append(f"operator-detail module node {node_id} must be expanded-elsewhere")
            if classification != "expanded-elsewhere" and node.get("kind") != "operator":
                errors.append(f"logical operator node {node_id} must use kind operator")
            if classification != "expanded-elsewhere":
                op_type = contract.get("op_type")
                if op_type not in OPERATOR_TYPES:
                    errors.append(f"operator-detail node {node_id} has invalid or missing op_type {op_type!r}")
                if contract.get("shape_rule") not in SHAPE_RULES:
                    errors.append(f"operator-detail node {node_id} has invalid or missing shape_rule")
                if (
                    op_type in PARAMETERIZED_OPERATOR_TYPES
                    and not node.get("parameter_shapes")
                    and not isinstance(node.get("parameterless_reason"), str)
                ):
                    errors.append(
                        f"parameterized operator {node_id} requires structured parameter_shapes "
                        "or a source-backed parameterless_reason"
                    )
                if "parameterless_reason" in node and (
                    not isinstance(node["parameterless_reason"], str) or not node["parameterless_reason"].strip()
                ):
                    errors.append(f"node {node_id}.parameterless_reason must be a non-empty string")
                if op_type == "custom" and (
                    not isinstance(contract.get("definition"), str) or not contract["definition"].strip()
                ):
                    errors.append(f"custom operator {node_id} requires a definition")
                if op_type == "custom" and (
                    not isinstance(contract.get("formula"), str) or not contract["formula"].strip()
                ):
                    errors.append(f"custom operator {node_id} requires a concrete formula")
                if op_type == "custom" and (
                    not isinstance(contract.get("atomicity_reason"), str)
                    or not contract["atomicity_reason"].strip()
                ):
                    errors.append(
                        f"custom operator {node_id} requires atomicity_reason or must be decomposed"
                    )
                expected_terms = OP_TYPE_DISPLAY_TERMS.get(op_type, ())
                if expected_terms and primary_label and not any(
                    re.search(pattern, primary_label, re.IGNORECASE) for pattern in expected_terms
                ):
                    errors.append(
                        f"operator-detail node {node_id} reader label does not identify op_type {op_type!r}"
                    )
                if classification == "atomic-operator" and op_type != "custom":
                    families = operator_families_in_label(str(node.get("label", "")))
                    if len(families) >= 2:
                        errors.append(
                            f"atomic operator {node_id} label appears to combine multiple operations: {sorted(families)}"
                        )
            if classification == "expanded-elsewhere":
                detail_region = contract.get("detail_region")
                if detail_region not in regions or regions.get(detail_region, {}).get("granularity") not in {
                    "operator-detail", "implementation-detail"
                }:
                    errors.append(f"operator-detail node {node_id} expanded-elsewhere requires a valid detail_region")
                elif detail_region == node.get("region"):
                    errors.append(f"operator-detail node {node_id} cannot expand into its own region")
                if not isinstance(contract.get("reason"), str) or not contract["reason"].strip():
                    errors.append(f"operator-detail node {node_id} expanded-elsewhere requires a reason")

    operator_detail_regions = {
        region_id for region_id, region in regions.items()
        if isinstance(region, dict) and region.get("granularity") == "operator-detail"
    }
    if require_logical_contracts and operator_detail_regions:
        naming_review = data.get("operator_naming_review")
        if not isinstance(naming_review, dict):
            errors.append("operator_naming_review is required for strict operator-detail IR")
        else:
            if naming_review.get("status") != "pass":
                errors.append("operator_naming_review.status must be pass")
            if naming_review.get("method") != "reader-and-source-review":
                errors.append("operator_naming_review.method must be reader-and-source-review")
            reviewed_regions = naming_review.get("reviewed_region_ids")
            if not isinstance(reviewed_regions, list) or any(
                not isinstance(region_id, str) for region_id in reviewed_regions
            ):
                errors.append("operator_naming_review.reviewed_region_ids must be a list of strings")
            elif set(reviewed_regions) != operator_detail_regions or len(reviewed_regions) != len(operator_detail_regions):
                errors.append(
                    "operator_naming_review.reviewed_region_ids must match all operator-detail regions exactly"
                )
            required_checks = {
                "reader-facing-labels", "source-symbol-traceability", "sibling-consistency"
            }
            checks = naming_review.get("checks")
            if (
                not isinstance(checks, list)
                or any(not isinstance(check, str) for check in checks)
                or not required_checks.issubset(set(checks))
            ):
                errors.append(
                    "operator_naming_review.checks must include reader-facing-labels, "
                    "source-symbol-traceability, and sibling-consistency"
                )
            findings = naming_review.get("findings")
            if not isinstance(findings, list) or not findings or any(
                not isinstance(finding, str) or not finding.strip() for finding in findings
            ):
                errors.append("operator_naming_review.findings must be a non-empty list of strings")

        display_contract = data.get("operator_display_contract")
        if not isinstance(display_contract, dict):
            errors.append("operator_display_contract is required for strict operator-detail IR")
        else:
            if display_contract.get("status") != "pass":
                errors.append("operator_display_contract.status must be pass")
            if display_contract.get("method") != "reader-shape-parameter-review":
                errors.append(
                    "operator_display_contract.method must be reader-shape-parameter-review"
                )
            reviewed_regions = display_contract.get("reviewed_region_ids")
            if not isinstance(reviewed_regions, list) or set(reviewed_regions) != operator_detail_regions:
                errors.append(
                    "operator_display_contract.reviewed_region_ids must match all operator-detail regions exactly"
                )
            placements = {
                "activation_shape_placement": "tensor-edges",
                "parameter_shape_placement": "external-annotations-or-structured-ir",
                "source_symbol_placement": "structured-ir-or-secondary-line",
            }
            for field, expected in placements.items():
                if display_contract.get(field) != expected:
                    errors.append(f"operator_display_contract.{field} must be {expected}")
            checks = display_contract.get("checks")
            if not isinstance(checks, list) or not DISPLAY_REQUIRED_CHECKS.issubset(set(checks)):
                errors.append(f"operator_display_contract.checks must include {sorted(DISPLAY_REQUIRED_CHECKS)}")
            if not non_empty_string_list(display_contract.get("findings")):
                errors.append("operator_display_contract.findings must be a non-empty string list")

    edges = data.get("edges")
    if not isinstance(edges, dict):
        errors.append("edges must be an object")
        edges = {}
    detail_tensor_edges: dict[str, dict] = {}
    unknown_material_edges: set[str] = set()
    for edge_id, edge in edges.items():
        if not ID.fullmatch(edge_id):
            errors.append(f"invalid edge id: {edge_id!r}")
        if not isinstance(edge, dict):
            errors.append(f"edge {edge_id} must be an object")
            continue
        if edge.get("source") not in nodes or edge.get("target") not in nodes:
            errors.append(f"edge {edge_id} has a missing endpoint")
        if edge.get("source") == edge.get("target"):
            errors.append(f"edge {edge_id} is a self-loop")
        if edge.get("kind") not in EDGE_KINDS:
            errors.append(f"edge {edge_id}.kind is invalid")
        if edge.get("kind") == "expand":
            if isinstance(project, dict) and project.get("output_view") == "end-to-end-dataflow":
                errors.append(f"edge {edge_id} uses hierarchy expansion in an end-to-end-dataflow view")
            source = nodes.get(edge.get("source"), {})
            target = nodes.get(edge.get("target"), {})
            if source.get("region") == target.get("region"):
                errors.append(f"edge {edge_id} expansion must target a different child region")
            if not isinstance(edge.get("label"), str) or not edge["label"].strip():
                errors.append(f"edge {edge_id} expansion requires a non-empty label")
            attachment = edge.get("visual_attachment")
            if attachment is not None:
                if not isinstance(attachment, dict):
                    errors.append(f"edge {edge_id}.visual_attachment must be an object")
                else:
                    mode = attachment.get("mode")
                    if mode not in HIERARCHY_ATTACHMENT_MODES:
                        errors.append(f"edge {edge_id}.visual_attachment.mode is invalid: {mode!r}")
                    side = attachment.get("side")
                    if side is not None and side not in HIERARCHY_SIDES:
                        errors.append(f"edge {edge_id}.visual_attachment.side is invalid: {side!r}")
                    if mode == "owner-region-boundary":
                        attachment_region = attachment.get("region")
                        source_region = source.get("region")
                        if attachment_region not in regions:
                            errors.append(f"edge {edge_id}.visual_attachment.region is invalid")
                        elif not region_owns_region(regions, attachment_region, source_region):
                            errors.append(
                                f"edge {edge_id} attachment region {attachment_region!r} "
                                f"does not own source node {edge.get('source')!r}"
                            )
                        anchor_label = attachment.get("anchor_label")
                        if not isinstance(anchor_label, str) or not anchor_label.strip():
                            errors.append(
                                f"edge {edge_id} owner-region-boundary attachment requires anchor_label"
                            )
                        elif isinstance(edge.get("label"), str) and anchor_label.casefold() not in edge["label"].casefold():
                            errors.append(
                                f"edge {edge_id} expansion label must name anchor_label {anchor_label!r}"
                            )
                    elif mode == "parent-node" and "region" in attachment:
                        errors.append(
                            f"edge {edge_id} parent-node attachment must not declare a region"
                        )
        elif edge.get("kind") == "tensor" and require_logical_contracts:
            source_region = regions.get(nodes.get(edge.get("source"), {}).get("region"), {})
            target_region = regions.get(nodes.get(edge.get("target"), {}).get("region"), {})
            touches_detail = any(
                region.get("granularity") in {"operator-detail", "implementation-detail"}
                for region in (source_region, target_region)
            )
            if touches_detail:
                tensor = edge.get("tensor")
                if not isinstance(tensor, dict):
                    errors.append(f"detail tensor edge {edge_id} requires a structured tensor contract")
                else:
                    detail_tensor_edges[edge_id] = tensor
                    if not isinstance(tensor.get("name"), str) or not tensor["name"].strip():
                        errors.append(f"detail tensor edge {edge_id}.tensor.name is required")
                    elif re.search(r",|\s+\+\s+|\s*/\s*", tensor["name"]):
                        errors.append(
                            f"detail tensor edge {edge_id}.tensor.name must identify one tensor, not a packed list"
                        )
                    shape = tensor.get("shape")
                    if not isinstance(shape, str) or not shape.strip():
                        errors.append(f"detail tensor edge {edge_id}.tensor.shape is required")
                    elif shape not in {"?", "scalar"} and not (shape.startswith("[") and shape.endswith("]")):
                        errors.append(
                            f"detail tensor edge {edge_id}.tensor.shape must be bracketed, scalar, or ?"
                        )
                    status = tensor.get("status")
                    if status not in TENSOR_SHAPE_STATUSES:
                        errors.append(f"detail tensor edge {edge_id}.tensor.status is invalid: {status!r}")
                    if shape == "?" and status not in {"unknown", "backend-dependent"}:
                        errors.append(f"detail tensor edge {edge_id} shape ? conflicts with status {status!r}")
                    if status == "unknown" and shape != "?":
                        errors.append(f"detail tensor edge {edge_id} status unknown requires shape ?")
                    if status in {"unknown", "backend-dependent", "inferred"} and (
                        not isinstance(tensor.get("reason"), str) or not tensor["reason"].strip()
                    ):
                        errors.append(f"detail tensor edge {edge_id}.tensor.reason is required for {status}")
                    refs = tensor.get("evidence", [])
                    if status in {"code-confirmed", "config-confirmed", "report-confirmed"} and not refs:
                        errors.append(f"detail tensor edge {edge_id}.tensor.evidence is required for {status}")
                    if not isinstance(refs, list):
                        errors.append(f"detail tensor edge {edge_id}.tensor.evidence must be a list")
                    else:
                        for ref in refs:
                            if ref not in evidence_ids:
                                errors.append(f"detail tensor edge {edge_id} cites unknown tensor evidence {ref!r}")
                    expected_roles = {
                        "code-confirmed": {"canonical-model", "inference-implementation"},
                        "config-confirmed": {"checkpoint-config"},
                        "report-confirmed": {"official-report"},
                    }.get(status)
                    if expected_roles and isinstance(refs, list) and refs and not any(
                        evidence_by_id.get(ref, {}).get("role") in expected_roles for ref in refs
                    ):
                        errors.append(
                            f"detail tensor edge {edge_id} status {status} lacks matching evidence role"
                        )
                    if "material" in tensor and not isinstance(tensor["material"], bool):
                        errors.append(f"detail tensor edge {edge_id}.tensor.material must be a boolean")
                    if shape == "?" and tensor.get("material", True) is True:
                        unknown_material_edges.add(edge_id)
                    for optional in ("dtype", "layout", "domain"):
                        if optional in tensor and (
                            not isinstance(tensor[optional], str) or not tensor[optional].strip()
                        ):
                            errors.append(f"detail tensor edge {edge_id}.tensor.{optional} must be a non-empty string")
                    constraints = tensor.get("constraints", [])
                    if not isinstance(constraints, list) or not all(
                        isinstance(item, str) and item.strip() for item in constraints
                    ):
                        errors.append(f"detail tensor edge {edge_id}.tensor.constraints must be a string list")

    errors.extend(validate_view_projection_contract(data, regions, nodes, edges))
    errors.extend(validate_loop_contracts(data, regions, nodes))

    fusion_ids: set[str] = set()
    fusion_by_id: dict[str, dict] = {}
    if require_logical_contracts:
        shape_symbols = data.get("shape_symbols")
        builtin_shape_terms = {"sum", "ceil", "floor", "max", "min"}
        if not isinstance(shape_symbols, dict) or not shape_symbols:
            errors.append("strict logical operator contracts require a non-empty shape_symbols object")
        else:
            for symbol, meaning in shape_symbols.items():
                valid_meaning = isinstance(meaning, str) and meaning.strip()
                if isinstance(meaning, dict):
                    valid_meaning = isinstance(meaning.get("meaning"), str) and meaning["meaning"].strip()
                if not isinstance(symbol, str) or not symbol.strip() or not valid_meaning:
                    errors.append("shape_symbols must map non-empty symbols to meanings or meaning objects")
            for edge_id, tensor in detail_tensor_edges.items():
                shape = tensor.get("shape", "")
                if not isinstance(shape, str) or not shape.startswith("["):
                    continue
                undefined = sorted(set(SHAPE_TOKEN.findall(shape)) - set(shape_symbols) - builtin_shape_terms)
                if undefined:
                    errors.append(f"detail tensor edge {edge_id} uses undefined shape symbols: {undefined}")
        for node_id, node in nodes.items():
            parameter_shapes = node.get("parameter_shapes") if isinstance(node, dict) else None
            if parameter_shapes is None:
                continue
            if not isinstance(parameter_shapes, list) or not parameter_shapes or any(
                not isinstance(item, str) or ":" not in item or not all(part.strip() for part in item.split(":", 1))
                for item in parameter_shapes
            ):
                errors.append(
                    f"node {node_id}.parameter_shapes must be a non-empty list of 'name: shape' strings"
                )
                continue
            if isinstance(shape_symbols, dict):
                for item in parameter_shapes:
                    shape = item.split(":", 1)[1]
                    undefined = sorted(set(SHAPE_TOKEN.findall(shape)) - set(shape_symbols) - builtin_shape_terms)
                    if undefined:
                        errors.append(
                            f"node {node_id}.parameter_shapes uses undefined shape symbols: {undefined}"
                        )

        for region_id, region in regions.items():
            if region.get("granularity") == "operator-detail" and region.get("operator_standard") != "logical-tensor-ops":
                errors.append(f"operator-detail region {region_id}.operator_standard must be logical-tensor-ops")

        view_types = {"split", "chunk", "slice", "unbind", "concatenate", "reshape", "view", "transpose", "permute", "repeat", "broadcast"}
        for node_id, node in nodes.items():
            region = regions.get(node.get("region"), {})
            contract = node.get("operator_contract", {})
            if region.get("granularity") != "operator-detail" or not isinstance(contract, dict):
                continue
            classification = contract.get("classification")
            op_type = contract.get("op_type")
            if classification == "view-transform" and op_type not in view_types:
                errors.append(f"view-transform {node_id} has non-view op_type {op_type!r}")
            if classification == "atomic-operator" and op_type in view_types:
                errors.append(f"view operation {node_id} must use classification view-transform")

            if classification not in {None, "expanded-elsewhere"}:
                incoming, outgoing = tensor_edges_for_node(edges, node_id)
                if not incoming or not outgoing:
                    errors.append(f"logical operator {node_id} requires incoming and outgoing tensor edges")
                incoming_shapes = [
                    detail_tensor_edges.get(edge_id, {}).get("shape")
                    for edge_id in incoming
                    if detail_tensor_edges.get(edge_id, {}).get("shape") not in {None, "?"}
                ]
                outgoing_shapes = [
                    detail_tensor_edges.get(edge_id, {}).get("shape")
                    for edge_id in outgoing
                    if detail_tensor_edges.get(edge_id, {}).get("shape") not in {None, "?"}
                ]
                shapes = [
                    detail_tensor_edges.get(edge_id, {}).get("shape")
                    for edge_id in incoming + outgoing
                    if detail_tensor_edges.get(edge_id, {}).get("shape") not in {None, "?"}
                ]
                shape_rule = contract.get("shape_rule")
                allowed_shape_rules = OP_TYPE_SHAPE_RULES.get(op_type)
                if allowed_shape_rules is not None and shape_rule not in allowed_shape_rules:
                    errors.append(
                        f"operator {node_id} op_type {op_type} requires shape_rule in {sorted(allowed_shape_rules)}"
                    )
                if shape_rule == "preserve" and len(set(shapes)) > 1:
                    errors.append(f"shape-preserving operator {node_id} has inconsistent edge shapes: {sorted(set(shapes))}")
                if shape_rule == "preserve" and isinstance(contract.get("shape_equation"), str):
                    equation = re.sub(r"\s+", "", contract["shape_equation"])
                    stated_shapes = re.findall(r"\[[^\[\]]+\]", equation)
                    if SHAPE_EQUATION_SEPARATOR.search(equation) and stated_shapes and any(
                        re.sub(r"\s+", "", shape) not in stated_shapes for shape in shapes
                    ):
                        errors.append(f"operator {node_id} preserve shape_equation omits input edge shapes or output edge shapes: {sorted(set(shapes))}")
                if shape_rule == "multi-input" and len(incoming) < 2:
                    errors.append(f"multi-input operator {node_id} requires at least two incoming tensor edges")
                if shape_rule == "multi-output" and len(outgoing) < 2:
                    errors.append(f"multi-output operator {node_id} requires at least two outgoing tensor edges")
                if shape_rule in {"transform", "multi-input", "multi-output", "stateful", "custom"} and (
                    not isinstance(contract.get("shape_equation"), str) or not contract["shape_equation"].strip()
                ):
                    errors.append(f"operator {node_id} shape_rule {shape_rule} requires shape_equation")
                elif shape_rule in {"transform", "multi-input", "multi-output"}:
                    equation = re.sub(r"\s+", "", contract["shape_equation"])
                    sides = SHAPE_EQUATION_SEPARATOR.split(equation, maxsplit=1)
                    if len(sides) != 2:
                        errors.append(
                            f"operator {node_id} shape_equation must separate input and output with ->, →, or <->"
                        )
                    else:
                        left, right = sides
                        missing_inputs = sorted({
                            shape for shape in incoming_shapes
                            if re.sub(r"\s+", "", shape) not in left
                        })
                        missing_outputs = sorted({
                            shape for shape in outgoing_shapes
                            if re.sub(r"\s+", "", shape) not in right
                        })
                        if missing_inputs:
                            errors.append(
                                f"operator {node_id} shape_equation omits input edge shapes: {missing_inputs}"
                            )
                        if missing_outputs:
                            errors.append(
                                f"operator {node_id} shape_equation omits output edge shapes: {missing_outputs}"
                            )
                        if shape_rule in {"multi-input", "multi-output"}:
                            side_shapes = incoming_shapes if shape_rule == "multi-input" else outgoing_shapes
                            side_text = left if shape_rule == "multi-input" else right
                            omitted_instances = sorted({
                                shape for shape in side_shapes
                                if 0 < side_text.count(re.sub(r"\s+", "", shape)) < side_shapes.count(shape)
                            })
                            if omitted_instances:
                                side_name = "input" if shape_rule == "multi-input" else "output"
                                errors.append(
                                    f"operator {node_id} shape_equation omits repeated {side_name} edge shapes: "
                                    f"{omitted_instances}"
                                )

            if classification == "packed-parameterized-op":
                outputs = contract.get("packed_outputs")
                path = contract.get("decomposition_path")
                if not isinstance(path, list) or len(path) < 2 or path[0] != node_id:
                    errors.append(f"packed operation {node_id} requires decomposition_path starting at itself")
                    path = []
                elif not all(isinstance(member, str) and ID.fullmatch(member) for member in path):
                    errors.append(f"packed operation {node_id} decomposition_path must contain valid node IDs")
                    path = []
                for member in path:
                    if member not in nodes or nodes.get(member, {}).get("region") != node.get("region"):
                        errors.append(f"packed operation {node_id} decomposition path has invalid member {member!r}")
                for member in path[1:-1]:
                    member_contract = nodes.get(member, {}).get("operator_contract", {})
                    if (
                        member_contract.get("classification") != "view-transform"
                        or member_contract.get("op_type") not in view_types - UNPACK_OPERATOR_TYPES
                    ):
                        errors.append(
                            f"packed operation {node_id} decomposition intermediate {member!r} "
                            "must be a non-splitting view transform"
                        )
                for source, target in zip(path, path[1:]):
                    if not any(
                        edge.get("kind") == "tensor" and edge.get("source") == source and edge.get("target") == target
                        for edge in edges.values() if isinstance(edge, dict)
                    ):
                        errors.append(f"packed operation {node_id} decomposition path lacks edge {source} -> {target}")
                unpack_node = path[-1] if path else None
                unpack_contract = nodes.get(unpack_node, {}).get("operator_contract", {})
                if unpack_contract.get("classification") != "view-transform" or unpack_contract.get("op_type") not in UNPACK_OPERATOR_TYPES:
                    errors.append(f"packed operation {node_id} decomposition must end at an explicit split/chunk/slice/unbind node")
                if not isinstance(outputs, list) or len(outputs) < 2 or not all(isinstance(item, dict) for item in outputs):
                    errors.append(f"packed operation {node_id} requires at least two mapped packed_outputs")
                    outputs = []
                seen_names: set[str] = set()
                seen_edges: set[str] = set()
                for output in outputs:
                    name, edge_id = output.get("name"), output.get("edge")
                    if not isinstance(name, str) or not name.strip() or name in seen_names:
                        errors.append(f"packed operation {node_id} has invalid or duplicate output name {name!r}")
                    else:
                        seen_names.add(name)
                    if (
                        not isinstance(edge_id, str)
                        or not ID.fullmatch(edge_id)
                        or edge_id in seen_edges
                        or edge_id not in edges
                    ):
                        errors.append(f"packed operation {node_id} has invalid or duplicate output edge {edge_id!r}")
                        continue
                    seen_edges.add(edge_id)
                    edge = edges[edge_id]
                    if edge.get("kind") != "tensor" or edge.get("source") != unpack_node:
                        errors.append(f"packed operation {node_id} output edge {edge_id} must leave unpack node {unpack_node}")
                    consumer = output.get("consumer")
                    if not isinstance(consumer, str) or consumer not in nodes:
                        errors.append(f"packed operation {node_id} output {name!r} requires a valid consumer")
                    elif edge.get("target") != consumer:
                        errors.append(f"packed operation {node_id} output {name!r} consumer does not match edge {edge_id}")
                    tensor = edge.get("tensor", {})
                    if tensor.get("name") != name:
                        errors.append(f"packed operation {node_id} output {name!r} does not match tensor name on {edge_id}")
                    output_shape = output.get("shape")
                    if not isinstance(output_shape, str) or not output_shape.strip():
                        errors.append(f"packed operation {node_id} output {name!r} requires shape")
                    elif tensor.get("shape") != output_shape:
                        errors.append(f"packed operation {node_id} output {name!r} shape does not match edge {edge_id}")

        execution_fusions = data.get("execution_fusions", [])
        if not isinstance(execution_fusions, list):
            errors.append("execution_fusions must be a list")
            execution_fusions = []
        for index, fusion in enumerate(execution_fusions):
            prefix = f"execution_fusions[{index}]"
            if not isinstance(fusion, dict):
                errors.append(f"{prefix} must be an object")
                continue
            fusion_id = fusion.get("id")
            if not isinstance(fusion_id, str) or not ID.fullmatch(fusion_id):
                errors.append(f"{prefix}.id is invalid")
            elif fusion_id in fusion_ids:
                errors.append(f"duplicate execution fusion id: {fusion_id}")
            else:
                fusion_ids.add(fusion_id)
                fusion_by_id[fusion_id] = fusion
            operator_ids = fusion.get("operators")
            if not isinstance(operator_ids, list) or len(operator_ids) < 2:
                errors.append(f"{prefix}.operators requires at least two logical operator nodes")
                operator_ids = []
            elif not all(isinstance(node_id, str) and ID.fullmatch(node_id) for node_id in operator_ids):
                errors.append(f"{prefix}.operators must contain valid node IDs")
                operator_ids = []
            elif len(set(operator_ids)) != len(operator_ids):
                errors.append(f"{prefix}.operators contains duplicate member IDs")
            fusion_regions = set()
            member_set = set(operator_ids)
            for node_id in operator_ids:
                if node_id not in nodes:
                    errors.append(f"{prefix} names unknown operator node {node_id!r}")
                else:
                    fusion_regions.add(nodes[node_id].get("region"))
                    member_contract = nodes[node_id].get("operator_contract", {})
                    if nodes[node_id].get("kind") != "operator" or member_contract.get("classification") not in {
                        "atomic-operator", "view-transform", "packed-parameterized-op"
                    }:
                        errors.append(f"{prefix} member {node_id!r} is not a logical operator")
            if any(regions.get(region_id, {}).get("granularity") != "operator-detail" for region_id in fusion_regions):
                errors.append(f"{prefix}.operators must belong to operator-detail regions")
            owner_region = fusion.get("owner_region")
            if owner_region not in regions:
                errors.append(f"{prefix}.owner_region is invalid")
            topology = fusion.get("topology")
            if topology not in {"connected", "parallel"}:
                errors.append(f"{prefix}.topology must be connected or parallel")
            elif topology == "connected" and member_set and not connected_member_subgraph(
                edges, member_set, {nid for nid, node in nodes.items() if node.get("kind") == "junction"}
            ):
                errors.append(f"{prefix}.operators do not form a connected tensor subgraph")
            elif topology == "parallel" and member_set:
                neighbor_sets = []
                for member in member_set:
                    incoming, outgoing = tensor_edges_for_node(edges, member)
                    neighbors = {
                        edges[edge_id]["source"] for edge_id in incoming
                    } | {
                        edges[edge_id]["target"] for edge_id in outgoing
                    }
                    neighbor_sets.append(neighbors - member_set)
                if not neighbor_sets or not set.intersection(*neighbor_sets):
                    errors.append(f"{prefix}.parallel operators lack a common external producer or consumer")
            refs = fusion.get("evidence")
            if not isinstance(refs, list) or not refs:
                errors.append(f"{prefix}.evidence must be a non-empty list")
            else:
                for ref in refs:
                    if ref not in evidence_ids:
                        errors.append(f"{prefix} cites unknown evidence {ref!r}")
                for node_id in operator_ids:
                    if node_id in nodes and not set(refs).intersection(nodes[node_id].get("evidence", [])):
                        errors.append(f"{prefix} member {node_id!r} does not cite fusion evidence")
            if not isinstance(fusion.get("source"), str) or not fusion["source"].strip():
                errors.append(f"{prefix}.source is required")
            if not isinstance(fusion.get("label"), str) or not fusion["label"].strip():
                errors.append(f"{prefix}.label is required")
            visualization = fusion.get("visualization")
            if visualization not in {"boundary", "implementation-node"}:
                errors.append(f"{prefix}.visualization must be boundary or implementation-node")
            elif visualization == "boundary":
                if len(fusion_regions) != 1 or owner_region not in fusion_regions:
                    errors.append(f"{prefix} boundary visualization requires one member/owner region")
            else:
                implementation_node = fusion.get("implementation_node")
                implementation = nodes.get(implementation_node, {})
                implementation_region = regions.get(implementation.get("region"), {})
                implementation_contract = implementation.get("implementation_contract", {})
                implements = implementation_contract.get("implements", [])
                if implementation_region.get("granularity") != "implementation-detail":
                    errors.append(f"{prefix}.implementation_node must belong to implementation-detail")
                if implementation.get("kind") != "operator":
                    errors.append(f"{prefix}.implementation_node must use kind operator")
                if implementation_contract.get("classification") != "fused-operation":
                    errors.append(f"{prefix}.implementation_node must declare fused-operation classification")
                if fusion_id not in implements:
                    errors.append(f"{prefix}.implementation_node must reciprocally implement {fusion_id!r}")
                if owner_region != implementation.get("region"):
                    errors.append(f"{prefix}.owner_region must own its implementation_node")

    edge_pairs = {
        (edge.get("source"), edge.get("target"))
        for edge in edges.values()
        if isinstance(edge, dict) and edge.get("kind") == "tensor"
    }
    detail_sequence_nodes: dict[str, set[str]] = {}
    for region_id, region in regions.items():
        if not isinstance(region, dict):
            continue
        required = {
            node_id for node_id, node in nodes.items()
            if isinstance(node, dict)
            and node.get("region") == region_id
            and node.get("kind") not in {"junction", "cache", "state"}
        }
        sequences = region.get("operator_sequences")
        requires_sequences = (
            region.get("granularity") in {"operator-detail", "implementation-detail"}
            or len(required) >= 2
        )
        if not isinstance(sequences, list) or not sequences:
            if requires_sequences:
                errors.append(
                    f"region {region_id} requires non-empty operator_sequences "
                    "for vertical block flow"
                )
            continue
        covered: set[str] = set()
        sequence_ids: set[str] = set()
        for index, sequence in enumerate(sequences):
            if not isinstance(sequence, dict):
                errors.append(f"region {region_id}.operator_sequences[{index}] must be an object")
                continue
            sequence_id = sequence.get("id")
            if not isinstance(sequence_id, str) or not ID.fullmatch(sequence_id):
                errors.append(f"region {region_id}.operator_sequences[{index}].id is invalid")
            elif sequence_id in sequence_ids:
                errors.append(f"region {region_id} has duplicate operator sequence id {sequence_id}")
            else:
                sequence_ids.add(sequence_id)
            path = sequence.get("nodes")
            if not isinstance(path, list) or len(path) < 2:
                errors.append(f"region {region_id} sequence {sequence_id!r} requires at least two nodes")
                continue
            for node_id in path:
                if node_id not in nodes:
                    errors.append(f"region {region_id} sequence {sequence_id!r} names unknown node {node_id!r}")
                elif nodes[node_id].get("region") != region_id:
                    errors.append(f"region {region_id} sequence {sequence_id!r} includes node {node_id!r} owned by another region")
                else:
                    covered.add(node_id)
            for source, target in zip(path, path[1:]):
                if source in nodes and target in nodes and (source, target) not in edge_pairs:
                    errors.append(
                        f"region {region_id} sequence {sequence_id!r} has no tensor edge {source} -> {target}"
                    )
        missing = sorted(required - covered)
        if missing:
            errors.append(f"region {region_id} operator sequence coverage is incomplete: {missing}")
        detail_sequence_nodes[region_id] = covered

    errors.extend(
        validate_hierarchy_summary_contracts(
            data,
            project if isinstance(project, dict) else {},
            regions,
            nodes,
            edges,
            evidence_ids,
        )
    )
    if require_logical_contracts:
        errors.extend(
            validate_detail_runtime_state_contracts(
                data, regions, nodes, edges, evidence_ids
            )
        )

    if require_logical_contracts:
        for node_id, node in nodes.items():
            contract = node.get("operator_contract", {})
            if not isinstance(contract, dict) or contract.get("classification") != "expanded-elsewhere":
                continue
            detail_region = contract.get("detail_region")
            matching_expansions = [
                edge for edge in edges.values()
                if isinstance(edge, dict)
                and edge.get("kind") == "expand"
                and edge.get("source") == node_id
                and nodes.get(edge.get("target"), {}).get("region") == detail_region
            ]
            if not matching_expansions:
                errors.append(f"expanded-elsewhere node {node_id} has no expansion into region {detail_region!r}")
            target_nodes = {
                target_id for target_id, target in nodes.items()
                if isinstance(target, dict) and target.get("region") == detail_region
            }
            if not target_nodes or not detail_sequence_nodes.get(detail_region):
                errors.append(f"expanded-elsewhere node {node_id} targets an empty or unsequenced region {detail_region!r}")

            source_region = regions.get(node.get("region"), {})
            target_region = regions.get(detail_region, {})
            if (
                source_region.get("granularity") == "operator-detail"
                and target_region.get("granularity") != "operator-detail"
            ):
                errors.append(
                    f"expanded-elsewhere node {node_id} in operator-detail cannot delegate its logical "
                    f"expansion to {target_region.get('granularity')!r} region {detail_region!r}; "
                    "keep logical tensor operators visible in an operator-detail region and map "
                    "implementation fusion separately"
                )

    require_source_coverage = isinstance(project, dict) and project.get("require_source_coverage") is True
    source_coverage = data.get("source_coverage")
    if require_logical_contracts and not require_source_coverage:
        errors.append(
            "project.require_source_coverage must be true when "
            "project.require_logical_operator_contracts is true; unmigrated IR cannot claim strict validity"
        )
    if require_source_coverage and not isinstance(source_coverage, dict):
        errors.append("project.require_source_coverage is true but source_coverage is missing")
    if source_coverage is not None and not isinstance(source_coverage, dict):
        errors.append("source_coverage must be an object")
    elif isinstance(source_coverage, dict):
        scope = source_coverage.get("scope")
        if scope not in SOURCE_COVERAGE_SCOPES:
            errors.append("source_coverage.scope must be complete-hierarchy or selected-paths")

        canonical_ids = source_coverage.get("canonical_source_ids")
        if not isinstance(canonical_ids, list):
            errors.append("source_coverage.canonical_source_ids must be a list")
            canonical_ids = []
        elif scope == "complete-hierarchy" and not canonical_ids:
            errors.append("complete-hierarchy source coverage requires at least one canonical source id")
        seen_canonical_ids: set[str] = set()
        for evidence_id in canonical_ids:
            if not isinstance(evidence_id, str):
                errors.append("source_coverage canonical source ids must be strings")
            elif evidence_id in seen_canonical_ids:
                errors.append(f"duplicate canonical source id: {evidence_id}")
            elif evidence_id not in evidence_ids:
                errors.append(f"source_coverage cites unknown canonical source {evidence_id!r}")
            elif evidence_by_id[evidence_id].get("role") != "canonical-model":
                errors.append(f"source_coverage canonical source {evidence_id!r} must have role canonical-model")
            else:
                seen_canonical_ids.add(evidence_id)

        paths = source_coverage.get("paths")
        if not isinstance(paths, list) or not paths:
            errors.append("source_coverage.paths must be a non-empty list")
            paths = []
        path_ids: set[str] = set()
        operation_ids: set[str] = set()
        for path_index, path in enumerate(paths):
            prefix = f"source_coverage.paths[{path_index}]"
            if not isinstance(path, dict):
                errors.append(f"{prefix} must be an object")
                continue
            path_id = path.get("id")
            if not isinstance(path_id, str) or not ID.fullmatch(path_id):
                errors.append(f"{prefix}.id is invalid")
                path_id = f"index-{path_index}"
            elif path_id in path_ids:
                errors.append(f"duplicate source coverage path id: {path_id}")
            else:
                path_ids.add(path_id)
            path_prefix = f"source coverage path {path_id!r}"
            path_evidence = path.get("evidence")
            if not isinstance(path_evidence, str) or path_evidence not in evidence_ids:
                errors.append(f"{path_prefix} cites unknown evidence {path_evidence!r}")
            elif evidence_by_id[path_evidence].get("role") not in {"canonical-model", "inference-implementation"}:
                errors.append(f"{path_prefix} evidence must be executable model source")
            if scope == "complete-hierarchy" and path_evidence not in canonical_ids:
                errors.append(f"{path_prefix} must use a declared canonical source")
            if not isinstance(path.get("source"), str) or not path["source"].strip():
                errors.append(f"{path_prefix}.source is required")
            path_regions = path.get("regions")
            if not isinstance(path_regions, list) or not path_regions:
                errors.append(f"{path_prefix}.regions must be a non-empty list")
                path_regions = []
            for region_id in path_regions:
                if not isinstance(region_id, str) or region_id not in regions:
                    errors.append(f"{path_prefix} names unknown region {region_id!r}")

            operations = path.get("operations")
            if not isinstance(operations, list) or not operations:
                errors.append(f"{path_prefix}.operations must be a non-empty list")
                continue
            for operation_index, operation in enumerate(operations):
                op_prefix = f"{path_prefix}.operations[{operation_index}]"
                if not isinstance(operation, dict):
                    errors.append(f"{op_prefix} must be an object")
                    continue
                operation_id = operation.get("id")
                if not isinstance(operation_id, str) or not ID.fullmatch(operation_id):
                    errors.append(f"{op_prefix}.id is invalid")
                elif operation_id in operation_ids:
                    errors.append(f"duplicate source operation id: {operation_id}")
                else:
                    operation_ids.add(operation_id)
                if not isinstance(operation.get("label"), str) or not operation["label"].strip():
                    errors.append(f"{op_prefix}.label is required")
                if not isinstance(operation.get("source"), str) or not operation["source"].strip():
                    errors.append(f"{op_prefix}.source is required")
                status = operation.get("status")
                if status not in SOURCE_OPERATION_STATUSES:
                    errors.append(f"{op_prefix}.status is invalid: {status!r}")
                    continue

                if status in {"visible-node", "source-confirmed-fusion"}:
                    node_id = operation.get("node")
                    if not isinstance(node_id, str) or node_id not in nodes:
                        errors.append(f"{op_prefix} names unknown node {node_id!r}")
                    else:
                        node = nodes[node_id]
                        if not isinstance(node, dict):
                            continue
                        if node.get("region") not in path_regions:
                            errors.append(f"{op_prefix} maps to node {node_id!r} outside the path regions")
                        if path_evidence not in node.get("evidence", []):
                            errors.append(f"{op_prefix} maps to node {node_id!r} without path evidence {path_evidence!r}")
                        node_region = node.get("region")
                        if (
                            node.get("kind") not in {"cache", "state"}
                            and node_region in detail_sequence_nodes
                            and node_id not in detail_sequence_nodes[node_region]
                        ):
                            errors.append(f"{op_prefix} maps to detail node {node_id!r} absent from operator_sequences")
                    if status == "source-confirmed-fusion" and (
                        not isinstance(operation.get("reason"), str) or not operation["reason"].strip()
                    ):
                        errors.append(f"{op_prefix}.reason is required for source-confirmed-fusion")
                    if (
                        status == "source-confirmed-fusion"
                        and require_logical_contracts
                        and isinstance(node_id, str)
                        and regions.get(nodes.get(node_id, {}).get("region"), {}).get("granularity") == "operator-detail"
                    ):
                        errors.append(
                            f"{op_prefix} cannot collapse a fused call into one operator-detail node; "
                            "map logical nodes and use fused-execution-group"
                        )
                elif status == "fused-execution-group":
                    fusion_id = operation.get("fusion")
                    if fusion_id not in fusion_ids:
                        errors.append(f"{op_prefix} names unknown execution fusion {fusion_id!r}")
                    else:
                        fusion = fusion_by_id[fusion_id]
                        if path_evidence not in fusion.get("evidence", []):
                            errors.append(f"{op_prefix} fusion {fusion_id!r} does not cite path evidence")
                        if operation.get("source") != fusion.get("source"):
                            errors.append(f"{op_prefix} source does not match fusion {fusion_id!r} source")
                elif status == "expanded-in-region":
                    region_id = operation.get("region")
                    if not isinstance(region_id, str) or region_id not in regions:
                        errors.append(f"{op_prefix} names unknown expansion region {region_id!r}")
                    else:
                        if region_id not in path_regions:
                            errors.append(f"{op_prefix} expansion region {region_id!r} is outside the path regions")
                        if regions[region_id].get("granularity") not in {"operator-detail", "implementation-detail"}:
                            errors.append(f"{op_prefix} expansion region {region_id!r} must be a detail region")
                        if not any(
                            isinstance(node, dict)
                            and node.get("region") == region_id
                            and path_evidence in node.get("evidence", [])
                            for node in nodes.values()
                        ):
                            errors.append(f"{op_prefix} expansion region {region_id!r} has no node citing path evidence {path_evidence!r}")
                elif status in {"out-of-scope", "unresolved"}:
                    if not isinstance(operation.get("reason"), str) or not operation["reason"].strip():
                        errors.append(f"{op_prefix}.reason is required for {status}")
                    if scope == "complete-hierarchy":
                        errors.append(f"{op_prefix} cannot be {status} in complete-hierarchy coverage")
        if scope == "complete-hierarchy" and unknown_material_edges:
            errors.append(
                "complete-hierarchy source coverage cannot leave material tensor shapes unknown: "
                f"{sorted(unknown_material_edges)}"
            )

        if require_logical_contracts:
            expanded_regions = {
                operation.get("region")
                for path in paths if isinstance(path, dict)
                for operation in path.get("operations", []) if isinstance(operation, dict)
                if operation.get("status") == "expanded-in-region"
                and isinstance(operation.get("region"), str)
            }
            directly_covered_nodes = {
                operation.get("node")
                for path in paths if isinstance(path, dict)
                for operation in path.get("operations", []) if isinstance(operation, dict)
                if operation.get("status") in {"visible-node", "source-confirmed-fusion"}
                and isinstance(operation.get("node"), str)
            }
            for region_id in sorted(expanded_regions):
                material_nodes = {
                    node_id for node_id, node in nodes.items()
                    if isinstance(node, dict)
                    and node.get("region") == region_id
                    and node.get("kind") in {"operator", "cache", "state"}
                }
                missing = sorted(material_nodes - directly_covered_nodes)
                if missing:
                    errors.append(
                        f"expanded source coverage for region {region_id!r} is only an umbrella mapping; "
                        f"child material nodes require direct coverage: {missing}"
                    )

        reconciliation = source_coverage.get("reconciliation")
        if require_source_coverage and not isinstance(reconciliation, dict):
            errors.append("source_coverage.reconciliation is required")
        elif isinstance(reconciliation, dict):
            if reconciliation.get("status") != "pass":
                errors.append("source_coverage.reconciliation.status must be pass")
            if reconciliation.get("method") != "independent-source-reread":
                errors.append(
                    "source_coverage.reconciliation.method must be independent-source-reread"
                )
            reviewed_path_ids = reconciliation.get("reviewed_path_ids")
            if not isinstance(reviewed_path_ids, list) or any(
                not isinstance(path_id, str) for path_id in reviewed_path_ids
            ):
                errors.append("source_coverage.reconciliation.reviewed_path_ids must be a list of strings")
            elif set(reviewed_path_ids) != path_ids or len(reviewed_path_ids) != len(path_ids):
                errors.append(
                    "source_coverage.reconciliation.reviewed_path_ids must match all source coverage paths exactly"
                )
            if not isinstance(reconciliation.get("architecture_changed"), bool):
                errors.append("source_coverage.reconciliation.architecture_changed must be a boolean")
            findings = reconciliation.get("findings")
            if not isinstance(findings, list) or not findings or any(
                not isinstance(finding, str) or not finding.strip() for finding in findings
            ):
                errors.append("source_coverage.reconciliation.findings must be a non-empty list of strings")

    repetitions = data.get("repetitions", [])
    if not isinstance(repetitions, list):
        errors.append("repetitions must be a list")
    else:
        seen_repetitions: set[tuple[str, str]] = set()
        for index, repetition in enumerate(repetitions):
            prefix = f"repetitions[{index}]"
            if not isinstance(repetition, dict):
                errors.append(f"{prefix} must be an object")
                continue
            region_id = repetition.get("region")
            target = repetition.get("target")
            key = (str(region_id), str(target))
            if key in seen_repetitions:
                errors.append(f"{prefix} duplicates repetition for region/target {key}")
            seen_repetitions.add(key)
            if region_id not in regions:
                errors.append(f"{prefix}.region names unknown region {region_id!r}")
            if target not in nodes:
                errors.append(f"{prefix}.target names unknown node {target!r}")
            elif nodes[target].get("region") != region_id:
                errors.append(f"{prefix}.target must be directly owned by its declared region")
            count = repetition.get("count")
            if not (
                isinstance(count, int) and not isinstance(count, bool) and count > 0
                or isinstance(count, str) and count.strip()
            ):
                errors.append(f"{prefix}.count must be a positive integer or non-empty source-backed expression")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("--require-source-files", action="store_true")
    args = parser.parse_args()
    try:
        data = load(args.architecture)
        errors = validate(data, args.architecture.parent, args.require_source_files)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        errors = [str(error)]
    if errors:
        print("architecture IR: FAIL")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("architecture IR: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
