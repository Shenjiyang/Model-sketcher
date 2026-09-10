# Layout failure recovery and stop conditions

Read this reference when a compiler-path diagram produces a large static failure set, repeated regressions, or an official export that omits content. It governs execution strategy, not semantic acceptance: zero blocking errors and the ordinary rendered/manual gates remain required.

## Diagnose before patching

Treat pairwise crossing and overlap findings as a conflict graph rather than independent coordinate tasks. Group errors by region, implicated edge, shared horizontal or vertical corridor, state/cache object, and relation class. Report both the raw finding count and the highest-degree root edges. A single route crossing twenty others is one layout root cause with many pairwise consequences.

After the first compile, create at most one low-scale official diagnostic overview when it is needed to judge macro composition. Mark it diagnostic, never accepted. If the overview already shows an unreadable routing wall, false ownership, excessive canvas scale, or omitted tiles, choose regional or full reflow immediately. Do not wait for final rendering to discover a visibly invalid composition.

## Reflow triggers

Use these thresholds as mandatory replanning triggers, not as acceptance thresholds:

- more than 100 blocking static findings on the first complete audit;
- one region contributes more than half of all blocking findings;
- edge/edge pair findings dominate and a small set of edges repeatedly appears in the root-edge summary;
- the region boundary is visibly inflated to hold routing corridors or persistent-state traffic;
- two consecutive iterations reduce raw blocking findings by less than 20 percent and do not visibly improve the diagnostic crop;
- an experiment lowers one category by moving comparable failures into another category.

When a trigger fires, stop individual coordinate edits. Preserve the validated architecture, canonical ASCII, source evidence, topology review, stable IDs, and unaffected accepted regions. Save the failed geometry as a recoverable snapshot, then regenerate the affected region under `regional-reflow` or the complete canvas under `full-rebuild`. Do not delete or weaken semantic edges merely to lower the geometry count.

## Focused recovery

Start with the region that owns the highest-degree root edges. Separate source-backed execution variants into adjacent vertical lanes and persistent cache/state into external side corridors. Establish distinct read and write lanes; introduce a visible semantic junction or bus only when the topology proves shared flow. Route region-local execution first, state/cache traffic second, and cross-region relationships last.

Audit each focused region to zero blocking static findings before master integration. Integration must preserve its node IDs, operator sequences, tensor shapes, branch attachments, repetition scope, and state lifecycle. A focused page is a derived validation view, not an independently maintained architecture.

Use line jumps only after port exchange, lane reordering, corridor movement, and local reflow leave an isolated perpendicular crossing. A bridge must not become a substitute for separating a dense bundle.

## Render and progress discipline

Do not repeat full-resolution official exports while any static error remains. Focused diagnostic crops are allowed when they answer a specific routing question. After static PASS, run the required official full and detail exports, rendered-SVG audit, and manual inspection.

At each iteration report category counts, root edges, changed regions, and whether the chosen strategy met its expected reduction. If a reflow experiment regresses, restore the recorded layout snapshot rather than layering another refiner over it. Time limits are reporting checkpoints, never permission to relabel a failing artifact as usable or to downgrade blocking findings.
