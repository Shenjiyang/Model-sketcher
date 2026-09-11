# Completion and certification gate

Use this gate for every compiler-path final delivery. It separates an editable
or renderable draft from an artifact that may be described as complete.

For a requested Model Sketcher diagram, direct SVG/XML/Mermaid authoring followed
by a generic Draw.io import/export is not a compiler path. Keep any exploratory
files under the project's `drafts/` directory and label them `DRAFT/BLOCKED`.
Export success and an editable file do not authorize final delivery. Read-only
visual diagnostics remain available; do not publish an alternative model or
reduced scope to get around missing evidence or pending review.

After official Draw.io rendering, inspect the full overview and every detail
region declared by the audit manifest. Copy `assets/visual-review-template.json`
into the project source directory, record the exact official overview and detail
crop files, calculate their SHA-256 digests, resolve every finding, and set the
verdict and checklist only from the images actually inspected. This is a
structured visual reflection, not a substitute for semantic or geometry audits.

Then run:

```bash
python3 scripts/complete_delivery.py model.drawio \
  --manifest model.audit.json \
  --layout sources/model/layout.json \
  --rendered-svg renders/model.svg \
  --visual-review sources/model/visual-review.json \
  --state sources/model/project-state.json \
  --receipt model.delivery-receipt.json
```

The command fails closed unless the intake, canonical IR, generated ASCII,
independent topology review, layout, compiler output, strict static audit,
official rendered audit, and visual review are current and passing. It also
recompiles the diagram from the current architecture and layout and requires
byte-for-byte equality, which rejects manual XML, stale output, and direct
Draw.io auto-routing as certified compiler output.

`DELIVERABLE` certifies that individual view; whole-project completion additionally
requires the project gate below. `DRAFT/BLOCKED` means the
files may be reported only as diagnostic or work in progress, together with the
missing gates. Creating or exporting a `.drawio`, PNG, or SVG never establishes
completion by itself. Verify an existing receipt and all bound artifact digests
with:

```bash
python3 scripts/complete_delivery.py \
  --verify-receipt model.delivery-receipt.json
```

The receipt detects drift and unsupported construction paths; it is not a
cryptographic identity signature. A process with write access can fabricate
files, so downstream automation and collaborators must accept only receipts
produced and reverified by this command.

## Whole-project acceptance

Per-view certification now binds the confirmed intake, inspected overview and
detail crops as well as the semantic, geometry and review artifacts. Re-certify
older delivery receipts to add these bindings; reuse an otherwise valid semantic
review. It is unnecessary to repeat the LLM Reviewer for this packaging change.

After all selected views pass, record `delivery-artifacts.json` using the intake
format (view ID -> selected format -> path), and `delivery-receipts.json` mapping
each view ID to its per-view receipt. Paths are relative to their respective JSON
files. Preserve each view's own layout, audit manifest and project state so later
view builds do not invalidate an earlier receipt. Run:

```bash
python scripts/complete_project.py --architecture sources/model/architecture.json \
  --artifacts sources/model/delivery-artifacts.json \
  --receipts sources/model/delivery-receipts.json \
  --receipt model.project-delivery-receipt.json

python scripts/complete_project.py --verify-receipt model.project-delivery-receipt.json
```

Only `PROJECT_DELIVERABLE` permits claiming the entire requested project complete.
The command reuses intake planning and revalidates every per-view receipt; it
requires exactly the selected views and formats. Draw.io must match its certified
diagram, SVG its certified rendered SVG, and PNG its inspected full overview.
Byte-identical copies in the public output directory are permitted. Select the
intended delivery-resolution full PNG as the visual review overview; a detail
crop or separate unreviewed PNG cannot substitute. Unexpected files elsewhere
in a shared directory are not scanned or deleted: the explicit artifact map is
the delivery boundary, and final links must come only from that accepted map.

## Enforcement boundary

These commands refuse certification; they cannot intercept arbitrary shell
writes, editor calls, Draw.io imports, or an agent's final prose. Repeating the
word MUST or adding another reflection JSON does not change that boundary.
For enforced publication, a host/CI/upload service outside the Builder's writable
environment must invoke the installed trusted `complete_project.py
--verify-receipt ...`, reject nonzero status, and publish only the verified mapped
bytes. The Builder must not be able to edit that service or its validation tools.
Publication must use the same immutable snapshot as verification to avoid a
check/copy race. A shell alias, same-user chmod, or an agent-editable hook is not
this isolation. This skill does not install or claim an enforced Codex host hook.
