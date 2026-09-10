"""Normalize tiny junction ports and describe only their shared terminal rails."""

from collections import defaultdict
from copy import deepcopy
import math


def port_point(box, port):
    side = port if isinstance(port, str) else port['side']
    p = .5 if isinstance(port, str) else port.get('position', .5)
    if side in ('north', 'south'):
        return (box['x'] + box['w'] * p,
                box['y'] + (box['h'] if side == 'south' else 0))
    return (box['x'] + (box['w'] if side == 'east' else 0), box['y'] + box['h'] * p)


def points_for(edge, route, boxes):
    return [port_point(boxes[edge['source']], route['source_port']),
            *[tuple(p) for p in route['waypoints']],
            port_point(boxes[edge['target']], route['target_port'])]


def groups_for(data, layout):
    groups = defaultdict(list)
    for eid, route in layout['edges'].items():
        edge = data['edges'][eid]
        for role in ('source', 'target'):
            nid = edge[role]
            if data['nodes'][nid].get('kind') != 'junction':
                continue
            port = route[role + '_port']
            side = port if isinstance(port, str) else port['side']
            groups[nid, role, side].append(eid)
    return groups


def normalize_junctions(data, layout):
    """Keep nodes fixed; coalesce adjacent terminal lanes, never arbitrary routes."""
    result = deepcopy(layout)
    for (nid, role, side), eids in groups_for(data, result).items():
        if len(eids) < 2:
            continue
        box = result['nodes'][nid]
        axis = 0 if side in ('north', 'south') else 1
        center = port_point(box, side)[axis]
        for eid in eids:
            edge, route = data['edges'][eid], result['edges'][eid]
            points = points_for(edge, route, result['nodes'])
            if role == 'target':
                points.reverse()
            old = points[0][axis]
            # Move the complete terminal straight run, not just its endpoint.
            stop = 0
            while stop < len(points) and abs(points[stop][axis] - old) < .02:
                p = list(points[stop])
                p[axis] = center
                points[stop] = tuple(p)
                stop += 1
            if stop == len(points):
                other = 'target' if role == 'source' else 'source'
                other_box = result['nodes'][edge[other]]
                other_port = route[other + '_port']
                other_side = other_port if isinstance(other_port, str) else other_port['side']
                position = (center - other_box['x' if axis == 0 else 'y']) / other_box['w' if axis == 0 else 'h']
                if not math.isfinite(position) or not 0 <= position <= 1:
                    raise ValueError(f'junction {nid}: straight route {eid} cannot retain its opposite boundary')
                route[other + '_port'] = {'side': other_side, 'position': position}
            route[role + '_port'] = {'side': side, 'position': .5}
            if role == 'target':
                points.reverse()
            route['waypoints'] = [list(p) for p in points[1:-1]]
    result['junction_rails'] = rail_contracts(data, result)
    return result


def rail_contracts(data, layout):
    """Register only center-aligned, outward terminal runs with one flow role."""
    rails = {}
    normals = {'north': (0, -1), 'south': (0, 1), 'west': (-1, 0), 'east': (1, 0)}
    for (nid, role, side), eids in sorted(groups_for(data, layout).items()):
        if len(eids) < 2:
            continue
        origin = port_point(layout['nodes'][nid], side)
        normal = normals[side]
        terminals = {}
        for eid in sorted(eids):
            route = layout['edges'][eid]
            points = points_for(data['edges'][eid], route, layout['nodes'])
            if role == 'target':
                points.reverse()
            if math.dist(origin, points[0]) > .02:
                raise ValueError(f'junction {nid}: crowded separate {side} ports; use an explicit common rail')
            end = origin
            for p in points[1:]:
                delta = (p[0] - origin[0], p[1] - origin[1])
                if abs(delta[0] * normal[1] - delta[1] * normal[0]) > .02:
                    break
                if delta[0] * normal[0] + delta[1] * normal[1] <= math.dist(origin, end):
                    raise ValueError(f'junction {nid}: reversed terminal rail on {eid}')
                end = p
            if end == origin:
                raise ValueError(f'junction {nid}: missing normal terminal on {eid}')
            terminals[eid] = list(end)
        rails[f'{nid}:{role}:{side}'] = {
            'junction': nid, 'role': role, 'side': side,
            'origin': list(origin), 'terminals': terminals,
        }
        distances = sorted(set(round(math.dist(origin, p), 2) for p in terminals.values()))
        font = float(data.get('project', {}).get('typography', {}).get('edge_label_font', 14))
        minimum = max(8, .8 * font)
        if any(b - a < minimum for a, b in zip([0, *distances], distances)):
            raise ValueError(f'junction {nid}: terminal branch points need at least {minimum:g}px clearance')
    return rails


def rail_markers(rails, diameter=6):
    markers = {}
    for rid, rail in rails.items():
        origin = rail['origin']
        ends = sorted(set(tuple(p) for p in rail['terminals'].values()),
                      key=lambda p: math.dist(origin, p))
        # The farthest endpoint is a turn, not a branching contact.
        for index, (x, y) in enumerate(ends[:-1]):
            markers[f'junction-rail:{rid}:{index}'] = {
                'x': x - diameter / 2, 'y': y - diameter / 2,
                'w': diameter, 'h': diameter,
            }
    return markers


def shared_terminal_overlap(left, right, lf, ll, rf, rl, rails):
    """Permit only the actual same-direction overlap inside a registered stem."""
    for rail in rails.values():
        ends = rail['terminals']
        if left not in ends or right not in ends:
            continue
        o = rail['origin']
        axis = 1 if rail['side'] in ('north', 'south') else 0
        fixed = 1 - axis
        if any(abs(p[fixed] - o[fixed]) > .02 for p in (lf, ll, rf, rl)):
            continue
        if (ll[axis] - lf[axis]) * (rl[axis] - rf[axis]) <= 0:
            continue
        lo = max(min(lf[axis], ll[axis]), min(rf[axis], rl[axis]))
        hi = min(max(lf[axis], ll[axis]), max(rf[axis], rl[axis]))
        allowed_lo = max(min(o[axis], ends[left][axis]), min(o[axis], ends[right][axis]))
        allowed_hi = min(max(o[axis], ends[left][axis]), max(o[axis], ends[right][axis]))
        if allowed_lo - .02 <= lo < hi <= allowed_hi + .02:
            return True
    return False


def main():
    import argparse
    import json
    from pathlib import Path
    from view_projection import project_layout_view
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('architecture', type=Path)
    parser.add_argument('layout', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    data = json.loads(args.architecture.read_text())
    layout = json.loads(args.layout.read_text())
    from compile_drawio import architecture_digest
    if layout.get('architecture_sha256') != architecture_digest(args.architecture):
        raise ValueError('stale architecture digest; regenerate the layout first')
    result = normalize_junctions(project_layout_view(data, layout), layout)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"Normalized {len(result['junction_rails'])} junction rails; node boxes unchanged")


if __name__ == '__main__':
    main()
