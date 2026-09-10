"""Indexed recurrence metadata is explicit, source-bound and projection-closed."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_architecture_ir import validate_loop_contracts
from render_topology_contract import render


def fixture():
    nodes = {
        nid: dict(kind=kind, region="scan", label=nid, evidence=["src"], views=["all"])
        for nid, kind in (("token", "operator"), ("old", "state"), ("new", "state"), ("stack", "operator"))
    }
    region = dict(label="Scan", parent=None, direction="column", flow_direction="bottom-to-top",
                  granularity="operator-detail", views=["all"],
                  operator_sequences=[dict(id="main", nodes=["token", "stack"])],
                  loop_contract=dict(domain="n=offset[b]+t; t<len[b]", step_inputs=["token"],
                      state_input="old", state_output="new", feedback="new at t becomes old at t+1",
                      output_assembly="stack", physical_execution="Equivalent scan, no state trajectory allocation asserted",
                      evidence=["src"], source="scan.py:10-40"))
    return dict(project=dict(id="test", title="Loop", output_view="hierarchy-master"),
                evidence=[dict(id="src",role="inference-implementation",path="scan.py",revision="pinned")],
                regions={"scan":region}, nodes=nodes,
                edges={"write":dict(source="token",target="stack",kind="tensor",tensor=dict(name="y",shape="[D]",status="inferred",reason="indexed"))})


class LoopContractTests(unittest.TestCase):
    def check(self, data):
        return validate_loop_contracts(data, data["regions"], data["nodes"])

    def test_valid_loop(self):
        self.assertEqual(self.check(fixture()), [])

    def test_malformed_contract_and_required_fields(self):
        data=fixture(); data["regions"]["scan"]["loop_contract"]=False
        self.assertTrue(self.check(data))
        for field in ("domain","feedback","physical_execution","source","evidence","step_inputs"):
            data=fixture(); del data["regions"]["scan"]["loop_contract"][field]
            with self.subTest(field=field): self.assertTrue(self.check(data))

    def test_wrong_owner_or_missing_boundary_rejected(self):
        for field in ("state_input","state_output","output_assembly"):
            data=fixture();data["regions"]["scan"]["loop_contract"][field]="missing"
            with self.subTest(field=field): self.assertTrue(self.check(data))
        data=fixture();data["nodes"]["token"]["region"]="elsewhere"
        self.assertTrue(self.check(data))

    def test_unknown_evidence_and_invalid_state_kind(self):
        data=fixture();data["regions"]["scan"]["loop_contract"]["evidence"]=["missing"]
        self.assertTrue(self.check(data))
        data=fixture();data["nodes"]["old"]["kind"]="operator"
        self.assertTrue(self.check(data))

    def test_partial_projection_rejected_before_render(self):
        data=fixture();data["nodes"]["old"]["views"]=["other"]
        self.assertTrue(any("loses" in e for e in self.check(data)))

    def test_step_and_assembly_require_execution_sequence(self):
        data=fixture();data["regions"]["scan"]["operator_sequences"]=[]
        self.assertTrue(any("operator_sequences" in e for e in self.check(data)))

    def test_ascii_exposes_loop_domain_feedback_and_assembly(self):
        data=fixture(); text=render(data)
        for value in ("indexed_loop_contract:", "n=offset[b]+t", "state-input: node:old",
                      "state-output: node:new", "new at t becomes old at t+1", "output-assembly: node:stack",
                      "scan.py:10-40", "no state trajectory allocation"):
            self.assertIn(value,text)
        reverse=deepcopy(data);reverse["nodes"]=dict(reversed(list(data["nodes"].items())))
        self.assertEqual(text,render(reverse))

    def test_ascii_exposes_backend_call_semantics(self):
        data = fixture()
        data["nodes"]["stack"]["implementation_contract"] = {
            "source": "scan.py:35", "semantics": "Assemble all request-local output rows"}
        text = render(data)
        self.assertIn("implementation-contract: node:stack", text)
        self.assertIn("Assemble all request-local output rows", text)


if __name__ == "__main__":
    unittest.main()
