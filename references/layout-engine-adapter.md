# Layout engine adapter

## Runtime diagnostics

The global path reports Node/ELK, route conversion and label geometry, macro
region placement, precision overrides, and hierarchy planning separately on
stderr, with phase durations and label progress. The 45-second subprocess limit
applies only to Node/ELK; Python postprocessing may take longer. `ELK_TIMEOUT`
means a caught Node `TimeoutExpired`, not a terminal yield or a geometric failure.
A matching previous layout reports reuse and does not start Node. Preserve the
terminal session ID across yields and wait for its actual exit result.

Use a mature graph layout engine for node placement and ordinary orthogonal
routing. Keep semantic view projection, Draw.io serialization, and delivery
auditing as separate stages.

The default adapter uses vendored `elkjs` `0.12.0` and one global compound graph:

```text
architecture IR -> view projection -> ELK problem -> global geometry
                                                -> Draw.io layout adapter
```

The current projection implementation already exposes the intended seam:

```text
project_active_view(canonical_ir)
    -> projected regions/nodes/edges
    -> one compound ELK problem for all visible regions and ordinary edges
    -> optional rigid placement of disconnected hierarchy components
    -> hierarchy-arrow planning
    -> schema-v3 layout.json
```

ELK must own every ordinary edge before recorded precision adjustments. Do not rewrite canonical IDs,
sequence membership, region ownership, expansion attachments, or edge kinds.
ELK global layout is the only compiler path; normal commands omit engine flags.
For compatibility only, hidden `--layout-engine elk` and
`--layout-engine elk-compound` arguments still call that same path. They are not
different modes and must not be presented as configuration choices.
Native and hybrid compiler backends have been removed; `native` is rejected.
No ordinary edge may silently fall back to a hand-written router.

This is one hierarchy-aware ELK solve, not a global pass followed by independent
per-module solves. The root container receives macro preferences while nested
region containers receive their local ordering, spacing, alignment and port
preferences in the same problem. A second independent local pass could invalidate
cross-region ports and routes and is therefore only a focused diagnostic, never
the compiler path.

The ELK problem contains only stable node IDs, measured node boxes, directed
edges, measured edge labels, port-side/order constraints, spacing, and optional
engine options. It must not contain architecture claims. The resulting
geometry remains disposable. The adapter records its exact engine version and
fails when ELK is unavailable or returns a detached/out-of-range endpoint; it
never clamps a bad port or silently falls back to the hand-written planner.

Run the included smoke example with:

```bash
python scripts/plan_layout_elk.py \
  assets/elk-layout-problem-example.json /tmp/elk-layout.json
```

ELK is the default layout backend, not a replacement for strict audit. A
layout engine can minimize crossings for a chosen graph, but it cannot decide
whether prefill, decode, and distributed variants belong in one reader-facing
view. Perform view projection first. If a focused graph remains infeasible or
dense, fail and split the view instead of layering project-specific coordinate
patches.

The pipeline uses global ELK without an engine flag:

```bash
python scripts/run_compiler_pipeline.py architecture.json \
  --topology-contract topology.contract.txt \
  --topology-review topology-review.json \
  --layout layout.json --drawio model.drawio
```

Compound ELK receives the entire
containment tree and ordinary graph. Its nested coordinates and edge-container
coordinates are converted to Draw.io's absolute layout coordinates. The same
port, label, endpoint and node-penetration checks still apply.

Retained helpers measure text and build hollow hierarchy arrows. For execution
components with no ordinary edges between top-level regions, hierarchy placement
may rigidly translate whole components to make short expansion corridors; all
internal ELK routes move with their endpoints. It may not reshape ordinary routes
or move connected components independently. Connected global graphs retain ELK
placement unless the validated precision pass explicitly changes it.

The backend records `elk_edge_ids` and `native_routed_edge_ids` (empty) in
layout metadata, `compound-elk-layered` and the exact
ELK version. A generated layout is provisional, never an audit PASS.

The compound backend supports global ELK followed by exact visual edits in
project-state `layout_overrides`. These are deterministic postprocessing edits,
not a promise that ELK can solve arbitrary fixed-coordinate constraints.
`nodes` and `regions` accept absolute nonnegative `x`/`y` keyed by stable ID;
sizes remain content-derived. Moving a region translates its descendants.
`edges` accept explicit normalized `source_port`/`target_port`, orthogonal
`waypoints`, and relative `label_position` (`x` in [-1,1], `y` in [-160,160]).
For example:

```json
{"layout_overrides": {"nodes": {"attention": {"x": 800}},
 "edges": {"output": {"label_position": {"x": 0, "y": -12}}}}}
```

Use the strict pipeline's `--state` to apply precision overrides.
Add `--previous-layout` and `--previous-architecture` to the pipeline to refine
an existing base without rerunning ELK; its
architecture digest, semantic view and visible IDs must match exactly.
Retain the state file and base for reproducibility. Absolute edits reapply on
rebuild; if a new ELK base makes them invalid, repair them rather than discarding
them. Frozen/preserved region policies remain unsupported and fail explicitly.

The adjustment pass reconnects moved endpoints by orthogonal route stretching,
or a bounded upward Z-route where possible. Otherwise supply explicit ports and
waypoints or revise placement. It checks all ordinary routes for node penetration,
including unrelated edges affected by a moved obstacle; it is not a global router.
Region bounds, titles, canvas and hierarchy-arrow geometry are regenerated.
Relative edge labels follow their routes; label collisions, node overlaps,
crossings and overall readability still require normal strict and visual audits.
Changed routes lose stale line-jump declarations and are recorded separately as
`precision_adjusted_edge_ids`; `elk_edge_ids` records their original provenance.
The result remains `acceptance: pending`. Never edit final XML to bypass this
path, skip reviewer gates, silently fall back to native routing, or call a
successful geometry adjustment a delivery PASS.

## Layout intent and precision edits

Prefer project-state `layout_hints` for an arrangement ELK should compute.
Keep `layout_overrides` for exact geometry after ELK. Both use stable IR IDs;
neither modifies operators, dependencies, source coverage, or semantic review.
The supported hints are:

- `macro.direction`: root arrangement preference (`up`, `down`, `left`, or
  `right`) for top-level region containers.
- `macro.spacing`: positive finite pixels for `region`, `layer`, `edge_region`,
  and `edge`; these map to root ELK spacing options and are the first choice for
  making top-level blocks more compact or giving cross-region routes more air.
- `macro.alignment`: root Brandes-Koepf alignment preference, with the same
  accepted values as region alignment.
- `region_order`: every visible region once; an input-order preference.
- `regions.<id>.node_order`: every direct visible node in that region once;
  activates ELK model-order preference. Use it to suggest parallel branch order,
  never to manufacture tensor edges or to promise a strict geometric ordering.
- `regions.<id>.spacing`: positive finite pixel values for `node`, `layer`,
  `edge_node`, and `edge`. Ordinary and between-layer variants are set together.
  Only the named region receives these options; labels and strict clearance
  audits may require more space. Node sizes remain content-derived.
- `regions.<id>.alignment`: ELK Brandes-Koepf alignment selection (`LEFTUP`,
  `RIGHTUP`, `LEFTDOWN`, `RIGHTDOWN`, `BALANCED`). This selects an algorithmic
  preference; it does not pin a chosen set of node centers or absolute coordinates.
- `edge_ports.<edge-id>.source/target`: boundary side (`north`, `south`, `east`,
  `west`) for each specified endpoint. Final sides are checked after precision.
- `port_order.<node-id>`: all visible incident endpoint IDs, written as
  `source:<edge-id>` or `target:<edge-id>`, each exactly once. The relative order
  on each side is left-to-right for north/south and top-to-bottom for east/west.
  This activates `FIXED_ORDER` on that node; the result is checked after ELK
  conversion and precision. Junction ports retain their separate normalization
  contract and cannot receive these hints.

For a region with input, query/key projections and a join:

```json
{"layout_hints": {
  "macro": {"direction": "right", "spacing": {"region": 80, "layer": 110}},
  "regions": {"attention": {
    "node_order": ["input", "query", "key", "join"],
    "spacing": {"node": 100, "layer": 80},
    "alignment": "BALANCED"
  }},
  "edge_ports": {"input_to_query": {"source": "north", "target": "south"}},
  "port_order": {"input": ["source:input_to_query", "source:input_to_key"]}
}}
```

The adapter validates IDs and complete orders against the selected view before
running ELK, and records the hints in `layout_engine.layout_hints`. Unsupported
intent is rejected rather than ignored. Changing hints invalidates reuse of a
previous layout, even when the architecture digest is unchanged: generate a
candidate without `--previous-layout`, then validate existing precision edits
against it. Hints are not consumed by the precision-only reuse path. Old layouts
without recorded hints can be reused only with empty hints.

Macro hints do not express arbitrary rows, grids, adjacency constraints, or
reserved hierarchy-arrow corridors. Such arrangements remain a validated
macro-planning or precision task; do not claim ELK guaranteed them.

Precision overrides continue to apply after ELK, so old absolute coordinates
can oppose a new spacing or ordering preference. Inspect the candidate diff and
revise affected overrides explicitly; do not automatically delete them or copy
every ELK coordinate into overrides. Conflicting port-side/order overrides fail.
Use `run_local_revision.py --repair overrides` for exact refinements of a saved
candidate, then the normal full static/render/visual gates. A hint change alone
does not require a new semantic Reviewer. Global ELK still receives the complete
visible graph, with local hints inside its compound containers.

Hierarchy-arrow drawing, text measurement, semantic ownership and style remain
separate responsibilities. Arbitrary nested multi-section edge output is not
yet supported and fails explicitly rather than losing route segments.

The default engine choice does not certify diagram quality. On the earlier
DPSK-V4.1 111-node/140-edge diagnostic, all edges were routed
by ELK and compilation passed, but static audit still reported 122 errors
(100 crossings). This is not a visually accepted replacement. Shared-state
placement and global routing still need refinement; do not claim that selecting
ELK alone solves those failures or that multi-page output is mandatory.

## Quality acceptance

Maintain focused fixtures for a vertical
chain, fork/join plus residual skip, cache side input, packed Q/K/V split,
multi-input attention, routed/shared MoE lanes, and one projected real-model
region. Compare refinement candidates with the same static audit. The ELK
candidate must not introduce node overlap, direction reversal, endpoint
detachment, avoidable main-spine bends, or additional blocking crossings.

The engine fails closed when `elkjs` or Node is unavailable. Repair the bundled
runtime or report the dependency blocker; never recreate the removed native path.
The focused-problem CLI remains a diagnostic tool, not a separate compiler backend.

## Bounded candidate selection and refinement

IR-derived problems use zero-size boundary ports and `FIXED_SIDE`: semantic
sequence order is not a physical port order. Use `FIXED_ORDER` only where a
real port-order contract exists. Sequence edges receive direction priority so
state feedback is not treated as an equally important forward execution edge.
The final bottom-to-top check still applies; priority is not a proof.

The focused-problem diagnostic adapter evaluates up to five alignments and, for larger regions, two ELK
node-placement strategies. Candidate scoring reuses route, sequence and density
checks with real labels and shared-node ownership. It records every attempt
and the selected strategy in layout engine metadata. This is a bounded search,
not a guarantee of a zero-error result. The global compound path currently uses
one ELK pass, not that focused candidate search. A generated layout with residual
findings remains a draft and must fail the ordinary delivery gates.

Route refinement precedes label placement. Preserve the separate label shelves
of multiple operand edges sharing both endpoints; straightening them into a
parallel wire fence can make every label placement impossible. Other route
shortcuts must preserve port order and clearances. Labels use bounded offsets
and display-only wrapping shared by measurement, compiler and manifest. Names
that merely repeat the edge ID are ledger metadata; the rendered label shows
the tensor shape. Canonical names and shapes are unchanged.

Region titles wrap within content-derived width and reserve measured vertical
headroom. Region measurement accounts for visible route and label extents.
Review any resulting side-slack finding rather than globally raising density
thresholds. For topology that still mixes mutually exclusive backend variants,
split reader projections before adding more layout candidates or exceptions.

Sparse isolated crossings may receive registered arc bridges only after the
bounded unbridged alternatives fail. Clustered crossings, contacts, collinear
sharing, crowded labels and short approaches remain blocking. Official SVG
and manual inspection are still required; a successful unit suite or adapter
conversion is never visual acceptance.

Set both ordinary and between-layer edge spacing: ELK's separate defaults can
otherwise leave only 10 px between horizontal routing shelves. Label placement
must reserve the visible-flank minimum plus the renderer's background padding;
provide enough chain-layer spacing for this budget rather than weakening audit.
Hypothetical shortcut checks must include sibling routes even when they share
an endpoint. Only a point contact at that endpoint is exempt, not a later
crossing or positive-length overlap. Count actual axis changes, not renderer
split points, when deciding whether a shortcut removes bends.

For three or more writers of one persistent state, reserve separate routing
shelves before bridge planning; the spacing derives from the edge font and
does not apply to ordinary chains. A staircase may be shortened while retaining
an existing perpendicular crossing only at the same point and with the same
other segment. This does not accept the crossing: the later bridge and strict
audits still decide whether the resulting route is usable.

Rendered shortcut proposals inherit the static route-to-node clearance, so a
shorter line that would hug a block is not a legal alternative. Merge forward
collinear SVG segments when measuring visible label flanks; Draw.io's internal
path split is not an endpoint. Preserve reversals and real turns, and ignore
sub-two-pixel perimeter adjustments only in the material staircase check.

An explicitly named owner-region egress uses its short `anchor_label` as the
visible hierarchy-arrow label. Keep the full relationship description in the
canonical edge record; do not concatenate it into a narrow arrow shaft.

Tiny `kind: junction` nodes are not ordinary multiport operators. After layout,
normalize same-side terminal runs onto the side center using `junction_routes.py`.
Keep node boxes and semantic edges unchanged. Record exact per-edge terminal
extents under layout `junction_rails`; only same-direction overlap inside those
extents is shared flow. Never exempt an entire edge pair or source. Incoming
lines end without an arrowhead at a junction; ordinary consumer arrowheads remain.
The compiler adds black dots at the registered branch contacts. Static audit
reconstructs the registry from XML, checks marker positions, and rejects separated
crowded junction ports, terminal reversals and insufficient branch spacing.
Ordinary operator ports remain independent. Recheck official rendering after
normalization; existing labels and bridges are not automatically proven safe.

For a visual-only migration of existing generated geometry, use
`python scripts/junction_routes.py architecture.json layout.json candidate.json`,
then compile, regenerate the manifest, and run both audits. This preserves the
accepted node placement instead of forcing a whole-view ELK rerun.
