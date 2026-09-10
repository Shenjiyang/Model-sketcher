#!/usr/bin/env python3
"""Recompute hierarchy-arrow geometry after a project-specific layout refinement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from plan_change_impact import validate_state
from plan_layout import apply_hierarchy_arrow_overrides, plan_hierarchy_arrows
from validate_architecture_ir import load, validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", type=Path)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()

    data = load(args.architecture)
    errors = validate(data, args.architecture.parent)
    if errors:
        print("hierarchy arrows: FAIL; architecture IR is invalid")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state else None
    if state:
        state_errors = validate_state(state, data)
        if state_errors:
            print("hierarchy arrows: FAIL; project state is invalid")
            for error in state_errors:
                print(f"ERROR: {error}")
            return 1
    try:
        layout["hierarchy_arrows"] = plan_hierarchy_arrows(data, layout)
        apply_hierarchy_arrow_overrides(layout, state)
    except (KeyError, TypeError, ValueError) as error:
        print(f"hierarchy arrows: FAIL; {error}")
        return 1
    args.layout.write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    print(f"hierarchy arrows: PASS ({len(layout['hierarchy_arrows'])} arrows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
