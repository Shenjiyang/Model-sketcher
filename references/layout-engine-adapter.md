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

Keep ELK local to ordinary node placement and routing at first. Do not let it
rewrite canonical IDs, sequence membership, region ownership, expansion
attachments, or semantic edge kinds. Cross-region edges and hierarchy arrows
remain later composition stages until their endpoint regions have final boxes.

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

The hybrid backend runs ELK only for ordinary nodes and edges owned directly
by one projected region. The existing planner still composes regions, places
hierarchy children, routes cross-region relations, applies incremental
preservation, and creates hierarchy arrows. `layout.json` and the generated
manifest record `hybrid-elk-layered`, the exact elkjs version, the ELK-owned
region IDs, and the native macro engine.

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
