#!/usr/bin/env python3
"""Certify a Model Sketcher delivery only after every final gate passes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_delivery_contract import validate_manifest
from compile_drawio import compile_diagram


CHECKS = {
    "full_canvas_readable",
    "hierarchy_and_ownership_clear",
    "main_path_traceable",
    "detail_text_readable",
    "detail_granularity_consistent",
    "routes_and_labels_unambiguous",
    "density_and_whitespace_acceptable",
    "no_blocking_visual_defects",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, label: str, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"cannot read {label}: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return {}
    return value


def resolve(base: Path, value: object, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must name a file")
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        errors.append(f"{label} is missing or empty: {path}")
    return path


def expected_drawio(architecture: Path, layout: Path) -> bytes:
    data = json.loads(architecture.read_text(encoding="utf-8"))
    geometry = json.loads(layout.read_text(encoding="utf-8"))
    tree = compile_diagram(data, geometry)
    ET.indent(tree, space="  ")
    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    return buffer.getvalue()


def validate_compiler_provenance(
    diagram: Path, architecture: Path, layout: Path, errors: list[str]
) -> None:
    geometry = load_json(layout, "layout", errors)
    engine = geometry.get("layout_engine", {}) if geometry else {}
    if not isinstance(engine, dict) or engine.get("name") not in {
        "elk-layered", "compound-elk-layered"
    }:
        errors.append("layout must record the supported global ELK engine")
    if engine.get("native_routed_edge_ids") not in (None, []):
        errors.append("layout contains native-routed ordinary edges")
    preflight = engine.get("route_preflight", {})
    if preflight and (not isinstance(preflight, dict) or preflight.get("route_errors") != []):
        errors.append("layout route preflight has unresolved errors")
    if not preflight and "precision_edits" not in geometry:
        errors.append("layout lacks route preflight and validated precision-edit provenance")
    try:
        if diagram.read_bytes() != expected_drawio(architecture, layout):
            errors.append(
                "diagram bytes do not match the current canonical compiler output; "
                "manual XML or stale compiled output cannot be certified"
            )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        errors.append(f"cannot reproduce diagram from architecture and layout: {error}")


def validate_visual_review(
    review_path: Path, manifest: dict, rendered_svg: Path, errors: list[str]
) -> dict:
    review = load_json(review_path, "visual review", errors)
    if review.get("schema_version") != 1 or review.get("verdict") != "pass":
        errors.append("visual review must be schema v1 with verdict pass")
    if review.get("rendered_svg_sha256") != sha256(rendered_svg):
        errors.append("visual review is stale for the official rendered SVG")

    overview = review.get("overview")
    if not isinstance(overview, dict):
        errors.append("visual review requires an inspected full-canvas overview")
    else:
        path = resolve(review_path.parent, overview.get("path"), "visual overview", errors)
        if path is not None and path.is_file() and overview.get("sha256") != sha256(path):
            errors.append("visual overview digest is missing or stale")

    declared = manifest.get("render", {}).get("detail_regions", [])
    declared_names = {
        item.get("name") for item in declared if isinstance(item, dict) and item.get("name")
    }
    crops = review.get("detail_crops")
    reviewed_names: set[str] = set()
    if not isinstance(crops, list) or len(crops) < 2:
        errors.append("visual review requires at least two inspected detail crops")
    else:
        for index, crop in enumerate(crops):
            if not isinstance(crop, dict):
                errors.append(f"visual detail crop {index} must be an object")
                continue
            name = crop.get("name")
            if isinstance(name, str):
                reviewed_names.add(name)
            path = resolve(review_path.parent, crop.get("path"), f"visual detail crop {index}", errors)
            if path is not None and path.is_file() and crop.get("sha256") != sha256(path):
                errors.append(f"visual detail crop {index} digest is missing or stale")
    if declared_names and not declared_names.issubset(reviewed_names):
        errors.append(
            "visual review does not cover every manifest detail region: "
            f"{sorted(declared_names - reviewed_names)}"
        )

    checklist = review.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != CHECKS:
        errors.append(f"visual review checklist must contain exactly {sorted(CHECKS)}")
    elif any(checklist[name] is not True for name in CHECKS):
        errors.append("every visual review checklist item must pass")
    if review.get("blocking_findings") != []:
        errors.append("visual review has unresolved blocking findings")
    if not isinstance(review.get("findings"), list):
        errors.append("visual review findings must be a list")
    return review


def artifact_entry(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def certify(args: argparse.Namespace) -> tuple[dict, list[str]]:
    errors: list[str] = []
    manifest, contract_errors = validate_manifest(args.diagram, args.manifest)
    errors.extend(contract_errors)
    workflow = manifest.get("workflow_contract", {}) if manifest else {}
    resolved = {
        name: resolve(args.manifest.parent, workflow.get(field), name.replace("_", " "), errors)
        for name, field in {
            "architecture": "architecture_file",
            "topology_contract": "topology_contract_file",
            "topology_review": "topology_review_file",
            "evidence": "evidence_file",
            "shape_ledger": "shape_ledger_file",
        }.items()
    }
    for path, label in ((args.diagram, "diagram"), (args.manifest, "manifest"),
                        (args.layout, "layout"), (args.rendered_svg, "rendered SVG"),
                        (args.visual_review, "visual review"), (args.state, "project state")):
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"{label} is missing or empty: {path}")

    if args.state.is_file():
        state = load_json(args.state, "project state", errors)
        if state.get("last_successful_gate") not in {
            "static-drawio-audit", "completion-gate"
        }:
            errors.append("project state has not passed the compiler static Draw.io audit")
        if state.get("current_stage") not in {"delivery-audit", "delivery-complete"}:
            errors.append("project state is not at the final delivery stage")

    architecture = resolved["architecture"]
    if architecture is not None and architecture.is_file() and args.layout.is_file() and args.diagram.is_file():
        validate_compiler_provenance(args.diagram, architecture, args.layout, errors)
    if args.visual_review.is_file() and args.rendered_svg.is_file() and manifest:
        validate_visual_review(args.visual_review, manifest, args.rendered_svg, errors)

    if not errors:
        audit = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("audit_delivery_contract.py")),
             str(args.diagram), "--manifest", str(args.manifest),
             "--rendered-svg", str(args.rendered_svg)],
            capture_output=True, text=True, check=False,
        )
        if audit.returncode:
            errors.append("strict or rendered delivery audit failed")
            errors.extend(line for line in (audit.stdout + audit.stderr).splitlines() if line.strip())

    receipt = {}
    if not errors:
        artifacts = {
            "diagram": args.diagram, "manifest": args.manifest, "layout": args.layout,
            "rendered_svg": args.rendered_svg, "visual_review": args.visual_review,
            "project_state": args.state, **resolved,
        }
        receipt = {
            "schema_version": 1,
            "status": "deliverable",
            "gate": "model-sketcher-completion-v1",
            "artifacts": {
                name: artifact_entry(path) for name, path in artifacts.items() if path is not None
            },
        }
    return receipt, errors


def verify_receipt(path: Path, rerun: bool = True) -> list[str]:
    errors: list[str] = []
    receipt = load_json(path, "delivery receipt", errors)
    if receipt.get("schema_version") != 1 or receipt.get("status") != "deliverable":
        errors.append("delivery receipt is not a completed schema-v1 receipt")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        errors.append("delivery receipt has no artifacts")
        return errors
    resolved_artifacts: dict[str, Path] = {}
    for name, entry in artifacts.items():
        if not isinstance(entry, dict):
            errors.append(f"receipt artifact {name} is invalid")
            continue
        target = resolve(path.parent, entry.get("path"), f"receipt artifact {name}", errors)
        if target is not None:
            resolved_artifacts[name] = target
        if target is not None and target.is_file() and entry.get("sha256") != sha256(target):
            errors.append(f"receipt artifact {name} changed after certification")
    if receipt.get("gate") != "model-sketcher-completion-v1":
        errors.append("delivery receipt has an unknown completion gate")
    required = {"diagram", "manifest", "layout", "rendered_svg", "visual_review", "project_state"}
    if not required.issubset(resolved_artifacts):
        errors.append(f"delivery receipt is missing required artifacts: {sorted(required - set(resolved_artifacts))}")
    if rerun and not errors:
        args = argparse.Namespace(
            diagram=resolved_artifacts["diagram"], manifest=resolved_artifacts["manifest"],
            layout=resolved_artifacts["layout"], rendered_svg=resolved_artifacts["rendered_svg"],
            visual_review=resolved_artifacts["visual_review"], state=resolved_artifacts["project_state"],
        )
        _, certification_errors = certify(args)
        errors.extend(certification_errors)
    return errors


def finalize_state(path: Path, receipt_path: Path, args: argparse.Namespace) -> None:
    state = json.loads(path.read_text(encoding="utf-8"))
    state["current_stage"] = "delivery-complete"
    state["last_successful_gate"] = "completion-gate"
    state["last_successful_audit"] = {
        "status": "pass",
        "diagram_sha256": sha256(args.diagram),
        "manifest_sha256": sha256(args.manifest),
        "rendered_svg_sha256": sha256(args.rendered_svg),
        "visual_review_sha256": sha256(args.visual_review),
        "receipt_path": str(receipt_path.resolve()),
    }
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagram", nargs="?", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--rendered-svg", type=Path)
    parser.add_argument("--visual-review", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--verify-receipt", type=Path)
    args = parser.parse_args()
    if args.verify_receipt:
        errors = verify_receipt(args.verify_receipt)
        if errors:
            print("DRAFT/BLOCKED")
            for error in errors:
                print(f"ERROR: {error}")
            return 2
        print("DELIVERABLE")
        return 0
    required = ("diagram", "manifest", "layout", "rendered_svg", "visual_review", "state", "receipt")
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        parser.error(f"certification requires {', '.join('--' + name.replace('_', '-') for name in missing)}")
    receipt, errors = certify(args)
    if errors:
        print("DRAFT/BLOCKED")
        for error in errors:
            print(f"ERROR: {error}")
        return 2
    finalize_state(args.state, args.receipt, args)
    receipt["artifacts"]["project_state"] = artifact_entry(args.state)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"DELIVERABLE ({args.receipt})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
