import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_edge_labels import visual_edge_label
from plan_layout_elk import elk_graph, problem_from_region, load_problem
from plan_layout import plan
from compile_drawio import compile_diagram
from compile_audit_manifest import build_manifest
from audit_drawio import PageAudit
from test_compiler_pipeline import strict_operator_sample


class VisualEdgeLabelTests(unittest.TestCase):
    def test_identifier_only_tensor_name_stays_in_ir_not_display(self):
        edge = {"tensor": {"name": "edge_001", "shape": "[N,H,Dh]"}}
        before = copy.deepcopy(edge)
        self.assertEqual(visual_edge_label(edge, edge_id="edge_001"), "[N,H,Dh]")
        self.assertEqual(edge, before)
        self.assertIn("edge_001", visual_edge_label(edge, edge_id="different_id"))

    def test_long_name_wrap_preserves_shape_and_characters(self):
        edge = {"tensor": {"name": "uninitialized_context_output", "shape": "[N,H,Dv]"}}
        before = copy.deepcopy(edge)
        text = visual_edge_label(edge)
        self.assertEqual(text, "uninitialized_context_\noutput\n[N,H,Dv]")
        self.assertEqual(edge, before)
        self.assertEqual(text.replace("\n", ""), "uninitialized_context_output[N,H,Dv]")

    def test_short_label_and_explicit_multiline_are_unchanged(self):
        self.assertEqual(visual_edge_label({"tensor": {"name": "q", "shape": "[N,H,Dh]"}}), "q [N,H,Dh]")
        self.assertEqual(visual_edge_label({"label": "first\\nsecond"}), "first\nsecond")

    def test_shape_is_never_split(self):
        shape = "[VeryLongSequenceAxis,VeryLongHeadAxis,VeryLongChannelAxis]"
        self.assertIn(shape, visual_edge_label({"tensor": {"name": "q", "shape": shape}}).splitlines())

    def test_compiler_and_elk_use_identical_visual_text(self):
        data = strict_operator_sample()
        data["edges"]["a_b"]["tensor"]["name"] = "uninitialized_context_output"
        before = copy.deepcopy(data)
        layout = plan(data, "fixture")
        tree = compile_diagram(data, layout)
        value = next(c.get("value") for c in tree.iter("mxCell") if c.get("id") == "edge:a_b")
        problem = problem_from_region(data, "model", {nid: (200, 60) for nid in data["nodes"]})
        self.assertEqual(value, problem["edges"]["a_b"]["label"]["text"])
        self.assertEqual(data, before)

    def test_ir_projection_does_not_invent_fixed_port_order(self):
        data = strict_operator_sample()
        problem = problem_from_region(data, "model", {nid: (200, 60) for nid in data["nodes"]})
        self.assertTrue(all(n["port_constraints"] == "FIXED_SIDE" for n in problem["nodes"].values()))
        graph = elk_graph(problem)
        self.assertTrue(all(n["layoutOptions"]["elk.portConstraints"] == "FIXED_SIDE" for n in graph["children"]))
        problem["nodes"]["a"].pop("port_constraints")
        graph = elk_graph(problem)
        self.assertEqual(next(n for n in graph["children"] if n["id"] == "a")["layoutOptions"]["elk.portConstraints"], "FIXED_ORDER")

    def test_generated_label_text_audit_accepts_wrap_but_rejects_shape_drift(self):
        data = strict_operator_sample()
        data["edges"]["a_b"]["tensor"]["name"] = "uninitialized_context_output"
        layout = plan(data, "fixture")
        tree = compile_diagram(data, layout)
        manifest = build_manifest(data, layout)
        model = tree.getroot().find("diagram/mxGraphModel")
        cell = next(c for c in tree.iter("mxCell") if c.get("id") == "edge:a_b")
        cell.set("value", cell.get("value").replace("\n", " "))
        audit = PageAudit("fixture", model, manifest["defaults"])
        audit.prepare()
        audit.check_required_and_text()
        self.assertFalse(audit.errors)
        cell.set("value", cell.get("value").replace("[B,S,D]", "[B,S,Wrong]"))
        audit = PageAudit("fixture", model, manifest["defaults"])
        audit.prepare()
        audit.check_required_and_text()
        self.assertTrue(any("edge label text differs" in error for error in audit.errors))


if __name__ == "__main__":
    unittest.main()
