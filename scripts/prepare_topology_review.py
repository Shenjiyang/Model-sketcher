#!/usr/bin/env python3
"""Create a digest-bound pending topology-review artifact for an independent reviewer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from topology_review_common import (
    RECONSTRUCTION_REVIEW_CHECKS,
    SEMANTIC_REVIEW_CHECKS,
    resolve_evidence_path,
    semantic_json_sha256,
    sha256,
)
from render_topology_contract import render
from validate_architecture_ir import load, validate
from audit_topology_review import validate_review


def build_pending_review(architecture: Path, topology: Path, trigger: str) -> dict:
    data = load(architecture)
    architecture_errors = validate(data, architecture.parent, require_files=True)
    if architecture_errors:
        raise ValueError("architecture IR is invalid: " + "; ".join(architecture_errors))
    if topology.read_text(encoding="utf-8") != render(data):
        raise ValueError("ASCII topology contract is not the canonical generated output for this architecture")
    source_artifacts = []
    missing = []
    for evidence in data.get("evidence", []):
        source = resolve_evidence_path(architecture, evidence["path"])
        if not source.is_file():
            missing.append(f"{evidence['id']}: {source}")
            continue
        source_artifacts.append({
            "evidence_id": evidence["id"],
            "role": evidence["role"],
            "path": evidence["path"],
            "revision": evidence["revision"],
            "sha256": sha256(source),
        })
    if missing:
        raise ValueError("review evidence files are missing: " + "; ".join(missing))
    path_ids = sorted(
        path["id"] for path in data.get("source_coverage", {}).get("paths", [])
        if isinstance(path, dict) and isinstance(path.get("id"), str)
    )
    region_ids = sorted(data.get("regions", {}))
    return {
        "schema_version": 2,
        "review_scope": "semantic-topology",
        "trigger": trigger,
        "architecture_semantic_sha256": semantic_json_sha256(data),
        "topology_contract_sha256": sha256(topology),
        "builder_id": "replace-with-builder-session-id",
        "reviewer_id": "replace-with-independent-reviewer-agent-id",
        "reviewer_attestation": {
            "independent_from_builder": False,
            "source_inventory_created_before_ir_comparison": False,
            "did_not_edit_semantic_inputs": False,
        },
        "source_artifacts": source_artifacts,
        "independent_source_inventory": {
            "status": "pending",
            "paths": [],
            "findings": ["Replace with concrete source-first inventory observations."],
            "blocking_findings": ["Independent source inventory has not run."],
        },
        "semantic_review": {
            "status": "pending",
            "method": "independent-source-first",
            "reviewed_path_ids": path_ids,
            "reviewed_region_ids": region_ids,
            "results": [
                {
                    "check": check,
                    "status": "pending",
                    "scope_refs": [],
                    "evidence_refs": [],
                    "finding": "Replace with a concrete source-to-IR comparison result.",
                }
                for check in sorted(SEMANTIC_REVIEW_CHECKS)
            ],
            "region_results": [
                {
                    "region_id": region_id,
                    "status": "pending",
                    "source_path_ids": [],
                    "finding": "Replace with the source-grounded result for this region.",
                }
                for region_id in region_ids
            ],
            "findings": ["Replace with concrete source-to-IR review findings."],
            "blocking_findings": ["Independent semantic review has not run."],
        },
        "reconstruction_review": {
            "status": "pending",
            "method": "ascii-reconstruction-review",
            "reviewed_region_ids": region_ids,
            "results": [
                {
                    "check": check,
                    "status": "pending",
                    "region_ids": [],
                    "contract_refs": [],
                    "finding": "Replace with a concrete ASCII reconstruction result.",
                }
                for check in sorted(RECONSTRUCTION_REVIEW_CHECKS)
            ],
            "region_results": [
                {
                    "region_id": region_id,
                    "status": "pending",
                    "reconstructable": False,
                    "contract_refs": [],
                    "finding": "Replace with what the ASCII exposes for this region.",
                }
                for region_id in region_ids
            ],
            "findings": ["Replace with what a reader can and cannot reconstruct from the ASCII contract."],
            "blocking_findings": ["ASCII reconstruction review has not run."],
        },
        "verdict": "pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("topology_contract", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--trigger",
        choices=("cold-start", "semantic-revision", "source-revision", "requested-recheck"),
        required=True,
    )
    args = parser.parse_args()
    if args.output.is_file():
        existing_errors = validate_review(args.architecture, args.topology_contract, args.output)
        if not existing_errors and args.trigger != "requested-recheck":
            print(f"topology review preparation: REUSED ({args.output}; no reviewer required)")
            return 0
        # Keep previous findings for recovery even when the replacement is pending.
        archive = args.output.with_name(args.output.name + "." + sha256(args.output) + ".bak")
        if not archive.exists():
            archive.write_bytes(args.output.read_bytes())
    try:
        review = build_pending_review(args.architecture, args.topology_contract, args.trigger)
    except (OSError, ValueError, KeyError) as error:
        print(f"topology review preparation: FAIL ({error})")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    print(f"topology review preparation: PENDING ({args.output})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
