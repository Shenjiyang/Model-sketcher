"""Projection keeps visual contracts closed without fabricating source review."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from view_projection import project_active_view, project_layout_view


def fixture():
    def node(visible=True):
        return {"region": "detail", "views": ["focused"] if visible else ["other"]}

    return {
        "project": {"semantic_view": "focused"},
        "view_projection_contract": {"views": {"focused": {}, "other": {}}},
        "regions": {"detail": {
            "views": ["focused"], "granularity": "implementation-detail",
            "operator_sequences": [
                {"id": "direct", "nodes": ["a", "b"]},
                {"id": "alternative", "nodes": ["a", "hidden", "b"]},
            ],
        }},
        "nodes": {"a": node(), "b": node(), "state": node(), "hidden": node(False)},
        "edges": {
            "direct": {"source": "a", "target": "b", "kind": "tensor", "views": ["focused"]},
            "write": {"source": "a", "target": "state", "kind": "tensor", "views": ["focused"]},
            "hidden-read": {"source": "state", "target": "hidden", "kind": "tensor", "views": ["other"]},
        },
        "cross_level_interface_contracts": {"hidden-expand": {"display_node": "hidden"}},
        "overview_contract": {"level0_region_ids": ["model"], "spine_nodes": ["hidden"]},
        "template_coverage_contract": {"regions": {"decoder": []}},
        "operator_display_contract": {"reviewed_region_ids": ["hidden-region"]},
        "operator_naming_review": {"reviewed_region_ids": ["hidden-region"]},
        "runtime_variant_contracts": {"detail": {
            "status": "pass", "method": "source-branch-review",
            "variants": [
                {"id": "normal", "sequence_ids": ["direct"]},
                {"id": "special", "sequence_ids": ["alternative"]},
            ],
            "shared_state_nodes": ["state", "hidden"],
        }},
        "state_lifecycle_contracts": {"state": {
            "status": "pass",
            "writers": [{"operation": "a", "edge": "write"}],
            "readers": [{"operation": "hidden", "edge": "hidden-read"}],
        }},
        "execution_fusions": [{
            "id": "fused", "operators": ["hidden"], "owner_region": "detail",
            "implementation_node": "b", "evidence": ["source"],
        }],
    }


class ProjectionContractTests(unittest.TestCase):
    def test_partial_alternative_cannot_become_complete_direct_path(self):
        result = project_active_view(fixture())
        seqs = result["regions"]["detail"]["operator_sequences"]
        self.assertEqual(seqs[0]["projection"], {"canonical_sequence_id": "direct", "complete": True})
        self.assertFalse(seqs[1]["projection"]["complete"])
        contract = result["runtime_variant_contracts"]["detail"]
        self.assertEqual([v["id"] for v in contract["variants"]], ["normal"])
        self.assertEqual(contract["status"], "pass")
        self.assertEqual(contract["projection_selection"]["excluded_variant_ids"], ["special"])

    def test_sequence_without_retained_edge_splits_and_stays_partial(self):
        data = fixture()
        del data["edges"]["direct"]
        result = project_active_view(data)
        seqs = result["regions"]["detail"]["operator_sequences"]
        self.assertTrue(all(len(s["nodes"]) == 1 for s in seqs))
        self.assertTrue(all(not s["projection"]["complete"] for s in seqs))
        self.assertEqual(result["runtime_variant_contracts"]["detail"]["variants"], [])

    def test_hidden_lifecycle_is_external_not_invented_initial_state(self):
        result = project_active_view(fixture())
        state = result["state_lifecycle_contracts"]["state"]
        self.assertEqual(state["readers"], [])
        self.assertNotIn("initial_state_reason", state)
        self.assertNotIn("output_state_reason", state)
        self.assertEqual(result["external_canonical_references"]["state_lifecycles"]["state"]["readers"][0]["operation"], "hidden")

    def test_lifecycle_wrong_direction_fails(self):
        data = fixture()
        data["edges"]["write"].update(source="state", target="a")
        with self.assertRaisesRegex(ValueError, "invalid direction"):
            project_active_view(data)

    def test_hidden_fusion_members_are_explicit_external_references(self):
        data = fixture()
        data["nodes"]["b"]["implementation_contract"] = {"implements": ["fused"]}
        result = project_active_view(data)
        contract = result["nodes"]["b"]["implementation_contract"]
        self.assertEqual(contract["implements"], [])
        self.assertEqual(contract["external_implements"], ["fused"])
        self.assertEqual(result["execution_fusions"], [])
        self.assertIn("fused", result["external_canonical_references"]["execution_fusions"])

    def test_unknown_fusion_fails_instead_of_becoming_external(self):
        data = fixture()
        data["nodes"]["b"]["implementation_contract"] = {"implements": ["invented"]}
        with self.assertRaisesRegex(ValueError, "unknown canonical fusions"):
            project_active_view(data)

    def test_backend_call_logical_members_are_scoped_without_physical_fusion(self):
        data = fixture()
        data["nodes"]["b"]["implementation_contract"] = {
            "classification": "backend-call-boundary", "logical_members": ["a", "hidden"],
        }
        original = deepcopy(data)
        result = project_active_view(data)
        contract = result["nodes"]["b"]["implementation_contract"]
        self.assertEqual(contract["logical_members"], ["a"])
        self.assertEqual(contract["external_logical_members"], ["hidden"])
        self.assertNotIn("implements", contract)
        self.assertEqual(result["external_canonical_references"]["logical_members"]["hidden"],
                         original["nodes"]["hidden"])
        self.assertNotIn("hidden", result["nodes"])
        self.assertEqual(project_active_view(result), result)
        result["external_canonical_references"]["logical_members"]["hidden"]["region"] = "changed"
        self.assertEqual(data, original)

    def test_unknown_or_malformed_logical_members_fail_closed(self):
        for members in (["invented"], "hidden", [None], [["hidden"]]):
            data = fixture()
            data["nodes"]["b"]["implementation_contract"] = {"logical_members": members}
            with self.subTest(members=members), self.assertRaisesRegex(ValueError, "logical.members"):
                project_active_view(data)

    def test_visible_logical_members_need_no_external_disposition(self):
        data = fixture()
        data["nodes"]["b"]["implementation_contract"] = {"logical_members": ["a"]}
        result = project_active_view(data)
        contract = result["nodes"]["b"]["implementation_contract"]
        self.assertEqual(contract["logical_members"], ["a"])
        self.assertNotIn("external_logical_members", contract)

    def test_hidden_overview_and_reviewed_region_ids_are_scoped(self):
        result = project_active_view(fixture())
        for field in ("cross_level_interface_contracts", "overview_contract", "template_coverage_contract"):
            self.assertEqual(result[field], {})
        self.assertEqual(result["operator_display_contract"]["reviewed_region_ids"], [])
        self.assertEqual(result["operator_naming_review"]["reviewed_region_ids"], [])

    def test_projection_is_pure_and_idempotent(self):
        data = fixture()
        original = deepcopy(data)
        once = project_active_view(data)
        twice = project_active_view(once)
        self.assertEqual(data, original)
        self.assertEqual(once, twice)
        self.assertIsNot(once, twice)

    def test_switching_view_on_materialized_data_fails(self):
        result = project_active_view(fixture())
        result["project"]["semantic_view"] = "other"
        with self.assertRaisesRegex(ValueError, "canonical IR"):
            project_active_view(result)

    def test_layout_selector_uses_canonical_without_mutation(self):
        data = fixture()
        data["project"]["semantic_view"] = "other"
        result = project_layout_view(data, {"semantic_view": "focused"})
        self.assertIn("a", result["nodes"])
        self.assertEqual(data["project"]["semantic_view"], "other")

    def test_layout_selector_rejects_unknown_or_incompatible_views(self):
        for value in ("missing", None, []):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unknown semantic view"):
                project_layout_view(fixture(), {"semantic_view": value})
        with self.assertRaisesRegex(ValueError, "materialized projection"):
            project_layout_view(project_active_view(fixture()), {"semantic_view": "other"})

    def test_legacy_layout_uses_active_view(self):
        self.assertEqual(project_layout_view(fixture(), {}), project_active_view(fixture()))
        self.assertEqual(project_layout_view(fixture(), None), project_active_view(fixture()))


if __name__ == "__main__":
    unittest.main()
