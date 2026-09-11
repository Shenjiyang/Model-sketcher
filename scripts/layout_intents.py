"""Translate bounded visual intent into supported ELK inputs."""

from copy import deepcopy
import math

SIDES = {'north', 'south', 'east', 'west'}
SPACING = {
    'node': ('elk.spacing.nodeNode',),
    'layer': ('elk.layered.spacing.nodeNodeBetweenLayers',),
    'edge_node': ('elk.spacing.edgeNode', 'elk.layered.spacing.edgeNodeBetweenLayers'),
    'edge': ('elk.spacing.edgeEdge', 'elk.layered.spacing.edgeEdgeBetweenLayers'),
}
MACRO_SPACING = {
    'region': ('elk.spacing.nodeNode',),
    'layer': ('elk.layered.spacing.nodeNodeBetweenLayers',),
    'edge_region': ('elk.spacing.edgeNode', 'elk.layered.spacing.edgeNodeBetweenLayers'),
    'edge': ('elk.spacing.edgeEdge', 'elk.layered.spacing.edgeEdgeBetweenLayers'),
}
ALIGNMENTS = {'LEFTUP', 'RIGHTUP', 'LEFTDOWN', 'RIGHTDOWN', 'BALANCED'}
DIRECTIONS = {'up': 'UP', 'down': 'DOWN', 'left': 'LEFT', 'right': 'RIGHT'}


def mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f'{name} must be an object')
    return value


def permutation(value, members, name):
    if (not isinstance(value, list) or any(not isinstance(x, str) for x in value)
            or len(value) != len(members) or set(value) != set(members)):
        raise ValueError(f'{name} must list every member exactly once')


def validate_hints(data, hints, *, projected=True):
    hints = {} if hints is None else mapping(hints, 'layout_hints')
    if set(hints) - {'macro', 'region_order', 'regions', 'edge_ports', 'port_order'}:
        raise ValueError('unsupported layout_hints field')
    macro = mapping(hints.get('macro', {}), 'layout_hints.macro')
    if set(macro) - {'direction', 'spacing', 'alignment'}:
        raise ValueError('unsupported layout_hints.macro field')
    if 'direction' in macro and (not isinstance(macro['direction'], str)
                                 or macro['direction'] not in DIRECTIONS):
        raise ValueError('macro.direction must be up, down, left, or right')
    if 'alignment' in macro and (not isinstance(macro['alignment'], str)
                                 or macro['alignment'] not in ALIGNMENTS):
        raise ValueError('unsupported macro alignment')
    for key, value in mapping(macro.get('spacing', {}), 'macro.spacing').items():
        if key not in MACRO_SPACING or (not isinstance(value, (int, float)) or isinstance(value, bool)
                                        or not math.isfinite(value) or value <= 0):
            raise ValueError(f'invalid macro spacing {key}; use positive finite pixels')
    if 'region_order' in hints:
        if projected:
            permutation(hints['region_order'], data['regions'], 'region_order')
        else:
            value = hints['region_order']
            if (not isinstance(value, list) or any(not isinstance(x, str) for x in value)
                    or len(value) != len(set(value)) or not set(value) <= set(data['regions'])):
                raise ValueError('region_order must contain distinct known regions')
    for rid, config in mapping(hints.get('regions', {}), 'layout_hints.regions').items():
        if rid not in data['regions']:
            raise ValueError(f'layout_hints names unknown or invisible region {rid}')
        mapping(config, f'region {rid}')
        if set(config) - {'node_order', 'spacing', 'alignment'}:
            raise ValueError(f'unsupported layout hint for region {rid}')
        if 'node_order' in config:
            members = {n for n, node in data['nodes'].items() if node['region'] == rid}
            if projected:
                permutation(config['node_order'], members, f'{rid}.node_order')
            else:
                order = config['node_order']
                if (not isinstance(order, list) or any(not isinstance(n, str) for n in order)
                        or len(order) != len(set(order)) or not set(order) <= members):
                    raise ValueError(f'{rid}.node_order must contain distinct direct nodes')
        if 'alignment' in config and (not isinstance(config['alignment'], str)
                                      or config['alignment'] not in ALIGNMENTS):
            raise ValueError(f'unsupported alignment for region {rid}')
        for key, value in mapping(config.get('spacing', {}), f'{rid}.spacing').items():
            if key not in SPACING or (not isinstance(value, (int, float)) or isinstance(value, bool)
                                      or not math.isfinite(value) or value <= 0):
                raise ValueError(f'invalid spacing {rid}.{key}; use positive finite pixels')
    for eid, ports in mapping(hints.get('edge_ports', {}), 'edge_ports').items():
        edge = data['edges'].get(eid)
        if not edge or edge.get('kind') == 'expand':
            raise ValueError(f'edge_ports requires a visible ordinary edge: {eid}')
        mapping(ports, f'edge_ports.{eid}')
        if not ports or set(ports) - {'source', 'target'}:
            raise ValueError(f'invalid edge_ports roles for {eid}')
        for role, side in ports.items():
            if not isinstance(side, str) or side not in SIDES:
                raise ValueError(f'invalid port side for {eid}.{role}')
            if data['nodes'][edge[role]].get('kind') == 'junction':
                raise ValueError('junction ports are normalized by the junction contract')
    for nid, order in mapping(hints.get('port_order', {}), 'port_order').items():
        if nid not in data['nodes'] or data['nodes'][nid].get('kind') == 'junction':
            raise ValueError(f'port_order requires a visible non-junction node: {nid}')
        members = {f'{role}:{eid}' for eid, e in data['edges'].items() if e.get('kind') != 'expand'
                   for role in ('source', 'target') if e[role] == nid}
        if projected:
            permutation(order, members, f'port_order.{nid}')
        elif (not isinstance(order, list) or any(not isinstance(x, str) for x in order)
              or len(order) != len(set(order)) or not set(order) <= members):
            raise ValueError(f'port_order.{nid} must contain distinct incident endpoint IDs')
    return deepcopy(hints)


def apply_problem_hints(problem, hints):
    for eid, ports in hints.get('edge_ports', {}).items():
        for role, side in ports.items():
            problem['edges'][eid][role + '_side'] = side
    for nid, order in hints.get('port_order', {}).items():
        problem['nodes'][nid]['port_constraints'] = 'FIXED_ORDER'
        for index, endpoint in enumerate(order):
            role, eid = endpoint.split(':', 1)
            problem['edges'][eid][role + '_order'] = index


def apply_macro_hints(graph, hints):
    """Apply root-container preferences without changing semantic containment."""
    macro = hints.get('macro', {})
    options = graph['layoutOptions']
    if 'direction' in macro:
        options['elk.direction'] = DIRECTIONS[macro['direction']]
    for key, value in macro.get('spacing', {}).items():
        for option in MACRO_SPACING[key]:
            options[option] = str(float(value))
    if 'alignment' in macro:
        options['elk.layered.nodePlacement.bk.fixedAlignment'] = macro['alignment']


def apply_region_hints(containers, hints):
    for rid, config in hints.get('regions', {}).items():
        container = containers[rid]
        options = container['layoutOptions']
        for key, value in config.get('spacing', {}).items():
            for option in SPACING[key]:
                options[option] = str(float(value))
        if 'alignment' in config:
            options['elk.layered.nodePlacement.bk.fixedAlignment'] = config['alignment']
        if 'node_order' in config:
            by_id = {n['id']: n for n in container['children']}
            container['children'] = [by_id[n] for n in config['node_order']]
            options['elk.layered.considerModelOrder.strategy'] = 'NODES_AND_EDGES'


def verify_ports(data, layout, hints):
    """Side/order contracts must survive conversion and subsequent precision edits."""
    for eid, ports in hints.get('edge_ports', {}).items():
        for role, side in ports.items():
            if layout['edges'][eid][role + '_port']['side'] != side:
                raise ValueError(f'layout intent port side violated: {eid}.{role}')
    for nid, order in hints.get('port_order', {}).items():
        last = {}
        for endpoint in order:
            role, eid = endpoint.split(':', 1)
            port = layout['edges'][eid][role + '_port']
            side, position = port['side'], port['position']
            if side in last and position < last[side] - 1e-6:
                raise ValueError(f'layout intent port order violated: {nid}/{side}/{endpoint}')
            last[side] = position
    if hints:
        layout.setdefault('layout_engine', {})['layout_intent_status'] = {
            'port_sides_and_order': 'verified',
            'macro_region_and_node_order': 'ELK input preference; inspect resulting geometry',
            'spacing_and_alignment': 'ELK options; normal geometry audits still required',
        }
