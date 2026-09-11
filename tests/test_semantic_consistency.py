import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from semantic_consistency import RULESET, lint, validate_expectations
from ir_graph_builder import add_lane, add_tensor_edge
from review_fixture import reviewed_project
from audit_topology_review import validate_review
from topology_review_common import seal_review


class SemanticConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.architecture = Path(self.temp.name) / "architecture.json"
        (self.architecture.parent / "model.py").write_text(
            "q = q_proj(x)\nk = kv_proj(x)\ny = attention(q, k)\n")
        self.refs = [{"evidence_id": "code", "line_start": 1, "line_end": 3}]
        self.data = {
            "evidence": [{"id": "code", "path": "model.py"}],
            "regions": {"att": {"granularity": "operator-detail"}},
            "nodes": {n: {"region": "att", "kind": "interface"} for n in ("x", "q", "k", "y")},
            "edges": {},
        }
        for eid, a, b, shape in [("xq", "x", "q", "[B,5120]"), ("xk", "x", "k", "[B,5120]"),
                                  ("qy", "q", "y", "[B,1280]"), ("ky", "k", "y", "[B,512]")]:
            add_tensor_edge(self.data, eid, a, b, {"name": eid, "shape": shape, "status": "code-confirmed"})
        self.review = {"semantic_expectations": {
            "ruleset": RULESET,
            "regions": {"att": {
                "source_refs": self.refs, "reason": "Q and KV independently consume x before the attention join.",
                "incoming_dependencies": [["x", "q", "[B,5120]"], ["x", "k", "[B,5120]"],
                                          ["q", "y", "[B,1280]"], ["k", "y", "[B,512]"]],
                "operators": {},
            }},
            "branch_claims": [{"kind": "parallel", "groups": [["q"], ["k"]],
                               "joins": ["y"], "source_refs": self.refs}],
            "lint_resolutions": {},
        }}

    def check(self):
        return validate_expectations(self.data, self.review, self.architecture)

    def test_parallel_projection_and_shared_prefix_pass(self):
        self.assertEqual(self.check(), [])

    def test_serialized_q_k_fails_even_when_expected_rows_are_copied(self):
        self.data["edges"]["xk"]["source"] = "q"
        errors = self.check()
        self.assertTrue(any("dependency mismatch" in e and "xk" in e for e in errors), errors)
        self.review["semantic_expectations"]["regions"]["att"]["incoming_dependencies"][1][0] = "q"
        self.assertTrue(any("forbidden tensor dependency" in e for e in self.check()))

    def test_wrong_projection_shape_fails(self):
        self.data["edges"]["qy"]["tensor"]["shape"] = "[B,5120]"
        self.assertTrue(any("dependency mismatch" in e for e in self.check()))

    def test_routed_and_shared_experts_must_both_read_original_input(self):
        names = {"x": "tokens", "q": "routed", "k": "shared", "y": "add"}
        self.data["nodes"] = {names[n]: v for n, v in self.data["nodes"].items()}
        for edge in self.data["edges"].values():
            edge["source"], edge["target"] = names[edge["source"]], names[edge["target"]]
        block = self.review["semantic_expectations"]
        for row in block["regions"]["att"]["incoming_dependencies"]:
            row[0], row[1] = names[row[0]], names[row[1]]
        block["branch_claims"][0].update(groups=[["routed"], ["shared"]], joins=["add"])
        self.assertEqual(self.check(), [])
        self.data["edges"]["xk"]["source"] = "routed"
        self.assertTrue(any("forbidden tensor dependency" in e for e in self.check()))

    def test_cross_region_dependency_is_owned_by_target_region(self):
        self.data["regions"]["input"] = {"granularity": "module-summary"}
        self.data["nodes"]["x"]["region"] = "input"
        self.review["semantic_expectations"]["regions"]["input"] = {
            "source_refs": self.refs, "reason": "The input boundary supplies the two projection branches.",
            "incoming_dependencies": [], "operators": {}}
        self.assertEqual(self.check(), [])

    def test_generic_activation_cannot_match_source_linear_expectation(self):
        self.data["nodes"]["q"]["operator_contract"] = {
            "classification": "atomic-operator", "op_type": "activation", "shape_rule": "preserve"}
        self.review["semantic_expectations"]["regions"]["att"]["operators"] = {"q": ["linear", "transform"]}
        self.assertTrue(any("operator type/shape-rule" in e for e in self.check()))

    def test_duplicate_edge_multiplicity_is_checked(self):
        self.data["edges"]["duplicate"] = copy.deepcopy(self.data["edges"]["qy"])
        self.assertTrue(any("dependency mismatch" in e for e in self.check()))

    def test_exclusive_prefill_decode_residual_edge_fails(self):
        claim = self.review["semantic_expectations"]["branch_claims"][0]
        claim.update(kind="exclusive", joins=[])
        self.assertEqual(self.check(), [])
        add_tensor_edge(self.data, "bad", "q", "k", {"name": "bad", "shape": "[B,1280]", "status": "code-confirmed"})
        self.assertTrue(any("exclusive groups" in e for e in self.check()))

    def test_join_cannot_hide_branch_member(self):
        self.review["semantic_expectations"]["branch_claims"][0]["joins"] = ["q"]
        self.assertTrue(any("joins are invalid" in e for e in self.check()))

    def test_malformed_branch_kind_returns_error(self):
        self.review["semantic_expectations"]["branch_claims"][0]["kind"] = []
        self.assertTrue(any("kind must be" in e for e in self.check()))

    def test_source_range_must_exist(self):
        self.refs[0]["line_end"] = 100
        self.assertTrue(any("outside pinned evidence" in e for e in self.check()))

    def test_lane_does_not_create_edges(self):
        before = copy.deepcopy(self.data["edges"])
        add_lane(self.data, "att", "q_lane", ["x", "q", "y"])
        self.assertEqual(self.data["edges"], before)
        with self.assertRaises(ValueError):
            add_lane(self.data, "att", "q_lane", ["x", "q", "y"])

    def test_uniform_activations_require_review_but_can_be_legitimate(self):
        (self.architecture.parent / "model.py").write_text(
            "q = relu(x)\nk = sigmoid(x)\ny = tanh(q)\n")
        del self.data["edges"]["ky"]
        for edge in self.data["edges"].values():
            edge["tensor"]["shape"] = "[B,5120]"
        self.review["semantic_expectations"]["branch_claims"] = []
        record = self.review["semantic_expectations"]["regions"]["att"]
        record["incoming_dependencies"] = [["x", "q", "[B,5120]"], ["x", "k", "[B,5120]"],
                                           ["q", "y", "[B,5120]"]]
        for nid in ("q", "k", "y"):
            self.data["nodes"][nid].update(label="Activation", operator_contract={
                "classification": "atomic-operator", "op_type": "activation", "shape_rule": "preserve"})
            record["operators"][nid] = ["activation", "preserve"]
        findings = lint(self.data)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "review")
        self.assertTrue(any("lint_resolutions" in e for e in self.check()))
        self.review["semantic_expectations"]["lint_resolutions"][findings[0]["id"]] = {
            "disposition": "source-confirmed", "reason": "Each inspected operation is a shape-preserving activation.",
            "source_refs": self.refs}
        self.assertEqual(self.check(), [])

    def test_stale_ruleset_or_missing_expectations_blocks_real_gate(self):
        temp, _, architecture, topology, review_path, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        review = json.loads(review_path.read_text())
        for mutate in (lambda r: r.pop("semantic_expectations"),
                       lambda r: r["semantic_expectations"].update(ruleset="old")):
            changed = copy.deepcopy(review)
            mutate(changed)
            review_path.write_text(json.dumps(seal_review(changed)))
            self.assertTrue(any("fresh independent review" in e for e in
                                validate_review(architecture, topology, review_path)))

    def test_geometry_does_not_invalidate_current_review(self):
        temp, _, architecture, topology, review_path, data = reviewed_project()
        self.addCleanup(temp.cleanup)
        data["regions"]["detail"]["child_direction"] = "row"
        data["nodes"]["projection"]["order"] = 500
        architecture.write_text(json.dumps(data))
        self.assertEqual(validate_review(architecture, topology, review_path), [])


if __name__ == "__main__":
    unittest.main()
