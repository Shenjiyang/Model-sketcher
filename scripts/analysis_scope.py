"""Validate algorithm completeness and reviewed, on-demand runtime extensions."""

from topology_review_common import is_concrete_text


POLICY = "complete-algorithm-with-runtime-inventory"
LEGACY_POLICY = "complete-canonical-source-analysis"
CATEGORIES = {"prefill", "decode", "backend"}


def string_list(value, allowed=None, nonempty=False):
    return (isinstance(value, list) and (bool(value) or not nonempty)
            and all(isinstance(x, str) and x.strip() for x in value)
            and len(value) == len(set(value))
            and (allowed is None or set(value) <= set(allowed)))


def categories(view):
    if view.get("kind") == "backend-runtime":
        return {"backend"}
    if view.get("kind") == "inference-runtime":
        phases = view.get("runtime_phases", [])
        return set(phases) if string_list(phases, {"prefill", "decode"}) else set()
    return set()


def validate_scope(data, requested=(), required=False):
    scope = data.get("analysis_scope")
    if scope is None:
        return ["analysis_scope is required for scoped algorithm analysis"] if required else []
    if not isinstance(scope, dict) or scope.get("policy") != POLICY:
        return ["analysis_scope must declare the supported algorithm/runtime policy"]
    errors = []
    for flag in ("require_source_coverage", "require_logical_operator_contracts"):
        if data.get("project", {}).get(flag) is not True:
            errors.append(f"analysis_scope requires project.{flag}")
    if data.get("source_coverage", {}).get("scope") != "complete-hierarchy":
        errors.append("analysis_scope requires complete-hierarchy source coverage")
    project = data.get("project", {})
    if project.get("request_contract", {}).get("depth") != "logical-operators":
        errors.append("analysis_scope requires canonical logical-operators depth; summary is a delivery choice")
    module_regions = project.get("delivery_scope", {}).get("module_regions", {})
    regions = data.get("regions", {})
    for module in project.get("request_contract", {}).get("required_modules", []):
        mapped_regions = module_regions.get(module, [])
        if not isinstance(mapped_regions, list) or not any(
            isinstance(rid, str) and isinstance(regions.get(rid), dict)
            and regions[rid].get("granularity") == "operator-detail"
            and regions[rid].get("semantic_layer", "model-algorithm") == "model-algorithm"
            for rid in mapped_regions
        ):
            errors.append(f"analysis_scope module {module} requires an algorithm operator-detail expansion")
    if scope.get("algorithm_coverage") != "complete-model-logical-operators":
        errors.append("analysis_scope must retain complete model logical operators")
    if not is_concrete_text(scope.get("inventory_basis")):
        errors.append("analysis_scope.inventory_basis must explain source coverage, including an empty inventory")
    items = scope.get("runtime_inventory")
    if not isinstance(items, list):
        return errors + ["analysis_scope.runtime_inventory must be a list"]
    nodes = data.get("nodes", {})
    views = data.get("view_projection_contract", {}).get("views", {})
    evidence = {e["id"] for e in data.get("evidence", []) if isinstance(e, dict) and "id" in e}
    seen = set()
    deferred = {}
    for item in items:
        if not isinstance(item, dict):
            errors.append("runtime inventory entry must be an object")
            continue
        ident = item.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            errors.append("runtime inventory IDs must be nonempty and unique")
            continue
        seen.add(ident)
        prefix = f"runtime inventory {ident}"
        cats = item.get("categories")
        if not string_list(cats, CATEGORIES, nonempty=True):
            errors.append(f"{prefix}: categories must name prefill/decode/backend")
            cats = []
        if not string_list(item.get("evidence"), evidence, nonempty=True):
            errors.append(f"{prefix}: pinned evidence is required")
        for field in ("source", "reason", "semantic_boundary"):
            if not is_concrete_text(item.get(field), minimum=8):
                errors.append(f"{prefix}: concrete {field} is required")
        affects = item.get("affects_algorithm")
        if not isinstance(affects, bool):
            errors.append(f"{prefix}: affects_algorithm must be a boolean")
        mapped = item.get("algorithm_nodes")
        if not string_list(mapped, nodes, nonempty=affects is True):
            errors.append(f"{prefix}: algorithm_nodes must map algorithm-relevant semantics")
        elif any(nodes[n].get("semantic_layer", "model-algorithm") not in
                 {"model-algorithm", "shared-interface"} for n in mapped):
            errors.append(f"{prefix}: algorithm_nodes cannot point only to runtime nodes")
        expanded = item.get("expanded_views")
        if not string_list(expanded, views):
            errors.append(f"{prefix}: expanded_views must name existing views")
            expanded = []
        disposition = item.get("disposition")
        if not isinstance(disposition, str) or disposition not in {"algorithm", "expanded", "deferred"}:
            errors.append(f"{prefix}: disposition must be algorithm, expanded or deferred")
        if disposition == "algorithm" and affects is not True:
            errors.append(f"{prefix}: algorithm disposition requires algorithm semantics")
        if disposition == "deferred":
            deferred[ident] = item
            if affects is not False or expanded:
                errors.append(f"{prefix}: algorithm semantics or expanded views cannot be deferred")
        if disposition == "expanded":
            covered = set().union(*(categories(views[v]) for v in expanded))
            if not expanded or not set(cats) <= covered:
                errors.append(f"{prefix}: expanded views must cover every declared runtime category")
            for view in expanded:
                if not any(view in n.get("views", []) for n in nodes.values()):
                    errors.append(f"{prefix}: expanded view {view} has no nodes")
        if disposition != "expanded" and set(cats) & set(requested):
            errors.append(f"{prefix}: requested runtime categories require expansion before delivery")
    for path in data.get("source_coverage", {}).get("paths", []):
        if not isinstance(path, dict) or not isinstance(path.get("operations"), list):
            continue
        for op in path.get("operations", []):
            if not isinstance(op, dict):
                continue
            if op.get("status") == "deferred-runtime":
                extension = op.get("runtime_extension")
                item = deferred.get(extension) if isinstance(extension, str) else None
                if item is None:
                    errors.append(f"source operation {op.get('id')}: deferred-runtime requires a deferred inventory entry")
                elif path.get("evidence") not in item.get("evidence", []):
                    errors.append(f"source operation {op.get('id')}: deferred inventory must cite path evidence")
                if any(key in op for key in ("node", "region", "fusion")):
                    errors.append(f"source operation {op.get('id')}: deferred runtime cannot claim a graph mapping")
    return errors


def validate_scope_review(data, review):
    if "analysis_scope" not in data:
        return []
    result = review.get("analysis_scope_review")
    if not isinstance(result, dict):
        return ["independent analysis_scope_review is required"]
    errors = []
    if result.get("status") != "pass" or result.get("inventory_complete") is not True:
        errors.append("analysis_scope_review must independently confirm inventory completeness")
    if not is_concrete_text(result.get("finding")):
        errors.append("analysis_scope_review requires a concrete source-first scope finding")
    expected = {x["id"]: x for x in data["analysis_scope"]["runtime_inventory"]}
    records = result.get("items")
    if not isinstance(records, dict) or set(records) != set(expected):
        return errors + ["analysis_scope_review must cover every inventory ID exactly"]
    for ident, item in expected.items():
        record = records[ident]
        if not isinstance(record, dict):
            errors.append(f"scope review {ident}: result must be an object")
            continue
        if record.get("disposition") != item["disposition"] or record.get("status") != "pass":
            errors.append(f"scope review {ident}: independent disposition must match and pass")
        if not is_concrete_text(record.get("finding")):
            errors.append(f"scope review {ident}: explain computational effect and why expansion can/cannot wait")
        if not string_list(record.get("evidence"), item["evidence"], nonempty=True):
            errors.append(f"scope review {ident}: pinned evidence is required")
        if not is_concrete_text(record.get("source"), minimum=8):
            errors.append(f"scope review {ident}: independent source locator is required")
    return errors
