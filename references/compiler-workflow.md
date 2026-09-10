# Compiler workflow

Use this workflow for new diagrams and substantial revisions. Legacy `.drawio` files may remain on the manual path until explicitly migrated.

Before layout, validate every detail expansion and runtime/state story using [detail-value-runtime-state-contract.md](detail-value-runtime-state-contract.md). The architecture IR owns these records. A child with no evidence-backed delta, an unreviewed runtime branch, or a cache/state object without explicit write/read edges must fail before geometry.

## Source of truth

`architecture.json` is the semantic source of truth. It owns stable IDs, regions, nodes, edges, evidence links, source-operation coverage, repetition, and unresolved claims. Do not encode coordinates or Draw.io styles in it.

Record the selected role palette under `project.typography` using
`ordinary_node_font`, `edge_label_font`, `annotation_font`,
`region_title_font`, and `hierarchy_label_font`. These are semantic viewing
profile choices rather than per-cell styling. The compiler applies the palette
to generated Draw.io cells; keep the delivery manifest's typography contract
numerically synchronized with it.

`layout.json` is generated geometry. It owns boxes, ports, waypoints, hierarchy-arrow boxes, canvas dimensions, and the input architecture digest. Do not add architecture claims to it. `kind: expand` is never an ordinary routed edge: layout writes it under `hierarchy_arrows`, and Draw.io compilation emits a large hollow block-arrow vertex.

For revisions, read [incremental-layout.md](incremental-layout.md). Generate a change plan from the old and new IR, apply region stability policies and reviewed overrides, and preserve unrelated geometry. Incremental work may adapt earlier content when evidence, dependencies, or routing clearance require it; it must record the affected scope rather than silently rebuilding everything.

The `.drawio` file is compiled output. Do not hand-edit compiled cells and then treat them as source changes; update the IR or record an explicit migration exception.

## Gates

Before the first review, preserve `project.request_contract`: `user_quote` contains
the original request verbatim, `source_ref` identifies its message/task record,
`views` lists requested semantic view IDs, `coverage` is `whole-model` or
`selected-modules`, and `depth` is `module-summary`, `logical-operators`, or
`implementation-detail`. `required_modules` lists the source-grounded modules
whose internals must meet that depth. Coverage and depth are independent: a focused
MLA view can require logical operators; an entire model can be an explicitly
requested overview. Level numbers describe presentation hierarchy, not these axes.

In `project.delivery_scope`, `module_regions` maps every requested module to a
non-empty list of region IDs. `required_regions` maps those regions and any
required overview/template regions to their granularity. For logical depth, every
requested module must map to an operator-detail region and enable logical operator
contracts. One unrelated detail region cannot satisfy the entire request. Shared
definitions may serve several modules when source-backed and reviewed.

Reviewer must receive the originating task separately from Builder's interpretation.
The required `user-request-coverage` check compares that task, preserved quotation,
all requested modules and their mappings, and the independent source inventory.
For whole-model coverage it must challenge missing module families, not merely
confirm the listed subset. An external request record must be read when referenced;
a source_ref string or hash alone does not authenticate user authorization.
Never narrow depth or coverage without an actual user change; preserve the prior
request in project history when changing it. Any request change invalidates review.
Migrate old overview/focused/detailed declarations from the original task, never
infer user consent from the previous diagram. The initial template intentionally
has empty module mappings and cannot pass until the task is interpreted.

Intermediate summaries are progress, not completion of a logical-depth request.
After semantic acceptance, focused geometric work remains valid; incomplete
required coverage blocks final acceptance. JSON records support independent
checking but are not an operating-system protection against deliberate edits.

Standalone `plan_layout.py` and `compile_drawio.py` enforce the same semantic gate
as the pipeline before writing output. They accept `--topology-contract`,
`--topology-review`, and `--state`; defaults are sibling `topology.contract.txt`
and `topology-review.json`, with an explicit or state-recorded review taking
precedence. An invalid selected review never falls back to another PASS.
There is no force/diagnostic bypass on these project CLIs. Internal Python APIs
remain usable for unit tests; project builders must use the gated entrypoints.

Revalidating a saved review performs local checks, not another LLM review.
Coordinates, typography, and expansion placement preserve semantic acceptance;
operators, shapes, ownership, source bytes, and delivery scope invalidate it.
Do not inherit partial semantic PASS results after a semantic change.
Ordinary audits remain callable for diagnostics. After semantic acceptance,
use visual previews when they answer a layout question; no timed preview is required.
Only the existing strict delivery audit, official rendered audit, and actual visual
inspection can establish completion. Direct CLI exports and geometry PASS alone
cannot advance delivery state or support a completion claim.

1. **Evidence:** record at least a versioned checkpoint/config source and executable implementation source. Material nodes cite evidence IDs.
2. **Source coverage:** for new diagrams and substantial topology expansions, enable `project.require_source_coverage`, inventory material executable operations from the selected forward paths, and map each operation; read [source-operation-coverage.md](source-operation-coverage.md).
3. **View projection:** preserve one complete canonical IR, enable `project.require_view_projection_contracts`, classify every region/node/edge, and select one `project.semantic_view`; read [view-projection-contract.md](view-projection-contract.md). Source coverage governs what must be known, while view membership governs what the selected reader-facing output renders.
4. **Topology and overview:** run `validate_architecture_ir.py`. Resolve missing endpoints, ownership cycles, invalid evidence links, source-coverage debt, discontinuous requested execution paths, and semantic-color conflicts before layout. For hierarchy/paired views, validate the standalone Level-0 synopsis, exact Level-1 template coverage, and every cross-level interface mapping according to [overview-level-contract.md](overview-level-contract.md). A heterogeneous repeated backbone cannot be represented only as an opaque stack count. Read [semantic-color-legend-contract.md](semantic-color-legend-contract.md); use an explicit `visual_class` only when the deterministic kind/op-type class would lose material meaning, and use the TP modifier rather than inventing a color.
5. **Granularity, logical operators, shapes, and direction:** every region declares `module-summary`, `operator-detail`, or `implementation-detail`, plus unconditional `direction: column` and `flow_direction: bottom-to-top`. Every region with two or more semantic small blocks declares complete `operator_sequences`; every detail region declares them even when small. New or substantially revised details enable the strict logical-operator contract, keep fused execution separate from logical leaves, and attach structured shape/status records to detail tensor edges. Parallel sequences become adjacent vertical lanes. Use `child_direction` only for the macro arrangement of large child regions. Enforce `operator_display_contract`: activation shapes belong on tensor edges, parameter dimensions do not belong inside operator boxes, and a custom operator needs a concrete formula plus atomicity justification. The compiler checks semantic contracts before final sequence geometry; read [logical-operator-contract.md](logical-operator-contract.md), [overview-level-contract.md](overview-level-contract.md), and [ascii-topology-contract.md](ascii-topology-contract.md).
6. **ASCII generation:** generate `topology.contract.txt` with `render_topology_contract.py`. Check that the Level-0 synopsis, Level-1 template mappings, cross-level shape closure, operator display roles, source-operation coverage, hierarchy, complete operator lanes, branches, and relations are present before requesting review.
7. **Independent topology review:** follow [topology-review-workflow.md](topology-review-workflow.md). On cold start or semantic/source change, create a schema-v2 pending digest-bound artifact and use a fresh-context Reviewer to inventory entrypoints, material callees, and executable operations from every pinned source path before comparing the IR and ASCII. Require exact source-operation reconciliation, one result per semantic check and region, and one reconstructability result per ASCII region. Existing PASS review is reused for visual-only iterations while its architecture, ASCII, and source digests remain current. This gate is unconditional for the compiler path; clearing a logical-operator option cannot bypass it.
8. **Layout:** run `plan_layout.py`. The result records the architecture SHA-256; stale layouts are rejected by the compiler. A mature graph engine may replace focused-region node placement and ordinary-edge routing only after reader-view projection; follow [layout-engine-adapter.md](layout-engine-adapter.md). Keep macro region composition and hierarchy-arrow planning separate until an alternative backend implements their complete contracts. Every sequence must rise compactly: an adjacent step with a clear horizontal gap greater than both `240 px` and four times the wider endpoint fails unless a source-backed ID-pair exception is recorded. Treat region and node geometry as content-first: derive ordinary node widths from text/ports, keep exclusive parts of parallel sequences in adjacent lanes, and close each region around its direct nodes and immediate child regions before placing hierarchy relationships. Generated strict manifests fail excessive four-side region slack and canvas-spanning parallel-lane gaps; aggregate density cannot be improved by stretching nodes or pushing branches apart. Every `expand` relation must retain its semantic parent and resolve to a large `hierarchy_arrows` box. Compare all four child sides instead of imposing one direction on a level. Prefer a short straight corridor from the parent node or a validated boundary egress of a region that owns it. If direct attachment would distort the content envelope, use a named owner-region egress; create a canonical-definition node only for a source-backed reusable definition. When several large children exhaust every collision-free direct corridor, the planner may derive a compact `target-signpost` immediately outside the child instead of stretching the execution graph or producing a cable. This fallback remains registered to the real parent, names its anchor visibly, points into the child boundary, and may not overlap any third-party region. It is layout-derived only: architecture IR still declares `parent-node` or `owner-region-boundary`, and an explicit `parent-node` fails rather than silently becoming a signpost. A straight arrow with length-to-thickness ratio above `6.0` fails unless a named obstacle justifies a reviewed ID-specific exception. The planner never changes ownership or degrades an expansion into a small edge arrowhead.
9. **Compile:** run `compile_drawio.py`. Cell IDs are deterministic (`region:*`, `node:*`, `edge:*`, `expand:*`, `legend:*`). Ordinary edges have declared ports and waypoints; every relative port position must remain within `[0,1]` and resolve to an endpoint boundary so Draw.io cannot silently clamp and reroute it. The generated manifest records the exact four normalized port coordinates and rejects XML drift. When automatic path-centered text would cover a bend or endpoint, record an optional `label_position: {"x": ..., "y": ...}` on that layout edge instead of patching compiled XML: `x` is Draw.io's along-edge relative coordinate in `[-1,1]`, while `y` is a finite perpendicular offset limited to `[-160,160]`. Both keys are required, the manifest records them, and official-render auditing keeps the label within the declared route neighborhood. For an unavoidable isolated perpendicular crossing, the upper edge may declare `line_jump: {"style": "arc", "size": 12, "crossings": {"other_edge_id": "reason"}}`. The compiler orders the lower edge first, emits Draw.io arc-jump style on the named upper edge, and registers the exact pair in the generated manifest. Cyclic over/under declarations, stale pairs, unrendered arcs, crowded bridges, and unregistered jump styles fail. Expansions compile as white `singleArrow` vertices and are excluded from `expected_edges`. The compiler—not project XML—applies the canonical Model Sketcher semantic styles and places one complete two-row Legend below the lower-left content boundary.
10. **Delivery:** run the existing strict delivery audit and official Draw.io renderer. Enable the density preflight so measurable whitespace and typography signals enter the `WARN` review queue before manual inspection. Compiler success means structural draft, not visual acceptance.

## Commands

```bash
python scripts/validate_architecture_ir.py architecture.json
python scripts/render_topology_contract.py architecture.json topology.contract.txt
python scripts/prepare_topology_review.py architecture.json topology.contract.txt topology-review.json --trigger cold-start
python scripts/audit_topology_review.py architecture.json topology.contract.txt topology-review.json
python scripts/plan_layout.py architecture.json layout.json
python scripts/plan_layout.py architecture.json layout-elk.json --layout-engine elk
python scripts/compile_drawio.py architecture.json layout.json model.drawio
python scripts/compile_audit_manifest.py architecture.json model.audit.generated.json --layout layout.json
python scripts/plan_change_impact.py old-architecture.json architecture.json change-plan.json --state project-state.json
```

Normally prefer the gated wrapper:

```bash
python scripts/run_compiler_pipeline.py architecture.json \
  --topology-contract topology.contract.txt \
  --topology-review topology-review.json \
  --layout layout.json --drawio model.drawio \
  --audit-manifest model.audit.generated.json --state project-state.json
```

On the first run, omit `--topology-review` or point it at the intended missing file. The wrapper generates and validates the ASCII contract, reports `gate 3c: PENDING`, and stops before creating `layout.json`. Create the pending artifact with `prepare_topology_review.py`, have the independent Reviewer complete only that artifact, audit it, and rerun the wrapper with `--topology-review`. Schema-v1, placeholder, duplicate, incomplete, self-authored, or stale reviews fail before layout. Later layout-only runs pass the same file: the wrapper performs a fast digest/coverage validation but does not invoke another Reviewer. If architecture meaning, generated ASCII, or pinned evidence changes, the stale review fails and a new event-triggered review is required.

The generated audit manifest owns only facts derivable from the IR. Before final delivery, merge in the human-owned `workflow_contract`, typography contract, evidence claims, detail review regions, and narrowly justified exceptions. Never overwrite those review records with a newly generated structural manifest.

For an incremental run, add:

```bash
--previous-architecture old-architecture.json \
--previous-layout old-layout.json --change-plan change-plan.json
```

Use `project-state.json` as the session recovery point. Advance `current_stage` only after the corresponding gate succeeds. Keep failed regions and unresolved claims explicit instead of hiding them in chat history.

If a project-specific refinement script moves or reflects nodes or regions after `plan_layout.py`, recompute the derived expansion geometry before compilation:

```bash
python scripts/plan_layout.py architecture.json layout.json --defer-hierarchy-arrows
python project/refine_layout.py
python scripts/refresh_hierarchy_arrows.py architecture.json layout.json \
  --state project-state.json
```

`--defer-hierarchy-arrows` is only a provisional-layout mode for a deterministic project refiner whose reflow creates the final expansion geometry. The compiler and manifest builder still fail closed while the registry is empty. `refresh_hierarchy_arrows.py` regenerates from the final node/region boxes and then reapplies any reviewed `project-state.json.layout_overrides.hierarchy_arrows` corridor adjustment. Use such an override only to move or resize a straight shaft inside its valid parent/child corridor, or a target signpost inside its valid child-side slot, when the automatic placement covers a real node, tensor/relation edge, or label. The override cannot change the semantic parent, attachment mode, attachment ID, or side, and remains subject to the same size, ownership, label, direction, child-boundary, and obstacle gates. Do not copy stale arrow coordinates forward or hand-edit the compiled XML. A diagonal direct placement with no shared straight corridor must be recomposed or use the planner's audited target-signpost fallback; never substitute a small connector.

## Repair order

Before ordinary repair, apply the failure-scale decision and iteration stop conditions in [layout-failure-recovery.md](layout-failure-recovery.md). A compiler PASS with a large static failure set is a structural draft requiring reflow, not a nearly finished diagram.

Repair failures in this order: evidence and semantics, topology and shapes, ownership and granularity, region geometry, node geometry, routes, typography and polish. Group errors by affected region and shared root cause. Do not patch downstream geometry while an upstream semantic gate is failing.
