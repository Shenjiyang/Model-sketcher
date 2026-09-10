import json
import subprocess
import sys
import unittest
from pathlib import Path


TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

from review_fixture import reviewed_project


class PipelineReviewGateTests(unittest.TestCase):
    def run_pipeline(self, architecture, topology, review, root):
        command = [
            sys.executable,
            str(SCRIPTS / "run_compiler_pipeline.py"),
            str(architecture),
            "--layout", str(root / "layout.json"),
            "--topology-contract", str(topology),
            "--drawio", str(root / "model.drawio"),
            "--require-source-files",
        ]
        if review is not None:
            command.extend(["--topology-review", str(review)])
        return subprocess.run(command, check=False, capture_output=True, text=True)

    def test_missing_review_blocks_before_layout_even_without_logical_flag(self):
        temp, root, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        review.rename(review.with_suffix(".saved"))
        data = json.loads(architecture.read_text(encoding="utf-8"))
        data["project"]["require_logical_operator_contracts"] = False
        architecture.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_pipeline(architecture, topology, None, root)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("gate 3c: PENDING", result.stdout)
        self.assertFalse((root / "layout.json").exists())

    def test_schema_v1_review_blocks_before_layout(self):
        temp, root, architecture, topology, review_path, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["schema_version"] = 1
        review_path.write_text(json.dumps(review), encoding="utf-8")
        result = self.run_pipeline(architecture, topology, review_path, root)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("schema_version must be 2", result.stdout)
        self.assertFalse((root / "layout.json").exists())

    def test_valid_schema_v2_review_allows_layout_and_compile(self):
        temp, root, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        result = self.run_pipeline(architecture, topology, review, root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("gate 3c: PASS", result.stdout)
        self.assertTrue((root / "layout.json").is_file())
        self.assertTrue((root / "model.drawio").is_file())

    def test_default_saved_review_is_reused_without_explicit_argument(self):
        temp, root, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        default = topology.with_name("topology-review.json")
        default.write_bytes(review.read_bytes())
        result = self.run_pipeline(architecture, topology, None, root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no reviewer invoked", result.stdout)

    def test_auto_discovery_does_not_accept_changed_source(self):
        temp, root, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        topology.with_name("topology-review.json").write_bytes(review.read_bytes())
        data = json.loads(architecture.read_text())
        source = architecture.parent / data["evidence"][0]["path"]
        source.write_text(source.read_text() + "\n")
        result = self.run_pipeline(architecture, topology, None, root)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertFalse((root / "layout.json").exists())

    def test_review_only_uses_state_relative_path_without_generating_geometry(self):
        temp, root, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        state = root / "project-state.json"
        state.write_text(json.dumps({"topology_review": {"path": review.name}}))
        result = subprocess.run([
            sys.executable, str(SCRIPTS / "run_compiler_pipeline.py"), str(architecture),
            "--topology-contract", str(topology), "--review-only", "--state", str(state),
            "--layout", str(root / "layout.json"), "--drawio", str(root / "model.drawio"),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no reviewer invoked", result.stdout)
        self.assertFalse((root / "layout.json").exists())
        self.assertFalse((root / "model.drawio").exists())
        self.assertEqual(json.loads(state.read_text())["topology_review"]["path"], str(review.resolve()))

    def test_prepare_preserves_valid_review_and_explicit_recheck_archives_it(self):
        temp, root, architecture, topology, review, _ = reviewed_project()
        self.addCleanup(temp.cleanup)
        before = review.read_bytes()
        command = [sys.executable, str(SCRIPTS / "prepare_topology_review.py"),
                   str(architecture), str(topology), str(review), "--trigger"]
        result = subprocess.run(command + ["semantic-revision"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REUSED", result.stdout)
        self.assertEqual(review.read_bytes(), before)
        result = subprocess.run(command + ["requested-recheck"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(review.read_text())["verdict"], "pending")
        backups = list(review.parent.glob(review.name + ".*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
