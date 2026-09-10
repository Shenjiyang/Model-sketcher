#!/usr/bin/env python3
"""Validate and seal a completed independent topology review for downstream gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_topology_review import validate_review
from topology_review_common import seal_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("topology_contract", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()

    try:
        review = json.loads(args.review.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"topology review finalization: FAIL ({error})")
        return 1

    if review.get("review_receipt") is not None:
        errors = validate_review(args.architecture, args.topology_contract, args.review)
        if not errors:
            print(f"topology review finalization: REUSED ({args.review})")
            return 0
        print("topology review finalization: FAIL")
        print("ERROR: refusing to reseal a previously finalized review; request a fresh review artifact")
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    errors = validate_review(
        args.architecture,
        args.topology_contract,
        args.review,
        require_receipt=False,
    )
    if errors:
        print("topology review finalization: FAIL")
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    seal_review(review)
    args.review.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    print(f"topology review finalization: PASS ({args.review})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
