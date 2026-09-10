"""Cross-topology, scale and label variations; keep legal and injected-bad pairs."""

from copy import deepcopy
import itertools
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_drawio import orthogonal_segments_conflict
from plan_layout_elk import layout_problem
from test_elk_layout import overlaps, route_points, segment_hits_interior


def geometry_findings(problem, layout):
    errors = []
    boxes = list(layout['nodes'].items())
    for (aid, a), (bid, b) in itertools.combinations(boxes, 2):
        if overlaps(a, b):
            errors.append(('node-overlap', aid, bid))
    routes = {}
    for eid, edge in problem['edges'].items():
        points = route_points(layout, problem, eid)
        routes[eid] = points
        for nid, box in boxes:
            if nid not in (edge['source'], edge['target']):
                for a, b in zip(points, points[1:]):
                    try:
                        if segment_hits_interior(a, b, box):
                            errors.append(('edge-node', eid, nid))
                    except AssertionError:
                        errors.append(('non-orthogonal', eid))
    for (aid, a), (bid, b) in itertools.combinations(routes.items(), 2):
        if any(orthogonal_segments_conflict(p, q, r, s)
               for p, q in zip(a, a[1:]) for r, s in zip(b, b[1:])):
            errors.append(('edge-edge', aid, bid))
    return errors


def fork_problem(branches, scale, multiline):
    problem = {'schema_version': 1, 'id': 'fork-join', 'direction': 'UP',
               'spacing': {'node': 80 * scale, 'layer': 180 * scale,
                           'edge': 24 * scale, 'edge_node': 32 * scale},
               'nodes': {'input': {'w': 420 * scale, 'h': 80 * scale},
                         'output': {'w': 420 * scale, 'h': 80 * scale}}, 'edges': {}}
    for i in range(branches):
        nid = f'branch-{i}'
        problem['nodes'][nid] = {'w': 220 * scale, 'h': 80 * scale}
        problem['edges'][f'in-{i}'] = {'source': 'input', 'target': nid, 'source_order': i}
        problem['edges'][f'out-{i}'] = {'source': nid, 'target': 'output', 'target_order': i,
                                       'label': {'text': '[B,S,H,Dh]\nbranch result' if multiline else '[N,D]',
                                                 'w': (170 if multiline else 70) * scale,
                                                 'h': (44 if multiline else 24) * scale}}
    return problem


class LayoutMatrixTests(unittest.TestCase):
    def test_fork_join_branch_scale_label_matrix(self):
        for branches, scale, multiline in itertools.product((2, 3, 6), (.75, 1.5), (False, True)):
            with self.subTest(branches=branches, scale=scale, multiline=multiline):
                problem = fork_problem(branches, scale, multiline)
                layout = layout_problem(problem, ROOT / 'scripts/elk_runner.cjs', 'node')
                self.assertEqual(geometry_findings(problem, layout), [])
                for i in range(branches):
                    self.assertLess(layout['nodes'][f'branch-{i}']['y'], layout['nodes']['input']['y'])
                    self.assertLess(layout['nodes']['output']['y'], layout['nodes'][f'branch-{i}']['y'])
                broken = deepcopy(layout)
                broken['nodes']['branch-1'] = deepcopy(broken['nodes']['branch-0'])
                self.assertTrue(any(e[0] == 'node-overlap' for e in geometry_findings(problem, broken)))

    def test_existing_topologies_at_two_scales(self):
        for family, scale in itertools.product(('problem-example', 'branching-example', 'qkv-example', 'moe-example'), (.75, 1.5)):
            with self.subTest(family=family, scale=scale):
                problem = json.loads((ROOT / f'assets/elk-layout-{family}.json').read_text())
                for box in problem['nodes'].values():
                    box['w'] *= scale
                    box['h'] *= scale
                for key in problem.get('spacing', {}):
                    problem['spacing'][key] *= scale
                for edge in problem['edges'].values():
                    if 'label' in edge:
                        edge['label']['w'] *= scale
                        edge['label']['h'] *= scale
                layout = layout_problem(problem, ROOT / 'scripts/elk_runner.cjs', 'node')
                self.assertEqual(geometry_findings(problem, layout), [])
                second = layout_problem(problem, ROOT / 'scripts/elk_runner.cjs', 'node')
                self.assertEqual(layout['nodes'], second['nodes'])
                self.assertEqual(layout['edges'], second['edges'])


if __name__ == '__main__':
    unittest.main()
