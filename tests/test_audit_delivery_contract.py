import json
import unittest
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_delivery_contract import validate_manifest
from fusion_presentation import execution_fusion_ledger, fusion_presentation
from review_fixture import reviewed_project


class DeliveryContractTests(unittest.TestCase):
    def project(self, mutate=None):
        temp, root, architecture, topology, topology_review, canonical = reviewed_project(with_views=True)
        diagram = root / "model.drawio"
        diagram.write_text("<mxfile/>", encoding="utf-8")
        for name in ("evidence.md", "shapes.md"):
            (root / name).write_text("evidence", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "workflow_contract": {
                "output_view": "hierarchy-master",
                "contains_detail_regions": True,
                "evidence_file": "evidence.md",
                "architecture_file": "architecture.json",
                "topology_contract_file": topology.name,
                "topology_review_file": "topology-review.json",
                "shape_ledger_file": "shapes.md",
                "evidence_sources": [
                    {"role": "checkpoint-config", "path": "config.json", "revision": "checkpoint", "claims": ["dimensions"]},
                    {"role": "canonical-model", "path": "model.py", "revision": "commit", "claims": ["forward path"]},
                ],
            },
            "defaults": {
                "require_granularity_contracts": True,
                "require_logical_operator_contracts": True,
                "require_source_coverage": True,
                "require_view_projection_contracts": True,
                "semantic_view": "model-algorithm",
                "view_projection_contract": {
                    "status": "pass",
                    "views": {"model-algorithm": {"kind": "algorithm-master"}},
                },
                "require_reader_facing_labels": True,
                "require_overview_contract": True,
                "overview_contract": {
                    "status": "pass", "method": "standalone-reader-review",
                    "level0_region_ids": ["model"],
                },
                "require_template_coverage_contract": True,
                "template_coverage_contract": {},
                "require_cross_level_interface_contracts": True,
                "cross_level_interface_contracts": {},
                "require_operator_display_contract": True,
                "operator_display_contract": {
                    "status": "pass", "method": "reader-shape-parameter-review",
                    "reviewed_region_ids": ["detail"],
                },
                "require_detail_information_gain_contracts": True,
                "detail_information_gain_contracts": {},
                "require_runtime_variant_contracts": True,
                "runtime_variant_contracts": {},
                "require_state_lifecycle_contracts": True,
                "state_lifecycle_contracts": {},
                "require_port_geometry_contracts": True,
                "expected_ports": {},
                "require_registered_edge_label_positions": True,
                "expected_edge_label_positions": {},
                "require_semantic_style_contract": True,
                "semantic_style_contract": {"profile": "model-sketcher-original"},
                "require_semantic_glyph_contract": True,
                "require_semantic_coverage": True,
                "require_compact_execution_geometry": True,
                "regions": ["region:model", "region:detail"],
                "granularity_contracts": {
                    "region:model": {"mode": "module-summary", "level": 0},
                    "region:detail": {"mode": "operator-detail", "level": 2},
                },
                "hierarchy_anchors": {},
                "node_semantics": {},
            },
            "render": {
                "overview_width": 2560,
                "detail_width": 4800,
                "detail_regions": [{"name": "a"}, {"name": "b"}],
            },
        }
        manifest["defaults"]["operator_display_contract"] = canonical["operator_display_contract"]
        manifest["defaults"]["execution_fusion_ledger"] = execution_fusion_ledger(canonical)
        manifest["defaults"]["fusion_presentation_policy"] = fusion_presentation(canonical)
        if mutate:
            mutate(manifest)
        manifest_path = root / "model.audit.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return temp, diagram, manifest_path

    def test_complete_contract_passes_preflight(self):
        temp, diagram, manifest = self.project()
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertEqual([], errors)

    def test_forged_projection_external_lifecycle_is_rejected(self):
        temp, diagram, manifest = self.project(lambda data: data["defaults"].update(
            external_canonical_references={"state_lifecycles": {"fake": {"writers": ["invented"]}}}))
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("external_canonical_references differs" in error for error in errors))

    def test_manifest_cannot_select_an_undeclared_canonical_view(self):
        temp, diagram, manifest = self.project(lambda data: data["defaults"].update(semantic_view="fake-view"))
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("unknown semantic view" in error for error in errors))

    def test_missing_granularity_gate_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["defaults"].pop("require_granularity_contracts")
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_granularity_contracts" in error for error in errors))

    def test_missing_logical_operator_gate_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["defaults"].pop("require_logical_operator_contracts")
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_logical_operator_contracts" in error for error in errors))

    def test_missing_source_coverage_gate_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["defaults"].pop("require_source_coverage")
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_source_coverage" in error for error in errors))

    def test_missing_view_projection_gate_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["defaults"].pop("require_view_projection_contracts")
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_view_projection_contracts" in error for error in errors))

    def test_missing_reader_facing_label_gate_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["defaults"].pop("require_reader_facing_labels")
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_reader_facing_labels" in error for error in errors))

    def test_missing_overview_and_operator_display_gates_fail(self):
        def mutate(data):
            data["defaults"].pop("require_overview_contract")
            data["defaults"].pop("overview_contract")
            data["defaults"].pop("require_operator_display_contract")
            data["defaults"].pop("operator_display_contract")

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_overview_contract" in error for error in errors))
        self.assertTrue(any("require_operator_display_contract" in error for error in errors))

    def test_cross_level_contract_ids_must_match_hierarchy_anchors(self):
        def mutate(data):
            data["defaults"]["hierarchy_anchors"] = {"expand:detail": {}}

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("missing=['detail']" in error for error in errors))

    def test_missing_semantic_style_gate_fails(self):
        def mutate(data):
            data["defaults"].pop("require_semantic_style_contract")
            data["defaults"].pop("semantic_style_contract")

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_semantic_style_contract" in error for error in errors))

    def test_missing_detail_runtime_state_and_glyph_gates_fail(self):
        def mutate(data):
            for key in (
                "require_detail_information_gain_contracts", "detail_information_gain_contracts",
                "require_runtime_variant_contracts", "runtime_variant_contracts",
                "require_state_lifecycle_contracts", "state_lifecycle_contracts",
                "require_semantic_glyph_contract",
            ):
                data["defaults"].pop(key)

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_detail_information_gain_contracts" in error for error in errors))
        self.assertTrue(any("require_runtime_variant_contracts" in error for error in errors))
        self.assertTrue(any("require_state_lifecycle_contracts" in error for error in errors))
        self.assertTrue(any("require_semantic_glyph_contract" in error for error in errors))

    def test_missing_layout_geometry_gates_fail(self):
        def mutate(data):
            for key in (
                "require_port_geometry_contracts", "expected_ports",
                "require_registered_edge_label_positions", "expected_edge_label_positions",
            ):
                data["defaults"].pop(key)

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_port_geometry_contracts" in error for error in errors))
        self.assertTrue(any("require_registered_edge_label_positions" in error for error in errors))

    def test_missing_compact_execution_gate_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["defaults"].pop("require_compact_execution_geometry")
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("require_compact_execution_geometry" in error for error in errors))

    def test_missing_review_regions_fails(self):
        temp, diagram, manifest = self.project(
            lambda data: data["render"].update(detail_regions=[])
        )
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("detail_regions" in error for error in errors))

    def test_missing_source_revision_fails(self):
        def mutate(data):
            data["workflow_contract"]["evidence_sources"][0].pop("revision")

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("requires revision" in error for error in errors))

    def test_estimator_only_evidence_fails(self):
        def mutate(data):
            for source in data["workflow_contract"]["evidence_sources"]:
                source["role"] = "supporting-analysis"

        temp, diagram, manifest = self.project(mutate)
        self.addCleanup(temp.cleanup)
        _, errors = validate_manifest(diagram, manifest)
        self.assertTrue(any("checkpoint-config" in error for error in errors))
        self.assertTrue(any("executable model evidence" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
