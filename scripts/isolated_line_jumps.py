"""Plan only sparse, isolated perpendicular arc bridges on fixed routes."""

from collections import Counter
from itertools import combinations
import math


def _port(box, port):
    side, t = port["side"], port["position"]
    return {"north": (box["x"] + box["w"] * t, box["y"]),
            "south": (box["x"] + box["w"] * t, box["y"] + box["h"]),
            "west": (box["x"], box["y"] + box["h"] * t),
            "east": (box["x"] + box["w"], box["y"] + box["h"] * t)}[side]


def _distance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2)) if length2 else 0
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


def plan_isolated_line_jumps(problem, layout, size=12):
    """Annotate safe crossings; never reroute, disguise contacts, or relax audits."""
    if not math.isfinite(size) or not 6 <= size <= 24:
        raise ValueError("line jump size must be finite within [6,24]")
    if any("line_jump" in route for route in layout["edges"].values()):
        return layout
    paths = {}
    for eid, route in layout["edges"].items():
        edge = problem["edges"][eid]
        paths[eid] = [_port(layout["nodes"][edge["source"]], route["source_port"]),
                      *map(tuple, route.get("waypoints", [])),
                      _port(layout["nodes"][edge["target"]], route["target_port"])]
    segments = {eid: list(zip(path, path[1:])) for eid, path in paths.items()}
    crossings, unsafe_pairs = [], set()
    eps = .01
    for left, right in combinations(sorted(paths), 2):
        for li, (a, b) in enumerate(segments[left]):
            for ri, (c, d) in enumerate(segments[right]):
                ah, ch = abs(a[1] - b[1]) < eps, abs(c[1] - d[1]) < eps
                av, cv = abs(a[0] - b[0]) < eps, abs(c[0] - d[0]) < eps
                if not ((ah or av) and (ch or cv)):
                    unsafe_pairs.add((left, right))
                    continue
                if ah == ch:
                    axis = 0 if ah else 1
                    if abs(a[1-axis] - c[1-axis]) < eps and min(max(a[axis], b[axis]), max(c[axis], d[axis])) > max(min(a[axis], b[axis]), min(c[axis], d[axis])) + eps:
                        unsafe_pairs.add((left, right))
                    continue
                horizontal, vertical = ((a, b), (c, d)) if ah else ((c, d), (a, b))
                point = (vertical[0][0], horizontal[0][1])
                if not (min(horizontal[0][0], horizontal[1][0]) - eps <= point[0] <= max(horizontal[0][0], horizontal[1][0]) + eps
                        and min(vertical[0][1], vertical[1][1]) - eps <= point[1] <= max(vertical[0][1], vertical[1][1]) + eps):
                    continue
                approach = min(math.dist(point, end) for end in (a, b, c, d))
                if approach <= 1.25 * size:
                    unsafe_pairs.add((left, right))
                    continue
                crossings.append((left, right, li, ri, point))
    counts = Counter((a, b) for a, b, *_ in crossings)
    approved = []
    if len(crossings) <= max(3, len(paths) // 4):
        for left, right, li, ri, point in crossings:
            if (left, right) in unsafe_pairs or counts[(left, right)] != 1:
                continue
            radius = 1.25 * size
            boxes = [*layout["nodes"].values(), *layout.get("edge_label_boxes", {}).values()]
            if any(box["x"] - radius <= point[0] <= box["x"] + box["w"] + radius
                   and box["y"] - radius <= point[1] <= box["y"] + box["h"] + radius for box in boxes):
                continue
            if any(math.dist(point, other[4]) <= 4 * size for other in crossings
                   if other != (left, right, li, ri, point)):
                continue
            if any(_distance(point, a, b) <= radius for eid, pieces in segments.items()
                   for index, (a, b) in enumerate(pieces)
                   if (eid, index) not in {(left, li), (right, ri)}):
                continue
            approved.append((left, right, point))
    per_edge = Counter(edge for left, right, _ in approved for edge in (left, right))
    approved_pairs = {(left, right) for left, right, _ in approved}
    # Draw.io applies jumpStyle to every earlier edge crossing, not just the
    # registry subset. An upper edge cannot carry one safe and one unsafe arc.
    unsafe_uppers = {right for left, right, *_ in crossings if (left, right) not in approved_pairs}
    planned = []
    for lower, upper, point in approved:
        if per_edge[upper] > 3 or per_edge[lower] > 3 or upper in unsafe_uppers:
            continue
        # Lexical lower -> upper is acyclic regardless of pair visitation order.
        contract = layout["edges"][upper].setdefault("line_jump", {"style": "arc", "size": size, "crossings": {}})
        contract["crossings"][lower] = "Isolated perpendicular crossing after bounded unbridged layout candidates were exhausted; node, label, bend and neighboring-route clearances verified."
        planned.append({"lower": lower, "upper": upper, "point": list(point)})
    layout.setdefault("engine", {})["isolated_line_jumps"] = {
        "planned": planned, "perpendicular_crossings": len(crossings),
        "policy": "sparse isolated crossings only; unsafe contacts remain audit failures",
    }
    return layout
