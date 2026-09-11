# Detail value, runtime variants, and state lifecycles

Use this contract before accepting any Level 2/3 expansion or implementation-detail region. It prevents a child region from merely restating its parent and prevents persistent state from being drawn as an ordinary sequential operator.

## Information gain is semantic, not a node-count threshold

Every `kind: expand` relation whose child is Level 2 or Level 3 must have one `detail_information_gain_contracts.<edge-id>` entry. The entry maps the exact parent and child regions and records at least one visible, evidence-backed delta. Valid delta kinds are:

- `logical-decomposition`
- `runtime-variant`
- `state-lifecycle`
- `kernel-fusion`
- `communication`
- `physical-layout`
- `dtype-or-quantization`
- `addressing-or-indexing`

A compact two-node detail can be valuable if it exposes a real delta; a ten-node restatement is not. If the reviewer cannot name new information and point to its child nodes, delete the expansion and fold the fact into the parent rather than inventing boxes.

```json
"detail_information_gain_contracts": {
  "expand_mla_runtime": {
    "parent_region": "mla",
    "child_region": "runtime_mla",
    "status": "pass",
    "method": "parent-child-delta-review",
    "new_information": [{
      "kind": "runtime-variant",
      "summary": "Prefill and decode use different execution paths",
      "nodes": ["prefill_kernel", "decode_kernel"],
      "evidence": ["runtime-source"]
    }],
    "findings": ["The child adds executable branch and cache behavior absent from Level 2."]
  }
}
```

## Runtime variants

Every `implementation-detail` region requires a `runtime_variant_contracts` entry. When source branches materially alter operators, cache access, communication, shapes, dtype, or kernels, use `status: pass`, list the source discriminators, and map at least two variants to real `operator_sequences`. Prefill/decode and cached/uncached paths are common examples. Shared state must be a visible cache/state node listed in `shared_state_nodes`.

Use `status: not-applicable` only after a source-branch review proves that the region has one material execution path. Record a source-backed reason, evidence, and findings. Static configuration must not be fabricated as a runtime decision diamond.

## Persistent state is a side-lane object

Apply [analysis-scope-contract.md](analysis-scope-contract.md) before choosing the
state abstraction. Algorithm graphs require logical storage shape, visibility,
producers, consumers and validity/update guards. Their `layout` and addressing
facts can describe logical token order or layer ranges; do not require physical
slots, Python attribute aliases or backend paging solely to fill these fields.
Physical details belong in requested runtime extensions. Every materialized state
object still requires the lifecycle contract below.

Use `kind: cache` or `kind: state` only for persistent storage. Cache read, cache write, cache update, and recurrent update are `kind: operator` nodes with the corresponding `operator_contract.op_type`. Persistent state uses the canonical slanted storage glyph and never appears in an `operator_sequence`.

Every persistent object requires one `state_lifecycle_contracts.<node-id>` entry with:

- `storage_shape`, `layout`, `dtype`, `scope`, and `lifetime`;
- at least one writer, or an explicit `initial_state_reason`;
- at least one reader, or an explicit `output_state_reason`;
- exact tensor edges connecting `writer operation -> state` and `state -> reader operation`;
- addressing/indexing facts such as `slot_mapping`, `block_table`, positions, or sequence lengths;
- executable-source evidence.

The reader must be the operation that actually consumes the cached tensor, not a convenient whole-module output. A cache edge is an additional side relation, not permission to write `update -> cache -> final output` as the main compute sequence.

## Recursive source closure

`expanded-in-region` is only an entry mapping. The target detail region must have direct source-operation mappings for each material operator/cache/state node it owns. One umbrella operation saying “runtime expanded here” cannot stand in for the child inventory.

Review these contracts in the generated ASCII sections `DETAIL INFORMATION GAIN`, `RUNTIME VARIANT COVERAGE`, and `STATE / CACHE LIFECYCLES` before layout.
