# Hierarchy-master layout derivation

Use this reference whenever the selected output includes a hierarchy master. Its purpose is to turn ownership and reuse contracts into a spatial composition before drawing arrows.

This reference governs macro placement only. Large child regions and hierarchy arrows may use any legal parent-relative side, but ordered small blocks inside every region—including Level 0/1 module summaries—remain vertically bottom-to-top according to [granularity-contract.md](granularity-contract.md). A horizontal row of large sibling regions is legal; a horizontal sequence of small blocks is not.

## 1. Build registries before coordinates

Maintain three separate records:

1. **Ownership tree:** one canonical definition parent for every expanded detail.
2. **Call-and-reuse DAG:** all callers of shared definitions, with typed `calls`, `uses`, `injects`, or `reuses` relations.
3. **Hierarchy-anchor registry:** one entry for every large expansion arrow:

```text
arrow_id
semantic_parent_definition_id
child_region_id
attachment_mode: parent-node | owner-region-boundary | target-signpost
attachment_id
anchor_label
attachment_side
child_side
preferred_direction
visual_zone
shared_family_key | none
```

Keep semantic ownership and physical arrow attachment separate. `semantic_parent_definition_id` is always the actual definition that owns the detail. `attachment_id` is only the visible tail surface: either that node itself or the boundary of a region that owns it. A region-boundary attachment does not become a second parent and does not change the ownership tree.

Never create an `expand:*` shape before its registry entry exists. Never export when an `expand:*` shape is not registered. In the compiler path, one IR relation `kind: expand` owns all three generated records: `layout.hierarchy_arrows[relation_id]`, Draw.io vertex `expand:relation_id`, and manifest `hierarchy_anchors[expand:relation_id]`. The relation must not also appear as `edge:relation_id`.

## 2. Derive placement from the parent

Lay out the owner's execution content before reserving expansion geometry. Compute each
execution region from the tight envelope of its direct nodes and immediate child regions,
plus title and role-based padding. A hierarchy arrow is external relationship geometry: it
must not enlarge an operator node, spread parallel lanes apart, or make an owner region
substantially wider or taller. If a clean tail cannot leave the semantic parent after this
content-first pass, change the visual attachment or the child side; do not distort the
execution graph to manufacture a corridor.

For each child region, enumerate at least the four parent-relative candidates: above, below, left, and right. A generator may add staggered or wrapped candidates, but it must not begin with an arbitrary leftover rectangle.

Score each candidate using the following ordered concerns:

1. **Semantic legality:** the child remains in the correct model-level, layer-level, or implementation-level sibling zone and does not imply a false parent.
2. **Direct corridor:** a straight block arrow can connect the registered visual attachment and child boundaries without crossing a node, titled region, tensor edge, or another hierarchy arrow.
3. **Locality:** minimize boundary-to-boundary Manhattan distance and the number of bends.
4. **Visual inference:** alignment and proximity make a new viewer infer the registered parent without reading fine print.
5. **Sibling compactness:** dependency-adjacent regions remain close, while unrelated siblings keep a visible gutter.
6. **Viewing scale:** the candidate does not enlarge the canvas so much that full-view titles and hierarchy arrows fall below their apparent-size floors.

Do not preassign every expansion the same compass direction. A level band is an output of the candidate comparison, not a constraint that suppresses left/right/down alternatives. Record a preferred side only after comparing all four sides, and reconsider it whenever a project refiner moves the parent, child, or neighboring obstacles.

Reject a direct-corridor candidate immediately when it requires an unregistered floating arrow, an arrow through another region, a cable-like long route, or a child aligned beneath an unrelated module. If no direct candidate survives, first reflow existing regions: move auxiliary heads above the backbone, move modality branches to a side, stagger deeper levels, exchange sibling order, or rebalance the canvas. When several large children genuinely exhaust the four direct sides, use the planner's registered `target-signpost` fallback: place a compact labeled block arrow immediately outside the child and point its tip into the child boundary. It must retain the real semantic parent and owner region in the registry, state the semantic anchor visibly, and avoid every other region. It is a target-side hierarchy road sign, not a line pretending to remain physically attached to the distant parent and not an arbitrary decoration.

The expected layout reasoning is therefore:

```text
semantic parent
  → select parent-node or owned-region-boundary attachment
  → enumerate N/S/E/W child slots
  → remove illegal/blocked slots
  → rank short direct corridors
  → reflow neighboring regions if none pass
  → if all direct sides remain exhausted, derive a registered target-signpost
  → place child and external expansion geometry
  → instantiate the registered hierarchy arrow
```

## 3. Shared implementations

A shared GR, MoE, adapter, or kernel is defined once. Do not give the detail region multiple ownership parents and do not place a large arrow above it without a source.

Use one of these representations:

- **Canonical-definition anchor:** show one source-backed canonical definition node, connect callers with lightweight typed reuse relations or a shared family marker, and draw the large arrow from the canonical node to its detail region.
- **Representative instance:** when the figure explicitly treats one repeated instance as representative, mark every equivalent call-site with the same family key and label the large arrow as the shared implementation expansion. Record which marked instance is the representative parent.

Prefer the canonical-definition anchor when multiple call-sites are simultaneously visible. Place its detail region in the nearest legal free zone around the callers' common container. For example, when two decoder templates both contain the same Sparse-MoE class and the space above the decoder is free, place the canonical MoE detail above the decoder and point a short upward block arrow from a visible shared-definition anchor. Do not send the detail to a remote corner and add a detached arrow later.

A numeric or symbolic family marker such as `①` may replace long reuse lines when all marked call-sites and the canonical definition are visible in the same primary reading frame. Define the marker once in or beside the canonical anchor. A marker does not replace the hierarchy arrow or its registry entry.

## 4. Physical attachment policy

Use `parent-node` when a short clean corridor leaves the semantic parent without disturbing its internal tensor flow. Use `owner-region-boundary` when attaching a large arrow directly to a small block would crowd the block, cross local operators, or create an awkward oversized shaft. The latter is a named region egress, not a floating proxy.

Prefer `owner-region-boundary` as soon as direct attachment would require any of these
tradeoffs: widening the source node beyond its text/port needs, moving sibling branch lanes
away from their common trunk, leaving a large empty pocket inside the owner, or expanding the
owner merely to hold the shaft. Place the egress on the nearest clean outer side and keep its
label visually associated with the source. A compact egress tab or lightweight leader is
legal when the boundary label alone is ambiguous.

In architecture IR:

```json
{
  "source": "mixer_core",
  "target": "mixer_detail_input",
  "kind": "expand",
  "label": "Mixer Core -> operator detail",
  "visual_attachment": {
    "mode": "owner-region-boundary",
    "region": "decoder_template",
    "side": "south",
    "anchor_label": "Mixer Core"
  }
}
```

The validator requires the attachment region to be the source node's direct owner or an ownership ancestor. The visible arrow label must contain `anchor_label`. This is especially important when one large region contains several expandable modules. If the label and region boundary still leave the origin perceptually ambiguous, add a short lightweight leader or a dedicated labeled egress tab; do not move the semantic parent to a fake proxy node.

For a reused definition, prefer a real source-backed canonical-definition node such as `Shared Sparse MoE definition`. Call-sites point to it through typed reuse relations or a shared family marker, and the expansion belongs to that canonical node. It may use its own node boundary or an owned-region boundary as the physical attachment.

Do not manufacture a `Shared ... definition` node only to improve layout. Use a canonical
definition node only when the evidence and ownership tree contain that reusable definition.
For an ordinary FFN, attention block, or other locally owned module without a separate
definition object, use a named owner-region egress such as `FFN detail` while retaining the
real module node as `semantic_parent_definition_id`.

`target-signpost` is a derived layout mode, not an allowed `visual_attachment.mode` in
`architecture.json`. The planner may use it only after it cannot place another large child on
any of the four direct parent/egress sides without collision. It positions the child outside
the occupied component and puts a short block arrow in the final gap, with its tip attached to
the child. The registry still records the real source node as semantic parent and an ancestor
region as the ownership-bearing attachment ID. The visible label must name the source anchor.
An explicitly requested `parent-node` attachment is strict and may not be converted to a
signpost; reflow or fail instead.

## 5. Geometry gate

Before export, validate every registry entry:

- parent and child identifiers exist;
- arrow identifier exists exactly once;
- arrow visual class is a hierarchy block arrow;
- the semantic parent exists and the registered attachment region, if used, owns it;
- in `parent-node` and `owner-region-boundary` mode, the tail touches the registered node or owner-region boundary on the declared side;
- in `target-signpost` mode, the arrow is compact, points from the registered parent's side toward the child, and does not pretend that its tail touches the distant owner;
- the tip touches the registered child boundary on the declared side;
- the arrow body does not intersect an unrelated visible node or region;
- its label names the semantic parent, canonical definition, or family key through the registered anchor label;
- every visible `expand_*` arrow is registered;
- no registered expansion is missing from the canvas.
- the owner's execution envelope remains compact without counting the arrow as content;
- parallel operator lanes remain adjacent and are not spread apart to create the arrow shaft;
- ordinary node widths remain content/port-sized and are never stretched to improve a region-density score.

The standard compiler emits a straight `singleArrow` when the selected attachment and child region share a clear horizontal or vertical corridor of sufficient width. It supports parent-node and owner-region-boundary direct attachment. After the layout planner proves that multiple large children exhaust all direct sides, it may emit a short target-signpost `singleArrow` at the child boundary; it never silently draws a thin connector or detached diagonal arrow. Recompose the macro layout when neither a direct corridor nor a legal signpost slot exists. A project-specific bent hollow-arrow implementation remains legal only when it preserves the same monolithic visual weight and passes the applicable endpoint registry checks.

Straight hierarchy arrows must also remain block-like rather than cable-like. The shared audit defaults to a maximum length-to-thickness ratio of `6.0`. Exceeding it is a blocking signal to compare the other three child sides, move the child closer, or use a compact reviewed bent block arrow. A project may declare an ID-specific exception only for a named source-backed obstacle; a desire to preserve an all-up/all-down level band is not a valid reason.

Project-specific layout refinement runs before hierarchy-arrow derivation. After moving, resizing, or reflecting regions, call `scripts/refresh_hierarchy_arrows.py` with `--state project-state.json`. Arrow geometry remains derived output. If centered placement blocks real diagram content, preserve the reviewed correction in `layout_overrides.hierarchy_arrows`, not as an untracked edit to generated XML or layout. A legal override may choose another straight shaft position or thickness inside the same direct corridor, or adjust a signpost within the same child-side slot; it may not override semantic parent, attachment mode, direction, or relax the manifest mapping, minimum size, applicable boundary attachment, ownership, label, or obstacle checks. Collision checks use the visible `singleArrow` polygon rather than its transparent rectangular corners.

Use [scripts/audit_hierarchy_anchors.py](../scripts/audit_hierarchy_anchors.py) when the generator can emit the simple JSON geometry ledger accepted by that script. An internal generator audit is acceptable only when it enforces the same conditions and fails the build on any mismatch.

## 6. Visual rejection pass

After the geometry gate passes, inspect the full master without reading small labels. For each child region, answer: “Which parent would a first-time viewer point to?” If the answer differs from the registry, reflow the layout. Geometry attachment is necessary but does not prove perceptual clarity.

Reject the master when any large arrow looks like a cable, appears in unregistered empty space, is substantially longer than nearby attachment/child gaps without an obstacle justification, or remains ambiguous even after its registered anchor label is read. An owner-region egress should look deliberately aligned with its semantic module or egress tab, not like an arbitrary point on a large frame. A target signpost should read immediately as “the named parent expands into this child”; reject it if proximity makes it look owned by a different neighboring module or if several signposts form an unexplained decorative band.
