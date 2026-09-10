import json
import tempfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

from prepare_topology_review import build_pending_review
from render_topology_contract import render
from topology_review_common import RECONSTRUCTION_REVIEW_CHECKS, SEMANTIC_REVIEW_CHECKS


def architecture_data() -> dict:
    return {
        "schema_version": 1,
        "project": {
            "id": "review-fixture",
            "title": "Review fixture",
            "output_view": "hierarchy-master",
            "require_source_coverage": True,
            "require_logical_operator_contracts": True,
            "request_contract": {"user_quote": "Review the projection logical operators",
                                 "source_ref": "test-user-message", "views": ["model-algorithm"],
                                 "coverage": "selected-modules", "depth": "logical-operators",
                                 "required_modules": ["projection"]},
            "delivery_scope": {"module_regions": {"projection": ["detail"]},
                               "required_regions": {"detail": "operator-detail"}},
        },
        "evidence": [
            {"id": "cfg", "role": "checkpoint-config", "path": "config.json", "revision": "fixture-v1"},
            {"id": "code", "role": "canonical-model", "path": "model.py", "revision": "fixture-v1"},
        ],
        "shape_symbols": {"B": "batch size", "D": "hidden dimension", "S": "sequence length"},
        "regions": {
            "detail": {
                "label": "Projection detail",
                "parent": None,
                "direction": "column",
                "flow_direction": "bottom-to-top",
                "level": 2,
                "granularity": "operator-detail",
                "operator_standard": "logical-tensor-ops",
                "operator_sequences": [{"id": "main", "nodes": ["input", "projection", "output"]}],
            }
        },
        "nodes": {
            "input": {
                "label": "Input", "kind": "interface", "region": "detail",
                "evidence": ["cfg"], "order": 0,
            },
            "projection": {
                "label": "Feature projection", "kind": "operator", "region": "detail",
                "evidence": ["code"], "order": 1,
                "parameter_shapes": ["W_proj: [D,D]"],
                "operator_contract": {
                    "classification": "atomic-operator",
                    "op_type": "linear",
                    "semantic_role": "feature-projection",
                    "source_symbols": ["self.proj"],
                    "shape_rule": "transform",
                    "shape_equation": "[B,S,D] -> [B,S,D]",
                },
            },
            "output": {
                "label": "Output", "kind": "interface", "region": "detail",
                "evidence": ["code"], "order": 2,
            },
        },
        "edges": {
            "input_projection": {
                "source": "input", "target": "projection", "kind": "tensor",
                "tensor": {
                    "name": "hidden_states", "shape": "[B,S,D]",
                    "status": "code-confirmed", "evidence": ["code"],
                },
            },
            "projection_output": {
                "source": "projection", "target": "output", "kind": "tensor",
                "tensor": {
                    "name": "projected_states", "shape": "[B,S,D]",
                    "status": "code-confirmed", "evidence": ["code"],
                },
            },
        },
        "source_coverage": {
            "scope": "complete-hierarchy",
            "canonical_source_ids": ["code"],
            "paths": [{
                "id": "model-forward",
                "evidence": "code",
                "source": "model.py:1-3",
                "regions": ["detail"],
                "operations": [{
                    "id": "model.projection",
                    "label": "Apply feature projection",
                    "status": "visible-node",
                    "node": "projection",
                    "source": "model.py:2",
                }],
            }],
            "reconciliation": {
                "status": "pass",
                "method": "independent-source-reread",
                "reviewed_path_ids": ["model-forward"],
                "architecture_changed": False,
                "findings": ["A second source-first pass found no omitted material operations."],
            },
        },
        "overview_contract": {
            "status": "pass",
            "method": "standalone-reader-review",
            "level0_region_ids": ["detail"],
            "spine_nodes": ["input", "projection", "output"],
            "facets": {"input": ["input"], "backbone": ["projection"], "output": ["output"]},
            "signature_components": [{
                "id": "projection-path",
                "display_text": "Feature projection",
                "level0_nodes": ["projection"],
                "level1_nodes": [],
                "evidence": ["code"],
            }],
            "checks": [
                "standalone-model-identity", "heterogeneous-backbone-summary",
                "model-level-branch-coverage", "output-readout-coverage",
            ],
            "findings": ["The fixture exposes the complete input, projection, and output path."],
        },
        "operator_naming_review": {
            "status": "pass", "method": "reader-and-source-review",
            "reviewed_region_ids": ["detail"],
            "checks": ["reader-facing-labels", "source-symbol-traceability", "sibling-consistency"],
            "findings": ["The projection uses reader-facing terminology and retains its source symbol."],
        },
        "operator_display_contract": {
            "status": "pass", "method": "reader-shape-parameter-review",
            "reviewed_region_ids": ["detail"],
            "activation_shape_placement": "tensor-edges",
            "parameter_shape_placement": "external-annotations-or-structured-ir",
            "source_symbol_placement": "structured-ir-or-secondary-line",
            "checks": [
                "operator-names", "activation-shapes-on-edges",
                "parameter-shapes-outside-blocks", "source-symbols-outside-primary-label",
            ],
            "findings": ["Operator names, activation shapes, parameters, and source symbols remain separated."],
        },
        "execution_fusions": [],
    }


def complete_review(review: dict, data: dict) -> dict:
    region_ids = sorted(data["regions"])
    path_ids = sorted(path["id"] for path in data["source_coverage"]["paths"])
    evidence_ids = sorted(item["id"] for item in data["evidence"])
    review.update({
        "builder_id": "builder-session-001",
        "reviewer_id": "reviewer-agent-002",
        "verdict": "pass",
    })
    review["reviewer_attestation"] = {
        "independent_from_builder": True,
        "source_inventory_created_before_ir_comparison": True,
        "did_not_edit_semantic_inputs": True,
    }
    review["independent_source_inventory"] = {
        "status": "pass",
        "paths": [{
            "path_id": "model-forward",
            "evidence_id": "code",
            "source": "model.py:1-3",
            "entrypoints": ["Model.forward"],
            "material_callees": [{
                "symbol": "Projection.forward",
                "source": "model.py:2",
                "evidence_id": "code",
            }],
            "operations": [{
                "id": "observed-projection",
                "kind": "operator",
                "label": "Apply the feature projection to hidden states",
                "source": "model.py:2",
                "evidence_id": "code",
                "source_operation_ids": ["model.projection"],
                "comparison": "matched",
            }],
            "closure_status": "complete",
            "findings": ["The executable path contains one material projection call and no hidden helper branch."],
        }],
        "findings": ["The independent inventory closes the selected forward path against executable source."],
        "blocking_findings": [],
    }
    all_scopes = [*(f"path:{item}" for item in path_ids), *(f"region:{item}" for item in region_ids)]
    review["semantic_review"].update({
        "status": "pass",
        "reviewed_path_ids": path_ids,
        "reviewed_region_ids": region_ids,
        "results": [{
            "check": check,
            "status": "pass",
            "scope_refs": all_scopes,
            "evidence_refs": evidence_ids,
            "finding": f"The {check} check closes against the pinned fixture sources and region contracts.",
        } for check in sorted(SEMANTIC_REVIEW_CHECKS)],
        "region_results": [{
            "region_id": region_id,
            "status": "pass",
            "source_path_ids": path_ids,
            "finding": "The detail region matches the independently inventoried projection forward path.",
        } for region_id in region_ids],
        "findings": ["Every source path, semantic region, tensor edge, and logical operation is reconciled."],
        "blocking_findings": [],
    })
    levels = {level: [rid for rid in region_ids if data["regions"][rid]["level"] == level] for level in range(4)}
    check_regions = {
        "standalone-level0": levels[0],
        "complete-level1": levels[1],
        "detail-sequence-reconstructable": levels[2] + levels[3],
        "cross-level-traceability": region_ids,
        "ambiguity-free-state-and-branches": region_ids,
        "no-informationless-detail": levels[2] + levels[3],
    }
    sequence_checks = {
        "standalone-level0", "complete-level1", "detail-sequence-reconstructable",
        "no-informationless-detail",
    }
    review["reconstruction_review"].update({
        "status": "pass",
        "reviewed_region_ids": region_ids,
        "results": [{
            "check": check,
            "status": "pass",
            "region_ids": check_regions[check],
            "contract_refs": (
                ["project:review-fixture"]
                + [f"region:{rid}" for rid in check_regions[check]]
                + ([f"sequence:{rid}/main" for rid in check_regions[check]] if check in sequence_checks else [])
            ),
            "finding": f"The generated ASCII exposes enough information to satisfy {check} without source guessing.",
        } for check in sorted(RECONSTRUCTION_REVIEW_CHECKS)],
        "region_results": [{
            "region_id": region_id,
            "status": "pass",
            "reconstructable": True,
            "contract_refs": [f"region:{region_id}", f"sequence:{region_id}/main"],
            "finding": "The ASCII gives the full ordered projection sequence and both tensor shapes.",
        } for region_id in region_ids],
        "findings": ["A reader can reconstruct the full fixture topology solely from the generated ASCII contract."],
        "blocking_findings": [],
    })
    return review


def reviewed_project(with_views=False) -> tuple[tempfile.TemporaryDirectory, Path, Path, Path, Path, dict]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    (root / "config.json").write_text('{"hidden_size": 16}\n', encoding="utf-8")
    (root / "model.py").write_text(
        "class Model:\n    def forward(self, hidden_states):\n        return self.proj(hidden_states)\n",
        encoding="utf-8",
    )
    data = architecture_data()
    if with_views:
        data["project"].update(require_view_projection_contracts=True, semantic_view="model-algorithm")
        data["view_projection_contract"] = {
            "status": "pass", "method": "canonical-ir-projection-review",
            "views": {"model-algorithm": {"kind": "algorithm-master", "purpose": "Fixture logical projection"}},
            "checks": ["canonical-entity-disposition", "algorithm-backend-separation",
                       "model-semantics-retained", "runtime-variant-placement"],
            "findings": ["The fixture has only a model-algorithm path."],
        }
        for collection in ("regions", "nodes", "edges"):
            for entity in data[collection].values():
                entity.update(semantic_layer="model-algorithm", views=["model-algorithm"])
    architecture = root / "architecture.json"
    architecture.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    topology = root / "topology.contract.txt"
    topology.write_text(render(data), encoding="utf-8")
    review_data = complete_review(build_pending_review(architecture, topology, "cold-start"), data)
    review = root / "topology-review.json"
    review.write_text(json.dumps(review_data, indent=2) + "\n", encoding="utf-8")
    return temp, root, architecture, topology, review, data
