"""Apply exact visual edits to ELK geometry and reconcile attached routes."""

import math
from copy import deepcopy

from junction_routes import points_for, port_point
from plan_layout_elk import _drop_collinear, _validate_endpoint_direction, _segment_hits_box


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def reconcile(points, start, end, source_side, target_side):
    # Stretch each coordinate independently: existing orthogonal runs stay orthogonal.
    transformed = []
    for p in points:
        out = []
        for axis in (0, 1):
            lo, hi = points[0][axis], points[-1][axis]
            if abs(hi - lo) < 1e-8:
                if abs(start[axis] - end[axis]) > 1e-8:
                    break
                out.append(p[axis] + start[axis] - lo)
            else:
                t = min(1, max(0, (p[axis] - lo) / (hi - lo)))
                out.append(p[axis] + (1-t)*(start[axis]-lo) + t*(end[axis]-hi))
        if len(out) != 2:
            break
        transformed.append(tuple(out))
    else:
        return _drop_collinear(transformed)
    if source_side == 'north' and target_side == 'south' and start[1] > end[1]:
        y = (start[1] + end[1]) / 2
        return _drop_collinear([start, (start[0], y), (end[0], y), end])
    raise ValueError('cannot reconcile fixed endpoints; supply explicit ports and waypoints')


def apply_precision(data, base, overrides):
    from plan_layout import region_title_layout
    out = deepcopy(base)
    if not isinstance(overrides, dict) or set(overrides) - {'nodes', 'regions', 'edges', 'hierarchy_arrows'}:
        raise ValueError('invalid precision override collections')
    for group in ('nodes', 'regions', 'edges'):
        edits = overrides.get(group, {})
        if not isinstance(edits, dict) or set(edits) - set(out[group]):
            raise ValueError(f'unknown precision {group} IDs or invalid collection')

    def depth(rid):
        parent = data['regions'][rid].get('parent')
        return 0 if parent is None else depth(parent) + 1

    def inside(rid, ancestor):
        return rid == ancestor or (data['regions'][rid].get('parent') is not None
                                  and inside(data['regions'][rid]['parent'], ancestor))

    def move(box, edit):
        if not isinstance(edit, dict) or not edit or set(edit) - {'x', 'y'}:
            raise ValueError('precision boxes accept absolute x/y only; sizes remain content-derived')
        if not all(finite(v) and v >= 0 for v in edit.values()):
            raise ValueError('precision coordinates must be finite and nonnegative')
        dx, dy = edit.get('x', box['x']) - box['x'], edit.get('y', box['y']) - box['y']
        return dx, dy

    for rid in sorted(overrides.get('regions', {}), key=depth):
        dx, dy = move(out['regions'][rid], overrides['regions'][rid])
        for child, box in out['regions'].items():
            if inside(child, rid):
                box['x'] += dx
                box['y'] += dy
        for nid, box in out['nodes'].items():
            if inside(data['nodes'][nid]['region'], rid):
                box['x'] += dx
                box['y'] += dy
    for nid, edit in overrides.get('nodes', {}).items():
        move(out['nodes'][nid], edit)
        out['nodes'][nid].update(edit)

    changed_routes = []
    for eid, route in out['edges'].items():
        edge = data['edges'][eid]
        edit = overrides.get('edges', {}).get(eid, {})
        if not isinstance(edit, dict) or set(edit) - {'source_port', 'target_port', 'waypoints', 'label_position'}:
            raise ValueError(f'invalid precision edge override: {eid}')
        old_points = points_for(edge, base['edges'][eid], base['nodes'])
        route.update(deepcopy(edit))
        for role in ('source_port', 'target_port'):
            port = route[role]
            if (not isinstance(port, dict) or set(port) != {'side', 'position'} or
                port['side'] not in {'north', 'south', 'east', 'west'} or
                not finite(port['position']) or not 0 <= port['position'] <= 1):
                raise ValueError(f'invalid precision port: {eid}/{role}')
        start = port_point(out['nodes'][edge['source']], route['source_port'])
        end = port_point(out['nodes'][edge['target']], route['target_port'])
        moved = start != old_points[0] or end != old_points[-1]
        if moved and 'waypoints' not in edit:
            try:
                points = reconcile(old_points, start, end, route['source_port']['side'], route['target_port']['side'])
            except ValueError as error:
                raise ValueError(f'precision edge {eid}: {error}') from error
            route['waypoints'] = [list(p) for p in points[1:-1]]
        if moved or any(k in edit for k in ('waypoints', 'source_port', 'target_port')):
            changed_routes.append(eid)
            route.pop('line_jump', None)
        if (not isinstance(route.get('waypoints'), list) or
            any(not isinstance(p, (list, tuple)) or len(p) != 2 or
                not all(finite(v) and v >= 0 for v in p) for p in route['waypoints'])):
            raise ValueError(f'invalid precision waypoints: {eid}')
        points = points_for(edge, route, out['nodes'])
        if any(len(p) != 2 or not all(finite(v) for v in p) for p in points):
            raise ValueError(f'invalid precision waypoints: {eid}')
        if any(a[0] != b[0] and a[1] != b[1] for a, b in zip(points, points[1:])):
            raise ValueError(f'non-orthogonal precision route: {eid}')
        _validate_endpoint_direction(points, route['source_port']['side'], route['target_port']['side'], eid)
        for nid, box in out['nodes'].items():
            if any(_segment_hits_box(a, b, box) for a, b in zip(points, points[1:])):
                raise ValueError(f'precision route {eid} penetrates {nid}; move obstacle or supply a new route')
        if 'label_position' in route:
            label = route['label_position']
            if (not isinstance(label, dict) or set(label) != {'x', 'y'} or
                not all(finite(v) for v in label.values()) or abs(label['x']) > 1 or abs(label['y']) > 160):
                raise ValueError(f'invalid precision label position: {eid}')

    font = data['project'].get('typography', {}).get('region_title_font', 20)
    for rid in sorted(out['regions'], key=depth, reverse=True):
        box = out['regions'][rid]
        contents = [b for nid, b in out['nodes'].items() if data['nodes'][nid]['region'] == rid]
        contents += [b for child, b in out['regions'].items() if data['regions'][child].get('parent') == rid]
        if contents:
            left = min(b['x'] for b in contents) - 42
            top = min(b['y'] for b in contents) - 42 - out['region_titles'][rid]['header_height']
            if rid in overrides.get('regions', {}) and (left < box['x'] or top < box['y']):
                raise ValueError(f'precision contents escape fixed region {rid}; move its anchor or contents')
            right = max(box['x'] + box['w'], *(b['x'] + b['w'] + 42 for b in contents))
            bottom = max(box['y'] + box['h'], *(b['y'] + b['h'] + 42 for b in contents))
            box['x'], box['y'] = min(box['x'], left), min(box['y'], top)
            box['w'], box['h'] = right-box['x'], bottom-box['y']
        out['region_titles'][rid] = region_title_layout(data['regions'][rid]['label'], box['w'], font)
        if box['x'] < 0 or box['y'] < 0:
            raise ValueError(f'precision region {rid} escapes canvas; increase node/region coordinates')
    boxes = list(out['regions'].values()) + list(out['nodes'].values())
    points = [p for route in out['edges'].values() for p in route['waypoints']]
    out['canvas'] = {'width': math.ceil(max([b['x']+b['w'] for b in boxes]+[p[0] for p in points])+40),
                     'height': math.ceil(max([b['y']+b['h'] for b in boxes]+[p[1] for p in points])+40)}
    out['hierarchy_arrows'], out['hierarchy_attachments'] = {}, {}
    engine = out.setdefault('layout_engine', {})
    engine.pop('route_preflight', None)
    engine.update(acceptance='pending', precision_adjusted_edge_ids=sorted(changed_routes))
    out['precision_edits'] = deepcopy(overrides)
    # Explicit ports must not be silently rewritten by junction normalization.
    from junction_routes import rail_contracts
    out['junction_rails'] = rail_contracts(data, out)
    return out
