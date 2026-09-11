import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from precision_layout import apply_precision
from plan_layout import plan
from junction_routes import points_for


def fixture():
    data = {'project': {}, 'regions': {'r': {'parent': None, 'label': 'Operators'}},
            'nodes': {nid: {'region': 'r', 'kind': 'operator', 'label': nid} for nid in ('a', 'b')},
            'edges': {'ab': {'source': 'a', 'target': 'b', 'kind': 'tensor'}}}
    base = {'schema_version': 3, 'architecture_sha256': 'digest',
            'nodes': {'a': {'x': 100, 'y': 400, 'w': 80, 'h': 40},
                      'b': {'x': 100, 'y': 200, 'w': 80, 'h': 40}},
            'regions': {'r': {'x': 40, 'y': 80, 'w': 240, 'h': 430}},
            'region_titles': {'r': {'header_height': 46}},
            'edges': {'ab': {'source_port': {'side': 'north', 'position': .5},
                             'target_port': {'side': 'south', 'position': .5},
                             'waypoints': [], 'label_position': {'x': 0, 'y': 0}}},
            'hierarchy_arrows': {}, 'hierarchy_attachments': {}, 'canvas': {'width': 400, 'height': 600}}
    return data, base


class PrecisionTests(unittest.TestCase):
    def test_translate_region_preserves_internal_geometry_and_original(self):
        data, base = fixture()
        original = copy.deepcopy(base)
        out = apply_precision(data, base, {'regions': {'r': {'x': 240, 'y': 180}}})
        self.assertEqual(out['nodes']['a']['x'], 300)
        self.assertEqual(out['nodes']['b']['y'], 300)
        self.assertEqual(out['edges']['ab']['label_position'], {'x': 0, 'y': 0})
        self.assertEqual(base, original)

    def test_move_node_reconnects_orthogonal_endpoints(self):
        data, base = fixture()
        out = apply_precision(data, base, {'nodes': {'b': {'x': 230}}})
        points = points_for(data['edges']['ab'], out['edges']['ab'], out['nodes'])
        self.assertEqual(points[-1], (270, 240))
        self.assertTrue(all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:])))
        self.assertEqual(out['layout_engine']['precision_adjusted_edge_ids'], ['ab'])

    def test_explicit_route_and_label_are_preserved(self):
        data, base = fixture()
        out = apply_precision(data, base, {'nodes': {'b': {'x': 230}}, 'edges': {
            'ab': {'waypoints': [[140, 300], [270, 300]], 'label_position': {'x': .1, 'y': -12}}}})
        self.assertEqual(out['edges']['ab']['waypoints'], [[140, 300], [270, 300]])
        self.assertEqual(out['edges']['ab']['label_position'], {'x': .1, 'y': -12})

    def test_new_obstacle_on_unrelated_route_is_detected(self):
        data, base = fixture()
        data['nodes']['c'] = {'region': 'r', 'kind': 'operator', 'label': 'Obstacle'}
        base['nodes']['c'] = {'x': 300, 'y': 300, 'w': 40, 'h': 40}
        with self.assertRaisesRegex(ValueError, 'penetrates c'):
            apply_precision(data, base, {'nodes': {'c': {'x': 120}}})

    def test_invalid_values_and_unknown_ids_fail(self):
        data, base = fixture()
        for edit in ({'nodes': {'z': {'x': 1}}}, {'nodes': {'a': {'x': float('nan')}}},
                     {'nodes': {'a': {'w': 600}}}, {'edges': {'ab': {'label_position': {'x': 0, 'y': 999}}}}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                apply_precision(data, base, edit)

    def test_previous_layout_precision_skips_elk_and_reapplies_exact_target(self):
        data, base = fixture()
        state = {'layout_overrides': {'nodes': {'b': {'x': 230}}}}
        with patch('compound_layout.subprocess.run', side_effect=AssertionError('ELK reran')):
            out = plan(data, 'digest', previous_layout=base, state=state, layout_engine='elk-compound')
            again = plan(data, 'digest', previous_layout=out, state=state, layout_engine='elk-compound')
        self.assertEqual(again['nodes'], out['nodes'])
        self.assertEqual(again['edges'], out['edges'])

    def test_stale_base_rejected(self):
        data, base = fixture()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            plan(data, 'changed', previous_layout=base, layout_engine='elk-compound')

    def test_malformed_waypoints_rejected(self):
        data, base = fixture()
        for points in (None, [1], [[1]], [[float('nan'), 2]], [[-1, 2]]):
            with self.subTest(points=points), self.assertRaisesRegex(ValueError, 'waypoints'):
                apply_precision(data, base, {'edges': {'ab': {'waypoints': points}}})

    def test_subpixel_port_reconstruction_noise_is_accepted(self):
        data, base = fixture()
        # Six-decimal normalized ports can differ by this amount after scaling by node width.
        base['edges']['ab']['target_port']['position'] = 0.5000013865
        out = apply_precision(data, base, {})
        points = points_for(data['edges']['ab'], out['edges']['ab'], out['nodes'])
        self.assertAlmostEqual(abs(points[0][0] - points[-1][0]), 0.00011092, places=8)

    def test_visible_diagonal_segment_is_rejected(self):
        data, base = fixture()
        base['edges']['ab']['target_port']['position'] = 0.50025
        with self.assertRaisesRegex(ValueError, 'non-orthogonal precision route: ab'):
            apply_precision(data, base, {})

    def test_previous_layout_cannot_ignore_frozen_policy(self):
        data, base = fixture()
        with self.assertRaisesRegex(ValueError, 'frozen'):
            plan(data, 'digest', previous_layout=base, layout_engine='elk-compound',
                 state={'region_policies': {'r': 'frozen'}})


if __name__ == '__main__':
    unittest.main()
