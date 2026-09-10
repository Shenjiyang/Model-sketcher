# Granularity contracts

Read this reference before creating or revising Level-2/Level-3 detail regions, operator/FLOPs views, or any diagram where sibling nodes expose implementation steps.

Granularity classification governs how inventoried source operations may be represented. Build and validate the upstream inventory according to [source-operation-coverage.md](source-operation-coverage.md); do not use a coarse granularity choice to make source operations disappear.

## Declare the region mode first

Classify every detailed region before drawing nodes:

- `module-summary`: named modules and short semantic qualifiers are the leaves. Internal operator chains remain folded.
- `operator-detail`: executable arithmetic, parameterized operations, activations, reductions, and shape/view operations are the leaves.
- `implementation-detail`: kernels, cache/state paths, runtime branches, or backend-specific fused execution are the leaves.

The label `Level 2` or `Level 3` does not select a mode by itself. The content and stated purpose do. A region used directly for FLOPs accounting is `operator-detail` even when it appears inside a hierarchy master.

Granularity says how far a visible region is decomposed; it does not decide whether that region belongs in the current reader view. Apply [view-projection-contract.md](view-projection-contract.md) separately so an implementation-detail region can remain complete in the canonical IR without appearing in the algorithm master.

Every region at every level and granularity uses one mandatory internal-flow grammar: ordered small blocks run vertically bottom-to-top. Put inputs at the bottom, outputs at the top, parallel branches in adjacent vertical lanes, and cache or recurrent state to the side. This includes Level 0 and Level 1 `module-summary` regions. Horizontal adjacency is legal only for source-backed parallel branches such as Q/K/V, experts, or alternative implementations; each lane still runs bottom-to-top. A sequential horizontal chain is never legal. The rule does not constrain the macro placement of large titled child regions or the direction of hierarchy-expansion arrows.

The rule is unconditional for compiler-path projects; there is no project-level compatibility switch. Declare it on every region. Use `child_direction` separately when large child regions should be arranged horizontally:

```json
"regions": {
  "mixer_detail": {
    "direction": "column",
    "flow_direction": "bottom-to-top",
    "child_direction": "row",
    "granularity": "operator-detail"
  }
}
```

The IR validator rejects any other internal direction. Every region with two or more semantic small blocks declares complete `operator_sequences`; multiple sequences declare parallel vertical lanes and may share branch or merge nodes. The layout planner places increasing sequence depth upward, and the compiler plus generated Draw.io manifest reject a refined layout when any adjacent pair fails to rise.

## Build a complete node ledger

Before geometry, classify every visible non-decorative node in the region as exactly one of:

- atomic arithmetic or activation;
- parameterized operation;
- zero-arithmetic tensor/view operation;
- state/cache;
- interface or junction;
- code-confirmed execution fusion boundary;
- named module boundary;
- composite expanded elsewhere.

Do this for the entire affected region, not only the nodes mentioned by the user. A targeted change invalidates the sibling-granularity review for that region.

## Operator-detail invariant

In an `operator-detail` region, one ordinary box represents one logical tensor operation or one zero-arithmetic tensor/view transformation. A source function, API call, or fused kernel is not automatically one logical operator. Do not put a normal sequence such as these in one box:

```text
Linear -> divide -> SiLU -> Linear -> sigmoid
Conv1D -> activation
RMSNorm -> LM Head
reshape -> repeat -> normalize
```

A multi-operation sequence may not remain in one ordinary operator box merely because executable source fuses it. Keep its logical nodes and record their `execution_fusions` membership according to [logical-operator-contract.md](logical-operator-contract.md). A compact named boundary is legal only as `expanded-elsewhere`, with the concrete detail region identified. An `implementation-detail` region may use a fused-kernel leaf, but it must map back to the logical operator IDs it implements.

Backend fusion is execution evidence, not an operator-detail stopping rule. A view/reshape may have zero arithmetic FLOPs, but show it when it changes the rank, broadcast rule, head layout, or later FLOPs domain.

Keep visual fields separated according to [overview-level-contract.md](overview-level-contract.md):
the operator block names the logical action, tensor edges carry activation shapes, parameter
dimensions live in external annotations or structured IR, and exact code identifiers live in
`source_symbols` or an optional subordinate source-alias line. Do not write `[B,S,D]`,
`[N,H,Dh]`, or `7168 -> 896` inside an ordinary operator label. Boundary interface, cache, and
persistent-state nodes may show their own shape because that tensor is the identity of the node.

Treat `op_type: custom` as a reviewed mathematical primitive, not a convenient unknown bucket.
It requires a concrete definition, formula, and explanation of why the formula is atomic at the
selected detail level. Decompose a fused or multi-step transform when those fields cannot be
provided.

## Draw.io manifest contract

For editable Draw.io diagrams, declare governed regions in `granularity_contracts`. Keep region and cell IDs project-specific; the rule and auditor remain reusable.

```json
"granularity_contracts": {
  "operator_region": {
    "mode": "operator-detail",
    "allowed_composites": {
      "mixer": {
        "classification": "expanded-elsewhere",
        "evidence": "code/config confirmed",
        "detail_target": "mixer_runtime_region",
        "reason": "The canonical logical expansion is shown once."
      }
    },
    "node_exclusions": {
      "decorative_marker": "Non-semantic alignment marker."
    }
  }
}
```

For a new diagram or a substantial revision spanning detail regions, enable the completeness gate:

```json
"require_granularity_contracts": true
```

By default this requires contracts for declared region titles containing `Level 2`, `Level 3`, `FLOP`, or `operator`. Override `granularity_region_patterns` only when the diagram uses a different explicit naming scheme; do not weaken it to avoid reviewing existing regions. During a bounded targeted revision of a legacy diagram, contracts may be introduced for the affected regions first, but report the remaining uncontracted regions as migration debt rather than claiming a whole-diagram granularity audit.

The generic auditor detects labels containing multiple known operator terms inside `operator-detail` regions. Detection is a backstop, not the source of semantic truth: visually inspect every node ledger entry, and register legitimate composites rather than disguising their labels to evade the check.

## Review gate

Before acceptance:

1. compare all sibling nodes in every affected detail region;
2. confirm every multi-operation box has an allowed classification and evidence;
3. confirm tensor shapes remain on edges and weight shapes remain side annotations;
4. run the static auditor with the project manifest;
5. inspect the official Draw.io export at detail scale.

Do not report a region as completely reviewed when only the originally reported node was inspected.
