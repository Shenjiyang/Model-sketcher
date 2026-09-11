import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analysis_scope import POLICY, LEGACY_POLICY, validate_scope, validate_scope_review
from project_intake import propose, confirm, delivery_plan
from review_fixture import reviewed_project, complete_review
from prepare_topology_review import build_pending_review
from audit_topology_review import validate_review
from render_topology_contract import render
from topology_review_common import seal_review, semantic_json_sha256
from validate_architecture_ir import validate
from semantic_gate import validate_semantic_gate


def scope():
    return {
        "policy": POLICY,
        "algorithm_coverage": "complete-model-logical-operators",
        "inventory_basis": "Traced the projection source and its physical cache helper boundary.",
        "runtime_inventory": [{
            "id": "physical-cache", "categories": ["prefill", "decode"],
            "evidence": ["code"], "source": "model.py:2 Cache.pack",
            "affects_algorithm": False, "algorithm_nodes": [],
            "disposition": "deferred", "expanded_views": [],
            "reason": "Physical packing preserves the logical inputs and outputs of the operator.",
            "semantic_boundary": "Storage slots are deferred; mathematical dependencies remain in the graph.",
        }],
    }


def scope_review():
    return {
        "status": "pass", "inventory_complete": True,
        "finding": "Source tracing confirms the operator and its physical cache extension boundary.",
        "items": {"physical-cache": {
            "status": "pass", "disposition": "deferred", "evidence": ["code"],
            "source": "model.py:2 Cache.pack",
            "finding": "The helper changes physical storage only; all logical dependencies are represented.",
        }},
    }


class AnalysisScopeTests(unittest.TestCase):
    def project(self):
        temp, root, arch, topology, review, data = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        data["analysis_scope"] = scope()
        intake = confirm(propose("review-fixture"),
                         {"coverage": "selected-modules", "modules": ["projection"]},
                         "user-1", "Draw the projection operators")
        return root, arch, topology, review, data, intake

    def test_default_algorithm_needs_no_runtime_graph(self):
        root, _, _, _, data, intake = self.project()
        self.assertEqual(validate(data, root, require_files=True), [])
        self.assertEqual(delivery_plan(intake, data)["views"], {"algorithm": ["model-algorithm"]})
        self.assertIn("runtime-extension:physical-cache", render(data))
        self.assertNotIn("inference-runtime", render(data))

    def test_new_policy_requires_scope_and_logical_contracts(self):
        _, _, _, _, data, intake = self.project()
        data.pop("analysis_scope")
        with self.assertRaisesRegex(ValueError, "analysis_scope is required"):
            delivery_plan(intake, data)
        data["analysis_scope"] = scope()
        data["project"]["require_logical_operator_contracts"] = False
        self.assertTrue(validate_scope(data))

    def test_algorithm_semantics_cannot_be_deferred_or_unmapped(self):
        _, _, _, _, data, _ = self.project()
        item = data["analysis_scope"]["runtime_inventory"][0]
        item["affects_algorithm"] = True
        errors = validate_scope(data)
        self.assertTrue(any("cannot be deferred" in e for e in errors))
        self.assertTrue(any("algorithm_nodes" in e for e in errors))
        item.update(disposition="algorithm", algorithm_nodes=["projection"])
        self.assertEqual(validate_scope(data), [])

    def test_summary_delivery_cannot_lower_canonical_depth(self):
        _, _, _, _, data, _ = self.project()
        data["project"]["request_contract"]["depth"] = "module-summary"
        data["regions"]["detail"]["granularity"] = "module-summary"
        errors = validate_scope(data)
        self.assertTrue(any("canonical logical-operators" in e for e in errors))
        self.assertTrue(any("operator-detail expansion" in e for e in errors))

    def test_requested_runtime_cannot_reuse_deferred_inventory(self):
        _, _, _, _, data, intake = self.project()
        changed = confirm(intake, {"delivery_views": ["algorithm", "decode"]},
                          "user-2", "Also draw decode")
        with self.assertRaisesRegex(ValueError, "require expansion"):
            delivery_plan(changed, data)

    def test_expanded_runtime_requires_real_views_and_matching_phases(self):
        _, _, _, _, data, _ = self.project()
        item = data["analysis_scope"]["runtime_inventory"][0]
        item.update(disposition="expanded", expanded_views=["runtime"])
        self.assertTrue(validate_scope(data))
        data["view_projection_contract"]["views"]["runtime"] = {
            "kind": "inference-runtime", "runtime_phases": ["prefill", "decode"]}
        self.assertTrue(any("no nodes" in e for e in validate_scope(data)))
        data["nodes"]["projection"]["views"].append("runtime")
        self.assertEqual(validate_scope(data, ["decode"]), [])
        data["view_projection_contract"]["views"]["runtime"]["runtime_phases"] = ["prefill"]
        self.assertTrue(any("every declared" in e for e in validate_scope(data)))

    def test_deferred_source_boundary_requires_inventory_and_evidence(self):
        root, _, _, _, data, _ = self.project()
        op = {"id": "model.pack", "label": "Physical cache packing helper",
              "source": "model.py:2", "status": "deferred-runtime",
              "runtime_extension": "physical-cache"}
        data["source_coverage"]["paths"][0]["operations"].append(op)
        self.assertEqual(validate(data, root), [])
        op["runtime_extension"] = "unknown"
        self.assertTrue(any("requires a deferred" in e for e in validate(data, root)))
        op["runtime_extension"] = "physical-cache"
        op["node"] = "projection"
        self.assertTrue(any("cannot claim a graph" in e for e in validate(data, root)))
        del op["node"]
        data.pop("analysis_scope")
        self.assertTrue(any("requires analysis_scope" in e for e in validate(data, root)))

    def test_scope_review_is_required_and_bound_to_receipt(self):
        root, arch, topology, path, data, intake = self.project()
        (root / "project-intake.json").write_text(json.dumps(intake))
        arch.write_text(json.dumps(data))
        topology.write_text(render(data))
        pending = build_pending_review(arch, topology, "semantic-revision")
        self.assertFalse(pending["analysis_scope_review"]["inventory_complete"])
        review = complete_review(pending, data)
        path.write_text(json.dumps(review))
        self.assertTrue(any("analysis_scope_review" in e for e in validate_review(arch, topology, path)))
        review["analysis_scope_review"] = scope_review()
        path.write_text(json.dumps(seal_review(review)))
        self.assertEqual(validate_review(arch, topology, path), [])
        self.assertEqual(validate_semantic_gate(arch), [])
        review["analysis_scope_review"]["items"]["physical-cache"]["finding"] += " Changed."
        path.write_text(json.dumps(review))
        self.assertTrue(any("receipt is stale" in e for e in validate_review(arch, topology, path)))

    def test_deferred_helper_still_requires_independent_source_reconciliation(self):
        _, arch, topology, path, data, _ = self.project()
        data["source_coverage"]["paths"][0]["operations"].append({
            "id": "model.pack", "label": "Physical packing helper boundary",
            "source": "model.py:2", "status": "deferred-runtime",
            "runtime_extension": "physical-cache"})
        arch.write_text(json.dumps(data))
        topology.write_text(render(data))
        review = complete_review(build_pending_review(arch, topology, "semantic-revision"), data)
        review["analysis_scope_review"] = scope_review()
        path.write_text(json.dumps(seal_review(review)))
        self.assertTrue(any("reconcile every source operation" in e
                            for e in validate_review(arch, topology, path)))
        review["independent_source_inventory"]["paths"][0]["operations"].append({
            "id": "observed-pack", "kind": "call", "label": "Physical packing helper boundary",
            "source": "model.py:2", "evidence_id": "code", "source_operation_ids": ["model.pack"],
            "comparison": "matched"})
        path.write_text(json.dumps(seal_review(review)))
        self.assertEqual(validate_review(arch, topology, path), [])

    def test_scope_reclassification_invalidates_existing_semantic_digest(self):
        _, _, _, _, data, _ = self.project()
        before = semantic_json_sha256(data)
        data["analysis_scope"]["runtime_inventory"][0]["reason"] += " New scope decision."
        self.assertNotEqual(before, semantic_json_sha256(data))
        self.assertTrue(validate_scope_review(data, {"analysis_scope_review": {
            **scope_review(), "items": {}}}))

    def test_legacy_policy_is_not_silently_narrowed(self):
        _, _, _, _, data, intake = self.project()
        legacy = propose("test")
        legacy["analysis_policy"] = LEGACY_POLICY
        legacy = confirm(legacy, {}, "user-1", "Use defaults")
        self.assertEqual(legacy["analysis_policy"], LEGACY_POLICY)
        intake["analysis_policy"] = LEGACY_POLICY
        intake = confirm(intake, {}, "user-2", "Reuse confirmed choices")
        with self.assertRaisesRegex(ValueError, "legacy intake requires full analysis"):
            delivery_plan(intake, data)

    def test_implementation_depth_is_only_legacy(self):
        with self.assertRaises(ValueError):
            confirm(propose("test"), {"depth": "implementation-detail"}, "user-1", "Implementation detail")
        legacy = propose("test")
        legacy["analysis_policy"] = LEGACY_POLICY
        self.assertEqual(confirm(legacy, {"depth": "implementation-detail"},
                                 "user-1", "Implementation detail")["choices"]["depth"], "implementation-detail")


if __name__ == "__main__":
    unittest.main()
