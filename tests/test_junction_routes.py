import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from junction_routes import normalize_junctions, rail_contracts, rail_markers, shared_terminal_overlap


def fixture():
    data = {'nodes': {'j': {'kind': 'junction'}, 'a': {'kind': 'operator'},
                      'b': {'kind': 'operator'}},
            'edges': {'a': {'source': 'j', 'target': 'a'},
                      'b': {'source': 'j', 'target': 'b'}}}
    layout = {'nodes': {'j': dict(x=100, y=200, w=12, h=12),
                        'a': dict(x=70, y=0, w=80, h=40),
                        'b': dict(x=200, y=0, w=80, h=40)},
              'edges': {'a': {'source_port': {'side': 'north', 'position': .25},
                              'target_port': {'side': 'south', 'position': .4125}, 'waypoints': []},
                        'b': {'source_port': {'side': 'north', 'position': .75},
                              'target_port': 'south', 'waypoints': [[109, 120], [240, 120]]}}}
    return data, layout


class JunctionTests(unittest.TestCase):
    def test_old_crowded_ports_fail(self):
        data, layout = fixture()
        with self.assertRaisesRegex(ValueError, 'crowded separate'):
            rail_contracts(data, layout)

    def test_normalize_is_idempotent_and_preserves_nodes(self):
        data, layout = fixture()
        fixed = normalize_junctions(data, layout)
        self.assertEqual(layout['nodes'], fixed['nodes'])
        self.assertEqual(fixed, normalize_junctions(data, fixed))
        self.assertEqual(len(rail_markers(fixed['junction_rails'])), 1)
        self.assertEqual(fixed['edges']['b']['waypoints'][0], [106, 120])

    def test_only_same_direction_terminal_is_allowed(self):
        data, layout = fixture()
        rails = normalize_junctions(data, layout)['junction_rails']
        self.assertTrue(shared_terminal_overlap('a', 'b', (106, 200), (106, 40),
                                               (106, 200), (106, 120), rails))
        self.assertFalse(shared_terminal_overlap('a', 'b', (106, 200), (106, 40),
                                                (106, 120), (106, 200), rails))
        self.assertFalse(shared_terminal_overlap('a', 'b', (106, 100), (106, 20),
                                                (106, 100), (106, 20), rails))
        self.assertFalse(shared_terminal_overlap('a', 'unrelated', (106, 200), (106, 40),
                                                (106, 200), (106, 120), rails))

    def test_out_of_bounds_opposite_port_fails(self):
        data, layout = fixture()
        layout['nodes']['a'].update(x=102, w=2)
        layout['edges']['a']['target_port']['position'] = .5
        with self.assertRaisesRegex(ValueError, 'opposite boundary'):
            normalize_junctions(data, layout)

    def test_unrelated_nodes_are_untouched(self):
        data, layout = fixture()
        data['nodes']['j']['kind'] = 'operator'
        fixed = normalize_junctions(data, layout)
        self.assertEqual(fixed['edges'], layout['edges'])
        self.assertEqual(fixed['junction_rails'], {})

    def test_reverse_terminal_rejected(self):
        data, layout = fixture()
        fixed = normalize_junctions(data, layout)
        fixed['edges']['b']['waypoints'][0][1] = 230
        with self.assertRaisesRegex(ValueError, 'reversed terminal'):
            rail_contracts(data, fixed)

    def test_tightly_spaced_branch_points_rejected(self):
        data, layout = fixture()
        fixed = normalize_junctions(data, layout)
        fixed['edges']['b']['waypoints'][0][1] = 195
        with self.assertRaisesRegex(ValueError, 'clearance'):
            rail_contracts(data, fixed)

    def test_static_registry_and_arrowhead_checks(self):
        import xml.etree.ElementTree as ET
        from audit_drawio import PageAudit
        from compile_drawio import geometry, port_coordinates
        data, layout = fixture()
        fixed = normalize_junctions(data, layout)
        model = ET.Element('mxGraphModel')
        root = ET.SubElement(model, 'root')
        ET.SubElement(root, 'mxCell', id='0')
        ET.SubElement(root, 'mxCell', id='1', parent='0')
        for nid, box in fixed['nodes'].items():
            cell = ET.SubElement(root, 'mxCell', id='node:' + nid, vertex='1', parent='1')
            geometry(cell, box)
        for eid, edge in data['edges'].items():
            route = fixed['edges'][eid]
            sx, sy = port_coordinates(route['source_port'])
            tx, ty = port_coordinates(route['target_port'])
            cell = ET.SubElement(root, 'mxCell', id='edge:' + eid, edge='1', parent='1',
                                 source='node:' + edge['source'], target='node:' + edge['target'],
                                 style=f'exitX={sx};exitY={sy};entryX={tx};entryY={ty};endArrow=block;')
            geo = ET.SubElement(cell, 'mxGeometry', relative='1', attrib={'as': 'geometry'})
            points = ET.SubElement(geo, 'Array', attrib={'as': 'points'})
            for x, y in route['waypoints']:
                ET.SubElement(points, 'mxPoint', x=str(x), y=str(y))
        markers = rail_markers(fixed['junction_rails'])
        for mid, box in markers.items():
            cell = ET.SubElement(root, 'mxCell', id=mid, vertex='1', parent='1',
                                 style='ellipse;fillColor=#000000;')
            geometry(cell, box)
        config = {'node_semantics': {'node:j': {'kind': 'junction'}},
                  'junction_rails': fixed['junction_rails'], 'junction_rail_markers': markers}
        audit = PageAudit('test', model, config)
        audit.prepare()
        self.assertTrue(audit.check_junction_rails())
        self.assertEqual(audit.errors, [])
        broken = deepcopy(config)
        broken['junction_rails'] = {}
        audit = PageAudit('test', model, broken)
        audit.prepare()
        audit.check_junction_rails()
        self.assertTrue(any('registry missing or stale' in e for e in audit.errors))
        marker = next(c for c in root if c.get('id') in markers)
        marker.find('mxGeometry').set('x', '999')
        audit = PageAudit('test', model, config)
        audit.prepare()
        audit.check_junction_rails()
        self.assertTrue(any('marker missing or moved' in e for e in audit.errors))


if __name__ == '__main__':
    unittest.main()
