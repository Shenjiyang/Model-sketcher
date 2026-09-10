import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from audit_drawio import PageAudit, decode_diagram
from compile_drawio import (
    compile_diagram,
    fusion_boundary_box,
    validate_detail_flow_geometry,
    validate_fusion_boundary_geometry,
    validate_hierarchy_arrow_geometry,
)
from compile_audit_manifest import build_manifest
from plan_layout import apply_hierarchy_arrow_overrides, plan, plan_hierarchy_arrows
from plan_change_impact import analyze, validate_state
from render_topology_contract import render
from validate_architecture_ir import validate, validate_detail_runtime_state_contracts
from view_projection import project_active_view


def sample():
    data = {
        "schema_version": 1,
        "project": {"id": "demo", "title": "A & B", "output_view": "hierarchy-master"},
        "evidence": [
            {"id": "cfg", "role": "checkpoint-config", "path": "config.json", "revision": "1"},
            {"id": "code", "role": "canonical-model", "path": "model.py", "revision": "abc"},
        ],
        "regions": {
            "model": {
                "label": "Model", "parent": None, "direction": "column",
                "flow_direction": "bottom-to-top", "level": 0,
                "granularity": "module-summary",
                "operator_sequences": [{"id": "main", "nodes": ["a", "b"]}],
            }
        },
        "nodes": {
            "a": {"label": "A", "kind": "interface", "region": "model", "evidence": ["cfg"], "order": 0},
            "b": {"label": "B", "kind": "module", "region": "model", "evidence": ["code"], "order": 1},
        },
        "edges": {"a_b": {"source": "a", "target": "b", "kind": "tensor", "label": "x"}},
    }
    data["overview_contract"] = {
        "status": "pass",
        "method": "standalone-reader-review",
        "level0_region_ids": ["model"],
        "spine_nodes": ["a", "b"],
        "facets": {"input": ["a"], "backbone": ["b"], "output": ["b"]},
        "signature_components": [{
            "id": "model-block", "display_text": "B", "level0_nodes": ["b"],
            "level1_nodes": [], "evidence": ["code"],
        }],
        "checks": [
            "standalone-model-identity", "heterogeneous-backbone-summary",
            "model-level-branch-coverage", "output-readout-coverage",
        ],
        "findings": ["The compact fixture exposes its input, model block, and output boundary."],
    }
    return data


def add_source_coverage(data, scope="complete-hierarchy"):
    data["project"]["require_source_coverage"] = True
    data["source_coverage"] = {
        "scope": scope,
        "canonical_source_ids": ["code"],
        "paths": [{
            "id": "model-forward",
            "evidence": "code",
            "source": "model.py:10-20",
            "regions": ["model"],
            "operations": [{
                "id": "model.b",
                "label": "Call B",
                "status": "visible-node",
                "node": "b",
                "source": "model.py:15",
            }],
        }],
        "reconciliation": {
            "status": "pass",
            "method": "independent-source-reread",
            "reviewed_path_ids": ["model-forward"],
            "architecture_changed": False,
            "findings": ["Second source-first pass found no omitted material operations."],
        },
    }
    return data


def projection_sample():
    data = sample()
    data["project"].update({
        "semantic_view": "model-algorithm",
        "require_view_projection_contracts": True,
    })
    data["view_projection_contract"] = {
        "status": "pass",
        "method": "canonical-ir-projection-review",
        "views": {
            "model-algorithm": {
                "kind": "algorithm-master",
                "purpose": "Reader-facing mathematical architecture.",
            },
            "backend": {
                "kind": "backend-runtime",
                "purpose": "Deployment-selected implementation details.",
            },
        },
        "checks": [
            "canonical-entity-disposition",
            "algorithm-backend-separation",
            "model-semantics-retained",
            "runtime-variant-placement",
        ],
        "findings": ["The model and backend implementation are separated."],
    }
    data["regions"]["model"].update({
        "semantic_layer": "model-algorithm", "views": ["model-algorithm"],
    })
    data["nodes"]["a"].update({
        "semantic_layer": "shared-interface", "views": ["model-algorithm"],
    })
    data["nodes"]["b"].update({
        "semantic_layer": "model-algorithm", "views": ["model-algorithm"],
    })
    data["edges"]["a_b"].update({
        "semantic_layer": "model-algorithm", "views": ["model-algorithm"],
    })
    data["regions"]["backend"] = {
        "label": "Backend", "parent": None, "direction": "column",
        "flow_direction": "bottom-to-top", "level": 3,
        "granularity": "module-summary", "operator_sequences": [{"id": "main", "nodes": ["c", "d"]}],
        "semantic_layer": "backend-implementation", "views": ["backend"],
    }
    data["nodes"]["c"] = {
        "label": "Backend input", "kind": "interface", "region": "backend", "evidence": ["code"],
        "semantic_layer": "shared-interface", "views": ["backend"],
    }
    data["nodes"]["d"] = {
        "label": "DCP combine", "kind": "module", "region": "backend", "evidence": ["code"],
        "semantic_layer": "backend-implementation", "views": ["backend"],
    }
    data["edges"]["c_d"] = {
        "source": "c", "target": "d", "kind": "tensor", "label": "partial output",
        "semantic_layer": "backend-implementation", "views": ["backend"],
    }
    return data


def strict_operator_sample():
    data = add_source_coverage(sample())
    data["project"]["require_logical_operator_contracts"] = True
    data["shape_symbols"] = {"B": "batch size", "S": "sequence length", "D": "hidden dimension"}
    data["regions"]["model"].update({
        "level": 2,
        "granularity": "operator-detail",
        "operator_standard": "logical-tensor-ops",
    })
    data["nodes"]["b"]["kind"] = "operator"
    data["nodes"]["b"]["label"] = "Feature projection"
    data["nodes"]["b"]["parameter_shapes"] = ["W_proj: [D,D]"]
    data["nodes"]["b"]["operator_contract"] = {
        "classification": "atomic-operator", "op_type": "linear",
        "semantic_role": "feature-projection", "source_symbols": ["self.proj"],
        "shape_rule": "transform",
        "shape_equation": "[B,S,D] -> [B,S,D]",
    }
    data["nodes"]["out"] = {
        "label": "Output", "kind": "interface", "region": "model", "evidence": ["code"], "order": 2,
    }
    data["edges"]["a_b"].pop("label")
    data["edges"]["a_b"]["tensor"] = {
        "name": "x", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"],
    }
    data["edges"]["b_out"] = {
        "source": "b", "target": "out", "kind": "tensor",
        "tensor": {"name": "y", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
    }
    data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "b", "out"]}]
    data["operator_naming_review"] = {
        "status": "pass", "method": "reader-and-source-review",
        "reviewed_region_ids": ["model"],
        "checks": ["reader-facing-labels", "source-symbol-traceability", "sibling-consistency"],
        "findings": ["Labels use reader-facing operator terminology."],
    }
    data["execution_fusions"] = []
    data["operator_display_contract"] = {
        "status": "pass", "method": "reader-shape-parameter-review",
        "reviewed_region_ids": ["model"],
        "activation_shape_placement": "tensor-edges",
        "parameter_shape_placement": "external-annotations-or-structured-ir",
        "source_symbol_placement": "structured-ir-or-secondary-line",
        "checks": [
            "operator-names", "activation-shapes-on-edges",
            "parameter-shapes-outside-blocks", "source-symbols-outside-primary-label",
        ],
        "findings": ["Operator names and shape roles are separated."],
    }
    return data


def packed_operator_sample(with_reshape=False):
    data = strict_operator_sample()
    del data["nodes"]["out"]
    data["nodes"]["b"]["label"] = "Packed QKV projection"
    data["nodes"]["b"]["operator_contract"] = {
        "classification": "packed-parameterized-op",
        "op_type": "linear",
        "semantic_role": "query-key-projection",
        "source_symbols": ["self.qk_proj"],
        "shape_rule": "transform",
        "shape_equation": "[B,S,D] -> [B,S,2D]",
        "packed_outputs": [
            {"name": "q", "edge": "split_q", "consumer": "q_out", "shape": "[B,S,D]"},
            {"name": "k", "edge": "split_k", "consumer": "k_out", "shape": "[B,S,D]"},
        ],
    }
    data["nodes"].update({
        "split": {
            "label": "Split Q/K", "kind": "operator", "region": "model", "evidence": ["code"], "order": 3,
            "operator_contract": {
                "classification": "view-transform", "op_type": "split",
                "semantic_role": "query-key-split", "source_symbols": ["packed.unbind"],
                "shape_rule": "multi-output",
                "shape_equation": "[B,S,2D] -> q[B,S,D] + k[B,S,D]",
            },
        },
        "q_out": {"label": "Q output", "kind": "interface", "region": "model", "evidence": ["code"], "order": 4},
        "k_out": {"label": "K output", "kind": "interface", "region": "model", "evidence": ["code"], "order": 5},
    })
    del data["edges"]["b_out"]
    predecessor = "b"
    path = ["b"]
    if with_reshape:
        data["nodes"]["reshape"] = {
            "label": "Reshape packed heads", "kind": "operator", "region": "model", "evidence": ["code"], "order": 2,
            "operator_contract": {
                "classification": "view-transform", "op_type": "reshape",
                "semantic_role": "packed-head-layout", "source_symbols": ["packed.view"],
                "shape_rule": "transform",
                "shape_equation": "[B,S,2D] -> [B,S,2,D]",
            },
        }
        data["edges"]["b_reshape"] = {
            "source": "b", "target": "reshape", "kind": "tensor",
            "tensor": {"name": "packed", "shape": "[B,S,2D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        predecessor = "reshape"
        path.append("reshape")
    data["edges"][f"{predecessor}_split"] = {
        "source": predecessor, "target": "split", "kind": "tensor",
        "tensor": {
            "name": "packed_heads", "shape": "[B,S,2,D]" if with_reshape else "[B,S,2D]",
            "status": "code-confirmed", "evidence": ["code"],
        },
    }
    data["edges"].update({
        "split_q": {
            "source": "split", "target": "q_out", "kind": "tensor",
            "tensor": {"name": "q", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        },
        "split_k": {
            "source": "split", "target": "k_out", "kind": "tensor",
            "tensor": {"name": "k", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        },
    })
    path.append("split")
    data["nodes"]["b"]["operator_contract"]["decomposition_path"] = path
    shared_prefix = ["a", "b"] + (["reshape"] if with_reshape else []) + ["split"]
    data["regions"]["model"]["operator_sequences"] = [
        {"id": "q_lane", "nodes": shared_prefix + ["q_out"]},
        {"id": "k_lane", "nodes": shared_prefix + ["k_out"]},
    ]
    return data


def expansion_sample():
    data = sample()
    data["regions"] = {
        "parent": {
            "label": "Parent", "parent": None, "direction": "column", "level": 1,
            "flow_direction": "bottom-to-top", "granularity": "module-summary", "order": 0,
        },
        "detail": {
            "label": "Detail", "parent": None, "direction": "column",
            "flow_direction": "bottom-to-top", "level": 2,
            "granularity": "operator-detail", "order": 1,
            "operator_sequences": [{"id": "main", "nodes": ["input", "output"]}],
        },
    }
    data["nodes"] = {
        "parent": {"label": "Parent definition", "kind": "module", "region": "parent", "evidence": ["code"]},
        "input": {"label": "Input", "kind": "interface", "region": "detail", "evidence": ["cfg"], "order": 0},
        "output": {"label": "Output", "kind": "operator", "region": "detail", "evidence": ["code"], "order": 1},
    }
    data["edges"] = {
        "expand_detail": {"source": "parent", "target": "input", "kind": "expand", "label": "expand Detail"},
        "compute": {"source": "input", "target": "output", "kind": "tensor", "label": "x"},
    }
    data["cross_level_interface_contracts"] = {
        "expand_detail": {
            "parent_shape": "[D]", "child_shape": "[D]", "mapping": "identity",
            "status": "code-confirmed", "evidence": ["code"],
        }
    }
    return data


class CompilerPipelineTest(unittest.TestCase):
    def test_level0_overview_contract_is_mandatory_and_visible(self):
        data = sample()
        del data["overview_contract"]
        errors = validate(data, Path("."))
        self.assertTrue(any("overview_contract is required" in error for error in errors))

        data = sample()
        data["overview_contract"]["signature_components"][0]["display_text"] = "Hidden feature"
        errors = validate(data, Path("."))
        self.assertTrue(any("display_text is not visible" in error for error in errors))

    def test_level1_template_sequences_must_be_summarized_at_level0(self):
        data = sample()
        data["regions"]["templates"] = {
            "label": "Layer Templates", "parent": None, "direction": "column",
            "flow_direction": "bottom-to-top", "level": 1,
            "granularity": "module-summary",
            "operator_sequences": [{"id": "variant_a", "nodes": ["template_in", "template_out"]}],
        }
        data["nodes"].update({
            "template_in": {
                "label": "Template input", "kind": "interface", "region": "templates",
                "evidence": ["code"],
            },
            "template_out": {
                "label": "Template output", "kind": "module", "region": "templates",
                "evidence": ["code"],
            },
        })
        data["edges"]["template_path"] = {
            "source": "template_in", "target": "template_out", "kind": "tensor", "label": "x",
        }
        errors = validate(data, Path("."))
        self.assertTrue(any("template_coverage_contract is required" in error for error in errors))

        data["nodes"]["b"]["label"] = "B\nVariant A"
        data["template_coverage_contract"] = {
            "status": "pass", "method": "template-family-review",
            "regions": {
                "templates": [{
                    "sequence_id": "variant_a", "summary": "Variant A",
                    "level0_nodes": ["b"], "evidence": ["code"],
                }]
            },
            "checks": [
                "distinct-template-families", "complete-template-paths", "level0-summary-mapping",
            ],
            "findings": ["The representative Level 1 template is named in Level 0."],
        }
        self.assertEqual(validate(data, Path(".")), [])

    def test_cross_level_shape_mapping_must_be_visible(self):
        data = expansion_sample()
        contract = data["cross_level_interface_contracts"]["expand_detail"]
        contract["child_shape"] = "[N,D]"
        errors = validate(data, Path("."))
        self.assertTrue(any("changes shape but declares identity" in error for error in errors))

        contract.update({"mapping": "N=B*S", "display_node": "input", "display_text": "N=B*S"})
        errors = validate(data, Path("."))
        self.assertTrue(any("shape mapping must be visible" in error for error in errors))
        data["nodes"]["input"]["label"] = "Input\nN=B*S"
        self.assertEqual(validate(data, Path(".")), [])

    def test_operator_display_contract_rejects_inline_shapes_and_opaque_custom_ops(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["label"] = "Feature projection [B,S,D->D]"
        errors = validate(data, Path("."))
        self.assertTrue(any("label contains an activation or parameter shape" in error for error in errors))

        data = strict_operator_sample()
        del data["operator_display_contract"]
        errors = validate(data, Path("."))
        self.assertTrue(any("operator_display_contract is required" in error for error in errors))

        data = strict_operator_sample()
        contract = data["nodes"]["b"]["operator_contract"]
        contract.update({
            "op_type": "custom", "shape_rule": "custom",
            "definition": "Model-specific feature transform",
            "shape_equation": "[B,S,D] -> [B,S,D]",
        })
        errors = validate(data, Path("."))
        self.assertTrue(any("requires a concrete formula" in error for error in errors))
        self.assertTrue(any("requires atomicity_reason" in error for error in errors))
        contract.update({
            "formula": "y = f(x)",
            "atomicity_reason": "The selected report defines f as one mathematical primitive.",
        })
        self.assertEqual(validate(data, Path(".")), [])
        self.assertIn(
            "custom-definition: Model-specific feature transform :: formula=y = f(x)",
            render(data),
        )

    def test_valid_ir_layout_and_compile(self):
        data = sample()
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        self.assertEqual(layout["architecture_sha256"], "digest")
        self.assertEqual(set(layout["nodes"]), {"a", "b"})
        tree = compile_diagram(data, layout)
        xml = ET.tostring(tree.getroot(), encoding="unicode")
        self.assertIn('id="node:a"', xml)
        self.assertIn('source="node:a"', xml)
        self.assertIn('exitX=0.5;', xml)
        self.assertIn('exitY=0.0;', xml)
        ET.fromstring(xml)
        manifest = build_manifest(data)
        self.assertEqual(manifest["defaults"]["expected_edges"]["edge:a_b"]["source"], "node:a")
        self.assertTrue(manifest["defaults"]["require_overview_contract"])
        self.assertEqual(manifest["defaults"]["overview_contract"], data["overview_contract"])
        self.assertEqual(manifest["defaults"]["granularity_contracts"]["region:model"]["level"], 0)
        self.assertEqual(manifest["defaults"]["region_content_contracts"]["region:model"], ["node:a", "node:b"])
        self.assertTrue(manifest["defaults"]["require_vertical_flow_contracts"])
        self.assertEqual(manifest["defaults"]["maximum_vertical_flow_lateral_gap_ratio"], 4.0)
        self.assertTrue(manifest["defaults"]["require_compact_execution_geometry"])
        slacks = manifest["defaults"]["maximum_region_content_slack"]
        self.assertEqual(set(slacks), {"left", "right", "top", "bottom"})
        self.assertGreater(slacks["top"], slacks["right"])

    def test_elk_layout_backend_emits_schema_v3_and_compiles(self):
        data = sample()
        layout = plan(data, "digest", layout_engine="elk")
        self.assertEqual(layout["schema_version"], 3)
        self.assertEqual(
            {key: value for key, value in layout["layout_engine"].items() if key != "route_preflight"},
            {
                "name": "compound-elk-layered",
                "elkjs_version": "0.12.0",
                "elk_region_ids": ["model"],
                "macro_engine": "elk-layered",
                "elk_edge_ids": ["a_b"],
                "native_routed_edge_ids": [],
                "acceptance": "pending",
            },
        )
        self.assertEqual(layout["edges"]["a_b"]["waypoints"], [])
        self.assertEqual(layout["edges"]["a_b"]["source_port"]["side"], "north")
        self.assertEqual(layout["edges"]["a_b"]["target_port"]["side"], "south")
        xml = ET.tostring(compile_diagram(data, layout).getroot(), encoding="unicode")
        self.assertIn('id="node:a"', xml)
        manifest = build_manifest(data, layout)
        self.assertEqual(manifest["defaults"]["layout_engine"], layout["layout_engine"])
        self.assertEqual(manifest["defaults"]["expected_ports"]["edge:a_b"]["exitSide"], "north")
        self.assertGreater(manifest["defaults"]["maximum_parallel_lane_gap"], 0)
        self.assertGreater(manifest["defaults"]["minimum_node_gutter"], 0)
        self.assertEqual(manifest["defaults"]["maximum_straight_hierarchy_arrow_aspect_ratio"], 6.0)
        self.assertEqual(
            manifest["defaults"]["vertical_flow_contracts"]["region:model"]["sequences"][0]["nodes"],
            ["node:a", "node:b"],
        )
        contract = render(data)
        self.assertIn("OWNERSHIP TREE", contract)
        self.assertIn("[a] interface :: A", contract)

    def test_project_typography_is_compiled_into_drawio_styles(self):
        data = sample()
        data["project"]["typography"] = {
            "ordinary_node_font": 27,
            "edge_label_font": 20,
            "annotation_font": 19,
            "region_title_font": 33,
            "hierarchy_label_font": 21,
        }
        layout = plan(data, "digest")
        xml = ET.tostring(compile_diagram(data, layout).getroot(), encoding="unicode")
        self.assertRegex(xml, r'id="node:a"[^>]+fontSize=27;')
        self.assertRegex(xml, r'id="edge:a_b"[^>]+fontSize=20;')
        self.assertRegex(xml, r'id="region:model"[^>]+fontSize=33;')

    def test_compiler_rejects_out_of_range_port_position(self):
        data = sample()
        layout = plan(data, "digest")
        layout["edges"]["a_b"]["source_port"] = {"side": "north", "position": 1.1}
        with self.assertRaisesRegex(ValueError, r"within \[0,1\]"):
            compile_diagram(data, layout)

    def test_compiler_serializes_edge_label_position(self):
        data = sample()
        layout = plan(data, "digest")
        layout["edges"]["a_b"]["label_position"] = {"x": 0.4, "y": -24}
        xml = ET.tostring(compile_diagram(data, layout).getroot(), encoding="unicode")
        self.assertRegex(xml, r'id="edge:a_b"[^>]*>\s*<mxGeometry[^>]+x="0.4"[^>]+y="-24.0"')

        manifest = build_manifest(data, layout)
        self.assertEqual(
            manifest["defaults"]["expected_edge_label_positions"]["edge:a_b"],
            {"x": 0.4, "y": -24.0},
        )
        self.assertEqual(
            set(manifest["defaults"]["expected_ports"]["edge:a_b"]),
            {"exitX", "exitY", "entryX", "entryY", "exitSide", "entrySide"},
        )

    def test_compiler_serializes_and_registers_line_jump(self):
        data = sample()
        data["edges"]["parallel"] = {
            "source": "a", "target": "b", "kind": "tensor", "label": "parallel"
        }
        layout = plan(data, "digest")
        layout["edges"]["parallel"]["line_jump"] = {
            "style": "arc",
            "size": 12,
            "crossings": {"a_b": "The focused layout proves this isolated crossing is unavoidable."},
        }
        tree = compile_diagram(data, layout)
        model = decode_diagram(tree.getroot().find("diagram"))
        cells = list(model.iter("mxCell"))
        ids = [cell.get("id") for cell in cells]
        self.assertLess(ids.index("edge:a_b"), ids.index("edge:parallel"))
        jumper = next(cell for cell in cells if cell.get("id") == "edge:parallel")
        self.assertIn("jumpStyle=arc;", jumper.get("style", ""))
        self.assertIn("jumpSize=12;", jumper.get("style", ""))
        manifest = build_manifest(data, layout)
        self.assertEqual(
            manifest["defaults"]["line_jump_crossings"]["edge:a_b|edge:parallel"]["jumper"],
            "edge:parallel",
        )
        self.assertEqual(
            manifest["defaults"]["rendered_svg_audit"]["line_jump_crossings"],
            manifest["defaults"]["line_jump_crossings"],
        )

    def test_compiler_rejects_malformed_or_cyclic_line_jumps(self):
        data = sample()
        data["edges"]["parallel"] = {
            "source": "a", "target": "b", "kind": "tensor", "label": "parallel"
        }
        for contract in (
            {"style": "gap", "size": 12, "crossings": {"a_b": "reason"}},
            {"style": "arc", "size": 2, "crossings": {"a_b": "reason"}},
            {"style": "arc", "size": 12, "crossings": {"missing": "reason"}},
            {"style": "arc", "size": 12, "crossings": {"a_b": ""}},
        ):
            with self.subTest(contract=contract):
                layout = plan(data, "digest")
                layout["edges"]["parallel"]["line_jump"] = contract
                with self.assertRaises(ValueError):
                    compile_diagram(data, layout)
        layout = plan(data, "digest")
        layout["edges"]["parallel"]["line_jump"] = {
            "style": "arc", "size": 12, "crossings": {"a_b": "reason"},
        }
        layout["edges"]["a_b"]["line_jump"] = {
            "style": "arc", "size": 12, "crossings": {"parallel": "reverse reason"},
        }
        with self.assertRaisesRegex(ValueError, "declared more than once|cycle"):
            compile_diagram(data, layout)

    def test_compiler_rejects_malformed_or_detached_label_positions(self):
        for value in ([], {"x": 0}, {"x": 1.1, "y": 0}, {"x": 0, "y": 161}, {"x": "nan", "y": 0}):
            with self.subTest(value=value):
                data = sample()
                layout = plan(data, "digest")
                layout["edges"]["a_b"]["label_position"] = value
                with self.assertRaisesRegex(ValueError, "label_position"):
                    compile_diagram(data, layout)

    def test_static_audit_detects_port_and_label_xml_drift(self):
        data = sample()
        layout = plan(data, "digest")
        layout["edges"]["a_b"]["label_position"] = {"x": 0.4, "y": -24}
        tree = compile_diagram(data, layout)
        model = decode_diagram(tree.getroot().find("diagram"))
        manifest = build_manifest(data, layout)
        edge = next(cell for cell in model.iter("mxCell") if cell.get("id") == "edge:a_b")
        edge.set("style", edge.get("style", "").replace("exitX=0.5", "exitX=0.6"))
        edge.find("mxGeometry").set("x", "0.5")
        manifest["defaults"]["expected_ports"]["edge:a_b"]["exitSide"] = "south"
        audit = PageAudit(data["project"]["title"], model, manifest["defaults"])
        audit.prepare()
        audit.check_ports_and_expected_edges()
        audit.check_edge_label_positions()
        self.assertTrue(any("port differs from layout contract" in error for error in audit.errors))
        self.assertTrue(any("side disagrees with its coordinates" in error for error in audit.errors))
        self.assertTrue(any("label position differs from layout contract" in error for error in audit.errors))

    def test_compiler_uses_canonical_palette_and_complete_legend(self):
        data = sample()
        data["nodes"]["b"]["visual_class"] = "tensor-op"
        data["nodes"]["b"]["visual_class_reason"] = "This summary node is exactly one matrix operation."
        data["nodes"]["b"]["visual_modifiers"] = ["tp-partition"]
        data["nodes"]["b"]["visual_modifier_reason"] = "The cited implementation shards this weight across tensor parallel ranks."
        layout = plan(data, "digest")
        tree = compile_diagram(data, layout)
        diagram = tree.getroot().find("diagram")
        model = decode_diagram(diagram)
        by_id = {cell.get("id"): cell for cell in model.iter("mxCell")}
        self.assertIn("fillColor=#DAE8FC", by_id["node:b"].get("style", ""))
        self.assertIn("fontColor=#FF0000", by_id["node:b"].get("style", ""))
        self.assertEqual(
            {cell_id for cell_id in by_id if cell_id.startswith("legend:")},
            {
                "legend:title", "legend:conditional", "legend:tensor-op", "legend:vector-op",
                "legend:io-op", "legend:tp-partition", "legend:communication",
                "legend:composite-op", "legend:residual-op", "legend:cache",
            },
        )
        manifest = build_manifest(data)
        result = PageAudit(data["project"]["title"], model, manifest["defaults"]).run()
        self.assertEqual(result["errors"], [])

        root = model.find("root")
        missing_entry = by_id["legend:cache"]
        root.remove(missing_entry)
        result = PageAudit(data["project"]["title"], model, manifest["defaults"]).run()
        self.assertTrue(any("Legend cells do not match" in error for error in result["errors"]))
        root.append(missing_entry)

        by_id["node:b"].set(
            "style", by_id["node:b"].get("style", "").replace("fillColor=#DAE8FC", "fillColor=#FFFFFF")
        )
        result = PageAudit(data["project"]["title"], model, manifest["defaults"]).run()
        self.assertTrue(any("semantic style mismatch" in error for error in result["errors"]))

        duplicate = ET.SubElement(model.find("root"), "mxCell", {
            "id": "extra-legend", "value": "Legend / 图例", "vertex": "1", "parent": "1",
            "style": "text;strokeColor=none;fillColor=none;",
        })
        ET.SubElement(duplicate, "mxGeometry", {"x": "0", "y": "0", "width": "100", "height": "20", "as": "geometry"})
        result = PageAudit(data["project"]["title"], model, manifest["defaults"]).run()
        self.assertTrue(any("exactly one canonical semantic Legend" in error for error in result["errors"]))

    def test_visual_class_rejects_semantic_color_mismatch(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["visual_class"] = "vector-op"
        errors = validate(data, Path("."))
        self.assertTrue(any("conflicts with its kind/op_type" in error for error in errors))

    def test_visual_overrides_require_source_backed_rationale(self):
        data = sample()
        data["nodes"]["b"]["visual_class"] = "tensor-op"
        data["nodes"]["b"]["visual_modifiers"] = ["tp-partition"]
        errors = validate(data, Path("."))
        self.assertTrue(any("requires visual_class_reason" in error for error in errors))
        self.assertTrue(any("requires visual_modifier_reason" in error for error in errors))

    def test_missing_evidence_is_rejected(self):
        data = sample()
        data["nodes"]["b"]["evidence"] = ["missing"]
        errors = validate(data, Path("."))
        self.assertTrue(any("unknown evidence" in error for error in errors))

    def test_region_cycle_is_rejected(self):
        data = sample()
        data["regions"]["model"]["parent"] = "model"
        errors = validate(data, Path("."))
        self.assertTrue(any("ownership cycle" in error for error in errors))

    def test_detail_region_requires_complete_operator_sequence(self):
        data = sample()
        data["regions"]["model"].update({
            "level": 2, "granularity": "operator-detail", "direction": "column",
            "flow_direction": "bottom-to-top",
        })
        data["regions"]["model"].pop("operator_sequences")
        errors = validate(data, Path("."))
        self.assertTrue(any("requires non-empty operator_sequences" in error for error in errors))
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "b"]}]
        self.assertEqual(validate(data, Path(".")), [])

    def test_strict_logical_operator_contract_is_structural(self):
        data = strict_operator_sample()
        self.assertEqual(validate(data, Path(".")), [])
        del data["nodes"]["b"]["operator_contract"]
        errors = validate(data, Path("."))
        self.assertTrue(any("requires operator_contract" in error for error in errors))

    def test_reader_facing_operator_contract_rejects_raw_or_opaque_labels(self):
        for label, expected in (
            ("f_b Projection", "contains a source identifier"),
            ("KDA Core", "primary label is opaque"),
        ):
            data = strict_operator_sample()
            data["nodes"]["b"]["label"] = label
            errors = validate(data, Path("."))
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_reader_facing_label_must_match_operator_type(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["label"] = "RMSNorm"
        errors = validate(data, Path("."))
        self.assertTrue(any("does not identify op_type 'linear'" in error for error in errors))

    def test_reader_facing_contract_requires_role_symbols_and_review(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["operator_contract"].pop("semantic_role")
        data["nodes"]["b"]["operator_contract"].pop("source_symbols")
        data.pop("operator_naming_review")
        errors = validate(data, Path("."))
        self.assertTrue(any("semantic_role" in error for error in errors))
        self.assertTrue(any("source_symbols" in error for error in errors))
        self.assertTrue(any("operator_naming_review is required" in error for error in errors))

    def test_common_qkv_reader_labels_are_valid(self):
        data = packed_operator_sample()
        self.assertEqual(validate(data, Path(".")), [])

    def test_strict_detail_tensor_edge_requires_shape_status_and_evidence(self):
        data = strict_operator_sample()
        del data["edges"]["a_b"]["tensor"]
        errors = validate(data, Path("."))
        self.assertTrue(any("structured tensor contract" in error for error in errors))
        data = strict_operator_sample()
        data["edges"]["a_b"]["tensor"] = {
            "name": "x", "shape": "[B,S,D]", "status": "unknown",
        }
        errors = validate(data, Path("."))
        self.assertTrue(any("reason is required for unknown" in error for error in errors))

    def test_packed_projection_requires_explicit_split(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["operator_contract"] = {
            "classification": "packed-parameterized-op", "op_type": "linear",
            "semantic_role": "query-key-value-projection", "source_symbols": ["self.qkv_proj"],
            "shape_rule": "transform",
            "shape_equation": "[B,S,D] -> [B,S,3D]",
            "packed_outputs": [
                {"name": "q", "edge": "split_q", "consumer": "out", "shape": "[B,S,D]"},
                {"name": "k", "edge": "split_k", "consumer": "out_k", "shape": "[B,S,D]"},
            ],
            "decomposition_path": ["b", "split"],
        }
        errors = validate(data, Path("."))
        self.assertTrue(any("decomposition path has invalid member" in error for error in errors))

        data["nodes"]["split"] = {
            "label": "Split Q/K/V", "kind": "operator", "region": "model", "evidence": ["code"],
            "operator_contract": {"classification": "view-transform", "op_type": "split", "semantic_role": "query-key-value-split", "source_symbols": ["packed.split"], "shape_rule": "multi-output", "shape_equation": "[B,S,3D] -> q[B,S,D] + k[B,S,D]"}, "order": 2,
        }
        data["nodes"]["out"] = {
            "label": "Output", "kind": "interface", "region": "model", "evidence": ["code"], "order": 3,
        }
        tensor = {"name": "packed_qkv", "shape": "[B,S,3D]", "status": "code-confirmed", "evidence": ["code"]}
        data["edges"]["b_split"] = {"source": "b", "target": "split", "kind": "tensor", "tensor": tensor}
        data["edges"]["split_q"] = {
            "source": "split", "target": "out", "kind": "tensor",
            "tensor": {"name": "q", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        data["nodes"]["out_k"] = {
            "label": "K output", "kind": "interface", "region": "model", "evidence": ["code"], "order": 4,
        }
        data["edges"]["split_k"] = {
            "source": "split", "target": "out_k", "kind": "tensor",
            "tensor": {"name": "k", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        del data["edges"]["b_out"]
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "b", "split", "out"]}]
        data["regions"]["model"]["operator_sequences"].append({"id": "k", "nodes": ["split", "out_k"]})
        self.assertEqual(validate(data, Path(".")), [])

    def test_atomic_operator_rejects_composite_but_allows_same_family_aliases(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["label"] = "RMSNorm + Linear + SiLU"
        errors = validate(data, Path("."))
        self.assertTrue(any("combine multiple operations" in error for error in errors))

        data["nodes"]["b"]["label"] = "Linear projection"
        self.assertEqual(validate(data, Path(".")), [])

    def test_shape_contract_rejects_undefined_symbols(self):
        data = strict_operator_sample()
        data["edges"]["a_b"]["tensor"]["shape"] = "[BANANA]"
        errors = validate(data, Path("."))
        self.assertTrue(any("undefined shape symbols" in error and "BANANA" in error for error in errors))

    def test_operator_type_rejects_incompatible_shape_rule(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["operator_contract"]["shape_rule"] = "preserve"
        data["nodes"]["b"]["operator_contract"].pop("shape_equation")
        errors = validate(data, Path("."))
        self.assertTrue(any("op_type linear requires shape_rule" in error for error in errors))

    def test_detail_edge_cannot_hide_multiple_tensors_in_one_name(self):
        data = strict_operator_sample()
        data["edges"]["b_out"]["tensor"]["name"] = "K,V"
        errors = validate(data, Path("."))
        self.assertTrue(any("must identify one tensor" in error for error in errors))

    def test_packed_outputs_must_bind_real_branches(self):
        data = packed_operator_sample()
        del data["edges"]["split_k"]
        errors = validate(data, Path("."))
        self.assertTrue(any("invalid or duplicate output edge 'split_k'" in error for error in errors))

    def test_packed_decomposition_allows_views_but_not_arithmetic(self):
        data = packed_operator_sample(with_reshape=True)
        data["nodes"]["split"]["operator_contract"]["shape_equation"] = (
            "[B,S,2,D] -> q[B,S,D] + k[B,S,D]"
        )
        self.assertEqual(validate(data, Path(".")), [])

        data["nodes"]["reshape"]["label"] = "Extra projection"
        data["nodes"]["reshape"]["operator_contract"].update({
            "classification": "atomic-operator", "op_type": "linear",
        })
        errors = validate(data, Path("."))
        self.assertTrue(any("must be a non-splitting view transform" in error for error in errors))

    def test_transform_equation_must_close_direct_edge_shapes(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["operator_contract"]["shape_equation"] = "[B,S,X] -> [B,S,D]"
        errors = validate(data, Path("."))
        self.assertTrue(any("omits input edge shapes" in error for error in errors))

        data = strict_operator_sample()
        data["nodes"]["b"]["operator_contract"]["shape_equation"] = "[B,S,D] -> [B,S,X]"
        errors = validate(data, Path("."))
        self.assertTrue(any("omits output edge shapes" in error for error in errors))

    def test_optional_preserve_equation_cannot_contradict_incident_shapes(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["label"] = "Scale Query"
        contract = data["nodes"]["b"]["operator_contract"]
        contract.update(op_type="scale", shape_rule="preserve", shape_equation="[S,D] -> [S,D]")
        errors = validate(data, Path("."))
        self.assertTrue(any("omits input edge shapes" in error for error in errors))
        contract["shape_equation"] = "[B,S,D] -> [B,S,D]"
        self.assertEqual(validate(data, Path(".")), [])
        del contract["shape_equation"]
        self.assertEqual(validate(data, Path(".")), [])

    def test_repetition_boundary_must_bind_an_owned_node_and_count(self):
        data = strict_operator_sample()
        data["repetitions"] = [{"region": "model", "target": "b", "count": "32 layers"}]
        self.assertEqual(validate(data, Path(".")), [])
        self.assertIn("[region:model/node:b] x32 layers", render(data))

        data["repetitions"].append({"region": "missing", "target": "b", "count": 0})
        errors = validate(data, Path("."))
        self.assertTrue(any("unknown region" in error for error in errors))
        self.assertTrue(any("directly owned" in error for error in errors))
        self.assertTrue(any("positive integer" in error for error in errors))

    def test_parameter_shapes_are_validated_and_rendered_in_ascii(self):
        data = strict_operator_sample()
        data["nodes"]["b"]["parameter_shapes"] = ["W_proj: [D,D]"]
        self.assertEqual(validate(data, Path(".")), [])
        self.assertIn("parameter-shape: W_proj: [D,D]", render(data))

        data["nodes"]["b"]["parameter_shapes"] = ["W_proj: [UNKNOWN,D]"]
        errors = validate(data, Path("."))
        self.assertTrue(any("parameter_shapes uses undefined" in error for error in errors))

        data = strict_operator_sample()
        del data["nodes"]["b"]["parameter_shapes"]
        errors = validate(data, Path("."))
        self.assertTrue(any("requires structured parameter_shapes" in error for error in errors))
        data["nodes"]["b"]["parameterless_reason"] = "The cited functional projection has no learned weight."
        self.assertEqual(validate(data, Path(".")), [])

    def test_multi_input_equation_must_name_every_direct_input_shape(self):
        data = strict_operator_sample()
        data["shape_symbols"]["M"] = "memory length"
        data["nodes"]["memory"] = {
            "label": "Memory", "kind": "interface", "region": "model",
            "evidence": ["code"], "order": 0,
        }
        data["edges"]["memory_b"] = {
            "source": "memory", "target": "b", "kind": "tensor",
            "tensor": {"name": "memory", "shape": "[B,M,D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        data["nodes"]["b"]["operator_contract"].update({
            "op_type": "matmul", "shape_rule": "multi-input",
            "shape_equation": "[B,S,D] -> [B,S,D]",
        })
        data["regions"]["model"]["operator_sequences"].append({"id": "memory", "nodes": ["memory", "b", "out"]})
        errors = validate(data, Path("."))
        self.assertTrue(any("omits input edge shapes" in error and "[B,M,D]" in error for error in errors))

    def test_multi_output_equation_must_name_every_direct_output_shape(self):
        data = packed_operator_sample()
        data["nodes"]["split"]["operator_contract"]["shape_equation"] = (
            "[B,S,2D] -> q[B,S,D]"
        )
        errors = validate(data, Path("."))
        self.assertTrue(any("omits repeated output edge shapes" in error for error in errors))

    def test_expanded_elsewhere_rejects_self_target_without_expand_edge(self):
        data = strict_operator_sample()
        data["nodes"]["b"].update({
            "kind": "module",
            "operator_contract": {
                "classification": "expanded-elsewhere", "detail_region": "model", "reason": "folded",
            },
        })
        errors = validate(data, Path("."))
        self.assertTrue(any("cannot expand into its own region" in error for error in errors))
        self.assertTrue(any("has no expansion into region" in error for error in errors))

    def test_execution_fusion_rejects_interface_member(self):
        data = strict_operator_sample()
        data["execution_fusions"] = [{
            "id": "bad_fusion", "label": "Invalid fusion", "operators": ["b", "out"],
            "evidence": ["code"], "source": "model.py:15", "owner_region": "model",
            "topology": "connected", "visualization": "boundary",
        }]
        errors = validate(data, Path("."))
        self.assertTrue(any("member 'out' is not a logical operator" in error for error in errors))

    def test_complete_hierarchy_rejects_unknown_material_shapes(self):
        data = add_source_coverage(strict_operator_sample())
        for edge in data["edges"].values():
            edge["tensor"].update({"shape": "?", "status": "unknown", "reason": "not established"})
            edge["tensor"].pop("evidence", None)
        errors = validate(data, Path("."))
        self.assertTrue(any("cannot leave material tensor shapes unknown" in error for error in errors))

    def test_source_fusion_cannot_hide_operator_detail_members(self):
        data = add_source_coverage(strict_operator_sample())
        operation = data["source_coverage"]["paths"][0]["operations"][0]
        operation.update({"status": "source-confirmed-fusion", "reason": "one fused call"})
        errors = validate(data, Path("."))
        self.assertTrue(any("cannot collapse a fused call" in error for error in errors))

        data["execution_fusions"] = [{
            "id": "fused_pair", "label": "Fused linear and activation", "operators": ["b", "b2"],
            "evidence": ["code"], "source": "model.py:15", "owner_region": "model",
            "topology": "connected", "visualization": "boundary",
        }]
        data["nodes"]["b2"] = {
            "label": "SiLU activation", "kind": "operator", "region": "model", "evidence": ["code"],
            "operator_contract": {"classification": "atomic-operator", "op_type": "silu", "semantic_role": "feature-activation", "source_symbols": ["torch.nn.functional.silu"], "shape_rule": "preserve"}, "order": 2,
        }
        data["nodes"]["out"] = {
            "label": "Output", "kind": "interface", "region": "model", "evidence": ["code"], "order": 3,
        }
        data["edges"]["b_b2"] = {
            "source": "b", "target": "b2", "kind": "tensor",
            "tensor": {"name": "hidden", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        data["edges"]["b2_out"] = {
            "source": "b2", "target": "out", "kind": "tensor",
            "tensor": {"name": "output", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "b", "b2", "out"]}]
        operation.pop("node")
        operation.pop("reason")
        operation.update({"status": "fused-execution-group", "fusion": "fused_pair"})
        self.assertEqual(validate(data, Path(".")), [])

    def test_fusion_boundary_compiles_and_is_registered_as_nonsemantic_geometry(self):
        data = strict_operator_sample()
        data["nodes"]["b2"] = {
            "label": "SiLU", "kind": "operator", "region": "model", "evidence": ["code"], "order": 2,
            "operator_contract": {"classification": "atomic-operator", "op_type": "silu", "semantic_role": "feature-activation", "source_symbols": ["torch.nn.functional.silu"], "shape_rule": "preserve"},
        }
        del data["edges"]["b_out"]
        data["edges"].update({
            "b_b2": {
                "source": "b", "target": "b2", "kind": "tensor",
                "tensor": {"name": "hidden", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
            },
            "b2_out": {
                "source": "b2", "target": "out", "kind": "tensor",
                "tensor": {"name": "output", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
            },
        })
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "b", "b2", "out"]}]
        data["execution_fusions"] = [{
            "id": "linear_activation", "label": "Fused linear + activation", "operators": ["b", "b2"],
            "evidence": ["code"], "source": "model.py:15", "owner_region": "model",
            "topology": "connected", "visualization": "boundary",
        }]
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        xml = ET.tostring(compile_diagram(data, layout).getroot(), encoding="unicode")
        self.assertIn('id="fusion:linear_activation"', xml)
        self.assertIn("dashed=1", xml)
        manifest = build_manifest(data, layout)
        defaults = manifest["defaults"]
        self.assertIn("fusion:linear_activation", defaults["required_cells"])
        self.assertIn("fusion:linear_activation", defaults["semantic_coverage_exclusions"])
        self.assertIn("fusion:linear_activation", defaults["ignore_geometry"])
        self.assertIn("fusion:linear_activation", defaults["rendered_svg_audit"]["ignored_cells"])
        boundary = fusion_boundary_box(data["execution_fusions"][0], layout)
        obstructed = json.loads(json.dumps(layout))
        obstructed["nodes"]["out"].update({
            "x": boundary["x"] + 8, "y": boundary["y"] + 8,
        })
        self.assertTrue(any(
            "intersects non-member node out" in error
            for error in validate_fusion_boundary_geometry(data, obstructed)
        ))

    def test_cross_region_fusion_uses_reciprocal_implementation_node(self):
        data = strict_operator_sample()
        data["regions"].update({
            "logical_tail": {
                "label": "Logical tail", "parent": None, "direction": "column",
                "flow_direction": "bottom-to-top", "level": 2, "granularity": "operator-detail",
                "operator_standard": "logical-tensor-ops",
                "operator_sequences": [{"id": "tail", "nodes": ["tail", "tail_out"]}],
            },
            "runtime": {
                "label": "Runtime", "parent": None, "direction": "column",
                "flow_direction": "bottom-to-top", "level": 3, "granularity": "implementation-detail",
                "operator_sequences": [{"id": "kernel", "nodes": ["kernel_in", "kernel", "kernel_out"]}],
            },
        })
        data["nodes"].update({
            "tail": {
                "label": "SiLU", "kind": "operator", "region": "logical_tail", "evidence": ["code"],
                "operator_contract": {"classification": "atomic-operator", "op_type": "silu", "semantic_role": "feature-activation", "source_symbols": ["torch.nn.functional.silu"], "shape_rule": "preserve"},
            },
            "tail_out": {"label": "Tail output", "kind": "interface", "region": "logical_tail", "evidence": ["code"]},
            "kernel_in": {"label": "Kernel input", "kind": "interface", "region": "runtime", "evidence": ["code"]},
            "kernel": {
                "label": "Fused kernel", "kind": "operator", "region": "runtime", "evidence": ["code"],
                "implementation_contract": {"classification": "fused-operation", "implements": ["cross_region"]},
            },
            "kernel_out": {"label": "Kernel output", "kind": "interface", "region": "runtime", "evidence": ["code"]},
        })
        del data["nodes"]["out"]
        del data["edges"]["b_out"]
        tensor = {"name": "hidden", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]}
        data["edges"].update({
            "b_tail": {"source": "b", "target": "tail", "kind": "tensor", "tensor": dict(tensor)},
            "tail_out_edge": {"source": "tail", "target": "tail_out", "kind": "tensor", "tensor": dict(tensor)},
            "kernel_in_edge": {"source": "kernel_in", "target": "kernel", "kind": "tensor", "tensor": dict(tensor)},
            "kernel_out_edge": {"source": "kernel", "target": "kernel_out", "kind": "tensor", "tensor": dict(tensor)},
        })
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "b"]}]
        data["operator_naming_review"]["reviewed_region_ids"] = ["model", "logical_tail"]
        data["operator_display_contract"]["reviewed_region_ids"] = ["model", "logical_tail"]
        data["execution_fusions"] = [{
            "id": "cross_region", "label": "Cross-region fused execution", "operators": ["b", "tail"],
            "evidence": ["code"], "source": "model.py:15", "owner_region": "runtime",
            "topology": "connected", "visualization": "implementation-node", "implementation_node": "kernel",
        }]
        data["runtime_variant_contracts"] = {
            "runtime": {
                "status": "not-applicable",
                "reason": "The fixture models one fused execution path.",
                "shared_state_nodes": [],
                "evidence": ["code"],
                "findings": ["Source review found no materially different runtime branch."],
            }
        }
        self.assertEqual(validate(data, Path(".")), [])

        data["nodes"]["kernel"]["implementation_contract"]["implements"] = []
        errors = validate(data, Path("."))
        self.assertTrue(any("reciprocally implement" in error for error in errors))

    def test_detail_sequence_rejects_missing_edge_and_coverage(self):
        data = sample()
        data["regions"]["model"].update({
            "level": 2,
            "granularity": "operator-detail",
            "direction": "column",
            "flow_direction": "bottom-to-top",
            "operator_sequences": [{"id": "main", "nodes": ["a", "b"]}],
        })
        data["nodes"]["c"] = {"label": "RMSNorm", "kind": "operator", "region": "model", "evidence": ["code"], "order": 2}
        errors = validate(data, Path("."))
        self.assertTrue(any("coverage is incomplete" in error for error in errors))
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "c", "b"]}]
        errors = validate(data, Path("."))
        self.assertTrue(any("has no tensor edge a -> c" in error for error in errors))

    def test_operator_sequence_uses_only_tensor_relations_and_renders_all_parallel_tensors(self):
        data = strict_operator_sample()
        data["edges"]["a_uses_projection"] = {
            "source": "a", "target": "b", "kind": "uses", "label": "implementation reuse",
        }
        self.assertEqual(validate(data, Path(".")), [])
        ascii_contract = render(data)
        sequence_section = ascii_contract.split("operator_sequences:", 1)[1].split("additional_relations:", 1)[0]
        self.assertIn("a_b:", sequence_section)
        self.assertNotIn("a_uses_projection", sequence_section)

        data["edges"]["b_out_parallel"] = {
            "source": "b", "target": "out", "kind": "tensor",
            "tensor": {
                "name": "auxiliary_output", "shape": "[B,S,D]",
                "status": "code-confirmed", "evidence": ["code"],
            },
        }
        ascii_contract = render(data)
        sequence_section = ascii_contract.split("operator_sequences:", 1)[1].split("additional_relations:", 1)[0]
        self.assertIn("b_out:", sequence_section)
        self.assertIn("b_out_parallel:", sequence_section)

        del data["edges"]["a_b"]
        errors = validate(data, Path("."))
        self.assertTrue(any("has no tensor edge a -> b" in error for error in errors))

    def test_vertical_detail_contract_rejects_horizontal_or_unspecified_flow(self):
        data = sample()
        data["project"]["require_vertical_detail_flow"] = False
        data["regions"]["model"].update({
            "level": 2,
            "granularity": "operator-detail",
            "direction": "row",
            "operator_sequences": [{"id": "main", "nodes": ["a", "b"]}],
        })
        data["regions"]["model"].pop("flow_direction")
        errors = validate(data, Path("."))
        self.assertTrue(any("direction must be column" in error for error in errors))
        self.assertTrue(any("flow_direction must be bottom-to-top" in error for error in errors))

    def test_module_summary_also_requires_vertical_complete_sequences(self):
        data = sample()
        data["regions"]["model"]["direction"] = "row"
        data["regions"]["model"].pop("operator_sequences")
        errors = validate(data, Path("."))
        self.assertTrue(any("direction must be column" in error for error in errors))
        self.assertTrue(any("requires non-empty operator_sequences" in error for error in errors))

    def test_parallel_module_summary_sequences_become_adjacent_vertical_lanes(self):
        data = sample()
        data["nodes"].update({
            "left": {"label": "Left", "kind": "module", "region": "model", "evidence": ["code"]},
            "right": {"label": "Right", "kind": "module", "region": "model", "evidence": ["code"]},
            "out": {"label": "Out", "kind": "interface", "region": "model", "evidence": ["code"]},
        })
        data["edges"] = {
            "a_left": {"source": "a", "target": "left", "kind": "tensor", "label": "x"},
            "a_right": {"source": "a", "target": "right", "kind": "tensor", "label": "x"},
            "left_out": {"source": "left", "target": "out", "kind": "tensor", "label": "y"},
            "right_out": {"source": "right", "target": "out", "kind": "tensor", "label": "y"},
            "out_b": {"source": "out", "target": "b", "kind": "tensor", "label": "z"},
        }
        data["regions"]["model"]["operator_sequences"] = [
            {"id": "left_lane", "nodes": ["a", "left", "out", "b"]},
            {"id": "right_lane", "nodes": ["a", "right", "out", "b"]},
        ]
        data["overview_contract"]["spine_nodes"] = ["a", "left", "out", "b"]
        data["overview_contract"]["facets"]["backbone"] = ["left", "right"]
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        self.assertNotEqual(layout["nodes"]["left"]["x"], layout["nodes"]["right"]["x"])
        for lane in data["regions"]["model"]["operator_sequences"]:
            for source, target in zip(lane["nodes"], lane["nodes"][1:]):
                self.assertGreater(layout["nodes"][source]["y"], layout["nodes"][target]["y"])

    def test_child_direction_keeps_large_sibling_regions_macro_flexible(self):
        data = sample()
        del data["overview_contract"]
        data["regions"] = {
            "parent": {
                "label": "Parent", "parent": None, "direction": "column",
                "flow_direction": "bottom-to-top", "child_direction": "row",
                "level": 1, "granularity": "module-summary",
            },
            "left": {
                "label": "Left detail", "parent": "parent", "direction": "column",
                "flow_direction": "bottom-to-top", "level": 2,
                "granularity": "module-summary", "order": 0,
            },
            "right": {
                "label": "Right detail", "parent": "parent", "direction": "column",
                "flow_direction": "bottom-to-top", "level": 2,
                "granularity": "module-summary", "order": 1,
            },
        }
        data["nodes"] = {
            "left_node": {"label": "Left", "kind": "module", "region": "left", "evidence": ["code"]},
            "right_node": {"label": "Right", "kind": "module", "region": "right", "evidence": ["code"]},
        }
        data["edges"] = {}
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        self.assertEqual(layout["regions"]["left"]["y"], layout["regions"]["right"]["y"])
        self.assertLess(layout["regions"]["left"]["x"], layout["regions"]["right"]["x"])

    def test_detail_planner_and_geometry_gate_enforce_bottom_to_top(self):
        data = sample()
        data["regions"]["model"].update({
            "level": 2,
            "granularity": "operator-detail",
            "direction": "column",
            "flow_direction": "bottom-to-top",
            "operator_sequences": [{"id": "main", "nodes": ["a", "b"]}],
        })
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        self.assertGreater(layout["nodes"]["a"]["y"], layout["nodes"]["b"]["y"])
        self.assertEqual(validate_detail_flow_geometry(data, layout), [])
        layout["nodes"]["b"]["y"] = layout["nodes"]["a"]["y"] + 100
        errors = validate_detail_flow_geometry(data, layout)
        self.assertTrue(any("does not rise bottom-to-top" in error for error in errors))

    def test_expand_compiles_as_registered_large_arrow_vertex(self):
        data = expansion_sample()
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        self.assertEqual(set(layout["hierarchy_arrows"]), {"expand_detail"})
        self.assertEqual(set(layout["edges"]), {"compute"})
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])

        tree = compile_diagram(data, layout)
        root = tree.getroot()
        arrow = root.find(".//mxCell[@id='expand:expand_detail']")
        self.assertIsNotNone(arrow)
        self.assertEqual(arrow.get("vertex"), "1")
        self.assertIn("shape=singleArrow", arrow.get("style", ""))
        self.assertIsNone(root.find(".//mxCell[@id='edge:expand_detail']"))

        manifest = build_manifest(data, layout)
        anchor = manifest["defaults"]["hierarchy_anchors"]["expand:expand_detail"]
        self.assertEqual(anchor["parent"], "node:parent")
        self.assertEqual(anchor["attachment_mode"], "owner-region-boundary")
        self.assertEqual(anchor["attachment"], "region:parent")
        self.assertEqual(anchor["anchor_label"], "Parent definition")
        self.assertEqual(anchor["child"], "region:detail")
        self.assertIn(anchor["direction"], {"up", "down", "left", "right"})
        self.assertNotIn("edge:expand_detail", manifest["defaults"]["expected_edges"])
        self.assertIn("expand:expand_detail", manifest["defaults"]["required_cells"])

        page = decode_diagram(root.find("diagram"))
        audit = PageAudit("compiled", page, manifest["defaults"])
        audit.prepare()
        audit.check_hierarchy()
        self.assertEqual(audit.errors, [])

    def test_expand_can_use_owned_region_boundary_without_losing_semantic_parent(self):
        data = expansion_sample()
        data["edges"]["expand_detail"].update({
            "label": "Parent definition -> Detail",
            "visual_attachment": {
                "mode": "owner-region-boundary", "region": "parent",
                "side": "south", "anchor_label": "Parent definition",
            },
        })
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        arrow = layout["hierarchy_arrows"]["expand_detail"]
        self.assertEqual(arrow["parent"], "parent")
        self.assertEqual(arrow["attachment_mode"], "owner-region-boundary")
        self.assertEqual(arrow["attachment_id"], "parent")
        self.assertEqual(arrow["direction"], "south")
        self.assertEqual(arrow["y"], layout["regions"]["parent"]["y"] + layout["regions"]["parent"]["h"])
        self.assertNotEqual(arrow["y"], layout["nodes"]["parent"]["y"] + layout["nodes"]["parent"]["h"])
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])
        topology = render(data)
        self.assertIn("[parent] --expand:Parent definition -> Detail--> [input]", topology)
        self.assertNotIn("visual_attachment", topology)

        root = compile_diagram(data, layout).getroot()
        manifest = build_manifest(data, layout)
        anchor = manifest["defaults"]["hierarchy_anchors"]["expand:expand_detail"]
        self.assertEqual(anchor["parent"], "node:parent")
        self.assertEqual(anchor["attachment"], "region:parent")
        self.assertEqual(anchor["anchor_label"], "Parent definition")
        page = decode_diagram(root.find("diagram"))
        audit = PageAudit("compiled", page, manifest["defaults"])
        audit.prepare()
        audit.check_hierarchy()
        self.assertEqual(audit.errors, [])

    def test_explicit_parent_node_attachment_is_not_auto_promoted(self):
        data = expansion_sample()
        data["nodes"]["sibling"] = {
            "label": "Sibling module", "kind": "module", "region": "parent",
            "evidence": ["code"], "order": 1,
        }
        data["regions"]["parent"]["operator_sequences"] = [
            {"id": "main", "nodes": ["parent", "sibling"]},
        ]
        data["edges"]["parent_sibling"] = {
            "source": "parent", "target": "sibling", "kind": "tensor", "label": "x",
        }
        data["edges"]["expand_detail"]["visual_attachment"] = {
            "mode": "parent-node", "side": "east",
        }
        layout = plan(data, "digest")
        arrow = layout["hierarchy_arrows"]["expand_detail"]
        self.assertEqual(arrow["attachment_mode"], "parent-node")
        self.assertEqual(arrow["attachment_id"], "parent")
        # Side is a preference; compact content may not fit a wide arrow there.
        # Explicit semantic attachment must survive trying another legal side.
        self.assertIn(arrow["direction"], {"north", "south", "east", "west"})
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])

    def test_auto_layout_distributes_competing_expansions_around_owner(self):
        data = expansion_sample()
        data["edges"]["expand_detail"].update({
            "label": "Parent definition -> Detail 1",
            "visual_attachment": {
                "mode": "owner-region-boundary", "region": "parent",
                "side": "north", "anchor_label": "Parent definition",
            },
        })
        for index in range(2, 5):
            region_id = f"detail_{index}"
            input_id = f"input_{index}"
            output_id = f"output_{index}"
            data["regions"][region_id] = {
                "label": f"Detail {index}", "parent": None, "direction": "column",
                "flow_direction": "bottom-to-top", "level": 2,
                "granularity": "operator-detail", "order": index,
                "operator_sequences": [{"id": "main", "nodes": [input_id, output_id]}],
            }
            data["nodes"][input_id] = {
                "label": f"Input {index}", "kind": "interface", "region": region_id,
                "evidence": ["cfg"], "order": 0,
            }
            data["nodes"][output_id] = {
                "label": f"Output {index}", "kind": "operator", "region": region_id,
                "evidence": ["code"], "order": 1,
            }
            data["edges"][f"compute_{index}"] = {
                "source": input_id, "target": output_id, "kind": "tensor", "label": "x",
            }
            data["edges"][f"expand_{index}"] = {
                "source": "parent", "target": input_id, "kind": "expand",
                "label": f"Parent definition -> Detail {index}",
                "visual_attachment": {
                    "mode": "owner-region-boundary", "region": "parent",
                    "side": "north", "anchor_label": "Parent definition",
                },
            }
            data["cross_level_interface_contracts"][f"expand_{index}"] = {
                "parent_shape": "[D]", "child_shape": "[D]", "mapping": "identity",
                "status": "code-confirmed", "evidence": ["code"],
            }
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        top_regions = ["parent", "detail", "detail_2", "detail_3", "detail_4"]
        for left_index, left_id in enumerate(top_regions):
            left = layout["regions"][left_id]
            for right_id in top_regions[left_index + 1:]:
                right = layout["regions"][right_id]
                overlap = not (
                    left["x"] + left["w"] <= right["x"]
                    or right["x"] + right["w"] <= left["x"]
                    or left["y"] + left["h"] <= right["y"]
                    or right["y"] + right["h"] <= left["y"]
                )
                self.assertFalse(overlap, f"{left_id} overlaps {right_id}")
        directions = {arrow["direction"] for arrow in layout["hierarchy_arrows"].values()}
        self.assertGreater(len(directions), 1)
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])

    def test_fifth_large_child_uses_audited_target_signpost(self):
        data = expansion_sample()
        data["edges"]["expand_detail"]["label"] = "Parent definition -> Detail 1"
        for index in range(2, 6):
            region_id = f"detail_{index}"
            lane = []
            data["regions"][region_id] = {
                "label": f"Large Detail {index}", "parent": None, "direction": "column",
                "flow_direction": "bottom-to-top", "level": 2,
                "granularity": "operator-detail", "order": index,
            }
            for step in range(12):
                node_id = f"detail_{index}_step_{step}"
                lane.append(node_id)
                data["nodes"][node_id] = {
                    "label": f"Large detail {index} operation {step}",
                    "kind": "interface" if step == 0 else "operator",
                    "region": region_id, "evidence": ["code"], "order": step,
                }
                if step:
                    data["edges"][f"detail_{index}_edge_{step}"] = {
                        "source": lane[-2], "target": node_id, "kind": "tensor", "label": "x",
                    }
            data["regions"][region_id]["operator_sequences"] = [{"id": "main", "nodes": lane}]
            data["edges"][f"expand_{index}"] = {
                "source": "parent", "target": lane[0], "kind": "expand",
                "label": f"Parent definition -> Detail {index}",
            }
            data["cross_level_interface_contracts"][f"expand_{index}"] = {
                "parent_shape": "[D]", "child_shape": "[D]", "mapping": "identity",
                "status": "code-confirmed", "evidence": ["code"],
            }

        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        signposts = {
            edge_id: arrow for edge_id, arrow in layout["hierarchy_arrows"].items()
            if arrow["attachment_mode"] == "target-signpost"
        }
        self.assertTrue(signposts)
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])
        tree = compile_diagram(data, layout)
        manifest = build_manifest(data, layout)
        for edge_id, arrow in signposts.items():
            anchor = manifest["defaults"]["hierarchy_anchors"][f"expand:{edge_id}"]
            self.assertEqual(anchor["attachment_mode"], "target-signpost")
            self.assertIn(anchor["anchor_label"], arrow["display_label"])
        page = decode_diagram(tree.getroot().find("diagram"))
        audit = PageAudit("compiled", page, manifest["defaults"])
        audit.prepare()
        audit.check_hierarchy()
        self.assertEqual(audit.errors, [])

        edge_id, arrow = next(iter(signposts.items()))
        child = layout["regions"][arrow["child_region"]]
        detached = json.loads(json.dumps(layout))
        detached["hierarchy_arrows"][edge_id]["x"] = child["x"] + child["w"] + 20
        errors = validate_hierarchy_arrow_geometry(data, detached)
        self.assertTrue(any("misses the child corridor" in error for error in errors))

        reversed_layout = json.loads(json.dumps(layout))
        reversed_layout["hierarchy_arrows"][edge_id]["direction"] = {
            "north": "south", "south": "north", "east": "west", "west": "east",
        }[arrow["direction"]]
        errors = validate_hierarchy_arrow_geometry(data, reversed_layout)
        self.assertTrue(any("points away from its child" in error for error in errors))

        obstructed = json.loads(json.dumps(layout))
        parent = layout["regions"]["parent"]
        obstructed["hierarchy_arrows"][edge_id].update({
            "x": parent["x"], "y": parent["y"],
        })
        errors = validate_hierarchy_arrow_geometry(data, obstructed)
        self.assertTrue(any("target signpost overlaps region parent" in error for error in errors))

    def test_region_boundary_expand_rejects_false_owner_and_ambiguous_label(self):
        data = expansion_sample()
        data["edges"]["expand_detail"].update({
            "label": "expand Detail",
            "visual_attachment": {
                "mode": "owner-region-boundary", "region": "detail",
                "anchor_label": "Parent definition",
            },
        })
        errors = validate(data, Path("."))
        self.assertTrue(any("does not own source node" in error for error in errors))
        self.assertTrue(any("must name anchor_label" in error for error in errors))

    def test_region_boundary_expand_rejects_invalid_or_unavailable_side(self):
        data = expansion_sample()
        data["edges"]["expand_detail"].update({
            "label": "Parent definition -> Detail",
            "visual_attachment": {
                "mode": "owner-region-boundary", "region": "parent",
                "side": "diagonal", "anchor_label": "Parent definition",
            },
        })
        errors = validate(data, Path("."))
        self.assertTrue(any("visual_attachment.side is invalid" in error for error in errors))

        data["edges"]["expand_detail"]["visual_attachment"]["side"] = "east"
        self.assertEqual(validate(data, Path(".")), [])
        layout = plan(data, "digest")
        self.assertIn(layout["hierarchy_arrows"]["expand_detail"]["direction"], {"north", "south", "east", "west"})
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])

    def test_expand_layout_and_manifest_fail_closed_when_arrow_is_missing(self):
        data = expansion_sample()
        layout = plan(data, "digest")
        layout["hierarchy_arrows"] = {}
        with self.assertRaisesRegex(ValueError, "hierarchy-arrow IDs"):
            compile_diagram(data, layout)
        with self.assertRaisesRegex(ValueError, "layout is required"):
            build_manifest(data)
        with self.assertRaisesRegex(ValueError, "hierarchy-arrow IDs"):
            build_manifest(data, layout)

    def test_provisional_layout_may_defer_arrows_but_cannot_compile(self):
        data = expansion_sample()
        layout = plan(data, "digest", defer_hierarchy_arrows=True)
        self.assertEqual(layout["hierarchy_arrows"], {})
        self.assertEqual(set(layout["edges"]), {"compute"})
        with self.assertRaisesRegex(ValueError, "hierarchy-arrow IDs"):
            compile_diagram(data, layout)
        layout["hierarchy_arrows"] = plan_hierarchy_arrows(data, layout)
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])

    def test_expand_requires_hierarchy_view_child_region_and_label(self):
        data = expansion_sample()
        data["project"]["output_view"] = "end-to-end-dataflow"
        data["edges"]["expand_detail"]["label"] = ""
        data["nodes"]["input"]["region"] = "parent"
        errors = validate(data, Path("."))
        self.assertTrue(any("end-to-end-dataflow" in error for error in errors))
        self.assertTrue(any("different child region" in error for error in errors))
        self.assertTrue(any("non-empty label" in error for error in errors))

    def test_hierarchy_arrow_planner_supports_all_straight_directions(self):
        data = expansion_sample()
        cases = {
            "north": ({"x": 200, "y": 300, "w": 100, "h": 60}, {"x": 160, "y": 0, "w": 180, "h": 200}),
            "south": ({"x": 200, "y": 0, "w": 100, "h": 60}, {"x": 160, "y": 160, "w": 180, "h": 200}),
            "west": ({"x": 300, "y": 200, "w": 100, "h": 60}, {"x": 0, "y": 160, "w": 200, "h": 180}),
            "east": ({"x": 0, "y": 200, "w": 100, "h": 60}, {"x": 200, "y": 160, "w": 200, "h": 180}),
        }
        for expected, (parent, child) in cases.items():
            with self.subTest(expected=expected):
                layout = {
                    "nodes": {"parent": parent, "input": {"x": child["x"] + 20, "y": child["y"] + 80, "w": 80, "h": 50}},
                    "regions": {"parent": parent, "detail": child},
                }
                arrow = plan_hierarchy_arrows(data, layout)["expand_detail"]
                self.assertEqual(arrow["direction"], expected)

    def test_hierarchy_arrow_planner_rejects_diagonal_or_tiny_corridor(self):
        data = expansion_sample()
        layout = {
            "nodes": {"parent": {"x": 0, "y": 0, "w": 60, "h": 60}, "input": {"x": 220, "y": 220, "w": 50, "h": 50}},
            "regions": {"parent": {"x": 0, "y": 0, "w": 100, "h": 100}, "detail": {"x": 200, "y": 200, "w": 120, "h": 120}},
        }
        with self.assertRaisesRegex(ValueError, "no straight hierarchy-arrow corridor"):
            plan_hierarchy_arrows(data, layout)

    def test_hierarchy_arrows_are_recomputed_after_final_layout_movement(self):
        data = expansion_sample()
        layout = plan(data, "digest")
        stale = json.loads(json.dumps(layout))
        layout["regions"]["parent"]["y"] += 20
        self.assertTrue(validate_hierarchy_arrow_geometry(data, layout))
        layout["hierarchy_arrows"] = plan_hierarchy_arrows(data, layout)
        self.assertEqual(validate_hierarchy_arrow_geometry(data, layout), [])
        self.assertNotEqual(layout["hierarchy_arrows"], stale["hierarchy_arrows"])

    def test_hierarchy_corridor_override_is_persistent_and_validated(self):
        data = expansion_sample()
        automatic = plan(data, "digest")
        arrow = automatic["hierarchy_arrows"]["expand_detail"]
        state = {
            "layout_overrides": {
                "regions": {}, "nodes": {}, "edges": {},
                "hierarchy_arrows": {"expand_detail": {"x": arrow["x"] + 8}},
            },
        }
        self.assertEqual(validate_state(state, data), [])
        refined = plan(data, "digest", state=state)
        self.assertEqual(refined["hierarchy_arrows"]["expand_detail"]["x"], arrow["x"] + 8)
        self.assertEqual(validate_hierarchy_arrow_geometry(data, refined), [])
        regenerated = json.loads(json.dumps(automatic))
        regenerated["hierarchy_arrows"] = plan_hierarchy_arrows(data, regenerated)
        apply_hierarchy_arrow_overrides(regenerated, state)
        self.assertEqual(regenerated["hierarchy_arrows"], refined["hierarchy_arrows"])

        state["layout_overrides"]["hierarchy_arrows"]["expand_detail"]["x"] = 10000
        invalid = plan(data, "digest", state=state)
        self.assertTrue(any("misses the attachment or child corridor" in error for error in validate_hierarchy_arrow_geometry(data, invalid)))

    def test_operator_detail_example_is_valid_and_renders_rmsnorm(self):
        example_path = Path(__file__).resolve().parents[1] / "assets" / "operator-detail-ir-example.json"
        data = json.loads(example_path.read_text(encoding="utf-8"))
        self.assertEqual(validate(data, example_path.parent), [])
        contract = render(data)
        self.assertIn(
            "[pre_norm] operator; operator=atomic-operator; op_type=rmsnorm; "
            "semantic_role=input-normalization; source_symbols=self.pre_norm; "
            "shape_rule=preserve :: RMSNorm",
            contract,
        )
        self.assertIn("<query_main>", contract)
        self.assertIn("<kv_cache_write>", contract)
        self.assertIn("STATE / CACHE LIFECYCLES", contract)
        self.assertIn("[kv_cache] [num_blocks,block_size,Hkv,Dh]", contract)
        self.assertIn("SOURCE OPERATION COVERAGE", contract)
        self.assertIn("[mixer.pre_norm] RMSNorm :: visible-node -> node:pre_norm", contract)
        self.assertIn("layout_axis: column", contract)
        self.assertIn("flow_direction: bottom-to-top", contract)
        layout = plan(data, "example-digest")
        root = compile_diagram(data, layout).getroot()
        cache_style = root.find(".//mxCell[@id='node:kv_cache']").get("style")
        update_style = root.find(".//mxCell[@id='node:cache_update']").get("style")
        legend_style = root.find(".//mxCell[@id='legend:cache']").get("style")
        self.assertIn("shape=parallelogram", cache_style)
        self.assertIn("shape=parallelogram", legend_style)
        self.assertNotIn("shape=parallelogram", update_style)
        manifest = build_manifest(data, layout)
        audit = PageAudit("example", root.find("diagram/mxGraphModel"), manifest["defaults"])
        audit.prepare()
        audit.check_semantic_styles()
        self.assertEqual(audit.errors, [])
        root.find(".//mxCell[@id='node:kv_cache']").set(
            "style", cache_style.replace("shape=parallelogram;", "rounded=1;")
        )
        drift = PageAudit("example", root.find("diagram/mxGraphModel"), manifest["defaults"])
        drift.prepare()
        drift.check_semantic_styles()
        self.assertTrue(any("semantic glyph mismatch" in error for error in drift.errors))

    def test_detail_runtime_and_state_contracts_are_fail_closed(self):
        regions = {
            "parent": {"level": 1, "granularity": "module-summary"},
            "detail": {
                "level": 3, "granularity": "implementation-detail",
                "operator_sequences": [
                    {"id": "prefill", "nodes": ["write", "read"]},
                    {"id": "decode", "nodes": ["read"]},
                ],
            },
        }
        nodes = {
            "parent": {"kind": "module", "region": "parent"},
            "write": {"kind": "operator", "region": "detail"},
            "cache": {"kind": "cache", "region": "detail"},
            "read": {"kind": "operator", "region": "detail"},
        }
        edges = {
            "expand": {"kind": "expand", "source": "parent", "target": "write"},
            "flow": {"kind": "tensor", "source": "write", "target": "read"},
            "cache_write": {"kind": "tensor", "source": "write", "target": "cache"},
            "cache_read": {"kind": "tensor", "source": "cache", "target": "read"},
        }
        evidence = {"code"}
        errors = validate_detail_runtime_state_contracts({}, regions, nodes, edges, evidence)
        self.assertTrue(any("detail_information_gain_contracts" in error for error in errors))
        self.assertTrue(any("runtime_variant_contracts" in error for error in errors))
        self.assertTrue(any("state_lifecycle_contracts" in error for error in errors))

        data = {
            "detail_information_gain_contracts": {
                "expand": {
                    "parent_region": "parent", "child_region": "detail",
                    "status": "pass", "method": "parent-child-delta-review",
                    "new_information": [{
                        "kind": "runtime-variant", "summary": "Separate prefill and decode paths",
                        "nodes": ["write", "read"], "evidence": ["code"],
                    }],
                    "findings": ["The child exposes runtime paths and persistent state."],
                }
            },
            "runtime_variant_contracts": {
                "detail": {
                    "status": "pass", "method": "source-branch-review",
                    "source_discriminators": ["is_prefill", "is_decode"],
                    "variants": [
                        {"id": "prefill", "sequence_ids": ["prefill"], "evidence": ["code"]},
                        {"id": "decode", "sequence_ids": ["decode"], "evidence": ["code"]},
                    ],
                    "shared_state_nodes": ["cache"], "evidence": ["code"],
                    "findings": ["The branches use different state access paths."],
                }
            },
            "state_lifecycle_contracts": {
                "cache": {
                    "status": "pass", "method": "state-lifecycle-review",
                    "storage_shape": "[blocks,tokens,D]", "layout": "paged",
                    "dtype": "bf16", "scope": "per layer", "lifetime": "request",
                    "writers": [{"operation": "write", "edge": "cache_write", "addressing": ["slot_mapping"]}],
                    "readers": [{"operation": "read", "edge": "cache_read", "addressing": ["block_table"]}],
                    "evidence": ["code"],
                }
            },
        }
        self.assertEqual(
            validate_detail_runtime_state_contracts(data, regions, nodes, edges, evidence), []
        )
        data["runtime_variant_contracts"]["detail"]["variants"][1]["sequence_ids"] = ["prefill"]
        errors = validate_detail_runtime_state_contracts(data, regions, nodes, edges, evidence)
        self.assertTrue(any("cover every region operator_sequence" in error for error in errors))
        data["runtime_variant_contracts"]["detail"]["variants"][1]["sequence_ids"] = ["decode"]
        regions["detail"]["operator_sequences"][0]["nodes"].insert(1, "cache")
        errors = validate_detail_runtime_state_contracts(data, regions, nodes, edges, evidence)
        self.assertTrue(any("side lane" in error for error in errors))

    def test_valid_complete_source_coverage(self):
        data = add_source_coverage(sample())
        self.assertEqual(validate(data, Path(".")), [])
        contract = render(data)
        self.assertIn("scope: complete-hierarchy", contract)
        self.assertIn("<model-forward> evidence=code", contract)

    def test_required_source_coverage_must_exist_and_be_non_empty(self):
        data = sample()
        data["project"]["require_source_coverage"] = True
        errors = validate(data, Path("."))
        self.assertTrue(any("source_coverage is missing" in error for error in errors))
        data["source_coverage"] = {
            "scope": "complete-hierarchy", "canonical_source_ids": ["code"], "paths": []
        }
        errors = validate(data, Path("."))
        self.assertTrue(any("paths must be a non-empty list" in error for error in errors))

    def test_source_coverage_rejects_unknown_evidence_node_and_region(self):
        data = add_source_coverage(sample())
        path = data["source_coverage"]["paths"][0]
        path["evidence"] = "missing"
        path["regions"] = ["missing-region"]
        path["operations"][0]["node"] = "missing-node"
        errors = validate(data, Path("."))
        self.assertTrue(any("unknown evidence" in error for error in errors))
        self.assertTrue(any("unknown region" in error for error in errors))
        self.assertTrue(any("unknown node" in error for error in errors))

    def test_complete_hierarchy_rejects_unresolved_and_out_of_scope(self):
        for status in ("unresolved", "out-of-scope"):
            data = add_source_coverage(sample())
            operation = data["source_coverage"]["paths"][0]["operations"][0]
            operation.pop("node")
            operation.update({"status": status, "reason": "Needs follow-up"})
            errors = validate(data, Path("."))
            self.assertTrue(any(f"cannot be {status}" in error for error in errors))

    def test_selected_paths_allows_explicit_out_of_scope_debt(self):
        data = add_source_coverage(sample(), scope="selected-paths")
        operation = data["source_coverage"]["paths"][0]["operations"][0]
        operation.pop("node")
        operation.update({"status": "out-of-scope", "reason": "Training-only branch"})
        self.assertEqual(validate(data, Path(".")), [])

    def test_fusion_requires_reason_and_matching_evidence(self):
        data = add_source_coverage(sample())
        operation = data["source_coverage"]["paths"][0]["operations"][0]
        operation["status"] = "source-confirmed-fusion"
        errors = validate(data, Path("."))
        self.assertTrue(any("reason is required" in error for error in errors))
        operation["reason"] = "One fused source call"
        data["nodes"]["b"]["evidence"] = ["cfg"]
        errors = validate(data, Path("."))
        self.assertTrue(any("without path evidence" in error for error in errors))

    def test_source_mapped_detail_node_must_be_in_operator_sequence(self):
        data = add_source_coverage(sample())
        data["regions"]["model"].update({
            "level": 2,
            "granularity": "operator-detail",
            "direction": "column",
            "flow_direction": "bottom-to-top",
            "operator_sequences": [{"id": "main", "nodes": ["a", "b"]}],
        })
        data["nodes"]["c"] = {
            "label": "C", "kind": "operator", "region": "model", "evidence": ["code"], "order": 2,
        }
        data["source_coverage"]["paths"][0]["operations"][0].update({
            "id": "model.c", "label": "Call C", "node": "c",
        })
        errors = validate(data, Path("."))
        self.assertTrue(any("absent from operator_sequences" in error for error in errors))

    def test_source_operation_can_expand_into_evidenced_detail_region(self):
        data = add_source_coverage(sample())
        data["regions"]["detail"] = {
            "label": "B detail", "parent": "model", "direction": "column",
            "flow_direction": "bottom-to-top", "level": 2,
            "granularity": "operator-detail", "operator_sequences": [{"id": "main", "nodes": ["c", "d"]}],
        }
        data["nodes"]["c"] = {
            "label": "C", "kind": "operator", "region": "detail", "evidence": ["code"], "order": 0,
        }
        data["nodes"]["d"] = {
            "label": "D", "kind": "operator", "region": "detail", "evidence": ["code"], "order": 1,
        }
        data["edges"]["c_d"] = {"source": "c", "target": "d", "kind": "tensor"}
        path = data["source_coverage"]["paths"][0]
        path["regions"].append("detail")
        path["operations"][0] = {
            "id": "model.b", "label": "Call B detail", "status": "expanded-in-region",
            "region": "detail", "source": "model.py:15",
        }
        self.assertEqual(validate(data, Path(".")), [])

        data["project"]["require_logical_operator_contracts"] = True
        errors = validate(data, Path("."))
        self.assertTrue(any("only an umbrella mapping" in error for error in errors))

    def test_strict_ir_without_source_coverage_is_rejected(self):
        data = strict_operator_sample()
        data["project"].pop("require_source_coverage")
        data.pop("source_coverage")
        errors = validate(data, Path("."))
        self.assertTrue(any("unmigrated IR cannot claim strict validity" in error for error in errors))

    def test_source_coverage_requires_independent_reconciliation(self):
        data = add_source_coverage(sample())
        data["source_coverage"].pop("reconciliation")
        errors = validate(data, Path("."))
        self.assertTrue(any("reconciliation is required" in error for error in errors))

    def test_operator_detail_cannot_expand_only_into_implementation_detail(self):
        data = strict_operator_sample()
        data["regions"]["runtime"] = {
            "label": "Runtime", "parent": "model", "direction": "column",
            "flow_direction": "bottom-to-top", "level": 3,
            "granularity": "implementation-detail",
            "operator_sequences": [{"id": "runtime", "nodes": ["rt_in", "rt_kernel"]}],
        }
        data["nodes"]["rt_in"] = {
            "label": "Runtime input", "kind": "interface", "region": "runtime",
            "evidence": ["code"], "order": 0,
        }
        data["nodes"]["rt_kernel"] = {
            "label": "Fused kernel", "kind": "operator", "region": "runtime",
            "evidence": ["code"], "order": 1,
            "implementation_contract": {"classification": "kernel"},
        }
        data["edges"]["rt_flow"] = {"source": "rt_in", "target": "rt_kernel", "kind": "tensor"}
        data["nodes"]["b"].update({
            "kind": "module",
            "operator_contract": {
                "classification": "expanded-elsewhere", "detail_region": "runtime",
                "reason": "Runtime kernel is shown elsewhere.",
            },
        })
        data["edges"]["expand_b"] = {"source": "b", "target": "rt_in", "kind": "expand"}
        errors = validate(data, Path("."))
        self.assertTrue(any("cannot delegate its logical expansion" in error for error in errors))

    def test_change_impact_propagates_and_respects_frozen(self):
        old = sample()
        new = json.loads(json.dumps(old))
        new["nodes"]["a"]["label"] = "A revised"
        result = analyze(old, new, {"region_policies": {"model": "frozen"}})
        self.assertEqual(result["mode"], "patch")
        self.assertEqual(result["affected_regions"], ["model"])
        self.assertTrue(result["blockers"])

    def test_invalid_stability_policy_and_override_are_rejected(self):
        data = sample()
        errors = validate_state({
            "region_policies": {"model": "absolutely-locked"},
            "layout_overrides": {"nodes": {"missing": {"x": 1}}, "edges": {}, "regions": {}},
        }, data)
        self.assertTrue(any("invalid stability policy" in error for error in errors))
        self.assertTrue(any("unknown node" in error for error in errors))

    def test_view_projection_contract_separates_algorithm_and_backend(self):
        data = projection_sample()
        self.assertEqual(validate(data, Path(".")), [])
        projected = project_active_view(data)
        self.assertEqual(set(projected["regions"]), {"model"})
        self.assertEqual(set(projected["nodes"]), {"a", "b"})
        self.assertEqual(set(projected["edges"]), {"a_b"})
        layout = plan(data, "canonical-digest")
        self.assertEqual(set(layout["regions"]), {"model"})
        self.assertEqual(set(layout["nodes"]), {"a", "b"})

    def test_view_projection_rejects_backend_leakage_into_algorithm_master(self):
        data = projection_sample()
        data["nodes"]["d"]["views"].append("model-algorithm")
        data["regions"]["backend"]["views"].append("model-algorithm")
        errors = validate(data, Path("."))
        self.assertTrue(any("leaks backend-implementation" in error for error in errors))

    def test_projection_never_invents_adjacency_across_hidden_operations(self):
        data = projection_sample()
        data["regions"]["model"]["operator_sequences"] = [{"id": "main", "nodes": ["a", "hidden", "b"]}]
        data["edges"] = {}
        projected = project_active_view(data)
        self.assertEqual([sequence["nodes"] for sequence in projected["regions"]["model"]["operator_sequences"]],
                         [["a"], ["b"]])
        self.assertEqual(data["regions"]["model"]["operator_sequences"][0]["nodes"], ["a", "hidden", "b"])
        data["edges"]["bypass"] = {"kind": "tensor", "source": "a", "target": "b", "views": ["model-algorithm"]}
        projected = project_active_view(data)
        self.assertEqual(projected["regions"]["model"]["operator_sequences"][0]["nodes"], ["a", "b"])

    def test_fusion_connectivity_can_cross_only_declared_junctions(self):
        from validate_architecture_ir import connected_member_subgraph
        edges = {"aj": {"source": "a", "target": "j", "kind": "tensor"},
                 "jb": {"source": "j", "target": "b", "kind": "tensor"}}
        self.assertFalse(connected_member_subgraph(edges, {"a", "b"}))
        self.assertTrue(connected_member_subgraph(edges, {"a", "b"}, {"j"}))
        edges["jb"]["kind"] = "uses"
        self.assertFalse(connected_member_subgraph(edges, {"a", "b"}, {"j"}))

    def test_view_projection_rejects_hidden_model_semantics(self):
        data = projection_sample()
        data["nodes"]["b"]["views"] = ["backend"]
        errors = validate(data, Path("."))
        self.assertTrue(any("absent from every algorithm-master" in error for error in errors))
        self.assertTrue(any("absent from owner region" in error for error in errors))

    def test_view_projection_requires_edge_endpoint_closure(self):
        data = projection_sample()
        data["edges"]["a_b"]["views"] = ["backend"]
        errors = validate(data, Path("."))
        self.assertTrue(any("lack both visible endpoints" in error for error in errors))

    def test_view_projection_rejects_backend_label_disguised_as_algorithm(self):
        data = projection_sample()
        data["nodes"]["b"]["label"] = "Paged cache kernel"
        errors = validate(data, Path("."))
        self.assertTrue(any("backend-specific label" in error for error in errors))

    def test_semantic_revision_cannot_reuse_old_geometry_or_ignore_preservation(self):
        old = sample()
        old["regions"]["side"] = {
            "label": "Side", "parent": None, "direction": "column",
            "flow_direction": "bottom-to-top", "level": 0,
            "granularity": "module-summary", "order": 1,
        }
        old["nodes"]["c"] = {"label": "C", "kind": "module", "region": "side", "evidence": ["code"]}
        previous = plan(old, "old")
        new = json.loads(json.dumps(old))
        new["nodes"]["a"]["label"] = "A much wider revised label"
        change_set = analyze(old, new, {"region_policies": {"model": "adaptive", "side": "preserve"}})
        state = {
            "change_set": change_set,
            "region_policies": {"model": "adaptive", "side": "preserve"},
            "layout_overrides": {"regions": {}, "nodes": {"a": {"y": 321.0}}, "edges": {}},
        }
        with self.assertRaisesRegex(ValueError, 'preserved/frozen'):
            plan(new, "new", previous, state)
        state['region_policies'] = {}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            plan(new, "new", previous, state)


if __name__ == "__main__":
    unittest.main()
