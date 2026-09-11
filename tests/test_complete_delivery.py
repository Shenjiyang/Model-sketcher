import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from unittest.mock import patch

from complete_delivery import (
    CHECKS, validate_compiler_provenance, validate_visual_review, verify_receipt,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CompletionGateTests(unittest.TestCase):
    def test_visual_review_requires_real_bound_images_and_all_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            svg = root / "model.svg"
            overview = root / "overview.png"
            first = root / "attention.png"
            second = root / "moe.png"
            for path, value in ((svg, b"svg"), (overview, b"overview"),
                                (first, b"attention"), (second, b"moe")):
                path.write_bytes(value)
            review = {
                "schema_version": 1, "verdict": "pass",
                "rendered_svg_sha256": digest(svg),
                "overview": {"path": overview.name, "sha256": digest(overview)},
                "detail_crops": [
                    {"name": "attention", "path": first.name, "sha256": digest(first)},
                    {"name": "moe", "path": second.name, "sha256": digest(second)},
                ],
                "checklist": {name: True for name in CHECKS},
                "findings": [], "blocking_findings": [],
            }
            review_path = root / "visual-review.json"
            review_path.write_text(json.dumps(review))
            errors = []
            manifest = {"render": {"detail_regions": [
                {"name": "attention"}, {"name": "moe"}]}}
            validate_visual_review(review_path, manifest, svg, errors)
            self.assertEqual([], errors)
            overview.write_bytes(b"changed")
            errors = []
            validate_visual_review(review_path, manifest, svg, errors)
            self.assertTrue(any("overview digest" in error for error in errors))

    def test_receipt_detects_artifact_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "model.drawio"
            artifact.write_bytes(b"compiled")
            receipt = root / "model.delivery-receipt.json"
            receipt.write_text(json.dumps({
                "schema_version": 1, "status": "deliverable",
                "gate": "model-sketcher-completion-v1",
                "artifacts": {name: {"path": str(artifact), "sha256": digest(artifact)}
                              for name in ("diagram", "manifest", "layout", "rendered_svg",
                                           "visual_review", "project_state")}
            }))
            # Unit-test digest drift without constructing a full compiler project.
            self.assertEqual([], verify_receipt(receipt, rerun=False))
            artifact.write_bytes(b"manual edit")
            self.assertTrue(any("changed after certification" in error
                                for error in verify_receipt(receipt, rerun=False)))

    def test_compiler_provenance_rejects_manual_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            diagram = root / "model.drawio"
            architecture = root / "architecture.json"
            layout = root / "layout.json"
            diagram.write_bytes(b"manual xml")
            architecture.write_text("{}")
            layout.write_text(json.dumps({"layout_engine": {
                "name": "compound-elk-layered", "native_routed_edge_ids": [],
                "route_preflight": {"route_errors": []}}}))
            errors = []
            with patch("complete_delivery.expected_drawio", return_value=b"compiler xml"):
                validate_compiler_provenance(diagram, architecture, layout, errors)
            self.assertTrue(any("do not match" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
