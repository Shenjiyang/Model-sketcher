from copy import deepcopy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compound_layout import build_graph, plan_compound
from layout_intents import validate_hints, verify_ports
from plan_layout import node_size
from precision_layout import apply_precision


def fork():
    return {
        'project': {},
        'regions': {'r': {'label': 'Parallel projections', 'parent': None}},
        'nodes': {n: {'region': 'r', 'kind': 'operator', 'label': n} for n in ('a', 'b', 'c', 'd')},
        'edges': {eid: {'source': src, 'target': dst, 'kind': 'tensor'}
                  for eid, src, dst in [('ab', 'a', 'b'), ('ac', 'a', 'c'), ('bd', 'b', 'd'), ('cd', 'c', 'd')]},
    }


class LayoutIntentsTests(unittest.TestCase):
    def test_problem_uses_real_elk_options_without_changing_semantics(self):
        data = fork()
        original = deepcopy(data)
        hints = {'regions': {'r': {'node_order': ['a', 'c', 'b', 'd'],
                                  'spacing': {'node': 120, 'layer': 150}, 'alignment': 'LEFTUP'}},
                 'edge_ports': {'ab': {'source': 'east', 'target': 'west'}},
                 'port_order': {'a': ['source:ac', 'source:ab']}}
        problem, graph = build_graph(data, {n: node_size(v, 18) for n, v in data['nodes'].items()}, 20, hints)
        region = graph['children'][0]
        self.assertEqual([n['id'] for n in region['children']], ['a', 'c', 'b', 'd'])
        self.assertEqual(region['layoutOptions']['elk.spacing.nodeNode'], '120.0')
        self.assertEqual(region['layoutOptions']['elk.layered.spacing.nodeNodeBetweenLayers'], '150.0')
        self.assertEqual(region['children'][0]['layoutOptions']['elk.portConstraints'], 'FIXED_ORDER')
        self.assertEqual(problem['edges']['ab']['source_side'], 'east')
        self.assertEqual(problem['edges']['ab']['target_side'], 'west')
        self.assertEqual(data, original)

    def test_real_elk_obeys_port_order_on_both_north_and_south(self):
        data = fork()
        hints = {'port_order': {'a': ['source:ac', 'source:ab'], 'd': ['target:cd', 'target:bd']}}
        layout = plan_compound(data, 'digest', {'layout_hints': hints})
        self.assertLess(layout['edges']['ac']['source_port']['position'], layout['edges']['ab']['source_port']['position'])
        self.assertLess(layout['edges']['cd']['target_port']['position'], layout['edges']['bd']['target_port']['position'])
        self.assertEqual(layout['layout_engine']['layout_hints'], hints)
        with patch('compound_layout.subprocess.run', side_effect=AssertionError('unexpected ELK rerun')):
            reused = plan_compound(data, 'digest', {'layout_hints': hints}, previous_layout=layout)
        self.assertEqual(reused['nodes'], layout['nodes'])

    def test_real_elk_local_spacing_increases_parallel_separation(self):
        data = fork()
        default = plan_compound(data, 'digest')
        hints = {'regions': {'r': {'spacing': {'node': 300}}}}
        wide = plan_compound(data, 'digest', {'layout_hints': hints})
        gap = lambda l: abs(l['nodes']['b']['x'] - l['nodes']['c']['x'])
        self.assertGreater(gap(wide), gap(default))

    def test_changed_hints_cannot_silently_reuse_layout(self):
        from test_precision_layout import fixture
        data, base = fixture()
        with self.assertRaisesRegex(ValueError, 'layout_hints changed'):
            plan_compound(data, 'digest', {'layout_hints': {'regions': {'r': {'spacing': {'node': 120}}}}},
                          previous_layout=base)

    def test_bad_hints_fail_before_running_elk(self):
        for hints in [False, {'unknown': 1}, {'regions': {'missing': {}}},
                      {'regions': {'r': {'node_order': ['a', 'b']}}},
                      {'regions': {'r': {'spacing': {'node': float('nan')}}}},
                      {'regions': {'r': {'alignment': []}}},
                      {'edge_ports': {'ab': {'source': 'inside'}}},
                      {'port_order': {'a': ['source:ab']}}]:
            with self.subTest(hints=hints), self.assertRaises(ValueError):
                validate_hints(fork(), hints)

    def test_state_preflight_rejects_misspelled_hint(self):
        from plan_change_impact import validate_state
        self.assertTrue(validate_state({'layout_hints': {'node_order': []}}, fork()))

    def test_inverted_ports_are_rejected_after_precision(self):
        data = fork()
        hints = {'port_order': {'a': ['source:ab', 'source:ac']}}
        layout = {'edges': {
            'ab': {'source_port': {'side': 'north', 'position': .8}},
            'ac': {'source_port': {'side': 'north', 'position': .2}},
        }}
        with self.assertRaisesRegex(ValueError, 'port order violated'):
            verify_ports(data, layout, hints)

    def test_precision_cannot_silently_override_requested_side(self):
        from test_precision_layout import fixture
        data, base = fixture()
        base['layout_engine'] = {'layout_hints': {'edge_ports': {'ab': {'source': 'south'}}}}
        with self.assertRaisesRegex(ValueError, 'port side violated'):
            apply_precision(data, base, {})


if __name__ == '__main__':
    unittest.main()
