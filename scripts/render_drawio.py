#!/usr/bin/env python3
"""Export Draw.io-owned review artifacts with the official desktop renderer."""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def find_drawio(explicit: Path | None) -> Path | None:
    candidates = [explicit]
    env_value = os.environ.get("DRAWIO_BIN")
    if env_value:
        candidates.append(Path(env_value))
    path_value = shutil.which("drawio")
    if path_value:
        candidates.append(Path(path_value))
    candidates.extend(
        [
            Path.cwd() / "tools/drawio/squashfs-root/AppRun",
            Path.cwd() / "tools/drawio/drawio.AppImage",
        ]
    )
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return struct.unpack(">II", header[16:24])


def export(
    renderer: Path,
    diagram: Path,
    output: Path,
    width: int | None,
    timeout_seconds: float,
) -> None:
    command = [
        str(renderer),
        "--no-sandbox",
        "--disable-update",
        "--export",
        "--border",
        "20",
        "--theme",
        "light",
        "--output",
        str(output),
    ]
    if width is not None:
        command.extend(["--width", str(width)])
    command.append(str(diagram))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        # Electron may leave renderer children alive when only the parent is killed.
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        detail = f"\n{combined}" if combined else ""
        raise RuntimeError(
            f"Draw.io export timed out after {timeout_seconds:g}s: {output}{detail}"
        ) from error
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    if process.returncode:
        raise RuntimeError(f"Draw.io export failed ({process.returncode}):\n{combined}")
    if "tile memory limits exceeded" in combined:
        raise RuntimeError(f"Draw.io export exceeded tile memory; artifact rejected:\n{combined}")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"Draw.io did not produce {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagram", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--drawio-bin", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--export-timeout",
        type=float,
        default=60,
        help="Maximum seconds allowed for each Draw.io export before its process group is killed.",
    )
    parser.add_argument(
        "--legacy-project",
        action="store_true",
        help="Explicitly bypass the strict project contract for an existing migration-only diagram.",
    )
    args = parser.parse_args()
    if args.export_timeout <= 0:
        parser.error("--export-timeout must be greater than zero")

    if not args.legacy_project:
        if args.manifest is None:
            print("Draw.io render: FAIL\n- strict delivery requires --manifest")
            return 2
        from audit_delivery_contract import validate_manifest

        _, contract_errors = validate_manifest(args.diagram, args.manifest)
        if contract_errors:
            print("Draw.io render: FAIL\n- strict delivery contract is incomplete")
            for error in contract_errors:
                print(f"ERROR: {error}")
            print("Use --legacy-project only for an explicitly reported migration audit.")
            return 2

    renderer = find_drawio(args.drawio_bin)
    if renderer is None:
        print("Draw.io renderer unavailable; Draw.io-rendered visual audit pending.")
        return 3

    manifest = {}
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    render = manifest.get("render", {})
    overview_width = int(render.get("overview_width", 2560))
    detail_width = int(render.get("detail_width", 4800))

    if args.output_dir:
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="drawio-review-"))

    stem = args.diagram.stem
    overview = output_dir / f"{stem}-{overview_width}.png"
    detail = output_dir / f"{stem}-{detail_width}.png"
    vector = output_dir / f"{stem}.svg"
    try:
        export(renderer, args.diagram, overview, overview_width, args.export_timeout)
        export(renderer, args.diagram, detail, detail_width, args.export_timeout)
        export(renderer, args.diagram, vector, None, args.export_timeout)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Draw.io render: FAIL\n- {error}")
        return 1

    overview_size = png_size(overview)
    detail_size = png_size(detail)
    print("Draw.io render: PASS")
    print(f"renderer: {renderer}")
    print(f"overview: {overview} ({overview_size[0]}x{overview_size[1]})")
    print(f"detail: {detail} ({detail_size[0]}x{detail_size[1]})")
    print(f"vector: {vector}")
    rendered_auditor = Path(__file__).with_name("audit_rendered_svg.py")
    audit_command = [sys.executable, str(rendered_auditor), str(args.diagram), str(vector)]
    if args.manifest:
        audit_command.extend(["--manifest", str(args.manifest)])
    audit = subprocess.run(audit_command, capture_output=True, text=True, check=False)
    if audit.stdout.strip():
        print(audit.stdout.strip())
    if audit.stderr.strip():
        print(audit.stderr.strip(), file=sys.stderr)
    if audit.returncode:
        print("Official export succeeded, but rendered geometry has hard failures.")
        return 1
    print("Inspect the full overview and the manifest's detail_regions manually.")
    print(
        "DRAFT/BLOCKED: rendered audit PASS is not final delivery; record visual-review.json "
        "and run complete_delivery.py to obtain a DELIVERABLE receipt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
