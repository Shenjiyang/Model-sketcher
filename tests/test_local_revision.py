from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_local_revision import (RevisionRun, changed_geometry, focused_layout,
                                merge_manifest, triage, verify_baseline_geometry)


def sample():
    data = {'project': {'semantic_view': 'master'},
            'view_projection_contract': {'views': {'master': {}, 'focus': {}}},
            'regions': {'r': {'views': ['master', 'focus']}, 'other': {'views': ['master']}},
            'nodes': {'a': {'region': 'r', 'views': ['master', 'focus'], 'kind': 'operator'},
                      'b': {'region': 'r', 'views': ['master', 'focus'], 'kind': 'operator'},
                      'c': {'region': 'other', 'views': ['master'], 'kind': 'operator'}},
            'edges': {'ab': {'source': 'a', 'target': 'b', 'kind': 'tensor', 'views': ['master', 'focus']}}}
    layout = {'semantic_view': 'master', 'regions': {'r': dict(x=500, y=500, w=200, h=500),
                                                    'other': dict(x=1000, y=1000, w=200, h=500)},
              'nodes': {'a': dict(x=550, y=800, w=100, h=50), 'b': dict(x=550, y=600, w=100, h=50),
                        'c': dict(x=1050, y=1100, w=100, h=50)},
              'edges': {'ab': {'source_port': 'north', 'target_port': 'south', 'waypoints': []}},
              'hierarchy_arrows': {}, 'canvas': {}}
    return data, layout


class LocalRevisionTests(unittest.TestCase):
    def test_editor_geometry_changes_cannot_be_silently_discarded(self):
        from test_compiler_pipeline import sample as compiler_sample
        from compile_drawio import compile_diagram
        from plan_layout import plan
        data = compiler_sample()
        layout = plan(data, 'test-digest')
        tree = compile_diagram(data, layout)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'diagram.drawio'
            tree.write(path, encoding='utf-8')
            verify_baseline_geometry(path, layout, data)
            node = next(c for c in tree.getroot().iter('mxCell') if c.get('id') == 'node:a')
            geo = node.find('mxGeometry')
            geo.set('x', str(float(geo.get('x')) + 10))
            tree.write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'geometry drift'):
                verify_baseline_geometry(path, layout, data)

    def test_supplied_hierarchy_override_is_rejected(self):
        data, layout = sample()
        candidate = deepcopy(layout)
        candidate['hierarchy_arrows']['new'] = {'x': 1}
        with self.assertRaisesRegex(ValueError, 'regenerated'):
            changed_geometry(layout, candidate, data, {'r'})

    def test_outside_region_change_fails(self):
        data, layout = sample()
        candidate = deepcopy(layout)
        candidate['nodes']['c']['x'] += 20
        with self.assertRaisesRegex(ValueError, 'out-of-scope nodes'):
            changed_geometry(layout, candidate, data, {'r'})

    def test_in_region_change_and_cross_edges_recorded(self):
        data, layout = sample()
        data['edges']['bc'] = {'source': 'b', 'target': 'c'}
        layout['edges']['bc'] = {'waypoints': []}
        candidate = deepcopy(layout)
        candidate['nodes']['a']['x'] += 20
        delta = changed_geometry(layout, candidate, data, {'r'})
        self.assertEqual(delta['nodes'], ['a'])
        self.assertEqual(delta['cross_region_edges_to_review'], ['bc'])

    def test_semantic_membership_change_rejected(self):
        data, layout = sample()
        candidate = deepcopy(layout)
        del candidate['nodes']['b']
        with self.assertRaisesRegex(ValueError, 'membership'):
            changed_geometry(layout, candidate, data, {'r'})

    def test_focused_view_is_exact_translation(self):
        data, layout = sample()
        focused = focused_layout(data, layout, 'focus')
        self.assertEqual(set(focused['nodes']), {'a', 'b'})
        self.assertEqual(set(focused['edges']), {'ab'})
        self.assertEqual(focused['nodes']['a']['y'] - focused['nodes']['b']['y'], 200)
        self.assertEqual(focused['regions']['r']['x'], 40)
        self.assertEqual(layout['regions']['r']['x'], 500)

    def test_missing_master_members_are_not_silently_dropped(self):
        data, layout = sample()
        del layout['nodes']['b']
        with self.assertRaisesRegex(ValueError, 'absent from master'):
            focused_layout(data, layout, 'focus')

    def test_manifest_keeps_policy_not_stale_generated_geometry(self):
        old = {'defaults': {'expected_ports': {'stale': {}}, 'typography_contract': {'ordinary_node_font': 27},
                            'route_quality_exclusions': {'edge:x': 'real obstacle'}},
               'workflow_contract': {'architecture_file': 'architecture.json',
                                     'evidence_sources': [{'path': 'model.py'}]},
               'render': {'overview_width': 2000}}
        generated = {'defaults': {'expected_ports': {'fresh': {}}, 'route_quality_exclusions': {}}}
        merged = merge_manifest(old, Path('/project/demo.audit.json'), generated)
        self.assertEqual(merged['defaults']['expected_ports'], {'fresh': {}})
        self.assertEqual(merged['defaults']['typography_contract']['ordinary_node_font'], 27)
        self.assertEqual(merged['defaults']['route_quality_exclusions'], {'edge:x': 'real obstacle'})
        self.assertEqual(merged['workflow_contract']['architecture_file'], '/project/architecture.json')
        self.assertEqual(old['workflow_contract']['architecture_file'], 'architecture.json')

    def test_page_override_cannot_restore_stale_machine_facts(self):
        old = {'defaults': {}, 'pages': {'*': {'expected_ports': {'stale': {}}}}, 'workflow_contract': {}}
        with self.assertRaisesRegex(ValueError, 'machine-owned'):
            merge_manifest(old, Path('/project/a.json'), {'defaults': {'expected_ports': {}}})

    def test_triage_does_not_invent_root_cause(self):
        result = triage('official-render', 'ERROR: rendered label overlaps edge:x / node:y')
        self.assertEqual(result[0]['root_cause'], 'not-established')
        self.assertEqual(result[0]['observed_stage'], 'official-render')
        self.assertEqual(result[0]['cell_ids'], ['edge:x', 'node:y'])
        self.assertEqual(triage('compile', 'ERROR: something new')[0]['suggested_component'], 'unknown')

    def test_existing_output_directory_is_never_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / 'keep'
            sentinel.write_text('original')
            with self.assertRaises(FileExistsError):
                RevisionRun(Path(tmp))
            self.assertEqual(sentinel.read_text(), 'original')

    def test_command_failure_records_log_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RevisionRun(Path(tmp) / 'run')
            with self.assertRaisesRegex(ValueError, 'failed'):
                run.command('probe', [sys.executable, '-c', 'print("ERROR: overlap"); raise SystemExit(2)'])
            report = json.loads((run.output / 'revision-report.json').read_text())
            self.assertEqual(report['stages'][0]['returncode'], 2)
            self.assertEqual(report['manual_review'], 'pending')

    def test_command_timeout_is_not_reported_as_layout_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RevisionRun(Path(tmp) / 'run')
            with self.assertRaises(ValueError):
                run.command('probe', [sys.executable, '-c', 'import time; time.sleep(5)'], timeout=.1)
            self.assertTrue(any(f['suggested_component'] == 'execution-environment' for f in run.report['findings']))


if __name__ == '__main__':
    unittest.main()
