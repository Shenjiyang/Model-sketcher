import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_fixture import reviewed_project, SCRIPTS
from semantic_gate import validate_delivery_scope, validate_semantic_gate
from render_topology_contract import render
from topology_review_common import semantic_json_sha256


class SemanticGateTests(unittest.TestCase):
    def setUp(self):
        temp, self.root, self.arch, self.ascii, self.review, self.data = reviewed_project()
        self.addCleanup(temp.cleanup)

    def command(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)],
                              capture_output=True, text=True)

    def test_standalone_tools_refuse_pending_without_touching_outputs(self):
        review = json.loads(self.review.read_text())
        review['verdict'] = 'pending'
        self.review.write_text(json.dumps(review))
        layout, output = self.root / 'layout.json', self.root / 'model.drawio'
        layout.write_text('preserve-layout')
        output.write_text('preserve-diagram')
        for name, args in [('plan_layout.py', [self.arch, layout]),
                           ('compile_drawio.py', [self.arch, layout, output])]:
            result = self.command(name, *args)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('semantic gate: REFUSED', result.stdout)
        self.assertEqual(layout.read_text(), 'preserve-layout')
        self.assertEqual(output.read_text(), 'preserve-diagram')

    def test_reviewed_standalone_layout_and_compile(self):
        layout, output = self.root / 'layout.json', self.root / 'model.drawio'
        for name, args in [('plan_layout.py', [self.arch, layout]),
                           ('compile_drawio.py', [self.arch, layout, output])]:
            result = self.command(name, *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.is_file())

    def test_engine_choice_hidden_but_legacy_commands_generate_same_layout(self):
        layout, output = self.root / 'layout.json', self.root / 'model.drawio'
        for name, args in [
            ('plan_layout.py', [self.arch, layout]),
            ('run_compiler_pipeline.py', [self.arch, '--layout', layout,
                '--drawio', output, '--topology-contract', self.ascii,
                '--topology-review', self.review]),
        ]:
            help_result = self.command(name, '--help')
            self.assertEqual(help_result.returncode, 0)
            self.assertNotIn('--layout-engine', help_result.stdout)
            baseline = None
            for engine in (None, 'elk', 'elk-compound'):
                with self.subTest(tool=name, engine=engine):
                    flags = [] if engine is None else ['--layout-engine', engine]
                    result = self.command(name, *args, *flags)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    generated = json.loads(layout.read_text())
                    self.assertEqual(generated['layout_engine']['name'], 'compound-elk-layered')
                    if baseline is None:
                        baseline = generated
                    self.assertEqual(generated, baseline)

    def test_visual_reuse_but_source_and_scope_edits_invalidate(self):
        self.data['project']['typography'] = {'ordinary_node_font': 22}
        self.arch.write_text(json.dumps(self.data))
        self.assertEqual(validate_semantic_gate(self.arch), [])
        self.data['project']['request_contract']['user_quote'] = 'Changed coverage request'
        self.arch.write_text(json.dumps(self.data))
        self.ascii.write_text(render(self.data))
        self.assertTrue(any('stale' in e for e in validate_semantic_gate(self.arch)))

    def test_changed_source_or_missing_ascii_blocks(self):
        source = self.root / 'model.py'
        source.write_text(source.read_text() + '\n# source revision\n')
        self.assertTrue(validate_semantic_gate(self.arch))
        self.ascii.unlink()
        self.assertTrue(validate_semantic_gate(self.arch))

    def test_no_fallback_from_explicit_missing_review(self):
        self.assertTrue(validate_semantic_gate(self.arch, review=self.root / 'missing.json'))
        self.assertEqual(validate_semantic_gate(self.arch), [])

    def test_detailed_scope_cannot_be_satisfied_by_overview(self):
        self.data['regions']['detail']['granularity'] = 'module-summary'
        self.data['project']['delivery_scope']['required_regions'] = {'detail': 'module-summary'}
        self.assertTrue(validate_delivery_scope(self.data))

    def test_one_detail_cannot_satisfy_another_required_module(self):
        self.data['project']['request_contract']['required_modules'].append('attention')
        self.assertTrue(validate_delivery_scope(self.data))

    def test_overview_and_selected_logical_depth_are_independent(self):
        self.assertEqual(validate_delivery_scope(self.data), [])
        self.data['project']['request_contract']['depth'] = 'module-summary'
        self.data['project']['request_contract']['coverage'] = 'whole-model'
        self.assertEqual(validate_delivery_scope(self.data), [])

    def test_missing_request_evidence_fails(self):
        self.data['project']['request_contract']['source_ref'] = ''
        self.assertTrue(validate_delivery_scope(self.data))

    def test_missing_request_review_result_blocks(self):
        review = json.loads(self.review.read_text())
        review['semantic_review']['results'] = [r for r in review['semantic_review']['results']
                                                if r['check'] != 'user-request-coverage']
        self.review.write_text(json.dumps(review))
        self.assertTrue(validate_semantic_gate(self.arch))

    def test_expansion_placement_is_visual_but_ownership_is_semantic(self):
        data = {'edges': {'expand': {'kind': 'expand', 'source': 'a', 'target': 'b', 'direction': 'up'}}}
        before = semantic_json_sha256(data)
        data['edges']['expand']['direction'] = 'left'
        self.assertEqual(before, semantic_json_sha256(data))
        data['edges']['expand']['source'] = 'c'
        self.assertNotEqual(before, semantic_json_sha256(data))
