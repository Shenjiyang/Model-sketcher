# Source expectations and IR consistency

Use this reference when authoring topology or performing its independent review.
It extends the existing Reviewer; it does not add another agent or reflection report.

## Builder

Build tensor edges from actual producer/consumer expressions, not the order of a
Python statement list or desired placement. Independent assignments from `x` are
parallel data branches even if Python executes the assignments sequentially.
For example, `q=q_proj(x); kv=kv_proj(x)` must not become `q -> kv`.
Shared experts consume the original expert input, not the routed expert result.
Early returns and mutually exclusive execution branches are not consecutive steps.

`scripts/ir_graph_builder.py` offers `add_tensor_edge` and `add_lane`. The latter
records a sequence only; it never manufactures edges or assigns default shapes.
Equivalent project helpers are allowed. An explicit chain helper is appropriate
only after source tracing proves every adjacent data dependency. The existing IR
validator still requires actual tensor edges between sequence members; split a
false lane instead of adding invented edges to satisfy this requirement.

Before scheduling review, run the existing IR validator and:

```bash
python scripts/semantic_consistency.py architecture.json
```

This fast lint reports review questions and exits successfully; it is not semantic
acceptance. The preparer includes the same questions in the pending review. A group
of preserve activations or a suspicious operator label is a reason to inspect
source, not proof of an error. Equal shapes, repeated source symbols and identical
shared prefill/decode algorithm sequences alone are never hard failures here.
Repair confirmed defects before review. Do not generate stock source-confirmed
resolutions in a Builder script.

## Reviewer

First trace the pinned source independently as already required by
`topology-review-workflow.md`. Persist observations about input producers, output
consumers, shape changes, independent branches and conditional execution in that
inventory before comparing Builder's nodes. Then map those observations to stable
IR IDs in `semantic_expectations`. Do not produce expected values by copying IR
edges, parsing generated ASCII, or running an IR-to-expectations script. Synthetic
test fixtures are the only place where automatic expected-value copying is valid.

The mandatory block uses `ruleset: semantic-consistency-v1`. It is included in the
existing finalized receipt and checked on every review reuse. Older reviews need
a fresh independent review with these comparisons; never upgrade them by merely
inserting the new fields. No separate review service or model upgrade is required.

`regions` maps every canonical region, including summaries and undelivered views,
to one record:

```json
{
  "source_refs": [{"evidence_id": "model", "line_start": 770, "line_end": 780}],
  "reason": "Q and window KV each consume the normalized input and meet at attention.",
  "incoming_dependencies": [
    ["input", "q_proj", "[B,S,5120]"],
    ["input", "kv_proj", "[B,S,5120]"],
    ["q_proj", "attention", "[B,S,1280]"],
    ["kv_proj", "attention", "[B,S,512]"]
  ],
  "operators": {
    "q_proj": ["linear", "transform"],
    "kv_proj": ["linear", "transform"],
    "attention": ["custom", "custom"]
  }
}
```

The example illustrates record syntax, not a complete model attention definition.
Each dependency is `[producer_id, consumer_id, expected_shape]`. Include every
tensor edge whose TARGET is in this region, including cross-region inputs. Empty
lists are valid for regions without incoming tensor edges. Multiplicity matters:
two equal-shaped operands remain two dependencies. A missing or extra dependency,
wrong endpoint, or wrong shape blocks PASS and reports the affected edge IDs.
Use the IR's declared symbolic vocabulary after independently verifying what the
symbols and transformations mean; this checker does not solve symbolic algebra.

`operators` covers exactly the region's contracted non-expanded operators with
`[expected_op_type, expected_shape_rule]`. Shapes, types and rules must be sourced,
not selected merely because the validator permits them. The existing logical
operator validator continues to check shape equations and parameter annotations.
Module summaries and expanded boundaries remain covered by the original source
inventory, scope, granularity and reconstruction checks.

`branch_claims` records source-discovered parallel and exclusive relationships:

```json
[
  {
    "kind": "parallel",
    "groups": [["q_proj", "q_norm"], ["kv_proj", "kv_norm"]],
    "joins": ["attention"],
    "source_refs": [{"evidence_id": "model", "line_start": 770, "line_end": 780}]
  }
]
```

Groups contain disjoint branch interiors. Shared prefixes and suffixes stay
outside the groups. `parallel` forbids directed tensor paths between groups
before a declared join; each join must be reachable from all groups. Joins may be
empty when convergence is outside the represented graph. `exclusive` forbids
tensor paths between its groups and uses an empty `joins` list. Cross-invocation
state transfer must use the project's explicit state lifecycle rather than a
fake same-invocation tensor chain. Shared algorithm sequences need no artificial
exclusive claim; apply claims to the genuinely distinct execution operations.
An empty claim list is valid only when source tracing finds no applicable branches.
The existing branch-and-merge review must challenge omitted claims. Reachability
checks verify the claim against IR, not whether the source warrants the claim.

`lint_resolutions` maps every current lint question ID to:

```json
{
  "disposition": "source-confirmed",
  "reason": "These three source calls are independent elementwise activations with unchanged dimensions.",
  "source_refs": [{"evidence_id": "model", "line_start": 10, "line_end": 15}]
}
```

Unresolved questions block finalization, while legitimate source-confirmed
exceptions pass. Actual defects must be fixed in IR and reviewed again; a prose
resolution cannot override dependency or type contradictions. The gate recomputes
questions rather than trusting the pending artifact's diagnostic list. References
must name pinned evidence and existing line ranges. The Reviewer remains responsible
for checking the meaning of those lines.

Classify semantic layers by function and selected abstraction: quantization can
define model mathematics and state can define the algorithm. Do not classify by
keywords alone. Physical paging and device communication usually belong in a
backend projection. Keep the existing source-grounded view review.

## Limits and reuse

The checker proves consistency between independent expectations and IR, not that
an LLM read or understood source. Same-account receipts are not identity proofs.
Do not claim that this update prevents arbitrary shell/XML bypass or fabricated
matching expectations; those require host-level isolation or enforcement.

The existing source/semantic/ASCII digests and receipt cover these records. The
ruleset version identifies this comparison policy; bump it when acceptance rules
change incompatibly. Layout-only changes reuse the current review without another
LLM call. Semantic changes still require the existing complete review: do not
introduce unvalidated per-region PASS inheritance to save time.
