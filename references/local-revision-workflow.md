# Local visual revision

Use this path for a visual-only repair of an existing compiler project with a
current architecture digest and valid saved topology review. It avoids repeating
semantic planning, but does not waive any delivery audit. Use the full compiler
pipeline for changed source bytes, operators, shapes, ownership, or reader views.

## One entrypoint

Start from `assets/local-revision-job-template.json`. Paths resolve relative to
the job file, not the shell working directory. Register the master plus each
focused view that must stay synchronized. `state` is optional; when supplied,
invalid state or a selected frozen region blocks the run. A focused view must be
an exact subset of the master and contain no expansion arrows in this initial
implementation. Missing nodes or unsupported views fail; they are never dropped.
Direct editor changes to baseline node boxes, edge ports, waypoints or endpoints
must first be reconciled with the source layout; the wrapper rejects that drift
instead of silently compiling away the user's changes.

```bash
python scripts/run_local_revision.py project/local-revision.json \
  --region attention --repair junctions --output-dir /tmp/attention-revision-01 \
  --render --drawio-bin /opt/drawio/drawio
```

Three repair modes are available:

- `junctions`: normalize only junctions in the explicitly selected region(s).
- `candidate`: accept a separately generated complete master layout with
  `--candidate-layout candidate.layout.json`. Membership/view/digest must match;
  unrelated node, region and edge geometry may not change. This mode supports
  ELK/refiner output but does not itself infer new ELK constraints or perform an
  automatic regional reflow. Hierarchy geometry is derived after node movement,
  not accepted as an unchecked candidate override.
- `overrides`: apply `--overrides edits.json` to the job's saved layout in memory.
  The file contains only changed `nodes`, `regions`, and `edges`, using the
  precision override schema. Region translations reconcile internal bends and
  attached routes; explicit replacement waypoints use final absolute coordinates.
  If a route cannot be reconciled, supply its ports/waypoints in the same delta.
  Select all affected regions (including descendants and resized ancestors).
  Scope, precision, compilation and full static audit run before a candidate can
  succeed. Original state and layout remain unchanged on failure or success.

```bash
python scripts/run_local_revision.py project/local-revision.json \
  --region attention --repair overrides --overrides project/attention-edits.json \
  --output-dir /tmp/attention-revision-02
```

Use the existing saved layout as the geometry baseline; previous refinements
already present in it are retained. Do not replay the whole historical state
override collection against that layout. Each bundle snapshots the baseline and
delta, records input hashes and geometry differences, and saves a candidate
layout. Continue from the validated candidate after reviewing it; publication
still requires the normal render, visual review and delivery receipts. A failed
candidate requires no rollback because it never overwrites the baseline.

Repeat `--region` for the precise affected scope. If an obstacle forces another
region to move, inspect that dependency and expand the scope explicitly; do not
disable the preservation check. Cross-region incident edges are included in the
review queue and the complete master still receives strict audit.

## Execution and outputs

The command validates the existing semantic/evidence review, snapshots input
files and hashes, runs baseline static audit, creates a local candidate, checks
scope, synchronizes configured focused views by exact extraction/translation,
regenerates manifests, then strictly audits every resulting view before rendering
any of them. Existing human typography and narrow exceptions are preserved;
machine-owned coordinates, ports, rails and bridge registrations are regenerated.
Page overrides of machine-owned facts require migration rather than guessing.

An existing output directory is rejected. Each stage writes its log and updates
`revision-report.json`; a waiting process emits a heartbeat every ten seconds.
Commands have bounded timeouts and no automatic retry loop. Original project files
are never overwritten, even on success. Final input hashes detect concurrent edits.

When a terminal call yields a running session, retain its session ID and poll the
same session until exit. A yield or quiet log does not establish process failure.
Read the final exit status and stage exception before retrying or reporting a
blocker; use background launchers only when the host actually requires them.

The bundle contains `backup/`, candidate layouts/Draw.io/manifests, optional
official PNG/SVG exports, `geometry-diff.json`, a short `revision-summary.md`, and
`revision-report.json` with input/output hashes, stage results and review regions.
The geometry diff plus backup provide the structural before/after comparison;
the command does not yet generate an image-difference overlay.

Without `--render`, success means `render-and-manual-review-pending`. With it,
success means `manual-review-pending`, not acceptance. Review official whole-view
and affected detail images plus warnings, then separately promote the reviewed
bundle using its digests. No automatic publication or synthetic reviewer PASS.
Normal sandbox/GUI approvals still apply to official rendering.

## Diagnostic boundaries

The report records the stage where a finding was observed, related cell IDs, and
a conservative suggested component. For example, a port failure suggests checking
ports/conversion; it does not prove ELK caused it. Unrecognized errors retain
`unknown`, and every suggestion retains `root_cause: not-established`.

This wrapper observes baseline XML, candidate compilation/static audit, and
official export/render audit. It explicitly lists raw ELK and intermediate adapter
geometry as unobserved. It cannot claim that a rendered-only failure originated
in the renderer rather than measurement. Add intermediate snapshots and equivalent
checks before making a stronger stage-of-origin claim.

## Regression gates

Run `python -m unittest discover -s tests -q`. The parameterized matrix in
`tests/test_layout_regression_matrix.py` exercises 2/3/6-way fork/join, short and
multiline labels, two scales, chain/cache, gated residual, packed QKV, and
routed/shared branches. Legal cases must stay legal; injected node-overlap
mutations must fail. Existing junction tests cover stale registries, reversed
sharing and near-coincident ports. Existing rendered tests remain authoritative
for label/arrowhead collisions; abstract ELK geometry is not pixel acceptance.

Set `LOCAL_REVISION_REAL_JOB` to a real project job to run the optional integration
tests in `test_local_revision_real.py`. They create fresh temporary bundles, check
the selected project's inputs remain unchanged, and verify an invalid scope stops
without publishing. Keep real-model fixtures and IDs in projects/tests, never in
the shared repair logic. Cross-model and fresh-session evaluation remain separate
acceptance tasks; passing this suite is not proof of exhaustive topology coverage.
