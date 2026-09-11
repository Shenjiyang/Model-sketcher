# Completion and certification gate

Use this gate for every compiler-path final delivery. It separates an editable
or renderable draft from an artifact that may be described as complete.

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

Only `DELIVERABLE` authorizes final-delivery language. `DRAFT/BLOCKED` means the
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
