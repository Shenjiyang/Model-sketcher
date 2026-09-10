import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from plan_layout import plan
from compound_layout import flatten_result
from test_layout_regression_matrix import geometry_findings


class CompoundLayoutTests(unittest.TestCase):
    def test_cross_region_edges_never_use_native_router(self):
        data = {
            'project': {},
            'regions': {rid: {'label': rid, 'parent': None, 'operator_sequences': []}
                        for rid in ('first', 'second')},
            'nodes': {'a': {'label': 'Input', 'region': 'first', 'kind': 'interface'},
                      'b': {'label': 'Linear', 'region': 'second', 'kind': 'operator'}},
            'edges': {'ab': {'source': 'a', 'target': 'b', 'kind': 'tensor'}},
        }
        with patch('plan_layout._route_edges', side_effect=AssertionError('native router called')):
            layout = plan(data, 'test', layout_engine='elk')
        self.assertEqual(set(layout['edges']), {'ab'})
        self.assertEqual(layout['layout_engine']['native_routed_edge_ids'], [])
        self.assertEqual(layout['layout_engine']['elk_edge_ids'], ['ab'])
        self.assertLess(layout['nodes']['b']['y'], layout['nodes']['a']['y'])
        self.assertEqual(geometry_findings(data, layout), [])
        for nid, node in layout['nodes'].items():
            region = layout['regions'][data['nodes'][nid]['region']]
            self.assertGreaterEqual(node['x'], region['x'])
            self.assertGreaterEqual(node['y'], region['y'])
            self.assertLessEqual(node['x'] + node['w'], region['x'] + region['w'])
            self.assertLessEqual(node['y'] + node['h'], region['y'] + region['h'])

    def test_nested_state_routes_keep_shapes_and_ownership(self):
        data = {
            'project': {},
            'regions': {
                'root': {'label': 'Decoder', 'parent': None},
                'compute': {'label': 'Attention', 'parent': 'root',
                            'operator_sequences': [{'id': 'main', 'nodes': ['a', 'b']}]},
                'storage': {'label': 'KV cache', 'parent': 'root'},
            },
            'nodes': {'a': {'label': 'Projection', 'region': 'compute', 'kind': 'operator'},
                      'b': {'label': 'Attention', 'region': 'compute', 'kind': 'operator'},
                      's': {'label': 'KV cache', 'region': 'storage', 'kind': 'cache'}},
            'edges': {eid: {'source': src, 'target': dst, 'kind': 'tensor',
                           'label': '[B,S,D]'}
                      for eid, src, dst in [('ab', 'a', 'b'), ('write', 'a', 's'), ('read', 's', 'b')]},
        }
        with patch('plan_layout._route_edges', side_effect=AssertionError('native router called')):
            result = plan(data, 'test', layout_engine='elk')
        self.assertEqual(set(result['nodes']), set(data['nodes']))
        self.assertEqual(set(result['edges']), set(data['edges']))
        self.assertTrue(all('label_position' in route for route in result['edges'].values()))
        self.assertEqual(result['edges']['read']['source_port']['side'], 'west')
        self.assertLess(result['nodes']['b']['y'], result['nodes']['a']['y'])
        findings = geometry_findings(data, result)
        self.assertFalse(any(finding[0] != 'edge-edge' for finding in findings), findings)
        if findings:
            self.assertTrue(result['layout_engine']['route_preflight']['route_errors'])
        self.assertEqual(result['layout_engine']['acceptance'], 'pending')

    def test_container_relative_edge_coordinates(self):
        raw = {'id': 'root', 'children': [{'id': 'region:r', 'x': 50, 'y': 70,
               'width': 200, 'height': 300, 'children': [
                   {'id': 'a', 'x': 10, 'y': 20, 'width': 30, 'height': 40}],
               'edges': [{'id': 'e', 'container': 'region:r',
                          'sections': [{'startPoint': {'x': 10, 'y': 20},
                                        'endPoint': {'x': 10, 'y': 100}}],
                          'labels': [{'x': 15, 'y': 50}]}]}]}
        flat, regions = flatten_result(raw, {'a'})
        self.assertEqual(flat['children'][0]['x'], 60)
        self.assertEqual(flat['edges'][0]['sections'][0]['startPoint'], {'x': 60, 'y': 90})
        self.assertEqual(flat['edges'][0]['labels'][0], {'x': 65, 'y': 120})
        self.assertEqual(regions['r']['x'], 50)

    def test_stale_coordinate_overrides_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown precision'):
            plan({'project': {}, 'nodes': {}, 'edges': {}, 'regions': {}}, 'test',
                 state={'layout_overrides': {'nodes': {'a': {'x': 4}}}},
                 layout_engine='elk-compound')


if __name__ == '__main__':
    unittest.main()
