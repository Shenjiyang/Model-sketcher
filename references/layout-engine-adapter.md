# Layout engine adapter

Use a mature graph layout engine for node placement and ordinary orthogonal
routing. Keep semantic view projection, Draw.io serialization, and delivery
auditing as separate stages.

The initial adapter uses vendored `elkjs` `0.12.0` and accepts a focused layout problem:

```text
architecture IR -> view projection -> ELK problem -> focused geometry
                                                -> Draw.io layout adapter
```

The current projection implementation already exposes the intended seam:

```text
project_active_view(canonical_ir)
    -> projected regions/nodes/edges
    -> one local ELK problem per visible region
    -> macro region composition
    -> hierarchy-arrow planning
    -> schema-v3 layout.json
```

ELK must own every ordinary edge when selected. Do not rewrite canonical IDs,
sequence membership, region ownership, expansion attachments, or edge kinds.
When an ordinary edge crosses region ownership, `elk` selects the compound
backend automatically. `elk-compound` explicitly selects the same global path.
No ordinary edge may silently fall back to the native router.

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

ELK is an optional layout backend, not a replacement for strict audit. A
layout engine can minimize crossings for a chosen graph, but it cannot decide
whether prefill, decode, and distributed variants belong in one reader-facing
view. Perform view projection first. If a focused graph remains infeasible or
dense, fail and split the view instead of layering project-specific coordinate
patches.

The pipeline exposes ELK as an explicit opt-in:

```bash
python scripts/run_compiler_pipeline.py architecture.json \
  --layout-engine elk \
  --topology-contract topology.contract.txt \
  --topology-review topology-review.json \
  --layout layout.json --drawio model.drawio
```

For independent regions with no ordinary cross-region edges, the hybrid backend
retains native macro composition and hierarchy-arrow geometry while ELK owns
all ordinary edges. For connected regions, compound ELK receives the entire
containment tree and ordinary graph. Its nested coordinates and edge-container
coordinates are converted to Draw.io's absolute layout coordinates. The same
port, label, endpoint and node-penetration checks still apply.

Both backends record `elk_edge_ids` and `native_routed_edge_ids` (empty) in
layout metadata. Compound mode records `compound-elk-layered` and the exact
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

Use the strict pipeline's `--state` with `--layout-engine elk-compound`.
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

LLM macro guidance may use project-state `layout_hints.region_order`, listing
each visible region once. This is an input-order preference, not a fixed spatial
position; inspect the result. Other hints are rejected rather than ignored.
Hierarchy-arrow drawing, text measurement, semantic ownership and style remain
separate responsibilities. Arbitrary nested multi-section edge output is not
yet supported and fails explicitly rather than losing route segments.

The original native default remains available while compound quality is being
validated. On the DPSK-V4.1 111-node/140-edge diagnostic, all edges were routed
by ELK and compilation passed, but static audit still reported 122 errors
(100 crossings). This is not a visually accepted replacement. Shared-state
placement and global routing still need refinement; do not claim that selecting
ELK alone solves those failures or that multi-page output is mandatory.

## Merge acceptance

Before replacing the default planner, require focused fixtures for a vertical
chain, fork/join plus residual skip, cache side input, packed Q/K/V split,
multi-input attention, routed/shared MoE lanes, and one projected real-model
region. Compare the old and ELK candidates with the same static audit. The ELK
candidate must not introduce node overlap, direction reversal, endpoint
detachment, avoidable main-spine bends, or additional blocking crossings.

Keep the existing planner as the default while the hybrid backend is being
validated against real projected model regions. The optional engine fails
closed when `elkjs` is unavailable; it never silently falls back and claims
the ELK layout was used.

## Bounded candidate selection and refinement

IR-derived problems use zero-size boundary ports and `FIXED_SIDE`: semantic
sequence order is not a physical port order. Use `FIXED_ORDER` only where a
real port-order contract exists. Sequence edges receive direction priority so
state feedback is not treated as an equally important forward execution edge.
The final bottom-to-top check still applies; priority is not a proof.

The adapter evaluates up to five alignments and, for larger regions, two ELK
node-placement strategies. Candidate scoring reuses route, sequence and density
checks with real labels and shared-node ownership. It records every attempt
and the selected strategy in layout engine metadata. This is a bounded search,
not a guarantee of a zero-error result. A generated layout with residual
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
