#!/usr/bin/env python3
"""Run semantic validation, deterministic layout, and Draw.io compilation as gated stages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from compile_audit_manifest import build_manifest
from compile_drawio import compile_diagram
from plan_layout import digest, plan
from plan_change_impact import analyze, validate_state
from render_topology_contract import render as render_topology
from semantic_gate import validate_semantic_gate
from topology_review_common import semantic_json_sha256, sha256
from validate_architecture_ir import load, validate


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def update_state(path: Path | None, stage: str, gate: str) -> None:
    if path is None:
        return
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
    else:
        state = {
            "schema_version": 1, "accepted_regions": [], "blocked_regions": {},
            "unresolved_claims": [], "last_successful_audit": None,
        }
    state["current_stage"] = stage
    state["last_successful_gate"] = gate
    write_json(path, state)


def read_state(path: Path | None) -> dict:
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def main() -> int:
    # Flush gate progress even when an orchestrator captures stdout through a pipe.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--topology-contract", required=True, type=Path)
    parser.add_argument("--topology-review", type=Path)
    parser.add_argument("--review-only", action="store_true",
                        help="Generate ASCII and validate saved review, then stop before layout")
    parser.add_argument("--drawio", required=True, type=Path)
    parser.add_argument("--audit-manifest", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--previous-architecture", type=Path)
    parser.add_argument("--previous-layout", type=Path)
    parser.add_argument("--change-plan", type=Path)
    parser.add_argument("--require-source-files", action="store_true")
    parser.add_argument("--layout-engine", choices=("elk", "elk-compound"), default="elk-compound")
    parser.add_argument("--semantic-view", help="Select a declared view in memory; never rewrite canonical architecture")
    args = parser.parse_args()

    data = load(args.architecture)
    if args.semantic_view is not None and args.semantic_view not in data.get("view_projection_contract", {}).get("views", {}):
        parser.error(f"undeclared semantic view: {args.semantic_view}")
    errors = validate(data, args.architecture.parent, args.require_source_files)
    if errors:
        print("gate 1-3: FAIL")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    state = read_state(args.state)
    state_errors = validate_state(state, data)
    if state_errors:
        print("project state gate: FAIL")
        for error in state_errors:
            print(f"ERROR: {error}")
        return 2
    if args.previous_architecture:
        change_set = analyze(load(args.previous_architecture), data, state)
        if args.change_plan:
            args.change_plan.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.change_plan, change_set)
        if change_set["blockers"]:
            print("incremental gate: BLOCKED")
            for blocker in change_set["blockers"]:
                print(f"ERROR: {blocker}")
            return 2
        state["change_set"] = change_set
        if args.state:
            write_json(args.state, state)
        print(f"incremental gate: PASS ({change_set['mode']})")
    elif args.previous_layout:
        print("incremental gate: FAIL; --previous-layout requires --previous-architecture")
        return 2
    args.topology_contract.parent.mkdir(parents=True, exist_ok=True)
    args.topology_contract.write_text(render_topology(data), encoding="utf-8")
    update_state(args.state, "topology-review", "ascii-topology-contract")
    print("gate 1-3: PASS (evidence, topology, granularity)")
    print(f"gate 3b: PASS ({args.topology_contract})")

    if args.topology_review is None:
        # An explicit or recorded artifact is authoritative; never hide a stale
        # review by searching for a different PASS elsewhere.
        saved = state.get("topology_review", {}).get("path")
        if isinstance(saved, str) and saved.strip():
            args.topology_review = Path(saved)
            if not args.topology_review.is_absolute():
                args.topology_review = args.state.parent / args.topology_review
        else:
            args.topology_review = args.topology_contract.with_name("topology-review.json")
    if not args.topology_review.is_file():
        target = args.topology_review or args.topology_contract.with_name("topology-review.json")
        print(
            "gate 3c: PENDING (independent topology review required; prepare with "
            f"prepare_topology_review.py and write {target})"
        )
        return 3
    review_started = time.monotonic()
    review_errors = validate_semantic_gate(args.architecture, args.topology_contract, args.topology_review)
    if review_errors:
        print("gate 3c: FAIL (topology review)")
        for error in review_errors:
            print(f"ERROR: {error}")
        return 3
    if args.state:
        state = read_state(args.state)
        state["topology_review"] = {
            "path": str(args.topology_review.resolve()),
            "architecture_semantic_sha256": semantic_json_sha256(data),
            "topology_contract_sha256": sha256(args.topology_contract),
        }
        state["current_stage"] = "layout"
        state["last_successful_gate"] = "independent-topology-review"
        write_json(args.state, state)
    print(f"gate 3c: PASS (reused {args.topology_review}; "
          f"saved-review validation {time.monotonic() - review_started:.3f}s; no reviewer invoked)")
    if args.review_only:
        return 0

    if args.semantic_view is not None:
        data["project"]["semantic_view"] = args.semantic_view
    layout_started = time.monotonic()
    print(f"gate 4: RUNNING ({args.layout_engine} layout)")
    previous_layout = json.loads(args.previous_layout.read_text(encoding="utf-8")) if args.previous_layout else None
    state = read_state(args.state)
    try:
        layout = plan(
            data,
            digest(args.architecture),
            previous_layout,
            state,
            layout_engine=args.layout_engine,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"gate 4: FAIL ({error})")
        return 1
    args.layout.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.layout, layout)
    update_state(args.state, "compile", "deterministic-layout")
    print(f"gate 4: GENERATED (geometry only; audit pending; {time.monotonic() - layout_started:.3f}s)")

    args.drawio.parent.mkdir(parents=True, exist_ok=True)
    try:
        tree = compile_diagram(data, layout)
    except ValueError as error:
        print(f"gate 5: FAIL ({error})")
        return 1
    import xml.etree.ElementTree as ET
    ET.indent(tree, space="  ")
    tree.write(args.drawio, encoding="utf-8", xml_declaration=True)
    update_state(args.state, "delivery-audit", "drawio-compile")
    print(f"gate 5: PASS ({args.drawio})")
    if args.audit_manifest is not None:
        args.audit_manifest.parent.mkdir(parents=True, exist_ok=True)
        try:
            generated_manifest = build_manifest(data, layout)
        except ValueError as error:
            print(f"gate 5b: FAIL ({error})")
            return 1
        write_json(args.audit_manifest, generated_manifest)
        auditor = Path(__file__).with_name("audit_drawio.py")
        result = subprocess.run(
            [sys.executable, str(auditor), str(args.drawio), "--manifest", str(args.audit_manifest)],
            check=False,
        )
        if result.returncode:
            print("gate 5b: FAIL (static Draw.io audit)")
            return result.returncode
        update_state(args.state, "delivery-audit", "static-drawio-audit")
        print("gate 5b: PASS (static Draw.io audit)")
    print("gate 6: PENDING (strict delivery and official rendered review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
