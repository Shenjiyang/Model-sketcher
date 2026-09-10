"""Opt-in integration with a supplied project job; never alter that project."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JOB = os.environ.get('LOCAL_REVISION_REAL_JOB')


@unittest.skipUnless(JOB, 'set LOCAL_REVISION_REAL_JOB to a real project job')
class RealRevisionTests(unittest.TestCase):
    def setUp(self):
        self.job = Path(JOB).resolve()
        config = json.loads(self.job.read_text())
        self.paths = [(self.job.parent / config[key]).resolve()
                      for key in ('architecture', 'layout', 'diagram', 'manifest')]
        self.hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths}
        data = json.loads(self.paths[0].read_text())
        layout = json.loads(self.paths[1].read_text())
        self.region = next((n['region'] for nid, n in data['nodes'].items()
                            if n.get('kind') == 'junction' and nid in layout['nodes']), next(iter(layout['regions'])))

    def tearDown(self):
        self.assertEqual(self.hashes, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths})

    def command(self, root, region):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/run_local_revision.py'), str(self.job),
                               '--region', region, '--output-dir', str(root / 'bundle')],
                              capture_output=True, text=True, timeout=120)

    def test_master_and_focused_bundle_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.command(root, self.region)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((root / 'bundle/revision-report.json').read_text())
            self.assertEqual(report['status'], 'render-and-manual-review-pending')
            self.assertEqual(report['publication'], 'not-performed')
            self.assertEqual(report['manual_review'], 'pending')
            self.assertIn('master.drawio', report['artifact_sha256'])
            self.assertTrue(all(s['status'] == 'PASS' for s in report['stages'] if s['name'] != 'baseline-static'))

    def test_bad_scope_stops_before_compile_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.command(root, '__nonexistent_region__')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'bundle/master.drawio').exists())
            report = json.loads((root / 'bundle/revision-report.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['current_stage'], 'semantic-preflight')


if __name__ == '__main__':
    unittest.main()
