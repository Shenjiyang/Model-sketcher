import copy
import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_topology_review import validate_review
from prepare_topology_review import build_pending_review
from render_topology_contract import render
from review_fixture import architecture_data, reviewed_project
from topology_review_common import semantic_json_sha256, sha256


class TopologyReviewTests(unittest.TestCase):
    def read_review(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def write_review(self, path, review):
        path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")

    def assert_review_error(self, mutate, fragment):
        temp, _, architecture, topology, review_path, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        review = self.read_review(review_path)
        mutate(review)
        self.write_review(review_path, review)
        errors = validate_review(architecture, topology, review_path)
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_complete_schema_v2_independent_review_passes(self):
        temp, _, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        self.assertEqual(validate_review(architecture, topology, review), [])

    def test_pending_and_schema_v1_reviews_fail(self):
        temp, root, architecture, topology, _, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        pending_path = root / "pending-review.json"
        pending_path.write_text(
            json.dumps(build_pending_review(architecture, topology, "cold-start")), encoding="utf-8"
        )
        errors = validate_review(architecture, topology, pending_path)
        self.assertTrue(any("verdict" in error for error in errors), errors)
        self.assertTrue(any("attestation" in error for error in errors), errors)

        review = json.loads(pending_path.read_text(encoding="utf-8"))
        review["schema_version"] = 1
        pending_path.write_text(json.dumps(review), encoding="utf-8")
        self.assertTrue(any("schema_version must be 2" in error for error in validate_review(
            architecture, topology, pending_path
        )))

    def test_placeholder_and_duplicate_review_records_fail(self):
        self.assert_review_error(
            lambda review: review["semantic_review"].update(findings=["TODO replace this finding"]),
            "concrete non-placeholder",
        )
        self.assert_review_error(
            lambda review: review["semantic_review"]["results"].append(
                copy.deepcopy(review["semantic_review"]["results"][0])
            ),
            "every required check exactly once",
        )
        self.assert_review_error(
            lambda review: review["semantic_review"]["region_results"].append(
                copy.deepcopy(review["semantic_review"]["region_results"][0])
            ),
            "every region exactly once",
        )

    def test_inventory_requires_every_path_and_operation_exactly_once(self):
        self.assert_review_error(
            lambda review: review["independent_source_inventory"].update(paths=[]),
            "cover every source path exactly",
        )
        self.assert_review_error(
            lambda review: review["independent_source_inventory"]["paths"][0]["operations"][0].update(
                source_operation_ids=[]
            ),
            "source_operation_ids",
        )
        self.assert_review_error(
            lambda review: review["independent_source_inventory"]["paths"][0]["operations"].append(
                copy.deepcopy(review["independent_source_inventory"]["paths"][0]["operations"][0])
            ),
            "source operation more than once",
        )

    def test_material_callee_must_bind_pinned_evidence(self):
        self.assert_review_error(
            lambda review: review["independent_source_inventory"]["paths"][0]["material_callees"][0].update(
                evidence_id="untracked-helper"
            ),
            "pinned evidence source",
        )

    def test_each_region_requires_semantic_and_reconstruction_results(self):
        self.assert_review_error(
            lambda review: review["semantic_review"].update(region_results=[]),
            "cover every region exactly once",
        )
        self.assert_review_error(
            lambda review: review["reconstruction_review"].update(region_results=[]),
            "cover every region exactly once",
        )
        self.assert_review_error(
            lambda review: review["semantic_review"]["results"][0].update(scope_refs=["evidence:code"]),
            "required per-check scopes",
        )
        self.assert_review_error(
            lambda review: next(
                result for result in review["reconstruction_review"]["results"]
                if result["check"] == "detail-sequence-reconstructable"
            ).update(contract_refs=["region:detail"]),
            "required reconstruction contracts",
        )

    def test_evidence_status_check_must_cover_every_pinned_source(self):
        self.assert_review_error(
            lambda review: next(
                result for result in review["semantic_review"]["results"]
                if result["check"] == "evidence-status"
            ).update(evidence_refs=["code"]),
            "every pinned evidence source",
        )

    def test_blockers_and_self_review_fail(self):
        self.assert_review_error(
            lambda review: review["semantic_review"].update(blocking_findings=["Decode branch is absent."]),
            "unresolved blocking",
        )
        self.assert_review_error(
            lambda review: review.update(reviewer_id=review["builder_id"]),
            "independent",
        )

    def test_invalid_architecture_cannot_be_reviewed(self):
        temp, _, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        data = json.loads(architecture.read_text(encoding="utf-8"))
        data["regions"]["detail"]["direction"] = "row"
        architecture.write_text(json.dumps(data), encoding="utf-8")
        errors = validate_review(architecture, topology, review)
        self.assertTrue(any("architecture IR invalid" in error for error in errors), errors)

    def test_architecture_ascii_and_source_changes_invalidate_review(self):
        for target in ("architecture.json", "topology.contract.txt", "model.py"):
            temp, root, architecture, topology, review, _ = reviewed_project()
            self.addCleanup(temp.cleanup)
            path = root / target
            if target == "architecture.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                data["nodes"]["projection"]["label"] = "Output projection"
                path.write_text(json.dumps(data), encoding="utf-8")
            else:
                path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
            errors = validate_review(architecture, topology, review)
            self.assertTrue(any("stale" in error for error in errors), (target, errors))

    def test_hand_edited_ascii_cannot_pass_with_a_refreshed_hash(self):
        temp, _, architecture, topology, review_path, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        topology.write_text(topology.read_text(encoding="utf-8") + "manual claim\n", encoding="utf-8")
        review = self.read_review(review_path)
        review["topology_contract_sha256"] = sha256(topology)
        self.write_review(review_path, review)
        with self.assertRaisesRegex(ValueError, "not the canonical generated output"):
            build_pending_review(architecture, topology, "requested-recheck")
        errors = validate_review(architecture, topology, review_path)
        self.assertTrue(any("not the canonical generated output" in error for error in errors), errors)

    def test_visual_and_review_only_changes_reuse_review(self):
        temp, _, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        data = json.loads(architecture.read_text(encoding="utf-8"))
        data["project"]["typography"] = {"ordinary_node_font": 27}
        data["regions"]["detail"]["child_direction"] = "row"
        data["nodes"]["projection"].update({
            "visual_class": "tensor-op", "visual_class_reason": "projection role",
            "visual_modifiers": ["tp-partition"], "visual_modifier_reason": "fixture partition styling",
        })
        data["operator_naming_review"]["findings"] = ["A revised review-only naming observation."]
        data["source_coverage"]["reconciliation"]["findings"] = ["A revised review-only source observation."]
        data["overview_contract"]["findings"] = ["A revised review-only overview observation."]
        data["operator_display_contract"]["findings"] = ["A revised review-only display observation."]
        architecture.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        topology.write_text(render(data), encoding="utf-8")
        self.assertEqual(validate_review(architecture, topology, review), [])

    def test_json_key_reordering_preserves_digest_and_ascii(self):
        data = architecture_data()
        reordered = {key: data[key] for key in reversed(list(data))}
        reordered["nodes"] = {key: data["nodes"][key] for key in reversed(list(data["nodes"]))}
        reordered["edges"] = {key: data["edges"][key] for key in reversed(list(data["edges"]))}
        self.assertEqual(semantic_json_sha256(data), semantic_json_sha256(reordered))
        self.assertEqual(render(data), render(reordered))

    def test_layout_order_changes_preserve_digest_and_ascii(self):
        data = architecture_data()
        changed = copy.deepcopy(data)
        changed["regions"]["detail"]["order"] = 99
        changed["nodes"]["input"]["order"] = 300
        changed["nodes"]["projection"]["order"] = -20
        self.assertEqual(semantic_json_sha256(data), semantic_json_sha256(changed))
        self.assertEqual(render(data), render(changed))

    def test_active_projection_selector_preserves_canonical_review_digest(self):
        data = architecture_data()
        data["project"]["semantic_view"] = "model-algorithm"
        changed = copy.deepcopy(data)
        changed["project"]["semantic_view"] = "backend-runtime"
        self.assertEqual(semantic_json_sha256(data), semantic_json_sha256(changed))
        self.assertEqual(render(data), render(changed))

    def test_malformed_review_and_missing_ascii_fail_without_crashing(self):
        temp, _, architecture, topology, review_path, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        review = self.read_review(review_path)
        review["semantic_review"]["reviewed_path_ids"] = None
        review["reconstruction_review"]["results"] = {"bad": "shape"}
        self.write_review(review_path, review)
        topology.unlink()
        errors = validate_review(architecture, topology, review_path)
        self.assertTrue(any("cannot read ASCII" in error for error in errors), errors)
        self.assertTrue(any("reviewed_path_ids" in error for error in errors), errors)
        self.assertTrue(any("results must be a list" in error for error in errors), errors)

    def test_unhashable_review_identifiers_fail_without_crashing(self):
        temp, _, architecture, topology, review_path, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        review = self.read_review(review_path)
        review["trigger"] = []
        review["source_artifacts"][0]["evidence_id"] = {}
        review["independent_source_inventory"]["paths"][0]["path_id"] = []
        review["semantic_review"]["results"][0]["check"] = {}
        review["reconstruction_review"]["region_results"][0]["region_id"] = []
        self.write_review(review_path, review)
        errors = validate_review(architecture, topology, review_path)
        self.assertTrue(any("trigger is invalid" in error for error in errors), errors)
        self.assertTrue(any("unknown or duplicate" in error for error in errors), errors)
        self.assertTrue(any("check is invalid" in error for error in errors), errors)
        self.assertTrue(any("region_id is unknown" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
