import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from complete_delivery import artifact_entry
from complete_project import certify_project, verify_project
from review_fixture import reviewed_project


class ProjectCompletionTests(unittest.TestCase):
    def setUp(self):
        temp, self.root, self.arch, _, _, data = reviewed_project(with_views=True)
        self.addCleanup(temp.cleanup)
        self.outputs = {}
        for fmt, payload in {"drawio": b"compiler output", "svg": b"official svg",
                             "png": b"\x89PNG\r\n\x1a\nfixture image"}.items():
            path = self.root / ("model." + fmt)
            path.write_bytes(payload)
            self.outputs[fmt] = path
        self.layout = self.root / "layout.json"
        self.layout.write_text(json.dumps({"semantic_view": "model-algorithm"}))
        self.receipt = self.root / "view.receipt.json"
        self.receipt.write_text(json.dumps({"artifacts": {
            "architecture": artifact_entry(self.arch),
            "project_intake": artifact_entry(self.root / "project-intake.json"),
            "layout": artifact_entry(self.layout),
            **{key: artifact_entry(self.outputs[fmt]) for fmt, key in
               {"drawio": "diagram", "svg": "rendered_svg", "png": "overview"}.items()}}}))
        self.artifacts = self.root / "delivery-artifacts.json"
        self.artifacts.write_text(json.dumps({"model-algorithm": {
            fmt: path.name for fmt, path in self.outputs.items()}}))
        self.receipts = self.root / "delivery-receipts.json"
        self.receipts.write_text(json.dumps({"model-algorithm": self.receipt.name}))

    def certify(self):
        return certify_project(self.arch, self.artifacts, self.receipts)

    def test_uncertified_direct_export_is_rejected_by_real_verifier(self):
        with self.assertRaisesRegex(ValueError, "DRAFT/BLOCKED"):
            self.certify()

    @patch("complete_project.verify_receipt", return_value=[])
    def test_current_bundle_and_byte_identical_publication_copy(self, verifier):
        result = self.certify()
        self.assertEqual(result["status"], "deliverable")
        verifier.assert_called_once_with(self.receipt)
        copied = self.root / "published.png"
        copied.write_bytes(self.outputs["png"].read_bytes())
        mapping = json.loads(self.artifacts.read_text())
        mapping["model-algorithm"]["png"] = copied.name
        self.artifacts.write_text(json.dumps(mapping))
        self.assertEqual(self.certify()["status"], "deliverable")

    @patch("complete_project.verify_receipt", return_value=[])
    def test_no_substitution_of_uncertified_svg_or_png(self, _):
        for fmt in ("svg", "png", "drawio"):
            with self.subTest(fmt=fmt):
                original = self.outputs[fmt].read_bytes()
                self.outputs[fmt].write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "not the certified"):
                    self.certify()
                self.outputs[fmt].write_bytes(original)

    @patch("complete_project.verify_receipt", return_value=[])
    def test_other_view_cannot_use_algorithm_receipt(self, _):
        self.layout.write_text(json.dumps({"semantic_view": "decode"}))
        with self.assertRaisesRegex(ValueError, "different view"):
            self.certify()

    @patch("complete_project.verify_receipt", return_value=[])
    def test_other_architecture_cannot_borrow_receipt(self, _):
        receipt = json.loads(self.receipt.read_text())
        receipt["artifacts"]["architecture"]["path"] = str(self.root / "other.json")
        self.receipt.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "another canonical"):
            self.certify()

    def test_selected_format_and_receipt_are_required(self):
        mapping = json.loads(self.artifacts.read_text())
        del mapping["model-algorithm"]["png"]
        self.artifacts.write_text(json.dumps(mapping))
        with self.assertRaisesRegex(ValueError, "selected formats"):
            self.certify()

    @patch("complete_project.verify_receipt", return_value=[])
    def test_project_receipt_binds_intake_changes(self, _):
        target = self.root / "project.receipt.json"
        target.write_text(json.dumps(self.certify()))
        verify_project(target)
        path = self.root / "project-intake.json"
        # Even a byte-only intake change must refresh final delivery certification.
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            verify_project(target)

    def test_cli_refuses_missing_architecture_and_does_not_create_receipt(self):
        receipt = self.root / "result.json"
        script = Path(__file__).resolve().parents[1] / "scripts" / "complete_project.py"
        result = subprocess.run([sys.executable, str(script), "--architecture", str(self.root / "missing.json"),
                                 "--artifacts", str(self.artifacts), "--receipts", str(self.receipts),
                                 "--receipt", str(receipt)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("DRAFT/BLOCKED", result.stdout)
        self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
