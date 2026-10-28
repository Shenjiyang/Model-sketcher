#!/usr/bin/env python3
"""Scale-free aim predicate for hierarchy expansion arrows.

A signpost is a short block arrow whose tip deliberately stops short of the
child region. Its only claim is "this module expands into that region", and
that claim is carried by the shaft: the arrow's own cross-section, extended in
its pointing direction, has to meet the child before any unrelated region.

This module owns that predicate so the planner, the compiler gate, and the
static auditor cannot drift into three slightly different notions of "points
at". The predicate deliberately contains no distance constant. Whether a
signpost is close enough to read comfortably is a project-level policy
(``signpost_aim_limits`` in the audit manifest); whether it points at the child
at all is geometry and must hold at every canvas scale.

Regions are nested, so a forward band necessarily crosses the child's ancestor
frames and whatever frame encloses the arrow itself. Those frames are
structure, not obstructions, and are transparent. The first region the band
meets after leaving its own frame must be the child or one of its descendants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

Box = Mapping[str, float]
Parents = Mapping[str, str | None]


@dataclass(frozen=True)
class AimResult:
    """Outcome of extending one arrow's cross-section toward its child."""

    hit: bool
    target: str | None = None
    blocked_by: str | None = None
    blocked_at: float | None = None
    child_distance: float | None = None
    overlap: float = 0.0
    overlap_ratio: float | None = None
    offset_ratio: float | None = None
    ambiguous: bool = False

    def describe(self) -> str:
        """One-line diagnosis for compiler and auditor messages."""
        if self.hit:
            return "the band meets its child first"
        if self.child_distance is None:
            text = "the arrow's cross-section does not overlap the child region"
        elif self.child_distance < 0:
            text = f"the child lies {-self.child_distance:.1f}px behind the arrow tip"
        else:
            text = f"the child boundary lies {self.child_distance:.1f}px ahead"
        if self.blocked_by is not None:
            at = f" at {self.blocked_at:.1f}px" if self.blocked_at is not None else ""
            text += f"; the first region on that line is {self.blocked_by}{at}"
        elif self.ambiguous:
            text += "; another region meets the band at the same distance"
        return text


def aim_band(
    box: Mapping[str, float],
    direction: str,
    child_id: str,
    boxes: Mapping[str, Box],
    parents: Parents,
    tolerance: float = 1.0,
) -> AimResult:
    """Extend ``box`` in ``direction`` and report whether it meets ``child_id`` first.

    ``boxes`` and ``parents`` use the same key space. ``parents`` maps a region
    to its enclosing region (``None`` for a top-level frame); it is the only
    nesting input, so callers never have to pre-expand ancestry or descendant
    lists. A region that intersects the arrow box is treated as its host frame:
    illegal overlaps are reported by the region/arrow gates, and letting them
    also decide aim would replace a precise failure with a confusing one.
    """
    if direction not in {"north", "south", "east", "west"}:
        raise ValueError(f"invalid hierarchy direction {direction!r}")
    if child_id not in boxes:
        raise KeyError(f"unknown child region {child_id!r}")

    vertical = direction in {"north", "south"}
    if vertical:
        low, high = float(box["x"]), float(box["x"]) + float(box["w"])
        tip = float(box["y"]) if direction == "north" else float(box["y"]) + float(box["h"])
    else:
        low, high = float(box["y"]), float(box["y"]) + float(box["h"])
        tip = float(box["x"]) + float(box["w"]) if direction == "east" else float(box["x"])
    sign = -1.0 if direction in {"north", "west"} else 1.0

    def cross(region: Box) -> tuple[float, float]:
        return (
            (float(region["x"]), float(region["x"]) + float(region["w"]))
            if vertical
            else (float(region["y"]), float(region["y"]) + float(region["h"]))
        )

    def near(region: Box) -> float:
        if direction == "north":
            return float(region["y"]) + float(region["h"])
        if direction == "south":
            return float(region["y"])
        if direction == "east":
            return float(region["x"])
        return float(region["x"]) + float(region["w"])

    child = boxes[child_id]
    child_low, child_high = cross(child)
    overlap = min(high, child_high) - max(low, child_low)
    band_span = high - low
    child_span = child_high - child_low
    overlap_ratio = (
        overlap / min(band_span, child_span)
        if overlap > tolerance and min(band_span, child_span) > 0
        else None
    )
    offset_ratio = (
        ((child_low + child_high) / 2 - (low + high) / 2) / ((band_span + child_span) / 2)
        if band_span + child_span > 0
        else None
    )
    child_distance = sign * (near(child) - tip) if overlap > tolerance else None

    ancestors: set[str] = set()
    cursor = parents.get(child_id)
    while cursor is not None and cursor not in ancestors:
        ancestors.add(cursor)
        cursor = parents.get(cursor)

    family = {child_id}
    for region_id in boxes:
        cursor = parents.get(region_id)
        seen: set[str] = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            if cursor == child_id:
                family.add(region_id)
                break
            cursor = parents.get(cursor)

    def intersects(a: Mapping[str, float], b: Box) -> bool:
        return (
            min(float(a["x"]) + float(a["w"]), float(b["x"]) + float(b["w"]))
            - max(float(a["x"]), float(b["x"])) > tolerance
            and min(float(a["y"]) + float(a["h"]), float(b["y"]) + float(b["h"]))
            - max(float(a["y"]), float(b["y"])) > tolerance
        )

    transparent = set(ancestors)
    transparent.update(
        region_id for region_id, region in boxes.items()
        if region_id not in family and intersects(box, region)
    )

    distances: dict[str, float] = {}
    for region_id, region in boxes.items():
        if region_id in transparent:
            continue
        region_low, region_high = cross(region)
        if min(high, region_high) - max(low, region_low) <= tolerance:
            continue
        distance = sign * (near(region) - tip)
        if distance < -tolerance:
            continue
        distances[region_id] = distance

    if not distances:
        return AimResult(
            hit=False,
            child_distance=child_distance,
            overlap=overlap,
            overlap_ratio=overlap_ratio,
            offset_ratio=offset_ratio,
        )

    nearest = min(distances.values())
    tied = {region_id for region_id, distance in distances.items()
            if distance <= nearest + tolerance}
    legal = tied & family
    illegal = tied - family
    if legal and not illegal:
        target = min(legal, key=lambda region_id: distances[region_id])
        return AimResult(
            hit=True,
            target=target,
            child_distance=child_distance,
            overlap=overlap,
            overlap_ratio=overlap_ratio,
            offset_ratio=offset_ratio,
        )
    blocked = min(illegal, key=lambda region_id: distances[region_id]) if illegal else None
    return AimResult(
        hit=False,
        blocked_by=blocked,
        blocked_at=distances[blocked] if blocked is not None else None,
        child_distance=child_distance,
        overlap=overlap,
        overlap_ratio=overlap_ratio,
        offset_ratio=offset_ratio,
        ambiguous=bool(legal and illegal),
    )
