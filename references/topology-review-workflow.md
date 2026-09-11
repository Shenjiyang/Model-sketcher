# Independent topology and ASCII review

Use this checkpoint to establish semantic accuracy before layout. It is event-triggered, not a per-render or per-layout review.

Read [semantic-consistency-review.md](semantic-consistency-review.md) before
authoring or accepting a review. The existing Reviewer must also supply complete
source-derived dependency/type expectations, branch claims and lint resolutions.
The finalizer and every downstream reuse gate compare them with the actual IR;
natural-language claims alone do not establish parallelism or shape correctness.

## When a new review is required

Run an independent reviewer for:

- a cold-start architecture and its first generated ASCII contract;
- any semantic revision to regions, nodes, edges, operator contracts, shapes, source coverage, runtime variants, state lifecycles, repetitions, or cross-level mappings;
- a change to any pinned evidence file or declared source revision;
- a user-requested topology recheck after a suspected omission or misunderstanding.

Reuse the existing review for changes limited to `layout.json`, ports, waypoints, hierarchy-arrow corridors or attachment sides, macro child-region arrangement, node coordinates, typography, semantic palette styling, density, rendered output, or narrowly scoped geometry exceptions. The pipeline still validates the saved review quickly; it does not invoke another reviewer when the canonical architecture meaning, generated ASCII bytes, and source bytes are unchanged. The semantic digest deliberately excludes `project.typography`, region `child_direction`, node `visual_*` fields, and expansion `visual_attachment`; the generated ASCII likewise excludes those layout/style choices. JSON whitespace/key-order changes do not invalidate the semantic architecture digest.

## Separation of roles

Keep one Builder as the topology owner. When subagents are available, create a fresh-context Reviewer after the Builder has generated `architecture.json` and `topology.contract.txt`. The Reviewer may write only the dedicated topology-review artifact; it must not modify the architecture, ASCII, layout, compiler, or Draw.io files. Do not run Builder and Reviewer edits concurrently.

The Reviewer must reconstruct a source inventory before opening or comparing the Builder's node list. It may use the pending artifact only to locate pinned evidence and selected path IDs; it fills `independent_source_inventory` from source first. Do not prime it with suspected bugs, intended node lists, or the Builder's conclusions. A useful task is:

```text
Act as the independent semantic reviewer for this model diagram. Do not edit semantic inputs.
Read every pinned evidence source and independently trace the selected forward paths before
comparing them with architecture.json and topology.contract.txt. Check the required semantic
and ASCII-reconstruction criteria, then complete only topology-review.json. A pass requires no
blocking findings; preserve concrete non-blocking observations in findings.
```

If subagents are unavailable, stop before layout and report that independent semantic acceptance remains pending. A same-agent reread may produce useful findings but cannot set `independent_from_builder: true` or support a strict final PASS.

## Required review content (schema v3)

The mandatory `user-request-coverage` semantic result covers every region and
selected source path. Read the originating user task and `project.request_contract`
before accepting Builder's scope: compare view, whole-model/selected-module
coverage, depth, and every required module mapping. Explicitly challenge omitted
families and summaries substituted for requested logical operators. Refuse PASS
when the preserved quotation or narrowed scope conflicts with the actual task.
This check is reused with the same semantic digest during visual-only iterations.

`source_artifacts` binds every architecture evidence entry by ID, role, path, revision, and file hash. `independent_source_inventory.paths` contains exactly one record for every selected source path. Each path record names its source entrypoints, every material helper/callee and pinned evidence ID, independent executable observations, and `closure_status: complete`. Every observation has a unique ID, source locator, kind, executable evidence ID, and an exact reconciliation to one or more Builder `source_operation_ids`; across the path, each Builder operation ID is mapped exactly once. Placeholder observations, duplicate paths or operations, unpinned helper evidence, unmatched comparisons, and incomplete closure fail.

The semantic pass checks model overview, template families, logical operator coverage, branches/merges, tensor shapes, runtime variants, state lifecycles, source-operation closure, evidence status, terminology/granularity, and the boundary between algorithm, inference, and backend projections. It contains exactly one result for every required check and one region result for every architecture region. Each check names all applicable path/region scopes and pinned evidence; each region result names every source path that covers that region. Aggregate lists cannot substitute for per-check and per-region results.

The reconstruction pass checks whether the generated ASCII alone exposes a standalone Level 0, complete Level 1 templates, reconstructable detail sequences, traceable cross-level mappings, unambiguous branches/state, and no informationless detail region. It contains exactly one result per required check and one `reconstructable: true` result per region, with real `project:`, `region:`, `node:`, `edge:`, or `sequence:` contract references. Applicable Level checks must cite every region's named sequences; cross-level checks cite expansion edges; branch/state checks cite the relevant fan-out/join/cache/state nodes and incident tensor edges. A region-only citation cannot prove sequence reconstruction. This is not a visual-layout review.

All three sections record concrete non-placeholder findings even when they pass. Duplicate IDs/checks/regions, placeholder prose, any blocking finding, or anything other than a final `verdict: pass` returns the artifact to the Builder for an IR repair and a newly generated ASCII contract.

## Artifact lifecycle

In autonomous mode, PENDING instructs the Builder to schedule the required Reviewer;
FAIL instructs it to repair actionable findings, regenerate ASCII, and request a
fresh review. Neither result alone is a reason to end the task or wait for user
confirmation. Follow [project-intake.md](project-intake.md) for real blockers and
replanning after non-improving attempts. Never change an independent FAIL to PASS
yourself. Reuse valid reviews for visual-only work as specified below.

Before scheduling a Reviewer, run the saved-review preflight:

```bash
python scripts/run_compiler_pipeline.py architecture.json \
  --topology-contract topology.contract.txt --review-only \
  --layout layout.json --drawio model.drawio
```

The pipeline checks the explicit `--topology-review` first, otherwise the artifact
recorded in `--state`, otherwise `topology-review.json` beside the ASCII contract.
Recorded relative paths resolve against the state file's directory; newly saved
paths are absolute. An invalid selected artifact blocks; no alternative PASS is
searched for. `--review-only` generates canonical ASCII and validates the entire
saved review against current source bytes, but creates no layout or Draw.io output.
Successful output explicitly says `reused` and reports local validation time.

Do not schedule another agent after this preflight passes. Changing the selected
view or choosing ELK does not itself require a semantic review. The preparer also
preserves a still-valid PASS instead of replacing it with pending; a deliberate
`--trigger requested-recheck` overrides reuse and archives the old artifact first.
Stale artifacts are likewise archived before replacement.

Semantic edits still require complete independent review. The current region
change planner is a geometry tool, not proof that unchanged source paths are
semantically independent. Do not inherit per-region PASS results across changed
semantic digests without a separately validated dependency and review protocol.

During a fresh review, return concrete blocking findings promptly and persist
completed source-path observations. Provide progress at least once per minute;
partial findings never count as PASS. Local audit timings do not measure LLM/API
latency and must not be presented as a guaranteed total generation time.

After the first ASCII generation, create a pending, digest-bound artifact:

```bash
python scripts/prepare_topology_review.py architecture.json topology.contract.txt \
  topology-review.json --trigger cold-start
```

The preparer first runs the complete architecture validator with source files required and verifies that the ASCII bytes exactly equal `render_topology_contract.py` output for that IR. It then hashes the canonical architecture meaning, exact generated ASCII, and every evidence file. The independent Reviewer replaces pending identity, attestations, inventory, per-check/per-region findings, statuses, and verdict. It must not alter the generated digests or evidence ledger. Use a real builder session ID and independent agent/session ID.

After the Reviewer finishes, run the controlled finalizer once:

```bash
python scripts/finalize_topology_review.py architecture.json topology.contract.txt \
  topology-review.json
```

The finalizer performs the complete semantic audit before adding a deterministic receipt over the normalized review. Layout, compiler, delivery, and reuse gates reject a missing receipt or any edit made after finalization. Formatting failure before finalization may be repaired from the preserved Reviewer output without another semantic read; a finding or verdict change requires the Reviewer. The receipt prevents accidental or casual direct JSON edits from silently passing, but it is not a cryptographic identity proof when Builder and Reviewer share the same operating-system account. Strong adversarial separation still requires a host-owned signing key or isolated Reviewer service.

Validate it before layout:

```bash
python scripts/audit_topology_review.py architecture.json topology.contract.txt \
  topology-review.json
```

The audit rejects an invalid architecture, non-canonical or hand-edited ASCII, stale semantic digest, regenerated ASCII, changed source file, incomplete or duplicate path/operation/check/region coverage, unpinned material callee, self-review, missing attestation, placeholder or blocking finding, non-pass verdict, missing receipt, or post-finalization edit. `run_compiler_pipeline.py --topology-review topology-review.json` enforces the gate for every compiler-path project, independent of optional project flags. A semantic change invalidates the old artifact by design; create a new pending artifact and rerun the Reviewer. Review-only prose and validated visual/layout fields do not change the semantic digest or generated ASCII, so they do not trigger another Reviewer.
## Canonical completeness and delivery selection

Read the originating user request and `project-intake.json` separately from
Builder's scope interpretation. Read [analysis-scope-contract.md](analysis-scope-contract.md).
Review the complete model algorithm and computational state semantics, every
materialized region, and all runtime extension boundaries. Under the new policy,
unrequested implementation internals may remain inventoried and unexpanded.
Fill `analysis_scope_review` independently; never accept Builder's category label
as proof that an omitted condition or state dependency is implementation-only.
Legacy policy continues requiring full canonical runtime analysis until migrated.
For whole-model logical detail, independently enumerate distinct non-atomic model
families and reconcile each with its logical expansion. A complete MLA/MoE pair
cannot certify other unexamined families. Existing user-request-coverage,
source-operation-closure and view-projection-boundary checks must address this.
Adding a previously reviewed delivery view changes the external intake, not the
canonical review. New semantic content or projection definitions need re-review.
