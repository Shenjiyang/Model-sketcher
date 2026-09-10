import tempfile
import time
import unittest
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render_drawio import export


class RenderDrawioTests(unittest.TestCase):
    def test_export_timeout_fails_promptly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            renderer = root / "fake-drawio"
            renderer.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
            renderer.chmod(0o755)
            diagram = root / "model.drawio"
            diagram.write_text("<mxfile/>", encoding="utf-8")

            started = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                export(renderer, diagram, root / "output.png", 2560, 0.1)
            self.assertLess(time.monotonic() - started, 2)


if __name__ == "__main__":
    unittest.main()
