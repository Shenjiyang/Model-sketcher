"""ELK compound layout: all ordinary edges participate in one hierarchy graph."""

import json
import math
import subprocess
import tempfile
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from clearance_contract import minimum_route_region_boundary_clearance
from plan_layout_elk import elk_graph, problem_from_region, convert_result, _port_point as port_point
from layout_progress import phase, progress
from layout_intents import (validate_hints, apply_problem_hints, apply_macro_hints,
                            apply_region_hints, verify_ports)
from typography import resolve_typography


def build_graph(data, sizes, title_font, hints=None):
    from plan_layout import region_title_layout
    hints = validate_hints(data, hints)
    padding = max(42.0, float(resolve_typography(data['project'].get('typography'))['ordinary_node_font']) * 2)
    flat = deepcopy(data)
    flat['regions'] = {'all': {'operator_sequences': [
        sequence for region in data['regions'].values()
        for sequence in region.get('operator_sequences', [])]}}
    for node in flat['nodes'].values():
        node['region'] = 'all'
    problem = problem_from_region(flat, 'all', sizes)
    problem['canvas_padding'] = 0
    apply_problem_hints(problem, hints)
    graph = elk_graph(problem)
    graph['id'] = '__elk_root__'
    graph['layoutOptions']['elk.hierarchyHandling'] = 'INCLUDE_CHILDREN'
    order = hints.get('region_order', list(data['regions']))
    if not isinstance(order, list) or any(not isinstance(rid, str) for rid in order) or (
        len(order) != len(data['regions']) or set(order) != set(data['regions'])
    ):
        raise ValueError('region_order must list every projected region exactly once')
    reserved = {graph['id'], *('region:' + rid for rid in data['regions'])}
    if reserved.intersection(data['nodes']):
        raise ValueError('compound graph container IDs collide with semantic node IDs')
    containers = {}
    for rid in order:
        region = data['regions'][rid]
        owns_nodes = any(node['region'] == rid for node in data['nodes'].values())
        minimum_width = max([sizes[nid][0] for nid, node in data['nodes'].items()
                             if node['region'] == rid] or [128.0]) + 2 * padding
        header = region_title_layout(region['label'], minimum_width, title_font)['header_height']
        macro_direction = 'RIGHT' if region.get('child_direction', 'row') == 'row' else 'UP'
        containers[rid] = {
            'id': 'region:' + rid,
            'children': [],
            'layoutOptions': {
                **graph['layoutOptions'],
                'elk.direction': 'UP' if owns_nodes else macro_direction,
                'elk.padding': f'[top={header + padding},left={padding},bottom={padding},right={padding}]',
            },
        }
    for node in graph['children']:
        containers[data['nodes'][node['id']]['region']]['children'].append(node)
    apply_region_hints(containers, hints)
    graph['children'] = []
    for rid in order:
        region = data['regions'][rid]
        parent = region.get('parent')
        target = graph if parent is None else containers[parent]
        target['children'].append(containers[rid])
    # Root macro preferences must not leak into nested operator containers.
    if 'region_order' in hints:
        graph['layoutOptions']['elk.layered.considerModelOrder.strategy'] = 'NODES_AND_EDGES'
    apply_macro_hints(graph, hints)
    if hints.get('macro', {}).get('composition') == 'separate':
        separate_region_layouts(data, graph, containers, hints)
    return problem, graph


# A region laid out on its own gets no label room from shared global layers, so its
# default 48 px layer gap cannot hold a two-line tensor label between bent segments.
SEPARATE_INTERIOR_LAYER_SPACING = 64.0
MACRO_EXPANSION_PREFIX = '__macro_expansion__:'


def separate_region_layouts(data, graph, containers, hints):
    """Lay out each region's upward flow on its own and the root as region boxes.

    In the joint graph the root direction also layers every operator, so a
    rightward macro turns operator chains into staircases. Here each container
    keeps `UP` and its own edges, and the root sees only region boxes plus one
    edge per cross-region expansion, laid out in the macro direction.
    """
    region_of = {nid: node['region'] for nid, node in data['nodes'].items()}
    root_of = {rid: rid for rid in data['regions']}
    for rid in data['regions']:
        cursor = rid
        while data['regions'][cursor].get('parent') is not None:
            cursor = data['regions'][cursor]['parent']
        root_of[rid] = cursor
    crossing = []
    for edge in graph['edges']:
        source = edge['sources'][0].split(':', 1)[0]
        target = edge['targets'][0].split(':', 1)[0]
        if region_of[source] != region_of[target]:
            crossing.append(edge['id'])
            continue
        containers[region_of[source]].setdefault('edges', []).append(edge)
    if crossing:
        raise ValueError(
            'macro.composition separate lays out each region on its own and cannot route ordinary '
            f'edges between regions: {sorted(crossing)[:5]}; use the joint composition'
        )
    graph['edges'] = []
    key = 'elk.layered.spacing.nodeNodeBetweenLayers'
    for container in containers.values():
        options = container['layoutOptions']
        options['elk.hierarchyHandling'] = 'SEPARATE_CHILDREN'
        options[key] = str(max(float(options.get(key, 0)), SEPARATE_INTERIOR_LAYER_SPACING))
    # Explicit per-region spacing still wins over the separate-layout floor.
    apply_region_hints(containers, {'regions': {
        rid: {k: v for k, v in config.items() if k != 'node_order'}
        for rid, config in hints.get('regions', {}).items()
    }})
    graph['layoutOptions']['elk.hierarchyHandling'] = 'SEPARATE_CHILDREN'
    seen = set()
    for edge_id, edge in sorted(data.get('edges', {}).items()):
        if edge.get('kind') != 'expand':
            continue
        pair = (root_of[region_of[edge['source']]], root_of[region_of[edge['target']]])
        if pair[0] == pair[1] or pair in seen:
            continue
        seen.add(pair)
        graph['edges'].append({
            'id': MACRO_EXPANSION_PREFIX + edge_id,
            'sources': ['region:' + pair[0]],
            'targets': ['region:' + pair[1]],
        })


def macro_expansion_attachments(data, layout):
    """Leave each ELK-placed child through the owner-region side that faces it."""
    from plan_layout import _resolved_attachment, _root_region
    attachments = {}
    for edge_id, edge in sorted(data.get('edges', {}).items()):
        if edge.get('kind') != 'expand' or edge.get('visual_attachment'):
            continue
        owner_id = _root_region(data['nodes'][edge['source']]['region'], data['regions'])
        child_id = data['nodes'][edge['target']]['region']
        if owner_id == child_id:
            continue
        owner, child = layout['regions'][owner_id], layout['regions'][child_id]
        gaps = {
            'east': child['x'] - (owner['x'] + owner['w']),
            'west': owner['x'] - (child['x'] + child['w']),
            'south': child['y'] - (owner['y'] + owner['h']),
            'north': owner['y'] - (child['y'] + child['h']),
        }
        side = max(gaps, key=gaps.get)
        attachments[edge_id] = _resolved_attachment(data, edge, side)
    return attachments


def flatten_result(result, node_ids):
    """ELK routes are relative to their returned edge container, not the root."""
    nodes, edges, regions = [], [], {}
    origins = {}
    pending = []

    def walk(container, ox, oy):
        origins[container['id']] = (ox, oy)
        for edge in container.get('edges', []):
            pending.append((edge, container['id']))
        for child in container.get('children', []):
            x, y = ox + child['x'], oy + child['y']
            if child['id'] in node_ids:
                nodes.append({**child, 'x': x, 'y': y})
            else:
                regions[child['id'].removeprefix('region:')] = {
                    'x': x, 'y': y, 'w': child['width'], 'h': child['height']}
            walk(child, x, y)

    walk(result, 0, 0)
    for original, owner in pending:
        edge = deepcopy(original)
        container = edge.get('container', owner)
        if container not in origins:
            raise ValueError(f'unknown ELK edge container {container}')
        ox, oy = origins[container]
        for section in edge.get('sections', []):
            for point in [section['startPoint'], *section.get('bendPoints', []), section['endPoint']]:
                point['x'] += ox
                point['y'] += oy
        for label in edge.get('labels', []):
            label['x'] += ox
            label['y'] += oy
        edges.append(edge)
    return {**result, 'children': nodes, 'edges': edges}, regions


def plan_compound(data, architecture_sha256, state=None, defer_hierarchy_arrows=False, previous_layout=None):
    from plan_layout import node_size, region_title_layout, plan_hierarchy_arrows, auto_place_expansion_regions
    from plan_layout import apply_hierarchy_arrow_overrides
    from junction_routes import normalize_junctions
    overrides = (state or {}).get('layout_overrides', {})
    hints = validate_hints(data, (state or {}).get('layout_hints'))
    from precision_layout import apply_precision
    policies = (state or {}).get('region_policies', {})
    if any(policy.get('policy') in {'preserve', 'frozen'} if isinstance(policy, dict)
           else policy in {'preserve', 'frozen'} for policy in policies.values()):
        raise ValueError('compound ELK requires adaptive regions; cannot silently ignore preserved/frozen geometry')
    if not isinstance(overrides, dict):
        raise ValueError('invalid precision override collections')
    for group in ('nodes', 'regions', 'edges'):
        if not isinstance(overrides.get(group, {}), dict) or set(overrides.get(group, {})) - set(data.get(group, {})):
            raise ValueError(f'unknown precision {group} IDs')
    if previous_layout is not None:
        if (previous_layout.get('architecture_sha256') != architecture_sha256 or
            previous_layout.get('semantic_view') != data['project'].get('semantic_view') or
            set(previous_layout.get('nodes', {})) != set(data['nodes']) or
            set(previous_layout.get('regions', {})) != set(data['regions']) or
            set(previous_layout.get('edges', {})) != {
                eid for eid, edge in data['edges'].items() if edge.get('kind') != 'expand'}):
            raise ValueError('precision base layout does not match current architecture/view; regenerate ELK base')
        recorded_hints = previous_layout.get('layout_engine', {}).get('layout_hints', {})
        if hints != recorded_hints:
            raise ValueError('layout_hints changed or were not recorded in this base; rerun without previous-layout '
                             'to compute a new ELK base, then validate existing precision overrides')
        progress('ELK: REUSED matching previous layout; no Node process started')
        with phase('precision overrides'):
            layout = apply_precision(data, previous_layout, overrides)
        if not defer_hierarchy_arrows:
            with phase('hierarchy planning'):
                layout['hierarchy_arrows'] = plan_hierarchy_arrows(data, layout)
                apply_hierarchy_arrow_overrides(layout, state)
        verify_ports(data, layout, hints)
        return layout
    typography = resolve_typography(data['project'].get('typography'))
    font = typography['ordinary_node_font']
    title_font = typography['region_title_font']
    sizes = {nid: node_size(node, font) for nid, node in data['nodes'].items()}
    problem, graph = build_graph(data, sizes, title_font, (state or {}).get('layout_hints'))
    with tempfile.TemporaryDirectory(prefix='model-sketcher-compound-') as folder:
        src, dst = Path(folder) / 'input.json', Path(folder) / 'output.json'
        src.write_text(json.dumps(graph))
        with phase('Node/ELK (timeout 45s)'):
            try:
                subprocess.run(['node', str(Path(__file__).with_name('elk_runner.cjs')), str(src), str(dst)],
                               check=True, timeout=45, capture_output=True, text=True)
            except subprocess.TimeoutExpired:
                progress('ELK_TIMEOUT: Node process exceeded 45s and was terminated')
                raise
            except subprocess.CalledProcessError as error:
                progress(f'ELK_PROCESS_FAILED: exit={error.returncode}; stderr={error.stderr}')
                raise
        raw = json.loads(dst.read_text())
    flattened, regions = flatten_result(raw, set(data['nodes']))
    with phase('route conversion and label geometry'):
        result = convert_result(problem, flattened)
    # ELK may reserve external label shelves inside a compound's side envelope.
    # Tighten visible borders to the nodes, but keep the region's own vertical route
    # segments at least the audited boundary clearance inside, plus rounding slack.
    padding = max(42.0, float(font) * 2)
    route_margin = minimum_route_region_boundary_clearance(font) + 1.0
    route_xs = defaultdict(list)
    for eid, route in result['edges'].items():
        edge = data['edges'][eid]
        rid = data['nodes'][edge['source']]['region']
        if data['nodes'][edge['target']]['region'] != rid:
            continue
        points = [port_point(result['nodes'][edge['source']], route['source_port']),
                  *map(tuple, route['waypoints']),
                  port_point(result['nodes'][edge['target']], route['target_port'])]
        route_xs[rid].extend(a[0] for a, b in zip(points, points[1:]) if abs(a[0] - b[0]) < 0.5)
    def tighten(rid):
        children = [child for child, region in data['regions'].items() if region.get('parent') == rid]
        for child in children:
            tighten(child)
        content = [box for nid, box in result['nodes'].items() if data['nodes'][nid]['region'] == rid]
        content += [regions[child] for child in children]
        if content:
            left = min(box['x'] for box in content) - padding
            right = max(box['x'] + box['w'] for box in content) + padding
            if route_xs[rid]:
                left = min(left, min(route_xs[rid]) - route_margin)
                right = max(right, max(route_xs[rid]) + route_margin)
            regions[rid]['x'], regions[rid]['w'] = left, right - left
    for rid, region in data['regions'].items():
        if region.get('parent') is None:
            tighten(rid)
    from focused_layout_quality import candidate_quality
    # A synthetic flattened envelope cannot audit per-region sequence spacing.
    quality = candidate_quality({**problem, 'operator_sequences': []}, result)
    ordinary = {eid for eid, edge in data.get('edges', {}).items() if edge.get('kind') != 'expand'}
    if set(result['edges']) != ordinary or set(result['nodes']) != set(data['nodes']):
        raise ValueError('compound ELK dropped or added semantic nodes/edges')
    elk_label_boxes = deepcopy(result.get('edge_label_boxes', {}))
    layout = {
        'schema_version': 3, 'architecture_sha256': architecture_sha256,
        'regions': regions, 'nodes': result['nodes'], 'edges': result['edges'],
        'region_titles': {rid: region_title_layout(data['regions'][rid]['label'], box['w'], title_font)
                          for rid, box in regions.items()},
        'hierarchy_arrows': {}, 'hierarchy_attachments': {},
        'canvas': {'width': math.ceil(raw['width'] + 40), 'height': math.ceil(raw['height'] + 40)},
        'layout_engine': {'name': 'compound-elk-layered', 'elkjs_version': result['engine']['elkjsVersion'],
                          **({'layout_hints': deepcopy(hints)} if hints else {}),
                          'elk_region_ids': sorted(regions), 'elk_edge_ids': sorted(ordinary),
                          'native_routed_edge_ids': [], 'macro_engine': 'elk-layered',
                          'route_preflight': quality, 'acceptance': 'pending'},
    }
    if data['project'].get('semantic_view'):
        layout['semantic_view'] = data['project']['semantic_view']
    if hints.get('macro', {}).get('composition') != 'separate':
        # The joint graph never saw expansions; re-place disconnected regions around owners.
        with phase('macro region placement'):
            auto_place_expansion_regions(data, layout)
    else:
        layout['hierarchy_attachments'] = macro_expansion_attachments(data, layout)
    layout['canvas'] = {
        'width': math.ceil(max(box['x'] + box['w'] for box in layout['regions'].values()) + 40),
        'height': math.ceil(max(box['y'] + box['h'] for box in layout['regions'].values()) + 40),
    }
    if any(overrides.get(group) for group in ('nodes', 'regions', 'edges')):
        with phase('precision overrides'):
            layout = apply_precision(data, layout, overrides)
    if not defer_hierarchy_arrows:
        with phase('hierarchy planning'):
            layout['hierarchy_arrows'] = plan_hierarchy_arrows(data, layout)
            apply_hierarchy_arrow_overrides(layout, state)
    layout = normalize_junctions(data, layout)
    with phase('isolated line jumps'):
        plan_compound_line_jumps(data, layout, elk_label_boxes)
    verify_ports(data, layout, hints)
    return layout


LINE_JUMP_SIZE = 12.0


def _route_points(data, layout, eid):
    edge, route = data['edges'][eid], layout['edges'][eid]
    return [port_point(layout['nodes'][edge['source']], route['source_port']),
            *map(tuple, route['waypoints']),
            port_point(layout['nodes'][edge['target']], route['target_port'])]


def label_box_at(points, position, w, h):
    """Place a label of size w x h where Draw.io draws label_position on this route."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    along = (float(position['x']) + 1.0) / 2.0 * sum(lengths)
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if length > 0 and along <= length + 1e-9:
            t = along / length
            dx, dy = b[0] - a[0], b[1] - a[1]
            nx, ny = dy / length, -dx / length
            cx = a[0] + t * dx + float(position['y']) * nx
            cy = a[1] + t * dy + float(position['y']) * ny
            return {'x': cx - w / 2, 'y': cy - h / 2, 'w': w, 'h': h}
        along -= length
    a = points[-1]
    return {'x': a[0] - w / 2, 'y': a[1] - h / 2, 'w': w, 'h': h}


def plan_compound_line_jumps(data, layout, elk_label_boxes):
    """Bridge sparse unavoidable perpendicular crossings on the final routes.

    A crossing that is blocked only because a label sits next to it gets that
    label moved along its own route, with every bridgeable crossing kept clear,
    before the bridges are planned.
    """
    from isolated_line_jumps import plan_isolated_line_jumps
    from plan_layout_elk import _label_position
    problem = {'edges': {eid: {'source': edge['source'], 'target': edge['target']}
                         for eid, edge in data['edges'].items() if eid in layout['edges']}}
    points = {eid: _route_points(data, layout, eid) for eid in layout['edges']}
    sizes = {eid: (box['w'], box['h']) for eid, box in elk_label_boxes.items()}

    def labels():
        return {eid: label_box_at(points[eid], layout['edges'][eid]['label_position'], *sizes[eid])
                for eid in sizes if 'label_position' in layout['edges'][eid]}

    def planned(boxes):
        view = {'nodes': layout['nodes'], 'edges': deepcopy(layout['edges']), 'edge_label_boxes': boxes}
        plan_isolated_line_jumps(problem, view, LINE_JUMP_SIZE)
        return view['engine']['isolated_line_jumps']['planned']

    current = labels()
    free = planned({})
    blocked = [item for item in free if item not in planned(current)]
    radius = 1.25 * LINE_JUMP_SIZE
    keep_out = [{'x': x - radius, 'y': y - radius, 'w': 2 * radius, 'h': 2 * radius}
                for x, y in (item['point'] for item in free)]
    edge_font = float(resolve_typography(data.get('project', {}).get('typography'))['edge_label_font'])
    for item in blocked:
        x, y = item['point']
        for eid, box in list(current.items()):
            if not (box['x'] - radius <= x <= box['x'] + box['w'] + radius
                    and box['y'] - radius <= y <= box['y'] + box['h'] + radius):
                continue
            w, h = sizes[eid]
            others = [b for other, b in current.items() if other != eid]
            try:
                position, _ = _label_position(
                    eid, points[eid], {'x': box['x'], 'y': box['y'], 'width': w, 'height': h}, 0.0,
                    [*layout['nodes'].values(), *others, *keep_out],
                    [route for other, route in points.items() if other != eid],
                    minimum_flank=max(12.0, 1.1 * edge_font),
                )
            except ValueError:
                continue
            layout['edges'][eid]['label_position'] = position
            current[eid] = label_box_at(points[eid], position, w, h)
    view = {'nodes': layout['nodes'], 'edges': layout['edges'], 'edge_label_boxes': current}
    plan_isolated_line_jumps(problem, view, LINE_JUMP_SIZE)
    summary = view.get('engine', {}).get('isolated_line_jumps')
    if summary and summary['planned']:
        layout['layout_engine']['isolated_line_jumps'] = summary
