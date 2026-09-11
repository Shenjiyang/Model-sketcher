#!/usr/bin/env python3
"""Accept exactly the selected delivery files using revalidated per-view receipts."""

import argparse
import json
from pathlib import Path

from complete_delivery import artifact_entry, sha256, verify_receipt
from project_intake import check_files, delivery_plan


def read(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def resolve(base, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact path must be a nonempty string")
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def certify_project(architecture, artifacts_path, receipts_path):
    data = read(architecture)
    intake_path = architecture.with_name("project-intake.json")
    plan = delivery_plan(read(intake_path), data)
    artifacts, receipts = read(artifacts_path), read(receipts_path)
    check_files(plan, artifacts, artifacts_path.parent)
    if set(receipts) != set(artifacts):
        raise ValueError("per-view receipts must cover exactly the selected views")
    bound = {"architecture": artifact_entry(architecture), "intake": artifact_entry(intake_path),
             "artifact_map": artifact_entry(artifacts_path), "receipt_map": artifact_entry(receipts_path)}
    for view_id, formats in artifacts.items():
        receipt_path = resolve(receipts_path.parent, receipts[view_id])
        errors = verify_receipt(receipt_path)
        if errors:
            raise ValueError(f"{view_id} is DRAFT/BLOCKED: " + "; ".join(errors))
        certified = read(receipt_path)["artifacts"]
        if resolve(receipt_path.parent, certified["architecture"]["path"]) != architecture.resolve():
            raise ValueError(f"{view_id} receipt belongs to another canonical architecture")
        if resolve(receipt_path.parent, certified["project_intake"]["path"]) != intake_path.resolve():
            raise ValueError(f"{view_id} receipt belongs to another intake")
        layout = read(resolve(receipt_path.parent, certified["layout"]["path"]))
        actual_view = layout.get("semantic_view", data.get("project", {}).get("semantic_view"))
        if actual_view != view_id:
            raise ValueError(f"{view_id} receipt certifies a different view: {actual_view}")
        bound[f"receipt:{view_id}"] = artifact_entry(receipt_path)
        for fmt, name in formats.items():
            target = resolve(artifacts_path.parent, name)
            key = {"drawio": "diagram", "svg": "rendered_svg", "png": "overview"}[fmt]
            if target.suffix.lower() == ".png":
                with target.open("rb") as stream:
                    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise ValueError(f"{view_id}/png is not a PNG file")
            if sha256(target) != certified[key]["sha256"]:
                raise ValueError(f"{view_id}/{fmt} is not the certified {key}; direct exports cannot substitute")
            bound[f"output:{view_id}:{fmt}"] = artifact_entry(target)
    return {"schema_version": 1, "gate": "model-sketcher-project-completion-v1",
            "status": "deliverable", "artifacts": bound}


def verify_project(path):
    saved = read(path)
    if (saved.get("schema_version") != 1 or saved.get("status") != "deliverable"
            or saved.get("gate") != "model-sketcher-project-completion-v1"):
        raise ValueError("invalid project delivery receipt")
    artifacts = saved["artifacts"]
    current = certify_project(*(resolve(path.parent, artifacts[key]["path"])
                                for key in ("architecture", "artifact_map", "receipt_map")))
    if current != saved:
        raise ValueError("project receipt is stale; selected files or certification inputs changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--verify-receipt", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_receipt:
            verify_project(args.verify_receipt)
        else:
            if any(getattr(args, name) is None for name in ("architecture", "artifacts", "receipts", "receipt")):
                parser.error("require --architecture, --artifacts, --receipts and --receipt")
            result = certify_project(args.architecture, args.artifacts, args.receipts)
            if args.receipt.resolve() in {Path(v["path"]).resolve() for v in result["artifacts"].values()}:
                raise ValueError("receipt must not overwrite a bound input or output")
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print("PROJECT_DELIVERABLE")
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"DRAFT/BLOCKED: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
