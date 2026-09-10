#!/usr/bin/env python3
"""Geometry helpers for Draw.io singleArrow collision checks."""

from __future__ import annotations


Point = tuple[float, float]


def single_arrow_polygon(
    x: float,
    y: float,
    width: float,
    height: float,
    direction: str,
    arrow_width: float = 0.3,
    arrow_size: float = 0.2,
) -> list[Point]:
    """Return the visible polygon used by mxGraph's singleArrow shape."""
    arrow_width = max(0.0, min(1.0, float(arrow_width)))
    arrow_size = max(0.0, min(1.0, float(arrow_size)))

    def east_polygon(local_width: float, local_height: float) -> list[Point]:
        shaft = local_height * arrow_width
        neck = local_width * (1.0 - arrow_size)
        upper = (local_height - shaft) / 2.0
        lower = upper + shaft
        return [
            (0.0, upper), (neck, upper), (neck, 0.0),
            (local_width, local_height / 2.0),
            (neck, local_height), (neck, lower), (0.0, lower),
        ]

    direction = {"right": "east", "left": "west", "down": "south", "up": "north"}.get(direction, direction)
    if direction in {"east", "west"}:
        points = east_polygon(width, height)
        if direction == "west":
            points = [(width - px, py) for px, py in points]
    elif direction in {"north", "south"}:
        # Build a horizontal arrow in transposed coordinates, then rotate it.
        points = east_polygon(height, width)
        if direction == "south":
            points = [(py, px) for px, py in points]
        else:
            points = [(py, height - px) for px, py in points]
    else:
        raise ValueError(f"invalid singleArrow direction: {direction!r}")
    return [(x + px, y + py) for px, py in points]


def _point_on_segment(point: Point, first: Point, last: Point, tolerance: float = 1e-6) -> bool:
    cross = (point[0] - first[0]) * (last[1] - first[1]) - (point[1] - first[1]) * (last[0] - first[0])
    if abs(cross) > tolerance:
        return False
    return (
        min(first[0], last[0]) - tolerance <= point[0] <= max(first[0], last[0]) + tolerance
        and min(first[1], last[1]) - tolerance <= point[1] <= max(first[1], last[1]) + tolerance
    )


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Return true only for strict interior points; boundary contact is legal."""
    inside = False
    for first, last in zip(polygon, polygon[1:] + polygon[:1]):
        if _point_on_segment(point, first, last):
            return False
        if (first[1] > point[1]) != (last[1] > point[1]):
            crossing_x = first[0] + (point[1] - first[1]) * (last[0] - first[0]) / (last[1] - first[1])
            if crossing_x > point[0]:
                inside = not inside
    return inside


def _orientation(first: Point, second: Point, third: Point) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (third[0] - first[0])


def _properly_intersects(a: Point, b: Point, c: Point, d: Point, tolerance: float = 1e-6) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    return first * second < -tolerance and third * fourth < -tolerance


def segment_intersects_polygon(first: Point, last: Point, polygon: list[Point]) -> bool:
    if point_in_polygon(first, polygon) or point_in_polygon(last, polygon):
        return True
    return any(
        _properly_intersects(first, last, edge_start, edge_end)
        for edge_start, edge_end in zip(polygon, polygon[1:] + polygon[:1])
    )


def polygons_intersect(first: list[Point], second: list[Point]) -> bool:
    """Return true for material overlap while allowing boundary-only contact."""
    if any(point_in_polygon(point, second) for point in first):
        return True
    if any(point_in_polygon(point, first) for point in second):
        return True
    if any(
        _properly_intersects(a, b, c, d)
        for a, b in zip(first, first[1:] + first[:1])
        for c, d in zip(second, second[1:] + second[:1])
    ):
        return True
    # Coincident polygons have no strict-interior vertices or proper crossings.
    first_center = (
        sum(point[0] for point in first) / len(first),
        sum(point[1] for point in first) / len(first),
    )
    second_center = (
        sum(point[0] for point in second) / len(second),
        sum(point[1] for point in second) / len(second),
    )
    return point_in_polygon(first_center, second) or point_in_polygon(second_center, first)


def box_intersects_polygon(x: float, y: float, width: float, height: float, polygon: list[Point]) -> bool:
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    if any(point_in_polygon(point, polygon) for point in corners):
        return True
    if any(x < px < x + width and y < py < y + height for px, py in polygon):
        return True
    box_edges = list(zip(corners, corners[1:] + corners[:1]))
    polygon_edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    return any(
        _properly_intersects(box_start, box_end, arrow_start, arrow_end)
        for box_start, box_end in box_edges
        for arrow_start, arrow_end in polygon_edges
    )
