"""ELK compound layout: all ordinary edges participate in one hierarchy graph."""

import json
import math
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

from plan_layout_elk import elk_graph, problem_from_region, convert_result


def build_graph(data, sizes, title_font, hints=None):
    flat = deepcopy(data)
    flat['regions'] = {'all': {'operator_sequences': [
        sequence for region in data['regions'].values()
        for sequence in region.get('operator_sequences', [])]}}
    for node in flat['nodes'].values():
        node['region'] = 'all'
    problem = problem_from_region(flat, 'all', sizes)
    problem['canvas_padding'] = 0
    graph = elk_graph(problem)
    graph['id'] = '__elk_root__'
    graph['layoutOptions']['elk.hierarchyHandling'] = 'INCLUDE_CHILDREN'
    hints = hints or {}
    if not isinstance(hints, dict):
        raise ValueError('layout_hints must be an object')
    if set(hints) - {'region_order'}:
        raise ValueError('unsupported compound layout hint; supported: region_order')
    order = hints.get('region_order', list(data['regions']))
    if not isinstance(order, list) or any(not isinstance(rid, str) for rid in order) or (
        len(order) != len(data['regions']) or set(order) != set(data['regions'])
    ):
        raise ValueError('region_order must list every projected region exactly once')
    if 'region_order' in hints:
        graph['layoutOptions']['elk.layered.considerModelOrder.strategy'] = 'NODES_AND_EDGES'
    reserved = {graph['id'], *('region:' + rid for rid in data['regions'])}
    if reserved.intersection(data['nodes']):
        raise ValueError('compound graph container IDs collide with semantic node IDs')
    containers = {}
    for rid in order:
        region = data['regions'][rid]
        owns_nodes = any(node['region'] == rid for node in data['nodes'].values())
        macro_direction = 'RIGHT' if region.get('child_direction', 'row') == 'row' else 'UP'
        containers[rid] = {
            'id': 'region:' + rid,
            'children': [],
            'layoutOptions': {
                **graph['layoutOptions'],
                'elk.direction': 'UP' if owns_nodes else macro_direction,
                'elk.padding': f'[top={title_font * 5 + 42},left=42,bottom=42,right=42]',
            },
        }
    for node in graph['children']:
        containers[data['nodes'][node['id']]['region']]['children'].append(node)
    graph['children'] = []
    for rid in order:
        region = data['regions'][rid]
        parent = region.get('parent')
        target = graph if parent is None else containers[parent]
        target['children'].append(containers[rid])
    return problem, graph


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
    from plan_layout import node_size, region_title_layout, plan_hierarchy_arrows
    from plan_layout import apply_hierarchy_arrow_overrides
    from junction_routes import normalize_junctions
    overrides = (state or {}).get('layout_overrides', {})
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
        layout = apply_precision(data, previous_layout, overrides)
        if not defer_hierarchy_arrows:
            layout['hierarchy_arrows'] = plan_hierarchy_arrows(data, layout)
            apply_hierarchy_arrow_overrides(layout, state)
        return layout
    font = data['project'].get('typography', {}).get('ordinary_node_font', 18)
    title_font = data['project'].get('typography', {}).get('region_title_font', 20)
    sizes = {nid: node_size(node, font) for nid, node in data['nodes'].items()}
    problem, graph = build_graph(data, sizes, title_font, (state or {}).get('layout_hints'))
    with tempfile.TemporaryDirectory(prefix='model-sketcher-compound-') as folder:
        src, dst = Path(folder) / 'input.json', Path(folder) / 'output.json'
        src.write_text(json.dumps(graph))
        subprocess.run(['node', str(Path(__file__).with_name('elk_runner.cjs')), str(src), str(dst)],
                       check=True, timeout=45, capture_output=True, text=True)
        raw = json.loads(dst.read_text())
    flattened, regions = flatten_result(raw, set(data['nodes']))
    result = convert_result(problem, flattened)
    from focused_layout_quality import candidate_quality
    # A synthetic flattened envelope cannot audit per-region sequence spacing.
    quality = candidate_quality({**problem, 'operator_sequences': []}, result)
    ordinary = {eid for eid, edge in data.get('edges', {}).items() if edge.get('kind') != 'expand'}
    if set(result['edges']) != ordinary or set(result['nodes']) != set(data['nodes']):
        raise ValueError('compound ELK dropped or added semantic nodes/edges')
    layout = {
        'schema_version': 3, 'architecture_sha256': architecture_sha256,
        'regions': regions, 'nodes': result['nodes'], 'edges': result['edges'],
        'region_titles': {rid: region_title_layout(data['regions'][rid]['label'], box['w'], title_font)
                          for rid, box in regions.items()},
        'hierarchy_arrows': {}, 'hierarchy_attachments': {},
        'canvas': {'width': math.ceil(raw['width'] + 40), 'height': math.ceil(raw['height'] + 40)},
        'layout_engine': {'name': 'compound-elk-layered', 'elkjs_version': result['engine']['elkjsVersion'],
                          'elk_region_ids': sorted(regions), 'elk_edge_ids': sorted(ordinary),
                          'native_routed_edge_ids': [], 'macro_engine': 'elk-layered',
                          'route_preflight': quality, 'acceptance': 'pending'},
    }
    if data['project'].get('semantic_view'):
        layout['semantic_view'] = data['project']['semantic_view']
    if any(overrides.get(group) for group in ('nodes', 'regions', 'edges')):
        layout = apply_precision(data, layout, overrides)
    if not defer_hierarchy_arrows:
        layout['hierarchy_arrows'] = plan_hierarchy_arrows(data, layout)
        apply_hierarchy_arrow_overrides(layout, state)
    return normalize_junctions(data, layout)
