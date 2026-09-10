# ASCII topology contract

Read this reference when creating or revising the pre-layout topology of a compiler-path project.

The generated ASCII contract is a review artifact, not a second semantic source. Author facts in `architecture.json`, generate the contract, review it, and change the IR when it is wrong. Never hand-edit generated text and leave the IR unchanged.

After a cold-start generation or any semantic/source revision, run the independent checkpoint in [topology-review-workflow.md](topology-review-workflow.md). The Reviewer must decide whether the ASCII alone can reconstruct the Level-0 synopsis, Level-1 templates, every detail sequence, branch/merge and state lifecycle, and all cross-level mappings. Do not repeat that Reviewer for coordinate, route, hierarchy-arrow, typography, color, density, or render-only work; reuse the digest-bound review while the canonical architecture meaning, exact ASCII bytes, and pinned source bytes remain unchanged.

The generator emits `DETAIL INFORMATION GAIN`, `RUNTIME VARIANT COVERAGE`, and `STATE / CACHE LIFECYCLES` before ownership and geometry. Use them to reject decorative detail, a collapsed prefill/decode branch, or a false `write -> storage -> module output` chain without opening Draw.io.

## Required separation

Keep these concepts separate:

- **Level-0 standalone synopsis:** which visible model-level nodes communicate the model identity, heterogeneous backbone, branches, and output without relying on detail panels.
- **Level-1 template coverage:** which complete representative sequence corresponds to each materially distinct fixed layer family and where it is summarized in Level 0.
- **Cross-level interface closure:** how parent and child shapes correspond at every hierarchy expansion, including visible flatten/head-layout mappings.
- **Operator display roles:** where reader names, activation shapes, parameter shapes, and exact source symbols are stored or rendered.
- **Source-operation coverage:** which material source operations were inventoried and how each maps into the IR.
- **Ownership tree:** which region owns each definition.
- **Region nodes:** the complete semantic inventory at that region's declared granularity.
- **Operator sequences:** source-backed execution lanes inside every `operator-detail` and `implementation-detail` region.
- **Additional edges:** branches, joins, cache/state edges, calls, injections, and reuse not consumed by one linear sequence.

Level 0 and Level 1 normally remain `module-summary`; do not expand every operation into the overview. They still declare complete `operator_sequences` whenever they contain two or more semantic blocks. Level 2 and Level 3 detail regions always declare `operator_sequences`. An ordinary operation such as RMSNorm, projection, activation, reshape, cache update, or reduction is its own node. Operator-detail entries report `classification`, `op_type`, `shape_rule`, every declared `shape_equation`, and sorted structured `parameter_shapes`, so reviewers can compare sibling stopping rules, direct edge-shape closure, and weight dimensions without reopening JSON. Packed operations additionally print their view-only decomposition path and every edge-bound packed output; `expanded-elsewhere` entries print their concrete target region and reason. Repetition boundaries and counts have their own generated section. Executable fusion is reported separately and never erases logical nodes from `operator-detail`.

For every `op_type: custom` leaf, the generated node ledger also prints its definition, formula, and atomicity reason; a reviewer must not need to reopen raw JSON to discover what `Core`, `Transform`, or `Update` hides.

All sequences at every level and granularity are laid out vertically and read bottom-to-top. The generated contract reports `layout_axis: column` and `flow_direction: bottom-to-top`. Multiple source-backed parallel sequences may form adjacent vertical lanes. Macro placement of large child regions uses `child_direction` and remains independent, as does hierarchy-expansion direction; these visual choices are intentionally absent from the semantic ASCII contract.

## IR form

Every detail region declares one or more named lanes:

```json
"mixer_detail": {
  "label": "Level 2 - Mixer operator detail",
  "parent": null,
  "direction": "column",
  "flow_direction": "bottom-to-top",
  "order": 1,
  "level": 2,
  "granularity": "operator-detail",
  "operator_sequences": [
    {"id": "main", "nodes": ["x", "pre_norm", "q_proj", "attention", "o_proj", "y"]},
    {"id": "kv_cache", "nodes": ["x", "kv_proj", "kv_reshape", "cache_update", "attention"]}
  ]
}
```

Each adjacent pair in a sequence must have one or more directed `tensor` edges in the IR; `uses`, `injects`, `reuses`, and `expand` relations never satisfy execution adjacency. When several tensors travel between the same pair, the generated sequence transition prints every edge ID and shape instead of choosing one arbitrarily. Every non-junction node owned directly by a detail region must occur in at least one sequence. Shared sources, consumers, and joins may occur in multiple sequences.

## Review rule

### Indexed recurrence domains

When a logical recurrence consumes one request/token at a time but projections
use packed tokens, declare `regions.<id>.loop_contract`. Do not equate total
packed tokens with request count or feed every query from one final state.

```json
"loop_contract": {
  "domain": "For request b and local t: n=cu_seqlens[b]+t; N=sum(lengths)",
  "step_inputs": ["query_at_t", "key_at_t", "value_at_t"],
  "state_input": "previous_state",
  "state_output": "updated_state",
  "feedback": "Updated state at t supplies the same request at t+1; t=0 uses initial state",
  "output_assembly": "stack_token_outputs",
  "physical_execution": "Logical recurrence may execute as a parallel prefill scan; no trajectory allocation asserted",
  "evidence": ["executable-source"],
  "source": "recurrence.py:100-150"
}
```

All referenced nodes belong to the region. State endpoints are persistent
state/cache boundaries, not sequence members; step inputs and output assembly
occur in operator sequences. The generator prints the domain, feedback,
assembly and source beside those sequences. Every view retaining the region
must retain these loop endpoints; partial filtering fails rather than silently
leaving a misleading loop. This contract supplements logical operators and
does not prove recurrence algebra or replace explicit per-step decomposition.

Reject the contract before layout when:

- Level 0 is a generic input/stack/output chain that does not name the source-backed layer families, cadence, state mechanisms, model-level branches, and readout needed to recognize the model;
- a Level-1 template sequence lacks an exact Level-0 summary mapping;
- an expansion silently changes tensor axes or symbols without a visible interface mapping;
- an operator box contains activation/parameter dimensions, or a custom operator lacks a formula and atomicity justification;
- a selected source path is absent, empty, or contains an unmapped/unresolved material operation;
- the ownership tree names the wrong parent;
- a displayed detail region lacks a complete operator sequence;
- one box silently combines multiple ordinary operations;
- a packed parameterized operation omits its packed tensor, view-only decomposition path, explicit unpack operation, or edge-bound independent output lanes;
- a fused source call is not mapped to the logical operator IDs it implements;
- a branch source or consumer is absent;
- a cache/state node has no incoming or outgoing relation;
- sequence order disagrees with the executable forward path;
- a detail tensor edge lacks a structured shape/status, or an unresolved shape is shown as established.

The contract intentionally uses stable IDs and deterministic ordering. JSON object-key order, review-only prose, visual/layout-only fields, and region/node `order` hints must not alter its bytes; explicit `operator_sequences` own execution order. Reviewers should be able to point to `region_id`, `sequence_id`, `node_id`, or `edge_id` without describing a location on the canvas.

Run [the operator-detail IR example](../assets/operator-detail-ir-example.json) through `render_topology_contract.py` when a concrete RMSNorm/projection/reshape/cache example is useful. It is a syntax and granularity example only, not evidence for a real model.
