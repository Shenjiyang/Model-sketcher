# Complete algorithms and on-demand runtime detail

Use this contract for new intake, source inventory, and independent semantic review.
New intake uses `complete-algorithm-with-runtime-inventory`. Existing confirmed
`complete-canonical-source-analysis` projects retain their full analysis scope;
do not silently migrate a failing project or rewrite its confirmation.

## Required knowledge

Always enumerate the whole model and every distinct module family, and expand
non-atomic families to logical operators in the canonical IR. Module-summary is
a delivery projection, not permission to omit canonical algorithm analysis.
Level 0-3 describes hierarchy; Prefill/Decode/backend describes reader views.
Implementation detail belongs in the backend view, not an algorithm-depth option.
New-policy `project.request_contract.depth` stays `logical-operators` and every
required module maps to an algorithm operator-detail region. Intake may select a
module-summary projection while preserving that canonical analysis floor.

Always trace state and conditions far enough to establish the computation:
input origin, valid attention domain, producer/consumer layer ranges, update
conditions, shared mutable state, recurrence, and branch/merge semantics. A cache,
guard, quantization or alias is not automatically an optional implementation fact.
If omitting it changes which value is consumed, when it is valid, which branch
executes or the mathematical result, represent it in algorithm nodes/edges and
applicable state/shape contracts. Repeated instances may use proven templates and
explicit layer ranges; forty identical cache implementations need not be copied.

Inventory extension boundaries encountered in the pinned model sources. Defer
physical cache slots, attribute handoff mechanics, scheduling, dispatch, kernel
internals and backend alternatives when they do not alter the represented model
semantics and are not requested. Do not research every available backend just to
complete the default algorithm diagram. Record source anchors for later expansion.
Missing evidence for required mathematics remains blocking.

## Machine-readable scope

Keep `analysis_scope` in the same canonical `architecture.json`; IDs and evidence
are shared with future extensions. The generated ASCII includes this inventory
as a ledger, not as invented operator regions or runtime paths.

```json
{
  "analysis_scope": {
    "policy": "complete-algorithm-with-runtime-inventory",
    "algorithm_coverage": "complete-model-logical-operators",
    "inventory_basis": "Inspected model forward and its cache helper at the pinned revision.",
    "runtime_inventory": [{
      "id": "cache-slot-addressing",
      "categories": ["prefill", "decode"],
      "evidence": ["model"],
      "source": "model.py:120-145 Cache.write",
      "affects_algorithm": false,
      "algorithm_nodes": [],
      "disposition": "deferred",
      "expanded_views": [],
      "semantic_boundary": "Logical valid-token reads and update guards remain in the attention graph; this entry covers physical slots only.",
      "reason": "Physical ring offsets preserve the logical token sequence and are not needed for the requested algorithm diagram."
    }]
  }
}
```

Inventory each distinct extension boundary, not each low-level statement.
`categories` contains applicable `prefill`, `decode`, and/or `backend` categories.
`disposition` is `algorithm`, `expanded`, or `deferred`. Algorithm-affecting entries
must map nonempty `algorithm_nodes` to real algorithm/shared-interface nodes and
cannot be deferred. The semantic boundary records actual producers, consumers,
guards and visibility where applicable; the linked graph must express them too.
Use separate entries for logical state semantics and deferred physical mechanics.

`expanded` entries name existing, nonempty runtime `expanded_views` covering all
their categories. Selecting a runtime category requires expansion of every matching
entry, including entries previously represented only at algorithm abstraction.
The normal source closure, runtime variant, state lifecycle, shape and independent
review checks still apply to every expanded region. Unknown required runtime
evidence blocks that requested view; an empty placeholder view cannot satisfy it.

At a deferred helper boundary in an inventoried forward path, use the source
operation disposition `deferred-runtime` and `runtime_extension: INVENTORY_ID`.
It may reference only a deferred, non-algorithm entry citing that path's evidence.
It cannot also claim node/region/fusion coverage. A helper containing mathematical
operators must first expose those operations; never defer a mixed helper wholesale.
Do not enumerate the helper's entire implementation solely to mark it deferred.
Ordinary `out-of-scope` and `unresolved` remain invalid for complete-hierarchy.

## Independent acceptance

The Reviewer first traces source, then checks inventory completeness and each
boundary. In addition to the existing review sections, it fills:

```json
{
  "analysis_scope_review": {
    "status": "pass",
    "inventory_complete": true,
    "finding": "Source tracing confirms every model family and all algorithm-relevant state dependencies are represented.",
    "items": {
      "cache-slot-addressing": {
        "status": "pass",
        "disposition": "deferred",
        "evidence": ["model"],
        "source": "model.py:120-145 Cache.write",
        "finding": "Physical slot arithmetic preserves the ordered logical cache domain already represented by the attention nodes."
      }
    }
  }
}
```

An empty inventory still needs an independent source-grounded completeness finding.
The finalizer checks exact inventory coverage, matching dispositions and evidence;
the existing receipt binds these decisions, scope, ASCII, IR and source bytes.
Builder cannot reclassify a Reviewer FAIL as optional or copy an old PASS across
scope changes. Reviewer must explain why a deferred detail has no omitted
computational effect. Fields cannot prove source understanding or prevent same-user
forgery; existing host-enforcement limits remain unchanged.

Findings should identify algorithm semantics, Prefill/Decode execution or backend
implementation as their affected scope, with source and stable IDs. Errors in any
materialized graph remain blocking even when that graph is not being delivered.
Unexpanded implementation work may remain in the reviewed inventory. Do not turn
an incorrect runtime graph into accepted content by unchecking its output view.

## Expansion, migration and repair

Changing files, layout or selecting already-reviewed views reuses review. Expanding
an inventory entry changes semantics: update its source inventory, nodes, edges,
views and ASCII, then obtain a fresh independent review. Preserve prior evidence
and IDs. If source revisions changed, revalidate the affected assumptions first.

Migration from legacy full-runtime policy requires an actual authorized scope
change, preserving prior intake and review records. Create and confirm a new-policy
intake from that authorization; do not re-sign the old confirmation automatically.
Existing runtime graphs can remain fully audited. Removing them requires explicit
semantic revision, retained algorithm dependencies and fresh scope review.

Group repairs by subsystem and fix shared root causes, retracing its inputs,
outputs, guards and state before another review. After three non-improving attempts,
replan within the autonomous task. Reuse source observations as references, but
do not inherit per-region PASS across semantic changes: validated dependency-based
partial certification is not yet implemented. The current receipt still audits all
materialized regions plus the much smaller extension-boundary inventory.
