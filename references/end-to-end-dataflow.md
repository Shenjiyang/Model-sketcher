# End-to-end dependency/dataflow view

Use this view to make every requested output traceable back to its inputs on one canvas. It is a curated execution graph, not a fully unrolled framework graph and not a hierarchy-page collage.

## Contract

Before geometry, extend the shared shape ledger with a dependency ledger containing:

- every external input, persistent/cache state, side-branch input, and requested output;
- producer and consumer identifiers for each tensor edge;
- edge shape and symbol definitions;
- call count or repetition scope;
- branch fan-out, merge, injection, residual, and state-update semantics;
- whether a repeated call reuses one implementation or executes a distinct topology;
- evidence status for every material dependency.

Write one continuous topology contract from inputs to outputs. A reader must be able to start at any output and follow solid tensor edges backward to its inputs without crossing a hierarchy-expansion arrow or consulting another page.

## Folding and reuse

Do not unroll many identical layers merely to appear complete. Expand each unique implementation once and fold only when its operator order, shapes, and branch semantics are identical. Label the fold with an exact repetition scope, such as `[Local, Local, Local, Global] ×12`, rather than an ambiguous ellipsis.

For a fixed hybrid cadence, show separate named templates and their order. Do not use an `if` diamond or visually merge them into one runtime branch.

In a complete end-to-end view, every unique requested implementation must be inserted directly into the solid execution path at its representative call. A token-mixer call-site box with GDN or attention expanded elsewhere is not complete, even when a dashed relation connects them. The solid path must enter the expanded implementation's real input node, traverse its internal branches and merge, and leave its real output node before continuing.

After the first inline expansion, a structurally identical repeated call may use a compact inline node labeled `same implementation` with an exact call count or repetition scope. Keep that compact node on the solid path. Use a dashed `implementation reuse` relation only for supplementary dependency-map views or when the user explicitly accepts detached implementation panels; do not use it to satisfy an inline-complete request.

Shared sublayers such as residual adapters or expert implementations may be expanded once when duplicating them would obscure the main path. Preserve their call-site input/output shapes and invocation scope. If a module's internal state differs between prefill and decode, split those paths or state updates explicitly instead of hiding the difference behind reuse.

## Layout

- Choose one main tensor reading direction and keep it continuous across the canvas.
- Put the actual expanded model spine near the visual center. Place preprocessing and genuine auxiliary inputs near their injection points; place auxiliary outputs near their source taps. Do not place a summary spine in the center and surround it with detached implementation satellites.
- Use solid black orthogonal arrows only for tensor/state flow. Use dashed thin relations for implementation reuse or evidence-qualified non-execution relationships.
- Give GDN/QSA-like parallel semantic projections separate lanes and merge them only at the real consumer.
- When several semantic lanes merely need to fan into mutually exclusive inline variants, use a small neutral junction or edge annotation. Do not introduce a boxed `interface`, `dispatch`, or equivalent pseudo-operator unless the code or contract defines one.
- Keep caches and recurrent states beside the operator that reads or updates them.
- Use titled dashed regions for ownership, but do not use nested regions merely to recreate hierarchy levels.
- Reserve branch corridors before placing nodes. Never route a side branch through an unrelated implementation region.

## Acceptance

Reject the view when any of these are true:

- an input or requested output is disconnected;
- a solid edge lacks a producer or consumer;
- a merge has no visible incoming branches or an output has multiple unexplained producers;
- a tensor changes shape without an edge annotation or explicit reshape/projection operator;
- a folded repetition lacks exact scope or hides a topology change;
- a reuse relation is visually indistinguishable from tensor flow;
- the reader must jump to a hierarchy expansion to continue the main path;
- GDN, attention, MoE, residual-wrapper, or another requested unique implementation is reachable only through a dashed reuse relation rather than solid tensor edges;
- most of the canvas is empty because implementation panels were pushed away from a skeletal summary spine instead of being composed inline;
- full-view region ownership or main-spine order is unclear;
- detail-view branch tracing, shape labels, caches, or state updates are unreadable.

Run graph-level validation in addition to geometric review: unique identifiers, valid edge endpoints, reachability from inputs to outputs, no unintended execution cycles, exact repetition labels, and agreement with the shared shape/dependency ledger. For every unique implementation claimed as expanded, assert both `model input → implementation anchor` and `implementation anchor → requested output` using solid execution edges only. A high-level call-site path passing while the expanded implementation is disconnected must fail the audit. Then inspect the declared full-canvas raster and at least two native-detail crops.
