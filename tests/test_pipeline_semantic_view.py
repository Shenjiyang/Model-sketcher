"""CLI projection selection must not rewrite or re-review canonical semantics."""

import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_topology_review import validate_review
from prepare_topology_review import build_pending_review
from render_topology_contract import render
from review_fixture import complete_review, reviewed_project
from topology_review_common import seal_review


class PipelineSemanticViewTests(unittest.TestCase):
    def project(self):
        temp, root, architecture, topology, review, data = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        data["view_projection_contract"]["views"]["projection-only"] = {
            "kind": "operator-flops", "purpose": "Projection-only operator view; GEMM uses 2MNK FLOPs."
        }
        for collection in ("regions", "nodes", "edges"):
            for item in data[collection].values():
                item["views"].append("projection-only")
        # A default-only interface lane makes selector failures observable in
        # geometry and XML, rather than just in a metadata string.
        for nid, order in (("aux_input", 0), ("aux_output", 1)):
            data["nodes"][nid] = {
                "label": nid.replace("_", " "), "kind": "interface", "region": "detail",
                "evidence": ["code"], "order": order,
                "semantic_layer": "shared-interface", "views": ["model-algorithm"],
            }
        data["edges"]["aux_pass"] = {
            "source": "aux_input", "target": "aux_output", "kind": "tensor",
            "semantic_layer": "shared-interface", "views": ["model-algorithm"],
            "tensor": {"name": "auxiliary", "shape": "[B,S,D]", "status": "code-confirmed", "evidence": ["code"]},
        }
        data["regions"]["detail"]["operator_sequences"].append(
            {"id": "aux", "nodes": ["aux_input", "aux_output"]}
        )
        architecture.write_text(json.dumps(data, indent=2) + "\n")
        topology.write_text(render(data))
        fixture_review = complete_review(
            build_pending_review(architecture, topology, "cold-start"), data
        )
        reconstruction = fixture_review["reconstruction_review"]
        for record in reconstruction["results"] + reconstruction["region_results"]:
            if "sequence:detail/main" in record["contract_refs"]:
                record["contract_refs"].append("sequence:detail/aux")
        seal_review(fixture_review)
        review.write_text(json.dumps(fixture_review, indent=2) + "\n")
        self.assertEqual(validate_review(architecture, topology, review), [])
        return root, architecture, topology, review

    def run_pipeline(self, root, architecture, topology, review, view, stem):
        state = root / "state.json"
        if not state.exists():
            state.write_text(json.dumps({"schema_version": 1, "topology_review": {"path": review.name}}))
        command = [sys.executable, str(SCRIPTS / "run_compiler_pipeline.py"), str(architecture),
                   "--topology-contract", str(topology), "--layout", str(root / f"{stem}.layout.json"),
                   "--drawio", str(root / f"{stem}.drawio"),
                   "--audit-manifest", str(root / f"{stem}.audit.json"), "--state", str(state),
                   "--require-source-files"]
        if view is not None:
            command.extend(["--semantic-view", view])
        return subprocess.run(command, capture_output=True, text=True, timeout=60)

    def test_selected_view_reuses_saved_review_and_preserves_canonical_bytes(self):
        root, architecture, topology, review = self.project()
        before = {p: p.read_bytes() for p in (architecture, topology, review)}
        for selector, stem, expected in (
            ("projection-only", "focused", {"input", "projection", "output"}),
            (None, "default", {"input", "projection", "output", "aux_input", "aux_output"}),
        ):
            with self.subTest(selector=selector):
                result = self.run_pipeline(root, architecture, topology, review, selector, stem)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("gate 3c: PASS (reused", result.stdout)
                self.assertIn("no reviewer invoked", result.stdout)
                layout = json.loads((root / f"{stem}.layout.json").read_text())
                self.assertEqual(set(layout["nodes"]), expected)
                cells = {c.get("id") for c in ET.parse(root / f"{stem}.drawio").iter("mxCell")}
                self.assertEqual({cid.removeprefix("node:") for cid in cells if cid and cid.startswith("node:")}, expected)
                manifest = json.loads((root / f"{stem}.audit.json").read_text())
                self.assertEqual(manifest["defaults"]["semantic_view"], selector or "model-algorithm")
                self.assertEqual(set(manifest["defaults"]["node_semantics"]), {f"node:{nid}" for nid in expected})
                expected_edges = {"edge:input_projection", "edge:projection_output"}
                if not selector:
                    expected_edges.add("edge:aux_pass")
                self.assertEqual(set(manifest["defaults"]["expected_edges"]), expected_edges)
                rendered_manifest = json.dumps(manifest)
                if selector:
                    self.assertNotIn("node:aux_input", rendered_manifest)
                    self.assertNotIn("edge:aux_pass", rendered_manifest)
                for path, content in before.items():
                    self.assertEqual(path.read_bytes(), content, f"Canonical input changed: {path}")
                self.assertEqual(validate_review(architecture, topology, review), [])

    def test_unknown_view_fails_before_outputs_or_canonical_changes(self):
        root, architecture, topology, review = self.project()
        before = {p: p.read_bytes() for p in (architecture, topology, review)}
        result = self.run_pipeline(root, architecture, topology, review, "missing", "bad")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared semantic view", result.stderr)
        for suffix in ("layout.json", "drawio", "audit.json"):
            self.assertFalse((root / f"bad.{suffix}").exists())
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
