"""Compare source-derived review expectations with IR; never infer source semantics."""

from collections import Counter
import argparse
import json
from pathlib import Path
import re

from topology_review_common import is_concrete_text, resolve_evidence_path

RULESET = "semantic-consistency-v1"


def tensor_shape(edge):
    return edge.get("tensor", {}).get("shape", edge.get("shape", "?"))


def lint(data):
    """Heuristics create review questions, not semantic verdicts."""
    findings = []
    for rid, region in data.get("regions", {}).items():
        if region.get("granularity") != "operator-detail":
            continue
        members = [nid for nid, node in data.get("nodes", {}).items()
                   if node.get("region") == rid and node.get("operator_contract")]
        contracts = [data["nodes"][nid]["operator_contract"] for nid in members]
        if len(contracts) >= 3 and all(c.get("op_type") == "activation"
                                     and c.get("shape_rule") == "preserve" for c in contracts):
            findings.append({"id": f"uniform-activation:{rid}", "region": rid,
                             "nodes": members, "severity": "review",
                             "reason": "All detail contracts are preserve activations; verify each source operation."})
        for nid in members:
            node = data["nodes"][nid]
            if node["operator_contract"].get("op_type") == "activation" and re.search(
                r"\b(linear|projection|reshape|split|concat|top.?k|cache|all.reduce)\b",
                node.get("label", ""), re.I
            ):
                findings.append({"id": f"type-label:{nid}", "region": rid,
                                 "nodes": [nid], "severity": "review",
                                 "reason": "Reader label suggests an operation other than activation; inspect source."})
    return findings


def _ids(value, known, minimum=0):
    return (isinstance(value, list) and len(value) >= minimum
            and all(isinstance(x, str) and x in known for x in value)
            and len(set(value)) == len(value))


def validate_expectations(data, review, architecture):
    """Enforce complete edge/type comparisons and source-backed anomaly resolutions."""
    errors = []
    block = review.get("semantic_expectations")
    if not isinstance(block, dict) or block.get("ruleset") != RULESET:
        return [f"semantic_expectations requires {RULESET}; obtain a fresh independent review"]
    nodes, regions = data["nodes"], data["regions"]
    edges = {eid: edge for eid, edge in data["edges"].items() if edge.get("kind") == "tensor"}
    evidence = {e["id"]: e for e in data.get("evidence", [])}
    line_counts = {}

    def source_refs(value, prefix):
        if not isinstance(value, list) or not value:
            errors.append(f"{prefix} requires source_refs into pinned evidence")
            return
        for ref in value:
            if not isinstance(ref, dict) or not isinstance(ref.get("evidence_id"), str):
                errors.append(f"{prefix} has malformed source reference")
                continue
            eid = ref["evidence_id"]
            start, end = ref.get("line_start"), ref.get("line_end")
            if eid not in evidence:
                errors.append(f"{prefix} references unpinned evidence {eid}")
                continue
            if eid not in line_counts:
                try:
                    path = resolve_evidence_path(Path(architecture), evidence[eid]["path"])
                    line_counts[eid] = len(path.read_text(encoding="utf-8").splitlines())
                except (OSError, UnicodeError):
                    line_counts[eid] = 0
            if (type(start) is not int or type(end) is not int
                    or not 1 <= start <= end <= line_counts[eid]):
                errors.append(f"{prefix} source line range is outside pinned evidence {eid}")

    records = block.get("regions")
    if not isinstance(records, dict) or set(records) != set(regions):
        return errors + ["semantic_expectations.regions must cover every canonical region exactly"]
    for rid, record in records.items():
        prefix = f"semantic_expectations region {rid}"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        source_refs(record.get("source_refs"), prefix)
        if not is_concrete_text(record.get("reason")):
            errors.append(f"{prefix} requires concrete source-to-IR reasoning")
        # Each edge is owned by its target region, including cross-region inputs.
        actual = Counter((e["source"], e["target"], tensor_shape(e)) for e in edges.values()
                         if nodes[e["target"]]["region"] == rid)
        expected = record.get("incoming_dependencies")
        valid = (isinstance(expected, list) and all(
            isinstance(row, list) and len(row) == 3
            and all(isinstance(x, str) for x in row)
            and row[0] in nodes and row[1] in nodes
            and nodes[row[1]]["region"] == rid for row in expected))
        if not valid:
            errors.append(f"{prefix} requires [producer, consumer, shape] dependency rows")
        else:
            expected = Counter(tuple(row) for row in expected)
            if expected != actual:
                unexpected = actual - expected
                implicated = [eid for eid, e in edges.items()
                              if (e["source"], e["target"], tensor_shape(e)) in unexpected]
                errors.append(f"{prefix} dependency mismatch: missing={list((expected-actual).elements())}; "
                              f"unexpected={list(unexpected.elements())}; edge_ids={implicated}")
        actual_ops = {nid: [node["operator_contract"].get("op_type"),
                            node["operator_contract"].get("shape_rule")]
                      for nid, node in nodes.items() if node.get("region") == rid
                      and isinstance(node.get("operator_contract"), dict)
                      and node["operator_contract"].get("classification") != "expanded-elsewhere"}
        if record.get("operators") != actual_ops:
            errors.append(f"{prefix} operator type/shape-rule expectations disagree with IR: {sorted(actual_ops)}")

    questions = {f["id"]: f for f in lint(data)}
    resolutions = block.get("lint_resolutions")
    if not isinstance(resolutions, dict) or set(resolutions) != set(questions):
        errors.append(f"semantic_expectations.lint_resolutions must resolve current questions exactly: {sorted(questions)}")
    else:
        for fid, resolution in resolutions.items():
            if not isinstance(resolution, dict):
                errors.append(f"lint resolution {fid} must be an object")
                continue
            if resolution.get("disposition") != "source-confirmed" or not is_concrete_text(resolution.get("reason")):
                errors.append(f"lint resolution {fid} requires source-confirmed reasoning; fix actual defects in IR")
            source_refs(resolution.get("source_refs"), fid)

    adjacency = {nid: set() for nid in nodes}
    for edge in edges.values():
        adjacency[edge["source"]].add(edge["target"])

    def reachable(starts, stops=()):
        seen, todo = set(stops), list(starts)
        reached = set()
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            reached.add(current)
            todo.extend(adjacency[current] - seen)
        return reached

    claims = block.get("branch_claims")
    if not isinstance(claims, list):
        return errors + ["semantic_expectations.branch_claims must be a list"]
    for i, claim in enumerate(claims):
        prefix = f"branch claim {i}"
        if not isinstance(claim, dict):
            errors.append(f"{prefix} must be an object")
            continue
        source_refs(claim.get("source_refs"), prefix)
        groups = claim.get("groups")
        if (not isinstance(groups, list) or len(groups) < 2
                or not all(_ids(group, nodes, 1) for group in groups)
                or len(set(n for group in groups for n in group)) != sum(map(len, groups))):
            errors.append(f"{prefix} requires disjoint nonempty node groups (shared prefix/suffix stay outside)")
            continue
        kind = claim.get("kind")
        if not isinstance(kind, str) or kind not in {"parallel", "exclusive"}:
            errors.append(f"{prefix} kind must be parallel or exclusive")
            continue
        joins = claim.get("joins", [])
        group_nodes = {n for group in groups for n in group}
        if not _ids(joins, nodes) or group_nodes.intersection(joins):
            errors.append(f"{prefix} joins are invalid")
            continue
        if kind == "exclusive" and joins:
            errors.append(f"{prefix} exclusive claims cannot hide paths behind join exclusions")
            continue
        if joins and any(not set(joins).issubset(reachable(group)) for group in groups):
            errors.append(f"{prefix} declared join is not reachable from every branch")
            continue
        for left in groups:
            reached = reachable(left, joins)
            for right in groups:
                if left is right:
                    continue
                if reached.intersection(right):
                    errors.append(f"{prefix} {kind} groups have a forbidden tensor dependency: {left} -> {right}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    args = parser.parse_args()
    print(json.dumps({"ruleset": RULESET, "review_questions": lint(json.loads(args.architecture.read_text()))}, indent=2))


if __name__ == "__main__":
    main()
