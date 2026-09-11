import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from project_intake import propose, confirm, validate, delivery_plan, validate_project_intake, check_files
from review_fixture import reviewed_project
from semantic_gate import validate_semantic_gate


class ProjectIntakeTests(unittest.TestCase):
    def test_defaults_require_confirmation_and_detect_later_edits(self):
        proposed = propose('test-model')
        self.assertEqual(proposed['choices']['delivery_views'], ['algorithm'])
        self.assertEqual(proposed['choices']['depth'], 'logical-operators')
        self.assertTrue(validate(proposed))
        accepted = confirm(proposed, {}, 'user-message-1', 'Use defaults')
        self.assertEqual(validate(accepted), [])
        accepted['choices']['depth'] = 'module-summary'
        self.assertTrue(any('changed' in error for error in validate(accepted)))

    def test_unknown_choices_and_whole_model_shortlists_are_rejected(self):
        for change in ({'engine': 'native'}, {'modules': ['moe']},
                       {'delivery_views': ['unknown']}, {'coverage': 'selected-modules'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                confirm(propose('test-model'), change, 'user-1', 'Select choices')

    def test_missing_intake_blocks_geometry_even_with_valid_review(self):
        temp, root, arch, _, _, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        (root / 'project-intake.json').unlink()
        self.assertTrue(any('intake gate' in e for e in validate_semantic_gate(arch)))

    def test_delivery_selection_does_not_mutate_canonical_analysis(self):
        temp, root, _, _, _, data = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        data['view_projection_contract']['views'].update({
            'prefill-detail': {'kind': 'inference-runtime', 'runtime_phases': ['prefill']},
            'decode-detail': {'kind': 'inference-runtime', 'runtime_phases': ['decode']},
            'backend-detail': {'kind': 'backend-runtime'},
        })
        for node in data['nodes'].values():
            node['views'] += ['prefill-detail', 'decode-detail', 'backend-detail']
        before = copy.deepcopy(data)
        intake = json.loads((root / 'project-intake.json').read_text())
        self.assertEqual(set(delivery_plan(intake, data)['views']), {'algorithm'})
        expanded = confirm(intake, {'delivery_views': ['algorithm', 'decode']}, 'user-2', 'Also draw decode')
        selected = delivery_plan(expanded, data)['views']
        self.assertEqual(selected['decode'], ['decode-detail'])
        self.assertNotIn('prefill', selected)
        self.assertEqual(data, before)
        self.assertEqual(expanded['analysis_policy'], intake['analysis_policy'])

    def test_whole_model_cannot_accept_narrow_canonical_scope(self):
        temp, _, _, _, _, data = reviewed_project()
        self.addCleanup(temp.cleanup)
        intake = confirm(propose('test-model'), {}, 'user-1', 'Use defaults')
        with self.assertRaisesRegex(ValueError, 'whole-model'):
            delivery_plan(intake, data)

    def test_missing_runtime_projection_is_not_silently_omitted(self):
        temp, root, _, _, _, data = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        intake = json.loads((root / 'project-intake.json').read_text())
        intake = confirm(intake, {'delivery_views': ['algorithm', 'prefill']}, 'user-2', 'Add prefill')
        with self.assertRaisesRegex(ValueError, 'missing requested categories'):
            delivery_plan(intake, data)

    def test_unselected_runtime_cannot_excuse_incomplete_source_coverage(self):
        temp, root, _, _, _, data = reviewed_project()
        self.addCleanup(temp.cleanup)
        intake = json.loads((root / 'project-intake.json').read_text())
        data['source_coverage']['scope'] = 'selected-paths'
        with self.assertRaisesRegex(ValueError, 'complete canonical source coverage'):
            delivery_plan(intake, data)

    def test_delivery_preferences_reuse_canonical_review(self):
        temp, root, arch, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        before = [p.read_bytes() for p in (arch, topology, review)]
        path = root / 'project-intake.json'
        intake = confirm(json.loads(path.read_text()), {'files': ['drawio']},
                         'user-message-2', 'Only export Draw.io')
        path.write_text(json.dumps(intake))
        self.assertEqual(validate_semantic_gate(arch), [])
        self.assertEqual([p.read_bytes() for p in (arch, topology, review)], before)

    def test_unselected_view_cannot_support_delivery(self):
        temp, _, arch, _, _, _ = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        self.assertTrue(validate_project_intake(arch, 'backend-detail'))

    def test_bundle_cannot_omit_selected_decode_or_png(self):
        plan = {'views': {'algorithm': ['model'], 'decode': ['decode-detail']},
                'files': ['drawio', 'png']}
        with self.assertRaisesRegex(ValueError, 'selected views'):
            check_files(plan, {'model': {}}, '.')
        with self.assertRaisesRegex(ValueError, 'selected formats'):
            check_files(plan, {'model': {'drawio': 'model.drawio'}, 'decode-detail': {}}, '.')

    def test_overview_option_requires_an_actual_overview_projection(self):
        temp, root, _, _, _, data = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        intake = confirm(json.loads((root / 'project-intake.json').read_text()),
                         {'depth': 'module-summary'}, 'user-2', 'Only show module summary')
        with self.assertRaisesRegex(ValueError, 'canonical overview projection'):
            delivery_plan(intake, data)


if __name__ == '__main__':
    unittest.main()
