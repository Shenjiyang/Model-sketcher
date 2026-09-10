"""Conservative port refinement before labels, with fixed ELK node boxes."""

from copy import deepcopy
from audit_drawio import avoidable_orthogonal_shortcut


def _proper_crossing(a, b, c, d):
    horizontal = abs(a[1] - b[1]) < .01
    vertical = abs(a[0] - b[0]) < .01
    other_horizontal = abs(c[1] - d[1]) < .01
    other_vertical = abs(c[0] - d[0]) < .01
    if not ((horizontal and other_vertical) or (vertical and other_horizontal)):
        return None
    h, v = ((a, b), (c, d)) if horizontal else ((c, d), (a, b))
    x, y = v[0][0], h[0][1]
    if (min(h[0][0], h[1][0]) + .01 < x < max(h[0][0], h[1][0]) - .01
            and min(v[0][1], v[1][1]) + .01 < y < max(v[0][1], v[1][1]) - .01):
        return x, y
    return None


def _near_segment(a, b, c, d, clearance):
    # All inputs are orthogonal; the bounding rectangles give exact L-infinity
    # clearance between parallel or perpendicular closed segments.
    return (max(min(a[0], b[0]), min(c[0], d[0]))
            <= min(max(a[0], b[0]), max(c[0], d[0])) + clearance
            and max(min(a[1], b[1]), min(c[1], d[1]))
            <= min(max(a[1], b[1]), max(c[1], d[1])) + clearance)


def refine_straight_routes(boxes, declarations, paths, *, node_clearance=16.0,
                           edge_clearance=8.0, port_clearance=16.0,
                           preserve_existing_crossings=False):
    """Remove doglegs only if port order and all new clearances remain legal.

    Declarations require source/target and explicit source_side/target_side.
    Paths include boundary endpoints. Labels must be placed after this pass.
    Existing obstacle-driven bends are left unchanged, never waived.
    """
    output = deepcopy(paths)
    opposite = {"north": "south", "south": "north", "east": "west", "west": "east"}
    for edge_id in sorted(output):
        points = output[edge_id]
        item = declarations[edge_id]
        if sum(other["source"] == item["source"] and other["target"] == item["target"]
               for other in declarations.values()) > 1:
            # Parallel operands need ELK's separate label shelves. Straightening
            # them creates a wire fence that leaves no legal label rectangle.
            continue
        side = item["source_side"]
        if len(points) <= 2 or item["target_side"] != opposite[side]:
            continue
        vertical = side in {"north", "south"}
        axis, along = (0, 1) if vertical else (1, 0)
        direction = -1 if side in {"north", "west"} else 1
        if (points[-1][along] - points[0][along]) * direction <= 0:
            continue
        position, size = ("x", "w") if vertical else ("y", "h")
        source, target = boxes[item["source"]], boxes[item["target"]]
        low = max(source[position], target[position]) + port_clearance
        high = min(source[position] + source[size], target[position] + target[size]) - port_clearance
        # Preserve ordering on both boundaries, including ports on other edges.
        for endpoint, index in (("source", 0), ("target", -1)):
            for other_id, other in declarations.items():
                if other_id == edge_id:
                    continue
                for other_endpoint, other_index in (("source", 0), ("target", -1)):
                    if (other[other_endpoint] == item[endpoint]
                            and other[other_endpoint + "_side"] == item[endpoint + "_side"]):
                        neighbor = output[other_id][other_index][axis]
                        if neighbor < points[index][axis]:
                            low = max(low, neighbor + port_clearance)
                        else:
                            high = min(high, neighbor - port_clearance)
        if low > high:
            continue
        candidates = [(low + high) / 2,
                      max(low, min(high, points[0][axis])),
                      max(low, min(high, points[-1][axis]))]
        for value in dict.fromkeys(candidates):
            first, last = list(points[0]), list(points[-1])
            first[axis] = last[axis] = value
            blocked = False
            for node_id, box in boxes.items():
                if node_id in {item["source"], item["target"]}:
                    continue
                if (max(min(first[0], last[0]), box["x"] - node_clearance)
                        <= min(max(first[0], last[0]), box["x"] + box["w"] + node_clearance)
                        and max(min(first[1], last[1]), box["y"] - node_clearance)
                        <= min(max(first[1], last[1]), box["y"] + box["h"] + node_clearance)):
                    blocked = True
                    break
            if blocked:
                continue
            if any(_near_segment(first, last, a, b, edge_clearance)
                   for other_id, path in output.items() if other_id != edge_id
                   for a, b in zip(path, path[1:])):
                continue
            output[edge_id] = [tuple(first), tuple(last)]
            break
    # Preserve ELK endpoints while removing longer monotonic staircases when
    # the same generic shortcut used by the audit has a genuinely clear lane.
    for edge_id in sorted(output):
        for _ in range(len(output[edge_id])):
            item = declarations[edge_id]
            if sum(other["source"] == item["source"] and other["target"] == item["target"]
                   for other in declarations.values()) > 1:
                break

            def blocked(first, last):
                for node_id, box in boxes.items():
                    if node_id in {item["source"], item["target"]}:
                        continue
                    if (max(min(first[0], last[0]), box["x"] - node_clearance)
                            <= min(max(first[0], last[0]), box["x"] + box["w"] + node_clearance)
                            and max(min(first[1], last[1]), box["y"] - node_clearance)
                            <= min(max(first[1], last[1]), box["y"] + box["h"] + node_clearance)):
                        return True
                for other_id, path in output.items():
                    if other_id == edge_id:
                        continue
                    for a, b in zip(path, path[1:]):
                        if not _near_segment(first, last, a, b, edge_clearance):
                            continue
                        crossing = _proper_crossing(first, last, a, b)
                        old_crossings = [_proper_crossing(c, d, a, b)
                                         for c, d in zip(output[edge_id], output[edge_id][1:])]
                        if (preserve_existing_crossings and crossing is not None
                                and any(p is not None and abs(p[0] - crossing[0]) < .01
                                        and abs(p[1] - crossing[1]) < .01 for p in old_crossings)):
                            continue
                        return True
                return False

            shortcut = avoidable_orthogonal_shortcut(output[edge_id], blocked)
            if shortcut is None:
                break
            start, end, replacement = shortcut
            output[edge_id] = output[edge_id][:start] + replacement + output[edge_id][end + 1:]
    return output
