"""Shared pre-layout gate for standalone tools and the compiler pipeline."""

import json
from pathlib import Path


def validate_delivery_scope(data):
    from topology_review_common import PLACEHOLDER_TEXT
    scope = data.get("project", {}).get("delivery_scope")
    if not isinstance(scope, dict):
        return ["project.delivery_scope is required before layout; record the requested coverage"]
    errors = []
    request = data.get("project", {}).get("request_contract")
    if not isinstance(request, dict):
        return ["project.request_contract is required; migrate from the original user request, not the old overview scope"]
    for key in ("user_quote", "source_ref"):
        value = request.get(key)
        if not isinstance(value, str) or not value.strip() or PLACEHOLDER_TEXT.search(value):
            errors.append(f"request_contract.{key} must preserve concrete original request evidence")
    views = request.get("views")
    if not isinstance(views, list) or not views or any(not isinstance(v, str) for v in views):
        errors.append("request_contract.views must be a non-empty list of view IDs")
    else:
        declared = data.get("view_projection_contract", {}).get("views", {})
        if declared and any(v not in declared for v in views):
            errors.append("request_contract.views references an undeclared view")
    if request.get("coverage") not in ("whole-model", "selected-modules"):
        errors.append("request_contract.coverage must be whole-model or selected-modules")
    depth = request.get("depth")
    if depth not in ("module-summary", "logical-operators", "implementation-detail"):
        errors.append("request_contract.depth is invalid")
    targets = request.get("required_modules")
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(t, str) or not t.strip() for t in targets)):
        return errors + ["request_contract.required_modules must name every required module"]
    if len(set(targets)) != len(targets):
        errors.append("request_contract.required_modules contains duplicates")
    mappings = scope.get("module_regions")
    if not isinstance(mappings, dict) or set(mappings) != set(targets):
        return errors + ["delivery_scope.module_regions must map every requested module exactly"]
    required = scope.get("required_regions")
    if not isinstance(required, dict) or not required:
        return errors + ["delivery_scope.required_regions must map required region IDs to granularity"]
    for region_id, mode in required.items():
        if mode not in {"module-summary", "operator-detail", "implementation-detail"}:
            errors.append(f"delivery_scope invalid granularity: {region_id}")
        elif data.get("regions", {}).get(region_id, {}).get("granularity") != mode:
            errors.append(f"delivery_scope missing required region or granularity: {region_id} ({mode})")
    expected = {"logical-operators": "operator-detail", "implementation-detail": "implementation-detail"}.get(depth)
    for module, region_ids in mappings.items():
        if (not isinstance(region_ids, list) or not region_ids
                or any(not isinstance(r, str) or r not in required for r in region_ids)):
            errors.append(f"delivery_scope module lacks required region mappings: {module}")
        elif expected and not any(required[r] == expected for r in region_ids):
            errors.append(f"delivery_scope module {module} must expand to {expected}")
    if depth == "logical-operators":
        if data.get("project", {}).get("require_logical_operator_contracts") is not True:
            errors.append("logical-operators depth requires logical operator contracts")
    return errors


def validate_semantic_gate(architecture, topology=None, review=None, state=None):
    from audit_topology_review import validate_review

    architecture = Path(architecture)
    topology = Path(topology) if topology else architecture.with_name("topology.contract.txt")
    try:
        if review is None and state is not None and Path(state).is_file():
            saved = json.loads(Path(state).read_text()).get("topology_review", {}).get("path")
            if saved:
                review = Path(saved)
                if not review.is_absolute():
                    review = Path(state).parent / review
        review = Path(review) if review else topology.with_name("topology-review.json")
        return validate_review(architecture, topology, review)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return [f"cannot validate semantic gate: {error}"]


def add_gate_arguments(parser, include_state=True):
    parser.add_argument("--topology-contract", type=Path)
    parser.add_argument("--topology-review", type=Path)
    if include_state:
        parser.add_argument("--state", type=Path)


def cli_gate(args):
    errors = validate_semantic_gate(
        args.architecture, args.topology_contract, args.topology_review, args.state
    )
    if errors:
        print("semantic gate: REFUSED; repair scope/ASCII/review before geometry")
        for error in errors:
            print(f"ERROR: {error}")
    return not errors
