# Draw.io audit workflow

Use this reference when the deliverable is an editable `.drawio`, when reviewing a hand-edited diagram, or when a final structural/visual acceptance pass is requested.

## Durable split

Keep four layers separate:

1. `scripts/audit_drawio.py` contains diagram-independent XML and geometry checks.
2. A project-owned `*.audit.json` records model semantics, hierarchy ownership, narrow routing exceptions, and review regions.
3. `scripts/audit_rendered_svg.py` checks the geometry Draw.io actually emitted, using official `data-cell-id` groups, rendered routes, visible shapes, and rendered text fallback boxes.
4. Human inspection of official Draw.io exports establishes perceptual clarity and aesthetic quality that geometry cannot prove.

Do not add a model-specific node or edge ID to the shared script. Add it to the project manifest. Change the shared script only when a new invariant applies across diagrams.

## Required order

1. For a new project, run `scripts/audit_delivery_contract.py` against the canonical `.drawio` and manifest. This verifies the evidence/topology/shape records and invokes the static auditor. Do not call the permissive static auditor alone and treat that result as delivery readiness.
2. Fix structural failures before rendering. Do not allowlist a failure until the route or overlap is confirmed intentional and the manifest records the exact IDs.
3. Run `scripts/render_drawio.py` with an official diagrams.net/Draw.io desktop binary. It repeats the strict contract preflight, exports PNG/SVG, and invokes the rendered-SVG auditor automatically. Use `--legacy-project` only while migrating an old project and report that strict acceptance remains unavailable.
4. Resolve every rendered `FAIL`. Review every rendered `WARN`; fix it or record a narrow, reasoned manifest exception when the geometry is intentional.
5. Inspect the complete overview at the declared viewport.
6. Inspect at least two semantically complete detail regions listed in `render.detail_regions`.
7. Report static, rendered-geometry, and manual-visual results separately. A successful export or geometry pass is not proof that the pixels are clear; reject exports that contain Chromium tile-memory warnings.

Example:

```bash
python3 scripts/audit_drawio.py model.drawio --manifest model.audit.json
python3 scripts/render_drawio.py model.drawio --manifest model.audit.json \
  --drawio-bin /path/to/drawio/AppRun --output-dir /tmp/model-review
```

The renderer may require execution outside a restricted sandbox. Request authorization immediately before launching it. The helper never downloads or installs Draw.io and never overwrites the source diagram.

## Rendered-SVG checks

The rendered auditor operates on the SVG produced by official Draw.io, not on an independently reconstructed preview. It distinguishes two severities:

- `FAIL` is deterministic geometry that blocks delivery: a route through an unrelated ordinary node, a route that enters or re-enters its own source/target, a route through visible region-title text, visible ordinary-node label overflow, a label covering an arrowhead or route bend, or a material label/node or label/label collision.
- `WARN` is a targeted visual-review signal: tight clearance without contact, a label near an arrowhead, missing rendered label geometry, or a route through a free annotation.

The fallback `<image>` emitted for HTML labels may span an entire layout area. For transparent title and annotation images, the auditor reads PNG alpha bounds to recover visible ink rather than treating transparent padding as text. Thresholds only absorb rasterization fringes and tiny contacts; do not increase them until a real collision disappears.

The machine cannot prove whether a long but legal route is ugly, whether non-intersecting branches are still hard to follow, whether whitespace is aesthetically balanced, or whether ownership is perceptually misleading. The optional density contract now pre-screens measurable sparse content, bracketed internal whitespace pockets, trailing whitespace, and large adjacent-region gaps as `WARN` items; those warnings still require review in the official export.

## Static checks

The generic auditor covers:

- XML/page decoding, duplicate IDs, invalid parents and invalid edge endpoints;
- canonical waypoint collections: every geometry `<Array>` must declare `as="points"`; newer desktop builds may tolerate a bare `<Array>`, while older embedded/Confluence codecs can fail during import;
- conflicting duplicate style keys such as `endFill=0;endFill=1`; relying on last-value-wins differs across Draw.io/Confluence codecs and is never a valid way to encode a visual role;
- three-way-or-larger fan-outs leaving opposite sides of one source node, which can look like a line passing through the node even when the individual routes do not intersect;
- connected source/target nodes with less than the configured endpoint gap, because an arrowhead-sized gap can collapse into a tiny terminal dogleg without technically entering either node;
- project-contracted content escaping its visual owner region, including spatially contained nodes whose XML parent is the page rather than the visible frame;
- ordinary nodes partially crossing any visible region boundary; only explicit boundary-interface nodes may use exact cell/region exceptions;
- edge segments riding collinearly on a dashed region boundary; perpendicular entry/exit crossings remain legal, while an intentional collinear overlap requires an exact edge/region exception;
- positive vertex geometry and nested-cell absolute coordinates;
- required cells, forbidden text, semantic-ledger entry completeness;
- declared detail-region granularity and unreviewed multi-operation boxes in `operator-detail` regions;
- generated all-level vertical-flow contracts: every Level 0-3 region is registered, and every adjacent pair in each sequential or parallel lane rises bottom-to-top;
- fixed Draw.io entry/exit ports and expected source/target contracts;
- node/node overlap, region containment, sibling-region intersections and gutters;
- scale-derived minimum visual gutters between sibling nodes in the same immediate owner region, even when their boxes do not mathematically intersect;
- minimum clearance for orthogonal route segments that run parallel to an ordinary node edge or to the boundary of the route's immediate owner region; terminal perpendicular entry/exit segments remain legal;
- content-first region envelopes and topology-aware parallel-lane compaction, so hierarchy corridors and aggregate density cannot be satisfied by inflating regions or spreading branches apart;
- explicit orthogonal edge/node crossings, edge/edge crossings and collinear overlaps; an isolated perpendicular edge/edge crossing passes only when `line_jump_crossings` binds it to a validated Draw.io arc bridge whose curve appears in the official SVG;
- conspicuously inflated routes and narrowly declared exceptions;
- explicit-route endpoint quality: east/west ports must leave and approach horizontally, while north/south ports must do so vertically; a tangential first or last segment is a blocking hook rather than a harmless bend;
- consecutive collinear route legs are normalized: a same-direction intermediate waypoint is a cleanup warning because it is not visibly different, while an opposite-direction pair is a blocking backtrack/U-turn once the reversal exceeds the scale-aware visibility floor;
- near-aligned one-in/one-out execution-chain endpoints that use unnecessary alternating-axis doglegs instead of node alignment; thick hollow hierarchy/reuse relations do not count toward execution degree, while a thick filled tensor edge still does. A detected obstacle in the direct corridor downgrades the finding to manual-review `WARN`; unusual relation styles can be listed in `route_degree_exclusions`. Use `route_quality_exclusions` only for a documented obstacle or lane contract. The default near-axis tolerance is 75% of the smaller endpoint height so it follows project scale; `near_axis_dogleg_tolerance` may override it explicitly.
- non-near-axis orthogonal staircases whose endpoint-compatible L-route removes at least two bends without increasing Manhattan length or crossing an unrelated node, hierarchy arrow, region-title corridor, or unrelated edge. This is a blocking avoidable-route defect even when every leg is monotonic and the total route-inflation ratio is small. Hierarchy-arrow obstacles use the visible block-arrow polygon rather than its transparent rectangular corners.
- hierarchy-arrow registration, labels, direction, and parent/child boundary attachment; a generated `target-signpost` instead requires proven owner-region ancestry, a visible semantic-parent label, correct parent-to-child direction, exact child-tip attachment, and no overlap with any other region.

Draw.io may auto-route an edge whose waypoint array is empty. The auditor can prove its ports and endpoint contract, but only the official export proves the final intermediate route. Fixed-port coordinates must be finite, stay within Draw.io's normalized `[0,1]` range, and place each endpoint on at least one boundary. These invariants apply even when fixed ports are otherwise optional or an edge is excluded from the missing-port requirement. Values outside that contract are invalid even when the XML imports: different renderers may clamp them and replace the intended first or last segment with a tangential hook. Generated manifests additionally bind every ordinary edge to the exact layout-derived port coordinates.

Edge-label geometry is also compiler-owned. A registered `label_position` uses an along-edge `x` in `[-1,1]` and a perpendicular `y` offset in `[-160,160]`. Static audit rejects missing, unregistered, malformed, non-finite, out-of-range, or XML-drifted positions. Official-render audit rejects a label detached by more than `64 px` from every segment of its own rendered route unless the exact edge has a non-empty `allowed_edge_label_distances` reason.

Official-render audit also keeps the route readable around its labels. A label hosted on one
straight segment must leave a scale-derived visible flank at both ends; moving the label onto
a connector that is barely longer than its white background is blocking. An unrelated edge
may not cross or crowd another edge's label box. Prefer moving the label or increasing the
dependency gap; use `allowed_edge_text_crossings` only for an exact, reviewed pair.
Draw.io may serialize a straight rendered leg as several collinear path segments; only an
actual horizontal-to-vertical or vertical-to-horizontal direction change counts as a bend.

## Project-manifest discipline

Use stable Draw.io cell IDs. Prefer exact allowlists over broad prefix or class exemptions. Every exception should have a nearby manifest comment field or semantic note explaining why it is legal.

Route exceptions are ID-to-reason objects, not bare ID lists. Use `route_quality_exclusions` only for an edge whose otherwise suspicious bends are required by a named obstacle or lane contract, and `route_degree_exclusions` only for a non-execution relation whose style cannot identify it reliably.

Do not use legacy `allowed_edge_crossings` to hide an unbridged intersection. Declare the bridge on the upper layout edge with `line_jump`, regenerate the manifest, and let `line_jump_crossings` record the canonical edge pair, jumper, arc size, and reason. The static audit verifies the exact XML style, actual interior intersection, bridge clearance, stale declarations, and jump-count ceiling; the official-SVG audit verifies that Draw.io emitted at least the declared number of curved bridge segments. This mechanism is only for isolated perpendicular non-connections. It never permits a T-intersection or positive-length collinear overlap; use a semantic junction or a declared same-direction rail for genuinely shared flow.

When adding an entity:

- ordinary nodes and edges are automatically included in generic scanning;
- add meaningful model nodes to `node_semantics`;
- add every affected Level-2/Level-3 region to `granularity_contracts` and classify legitimate composites with evidence;
- regenerate `vertical_flow_contracts` from the IR after changing any region sequence; never hand-author them to excuse horizontal ordering;
- add a hierarchy expansion to `hierarchy_anchors`;
- add an important topology edge to `expected_edges`;
- add an exception only after visual confirmation that it is intentional;
- add or update a detail region when the new module needs dedicated visual review.

Do not use a stored SHA-256 as a replacement for rerunning the audit. A checksum is useful only for detecting concurrent edits between audit and render.

## Manual visual checks

Static checks cannot establish perceptual clarity. Inspect these in the official exports:

- clipped, unexpectedly wrapped, substituted, or visually tiny text;
- labels touching borders, edges, arrowheads, or unrelated labels;
- labels erasing every visible pixel of a bend or short terminal segment, even when the edge remains topologically connected;
- fan-outs whose common input shape is attached to only one outgoing branch instead of a shared source/stem or every branch;
- avoidable hooks, U-turns, and multi-branch rails whose coincident lines or arrowheads obscure branch identity;
- edge segments riding on node borders or entering an unrelated node before reaching their declared target;
- false ownership suggested by proximity or alignment;
- hierarchy arrows that look like cables, overlap another hierarchy arrow, or appear to start in unregistered whitespace; a labeled, manifest-registered owner-region boundary egress is legal, and a generated target-side signpost is legal only when it remains compact, visibly names the real parent, points into the exact child, and is perceptually unambiguous;
- nominally bottom-to-top sequences whose adjacent steps drift across several node widths, splitting a shared trunk into a canvas-spanning zigzag;
- ambiguous direction after two lines share a port or segment;
- excessive dead space, stretched operator boxes, or inconsistent sibling density;
- semantic colors, dashed-boundary visibility, and hierarchy/tensor stroke distinction;
- render-order occlusion and content omitted by renderer memory limits.

Conclude with one of these precise states:

- `Static and rendered-geometry audits passed; official Draw.io visual audit passed.`
- `Static audit passed; rendered geometry has warnings; reviewed and official Draw.io visual audit passed.`
- `Static audit passed; official Draw.io render or visual audit pending.`
- `Audit failed`, followed by categorized failures.
