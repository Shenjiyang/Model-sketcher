# Source-operation coverage

Read this reference for every compiler-path diagram and topology revision. Its purpose is to prevent a detailed executable forward path from being silently collapsed into a few generic boxes before the architecture IR is built. Source coverage is mandatory for strict logical-operator work; an older IR without it is migration input, not a valid project.

## Inventory boundary

Choose and pin the executable forward paths first. Prefer version-matched `canonical-model` evidence. An inference-framework implementation may support a bounded `selected-paths` study, but it does not become canonical merely because it is locally available.

Inventory material executable operations in source order, including:

- parameterized calls and projections;
- normalization, activation, arithmetic, reductions, masking, routing, and dispatch;
- reshape, split, concatenate, repeat, transpose, broadcast, or other view operations that change later shape or FLOPs reasoning;
- cache reads/writes, recurrent-state updates, and materially different runtime branches;
- calls into child modules whose internals are represented by a concrete detail region.

Do not inventory ordinary Python bookkeeping, logging, assertions, container construction, or return-object packaging unless it changes the represented execution semantics. The inventory is a reviewed extraction from source; the validator can prove that inventoried items are mapped, but it cannot discover an operation that was omitted from the inventory. Review the source and inventory side by side before accepting this gate.

Source completeness does not require every inventoried operation to appear on the same reader-facing page. After mapping every operation into the canonical IR, use [view-projection-contract.md](view-projection-contract.md) to route model mathematics, inference execution, and backend implementation into appropriate projections. A view assignment is presentation metadata, not an `out-of-scope` status.

## IR contract

Set `project.require_source_coverage: true`; omitting or disabling it is a validation failure whenever strict logical-operator contracts are enabled. Add:

```json
"source_coverage": {
  "scope": "complete-hierarchy",
  "canonical_source_ids": ["official-model"],
  "paths": [
    {
      "id": "decoder-forward",
      "evidence": "official-model",
      "source": "modeling.py:410-470",
      "regions": ["decoder", "mixer_detail"],
      "operations": [
        {
          "id": "decoder.input_norm",
          "label": "Input RMSNorm",
          "status": "visible-node",
          "node": "input_norm",
          "source": "modeling.py:426"
        },
        {
          "id": "decoder.mixer",
          "label": "Mixer call",
          "status": "expanded-in-region",
          "region": "mixer_detail",
          "source": "modeling.py:430"
        }
      ]
    }
  ],
  "reconciliation": {
    "status": "pass",
    "method": "independent-source-reread",
    "reviewed_path_ids": ["decoder-forward"],
    "architecture_changed": true,
    "findings": ["Added the output activation omitted by the first IR draft."]
  }
}
```

IDs are stable and unique. Every path names its executable evidence, exact source range, governed regions, and a non-empty ordered operation list. Every operation has its own source locator and exactly one disposition:

- `visible-node`: maps to one visible IR node.
- `source-confirmed-fusion`: legacy/implementation-detail mapping to one visible fused-kernel node with a source-backed `reason`; it may not collapse logical members in strict `operator-detail`.
- `fused-execution-group`: maps one fused source call to an `execution_fusions` record whose member logical operators remain visible.
- `expanded-in-region`: maps a child-module call to a concrete `operator-detail` or `implementation-detail` region.
- `out-of-scope`: allowed only for a bounded `selected-paths` contract and includes a reason.
- `unresolved`: allowed only as explicit debt in `selected-paths` work and includes a reason.

For `complete-hierarchy`, declare at least one canonical source and use canonical evidence for every governed path. `out-of-scope` and `unresolved` are blocking because they contradict a completeness claim. For `selected-paths`, keep exclusions and uncertainty visible in both the contract and `project-state.json.source_coverage_debt`; do not describe the whole diagram as source-complete.

Mapped nodes must cite the same executable evidence as their path and belong to one of the path's governed regions. A mapped node inside a detail region must also occur in that region's `operator_sequences`. An `expanded-in-region` target must be a detail region containing nodes backed by the path evidence.

An `expanded-elsewhere` boundary inside `operator-detail` may point only to another `operator-detail` region. A kernel, cache, dispatch, or prefill/decode expansion in `implementation-detail` does not satisfy missing mathematical operators. Keep the logical operations visible, then map their physical fusion to implementation nodes separately.

## Review and repair

After the first IR draft, put the IR aside and reopen every pinned source range. Walk the executable path again from source to sink without using the existing node list as a checklist. Compare that fresh pass with the inventory, question every composite/core/fused label, and update the inventory and IR before recording `reconciliation`. Its `reviewed_path_ids` must cover every path, `architecture_changed` states whether the second pass changed the IR, and `findings` records concrete corrections or an explicit no-omission result. This is a source-first adversarial review, not a reread of the generated contract.

Then generate `topology.contract.txt` and review its `SOURCE OPERATION COVERAGE` section beside the pinned source. Check operation order, runtime branches, child calls, output epilogues, state/cache updates, and every fusion or exclusion. Repair omissions in this order:

1. source inventory;
2. operation disposition and evidence;
3. IR nodes, regions, and edges;
4. detail-region operator sequences;
5. geometry.

Never add a fake node merely to make the gate pass. If source semantics remain uncertain, retain explicit debt in a bounded contract or gather better evidence before claiming a complete hierarchy.
