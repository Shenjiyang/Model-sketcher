#!/usr/bin/env python3
"""Validate hierarchy-arrow parent/child boundary attachments from JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SIDES = {"top", "bottom", "left", "right"}


def boundary_coordinate(box: dict, side: str) -> float:
    if side == "top":
        return box["y"]
    if side == "bottom":
        return box["y"] + box["h"]
    if side == "left":
        return box["x"]
    return box["x"] + box["w"]


def audit(data: dict) -> list[str]:
    objects = data.get("objects", {})
    arrows = data.get("arrows", {})
    anchors = data.get("anchors", {})
    failures: list[str] = []

    unregistered = set(arrows) - set(anchors)
    missing = set(anchors) - set(arrows)
    if unregistered:
        failures.append(f"unregistered arrows: {sorted(unregistered)}")
    if missing:
        failures.append(f"registered arrows missing geometry: {sorted(missing)}")

    for arrow_id, anchor in anchors.items():
        if arrow_id not in arrows:
            continue
        parent_id = anchor.get("parent")
        attachment_mode = anchor.get("attachment_mode", "parent-node")
        attachment_id = anchor.get("attachment", parent_id)
        child_id = anchor.get("child")
        if parent_id not in objects:
            failures.append(f"{arrow_id}: missing parent {parent_id!r}")
            continue
        if attachment_id not in objects:
            failures.append(f"{arrow_id}: missing attachment {attachment_id!r}")
            continue
        if child_id not in objects:
            failures.append(f"{arrow_id}: missing child {child_id!r}")
            continue
        if attachment_mode == "parent-node" and attachment_id != parent_id:
            failures.append(f"{arrow_id}: parent-node attachment differs from semantic parent")
        elif attachment_mode == "owner-region-boundary":
            owned = set(data.get("region_content", {}).get(attachment_id, []))
            if parent_id not in owned:
                failures.append(f"{arrow_id}: attachment region does not own semantic parent")
            anchor_label = anchor.get("anchor_label")
            if not isinstance(anchor_label, str) or not anchor_label.strip():
                failures.append(f"{arrow_id}: missing boundary anchor label")
        elif attachment_mode != "parent-node":
            failures.append(f"{arrow_id}: invalid attachment mode {attachment_mode!r}")

        parent_side = anchor.get("parent_side")
        child_side = anchor.get("child_side")
        if parent_side not in SIDES or child_side not in SIDES:
            failures.append(f"{arrow_id}: invalid parent/child side")
            continue

        arrow = arrows[arrow_id]
        tail = arrow.get("tail")
        tip = arrow.get("tip")
        if not isinstance(tail, list) or len(tail) != 2:
            failures.append(f"{arrow_id}: tail must be [x,y]")
            continue
        if not isinstance(tip, list) or len(tip) != 2:
            failures.append(f"{arrow_id}: tip must be [x,y]")
            continue

        parent_axis = 1 if parent_side in {"top", "bottom"} else 0
        child_axis = 1 if child_side in {"top", "bottom"} else 0
        tolerance = float(data.get("tolerance", 1.0))
        parent_expected = boundary_coordinate(objects[attachment_id], parent_side)
        child_expected = boundary_coordinate(objects[child_id], child_side)
        if abs(tail[parent_axis] - parent_expected) > tolerance:
            failures.append(
                f"{arrow_id}: tail detached from {attachment_id}.{parent_side} "
                f"({tail[parent_axis]} != {parent_expected})"
            )
        if abs(tip[child_axis] - child_expected) > tolerance:
            failures.append(
                f"{arrow_id}: tip detached from {child_id}.{child_side} "
                f"({tip[child_axis]} != {child_expected})"
            )

        label = arrow.get("label", "")
        if not label.strip():
            failures.append(f"{arrow_id}: missing hierarchy label")
        anchor_label = anchor.get("anchor_label")
        if isinstance(anchor_label, str) and anchor_label.strip() and anchor_label.casefold() not in label.casefold():
            failures.append(f"{arrow_id}: hierarchy label does not name semantic anchor")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    data = json.loads(args.ledger.read_text(encoding="utf-8"))
    failures = audit(data)
    if failures:
        print("hierarchy-anchor audit: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("hierarchy-anchor audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
