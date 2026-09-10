# Canonical IR and reader-view projections

Read this reference when one source-grounded architecture contains model mathematics, inference paths, and backend implementations. Completeness belongs to the canonical IR; visual inclusion belongs to an explicit projection. Never reduce source coverage merely to make one page readable.

## Separate semantic layers

Classify every region, node, and edge with exactly one `semantic_layer`:

- `model-algorithm`: checkpoint/config-defined mathematics, learned projections, logical tensor operations, model-specific routing, and recurrent state that changes the model function;
- `inference-execution`: prefill/decode paths, cache reads and writes, scheduling or recovery paths, and state lifecycle operations needed to explain inference but not the model definition itself;
- `backend-implementation`: deployment-selected distributed collectives, DCP, paged-cache physical layout, fused kernels, hardware-specific paths, and fallbacks;
- `shared-interface`: an input, output, or boundary tensor legitimately reused across layers.

Fusion does not move its logical members out of `model-algorithm`. Record the physical fused implementation separately. KV-cache storage and access are normally `inference-execution`; a learned or mathematically required recurrent state update such as an SSM/KDA recurrence remains `model-algorithm`, while its storage implementation may have a separate runtime representation.

## Declare projections

Set `project.require_view_projection_contracts: true`, choose `project.semantic_view`, and add a `view_projection_contract`. Every region, node, and edge has a non-empty `views` list naming declared projections.

```json
{
  "project": {
    "semantic_view": "model-algorithm",
    "require_view_projection_contracts": true
  },
  "view_projection_contract": {
    "status": "pass",
    "method": "canonical-ir-projection-review",
    "views": {
      "model-algorithm": {
        "kind": "algorithm-master",
        "purpose": "Reader-facing mathematical architecture"
      },
      "prefill-decode": {
        "kind": "inference-runtime",
        "purpose": "Prefill/decode shapes, cache access, and state transitions"
      },
      "distributed-backend": {
        "kind": "backend-runtime",
        "purpose": "DCP, communication, paged storage, kernels, and fallbacks"
      }
    },
    "checks": [
      "canonical-entity-disposition",
      "algorithm-backend-separation",
      "model-semantics-retained",
      "runtime-variant-placement"
    ],
    "findings": ["Every canonical entity has a reader-view disposition."]
  }
}
```

An algorithm master is mandatory. Add an inference-runtime view when the canonical IR contains inference-execution entities, and a backend-runtime view when it contains backend-implementation entities. Add `operator-flops` only when FLOPs or operator accounting is requested; state the counting convention and retain zero-FLOP shape transforms needed for domain closure.

## Projection invariants

- Every canonical entity belongs to at least one declared view. View filtering is not an out-of-scope disposition and cannot hide missing source operations.
- Every `model-algorithm` entity appears in an `algorithm-master` projection.
- `inference-execution` and `backend-implementation` entities do not appear in an algorithm master. Reclassify a genuinely model-semantic state mechanism instead of creating an exception.
- Every visible child region is visible with its ancestor regions. A node is visible only with its owner region. An edge is visible only when both endpoints are visible in that view.
- Sequence projection retains adjacency only when the selected view contains an explicit tensor edge. Hidden operations never imply a new shortcut: disconnected remnants become separately named sequence parts. Review their boundary completeness before layout; splitting a sequence is not proof that the view tells a complete execution story.
- Prefill and decode use separate sequences in an inference view whenever shapes, attention domains, operators, cache/state behavior, communication, dtype, or kernels materially differ.
- DCP/non-DCP, fused/unfused, Flash/eager, DeepGEMM/fallback, and physical paged-cache alternatives normally share one logical model node and separate only in backend-runtime.
- A projection selector changes presentation, not canonical evidence. The generated ASCII records the complete ledger plus every entity's semantic layer and view membership, but not the currently selected layout view; Reviewer and semantic digests remain bound to the canonical IR and can be reused when only `project.semantic_view` changes.

The layout planner, compiler, and generated audit manifest materialize only `project.semantic_view`. Change that selector and generate a separate layout/output from the same canonical architecture. Do not manually delete hidden entities or maintain independent semantic IR copies for the views.

The gated pipeline also accepts `--semantic-view VIEW_ID`: it selects the view in memory after validating the canonical review, without rewriting `architecture.json`. The generated layout records `semantic_view`; compiler and manifest generation honor that field and reject attempts to switch an already materialized projection.

Projection must scope nested contracts as well as visual entities. Only fully retained sequences support a canonical runtime variant. Filter cross-level/display contracts and local state readers/writers; keep omitted lifecycle and fusion mappings in `external_canonical_references`, never as nonexistent local cells or fabricated initialization reasons. A page selecting one runtime variant is not proof that the source has no alternatives. Strict delivery recomputes these records from the canonical IR to reject forged projection metadata.

## Review questions

Before layout, inspect the generated `VIEW PROJECTIONS` section and answer:

1. Can the algorithm master explain the checkpoint's distinctive model function without backend knowledge?
2. Did any model-semantic branch disappear merely because its source is fused or runtime-dependent?
3. Are Prefill/Decode and cache/state differences routed to the inference view rather than mixed into the model spine?
4. Are distributed, physical-layout, kernel, and fallback alternatives confined to the backend view unless that is the requested primary deliverable?
5. Can every source operation still be traced through the canonical IR regardless of which projection is rendered?
