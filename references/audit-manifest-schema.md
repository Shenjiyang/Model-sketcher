# Draw.io audit manifest, schema version 1

The project manifest is JSON and normally sits beside the canonical diagram as `<diagram-stem>.audit.json`. It contains diagram-specific facts; the shared skill script remains model-independent.

## Top-level fields

```json
{
  "schema_version": 1,
  "defaults": {},
  "pages": {"*": {}},
  "render": {
    "overview_width": 2560,
    "detail_width": 4800,
    "detail_regions": []
  }
}
```

New projects also require the top-level `workflow_contract` described in `strict-delivery-contract.md`. The strict gate rejects a manifest that omits its architecture, independent topology review, evidence, generated topology, shape-ledger, logical-operator, source-claim, or review-region records even when the lower-level static geometry audit would pass.

The workflow contract names `architecture_file` and `topology_review_file` in addition to `topology_contract_file`. `audit_delivery_contract.py` validates these three together using the same schema-v2 checks as `audit_topology_review.py`: full architecture/source-file validity, canonical architecture meaning, exact generated ASCII bytes, pinned source bytes and revisions, independent builder/reviewer identities, source-first entrypoint/callee/operation inventory, exact source-operation reconciliation, per-check and per-region semantic/reconstruction results, required attestations, concrete findings, no blockers, and a pass verdict. The saved review is reused for visual-only iterations; it becomes invalid only when one of its bound semantic, ASCII, or evidence inputs changes.

`defaults` applies to every page. `pages["*"]` extends the defaults. A page-name entry extends both. Nested objects are merged; arrays replace the inherited array.

## Page audit fields

- `require_fixed_ports`: require `exitX`, `exitY`, `entryX`, and `entryY` on edges.
- `port_check_exclusions`: edge IDs not governed by fixed-port policy.
- `require_port_geometry_contracts`: strict-delivery gate requiring `expected_ports` to cover every ordinary expected edge. The four coordinates are generated from `layout.json`; present coordinates must always be finite, normalized to `[0,1]`, and lie on the endpoint boundary even when an edge is excluded from the missing-port policy.
- `expected_ports`: exact edge-ID mapping to layout-derived `exitX`, `exitY`, `entryX`, `entryY`, `exitSide`, and `entrySide`; XML drift fails static audit, while the named sides preserve direction at legal corner positions where coordinates alone are ambiguous.
- `require_registered_edge_label_positions`: when true, every edge-label `mxGeometry.x/y` pair must be registered in `expected_edge_label_positions`, and every registered pair must exist in XML.
- `expected_edge_label_positions`: layout-derived edge-ID mapping to Draw.io relative `x` (`[-1,1]`) and perpendicular-offset `y` (`[-160,160]`).
- `required_cells`: stable IDs that must exist.
- `expected_edges`: mapping from edge ID to expected `source` and `target`.
- `regions`: declared titled-region IDs.
- `region_parents`: mapping from child-region ID to containment-parent ID.
- `min_region_gutter`: minimum sibling-region clearance in native canvas units.
- `hierarchy_anchors`: mapping from arrow ID to semantic `parent`, ownership-bearing `attachment`, `attachment_mode`, `child`, and direction (`left`, `right`, `up`, or `down`). `parent-node` attaches the tail to the parent itself. `owner-region-boundary` attaches the tail to a region proven to own that parent and requires `anchor_label` in the visible arrow text. Layout-derived `target-signpost` also records that owning region and label, but places the compact arrow at the child boundary after all direct corridors are exhausted; audit therefore requires the tip to touch the child, the arrow to point from the parent's side toward it, and the signpost to avoid every other region. It is not a valid architecture-IR `visual_attachment.mode`.
- `hierarchy_tolerance`: permitted boundary-coordinate error.
- `node_semantics`: mapping from meaningful cell ID to at least `kind` and `evidence`.
- `granularity_contracts`: mapping from detail-region ID to its declared mode and reviewed composite policy.
- `require_granularity_contracts`: when true, every declared detail region whose title matches the configured patterns must have a contract.
- `require_logical_operator_contracts`: must be true for strict delivery; confirms the source IR used structured detail-edge shapes, logical operator classifications, packed-operation splits, and separate execution-fusion mappings.
- `require_source_coverage`: must be true for strict delivery; confirms the compiled IR contained a reconciled source-operation inventory rather than relying on legacy self-consistency alone.
- `require_view_projection_contracts`, `semantic_view`, and `view_projection_contract`: bind the compiled canvas to one declared reader-view projection of the complete canonical IR. Strict delivery rejects a manifest that cannot identify the selected projection or prove that algorithm, inference, and backend entities were dispositioned before layout.
- `require_reader_facing_labels`: must be true for strict delivery; confirms logical nodes carried reader-facing labels plus semantic-role and source-symbol mappings and passed the author naming review.
- `require_overview_contract` and `overview_contract`: must be enabled and generated from the validated IR. A hierarchy/paired delivery requires a non-empty standalone Level-0 synopsis contract.
- `require_template_coverage_contract` and `template_coverage_contract`: must be enabled and generated from the validated IR. The IR validator ensures every applicable Level-1 template sequence maps exactly once to visible Level-0 summary text; an empty object means no Level-1 template sequence is applicable.
- `require_cross_level_interface_contracts` and `cross_level_interface_contracts`: must be enabled and generated from the validated IR. Their keys must match the `hierarchy_anchors` expansion IDs exactly after removing the `expand:` cell prefix, including when the mapping is identity.
- `require_operator_display_contract` and `operator_display_contract`: must be enabled and generated from the validated IR. Any `operator-detail` granularity contract requires a non-empty display contract covering operator names, tensor-edge activation shapes, external/structured parameter shapes, and source-symbol placement.
- `require_detail_information_gain_contracts` and `detail_information_gain_contracts`: keys match every Level-2/Level-3 hierarchy expansion. Each entry records a reviewed, non-empty semantic delta from its parent; node count alone is not a delta.
- `require_runtime_variant_contracts` and `runtime_variant_contracts`: keys match every `implementation-detail` region. Each entry maps materially distinct source branches to named operator sequences or records a source-backed `not-applicable` result.
- `require_state_lifecycle_contracts` and `state_lifecycle_contracts`: keys match every persistent `cache`/`state` node and record storage properties plus exact writer/readers, edges, addressing, lifetime, and evidence.
- `require_semantic_style_contract`: must be true for strict delivery. The generated `semantic_style_contract` fixes the `dpsk-v4-original` palette, the resolved class/modifiers of every semantic node, and the complete nine-entry Legend. Missing Legend cells or exact fill/border/font/dash drift are blocking failures; see `semantic-color-legend-contract.md`.
- `require_semantic_glyph_contract`: must be true for strict delivery. Persistent cache/state nodes and the Cache legend swatch use the canonical slanted-storage glyph; cache access/update operators retain the ordinary rounded operator rectangle.
- `vertical_flow_contracts`: machine-generated mapping from every region ID to `direction: bottom-to-top` and its complete named block sequences. Sequence node IDs are stable Draw.io cell IDs. Multiple sequences represent source-backed parallel vertical lanes, not permission for a horizontal sequential chain.
- `require_vertical_flow_contracts`: when true, every declared region must have a vertical-flow contract, including Level 0/1 module summaries. The static auditor rejects any adjacent sequence pair whose target center does not lie above its source center.
- `maximum_vertical_flow_lateral_gap_ratio` and `minimum_vertical_flow_lateral_gap_allowance`: reject a nominally vertical adjacent sequence step when its clear horizontal gap exceeds both limits. Generated manifests default to `4.0` times the wider endpoint and a `240 px` floor, which permits nearby branch lanes but catches canvas-spanning zigzags.
- `vertical_flow_lateral_gap_exclusions`: exact `source-id->target-id` mappings to non-empty source-backed reasons. Stale keys and blank reasons fail; do not exempt an entire region.
- `minimum_node_gutter`, `minimum_route_node_clearance`, and `minimum_route_region_boundary_clearance`: scale-derived hard clearances for sibling boxes and parallel route segments. Their companion exclusion maps use exact `left|right` cell pairs with non-empty reasons.
- `require_compact_execution_geometry`: enables the content-first hard gate. `maximum_region_content_slack` contains exact positive `left`, `right`, `top`, and `bottom` limits outside each region's immediate execution envelope. The top budget may be larger because generated region geometry contains the title header; this must not loosen the other sides. `maximum_region_content_side_slack` is a legacy uniform fallback only. `region_side_slack_exceptions` accepts either a whole region ID or `region-id|side`, always with a non-empty reason.
- `maximum_parallel_lane_gap`: limits the clear horizontal strip between adjacent exclusive portions of named `operator_sequences` in one region. `parallel_lane_gap_exceptions` uses `region-id|sequence-a|sequence-b` with a non-empty source-backed reason. This catches branch lanes spread across a canvas even when their shared source/sink makes the region's aggregate density look acceptable.
- `maximum_straight_hierarchy_arrow_aspect_ratio`: maximum length-to-thickness ratio for a straight `singleArrow`; generated manifests default to `6.0` so a hierarchy block cannot become a cable merely to preserve a level band.
- `straight_hierarchy_arrow_aspect_exceptions`: hierarchy-arrow ID to non-empty obstacle reason. Use only after comparing all four child sides; missing IDs and blank reasons fail.
- `granularity_region_patterns`: optional regular expressions used by the completeness gate; defaults cover Level 2/3, FLOPs, and operator-detail titles.
- `typography_contract`: project-native font palette, estimated wrapped-text height, region-title clearance, text-density floor, and ID-specific exceptions; see `typography-density-contract.md`.
- `density_contract`: optional machine preflight for sparse region content, trailing right/bottom whitespace, and unusually large gaps between spatially adjacent sibling regions. These signals are `WARN` review items, not proof of poor aesthetics.
- `require_semantic_coverage`: when true, every ordinary visible vertex must have a `node_semantics` entry.
- `semantic_coverage_exclusions`: decorative or intentionally out-of-ledger vertex IDs used only with strict coverage.
- `ignore_geometry`: text, decoration, or other vertices omitted from ordinary node collision checks.
- `route_node_exclusions`: vertices that explicit edge segments may geometrically traverse.
- `allowed_node_overlaps`: exact pairs of intentionally overlapping node IDs.
- `allowed_region_contacts`: exact region pairs exempt from sibling intersection/gutter checks.
- `line_jump_crossings`: compiler-generated canonical `edge:a|edge:b` entries. Each records the exact `jumper`, `style: "arc"`, bounded `size`, and non-empty reason copied from the upper edge's layout `line_jump`. A legacy `allowed_edge_crossings` entry cannot establish visual separation and fails strict audit.
- `maximum_line_jumps_per_edge` and `line_jump_count_exceptions`: default bridge-count ceiling and narrow edge-ID-to-reason exceptions. Several bridges on one edge normally require lane reflow.
- `allowed_edge_overlaps`: exact edge pairs whose collinear overlap is intentional. Do not use this for independent routes; positive-length sharing requires a directionally clear semantic rail/bus or junction contract.
- `allowed_shared_rail_sources`: source-node IDs whose outgoing edges form a declared same-direction fan-out rail.
- `junction_rails`: compiler-generated exact terminal-run contracts keyed by junction/role/side, with canonical junction ID, origin, and per-edge terminal coordinates. Static audit reconstructs these from actual XML and permits overlap only inside the corresponding same-direction terminal extents. Missing/stale registries and crowded non-centered junction ports fail.
- `junction_rail_markers`: generated black-dot boxes at shared terminal branch contacts. Their exact positions and glyphs are checked separately; they are not new semantic operators. Incoming junction edges must have no terminal arrowhead.
- `fanout_shape_contracts`: mappings for fan-outs with at least three consumers. Use `mode: "source-node"` when one shape belongs to every branch and put it in the source/interface node; use `mode: "every-branch"` when every branch must repeat it. Include the exact `shape` text and optional complete `edge_ids` set so topology drift fails the audit.
- `fanout_shape_exclusions`: narrowly justified source IDs whose mixed branch labels are semantic rather than tensor-shape annotations.
- `fanout_side_exclusions`: narrowly justified source IDs whose three-way-or-larger fan-out must leave more than one side. Prefer a common source side with distinct ports and lanes; use this only when the topology cannot be made clear that way.
- `minimum_edge_endpoint_gap`: minimum page-unit separation between connected source and target boxes; defaults to `16`, which preserves an independently visible arrow approach.
- `edge_endpoint_gap_exclusions`: narrowly justified edge IDs allowed to connect closer than the minimum, with the reason recorded in the manifest rationale.
- `region_content_contracts`: mappings from a visible region ID to the exact non-region cell IDs that must remain geometrically contained in it, especially when those cells use page-level XML parents.
- `allowed_region_boundary_nodes`: exact `[cell_id, region_id]` pairs for deliberate boundary-interface symbols that straddle a region frame. Do not use this for ordinary operators or tensor nodes.
- `allowed_region_border_overlaps`: narrowly justified `[edge_id, region_id]` pairs allowed to share a collinear segment. Ordinary perpendicular boundary crossings do not need an exception.
- `allowed_long_routes`: edge IDs with reviewed, obstacle-justified detours.
- `route_inflation_floor` and `route_inflation_ratio`: long-route review thresholds.
- `route_quality_exclusions`: ID-to-reason mapping for explicit paths whose otherwise suspicious hook, collinear waypoint, or near-axis dogleg is required by a named obstacle or lane contract.
- `route_degree_exclusions`: ID-to-reason mapping for non-execution relations that must not affect one-in/one-out chain detection and are not identifiable by the standard thick hierarchy/reuse style.
- `near_axis_dogleg_tolerance`: optional native-unit override for near-axis chain alignment; when omitted, the auditor uses 75% of the smaller endpoint height.
- Port-alignment doglegs are rejected independently of center distance when the source and target boundary spans overlap and a clear straight route can be formed by moving the endpoint ports. This also applies to fan-out and fan-in edges; use a reasoned `route_quality_exclusions` entry only when a named obstacle or port-order contract requires the bend.
- `minimum_route_backtrack`: optional native-unit visibility floor for U-turns; shorter reversals are cleanup warnings, while larger reversals block delivery. When omitted, the floor is the larger of 2 units and 5% of the smaller endpoint height.
- `forbidden_exact_text`: exact visible strings that indicate garbage or stale placeholders.
- `forbidden_text_patterns`: regular expressions that must not match visible text.
- `unregistered_hierarchy_exclusions`: arrow-shaped decorative vertices that are not expansions.
- `rendered_svg_audit`: thresholds and narrowly reasoned exceptions for geometry extracted from the official Draw.io SVG.
- `rendered_svg_audit.maximum_edge_label_distance`: maximum distance from an edge label to the expanded neighborhood of at least one segment of its own rendered route; generated manifests use `64 px`.
- `rendered_svg_audit.allowed_edge_label_distances`: exact edge IDs with non-empty reasons for an unavoidable larger rendered label offset.
- `rendered_svg_audit.minimum_visible_edge_label_flank`: minimum visible route length required on both sides of a label hosted by one straight segment; generated manifests scale it from the edge-label font so a white label box cannot erase nearly the whole connector.
- `rendered_svg_audit.minimum_edge_label_route_clearance`: clearance between an ordinary rendered route and another edge's label box. A crossing or near-touch fails unless the exact edge/text pair is registered in `allowed_edge_text_crossings` with a reason.

Pairs are two-element arrays, for example `["edge_a", "edge_b"]`. Keep exceptions narrow and stable.

Compiler-generated `fusion:<id>` dashed boundaries appear in `required_cells`, `semantic_coverage_exclusions`, `ignore_geometry`, and the rendered auditor's reasoned `ignored_cells`: the boundary is a physical-execution annotation rather than another logical operator, and its intentional containment of member nodes must not look like an ordinary overlap. This does not make it unchecked. Before compilation, the fusion-boundary geometry gate requires the boundary to remain inside its declared owner region and rejects a boundary that intersects a non-member node.

```json
"fanout_shape_contracts": {
  "input_x": {
    "mode": "source-node",
    "shape": "[B,S,D]",
    "edge_ids": ["x_to_q", "x_to_k", "x_to_v"]
  }
}
```

Do not place a shared input shape on only one of several outgoing branches. It makes sibling paths appear dimensionally different even when their source tensor is identical.

## Compact execution geometry

Strict compiler-path manifests make content-first geometry blocking rather than advisory:

```json
"require_compact_execution_geometry": true,
"maximum_region_content_slack": {
  "left": 132,
  "right": 132,
  "top": 160,
  "bottom": 132
},
"region_side_slack_exceptions": {},
"maximum_parallel_lane_gap": 160,
"parallel_lane_gap_exceptions": {}
```

The auditor derives each region's immediate execution envelope from directly owned nodes and
immediate child regions. When Draw.io `startSize` is present it is excluded from top slack;
otherwise the generated title header is covered by the larger top budget. A hierarchy arrow, route,
or alignment grid is not region content and cannot justify inflating the frame. A whole-region
exception or a narrower `region-id|side` exception needs a non-empty reason.

For regions with multiple named operator sequences, the auditor removes their shared
prefix/suffix nodes and compares the exclusive branch envelopes in horizontal order. Adjacent
branches farther apart than `maximum_parallel_lane_gap` fail. Use
`region-id|sequence-a|sequence-b` exceptions only for a source-backed distant state/cache lane
or another semantic separation; a desire to reserve an expansion corridor or improve a
density ratio is not valid.

## Density preflight

Use the generic density preflight to reduce repetitive manual scanning while preserving human visual judgment:

```json
"density_contract": {
  "minimum_region_content_width_ratio": 0.35,
  "minimum_region_content_height_ratio": 0.35,
  "maximum_trailing_right_ratio": 0.30,
  "maximum_trailing_bottom_ratio": 0.30,
  "maximum_horizontal_region_gap": 240,
  "maximum_vertical_region_gap": 180,
  "minimum_perpendicular_overlap_ratio": 0.25,
  "minimum_internal_void_area_ratio": 0.12,
  "minimum_internal_void_width_ratio": 0.30,
  "minimum_internal_void_height_ratio": 0.20,
  "internal_void_grid_size": 40,
  "internal_void_node_padding": 12,
  "region_exceptions": {},
  "gap_exceptions": {}
}
```

Region density uses the exact members in `region_content_contracts`, so decorations and unrelated cells do not distort the content bounding box. It also rasterizes each region at the configured grid size and finds large empty rectangles bracketed by content on opposite sides; this catches internal whitespace pockets between operator lanes that an outer bounding box cannot see. Node padding keeps ordinary label clearance from being mistaken for empty space. Adjacent-gap checks consider only the nearest sibling in each direction whose perpendicular overlap reaches the configured ratio. An excluded or non-candidate sibling still acts as a separator when it crosses the open gap and fully covers the pair's shared perpendicular projection; a partial side obstacle does not suppress the warning. All findings are warnings with the measured ratio, gap, or approximate empty-box coordinates. Review the official export before changing geometry: routing corridors, hierarchy expansion space, and intentional comparison alignment can legitimately be sparse.

`region_exceptions` maps a region ID to a reason and suppresses all density warnings for that region. `gap_exceptions` uses a normalized `left-id|right-id` key and a non-empty reason. Prefer adjusting project thresholds or recording a narrow exception over weakening the shared auditor.

## Rendered-SVG audit

`scripts/render_drawio.py` invokes the rendered auditor after official SVG export. Its page-level configuration is nested so it cannot be confused with static XML geometry policy:

```json
"rendered_svg_audit": {
  "minimum_clearance": 2.0,
  "label_fit_tolerance": 3.0,
  "material_overlap_depth": 3.0,
  "material_overlap_ratio": 0.08,
  "ignored_cells": {},
  "allowed_label_overlaps": {},
  "allowed_label_node_overlaps": {},
  "allowed_edge_text_crossings": {},
  "allowed_edge_node_crossings": {},
  "allowed_labels_outside_nodes": {},
  "allowed_label_at_bends": {},
  "route_quality_exclusions": {},
  "route_degree_exclusions": {},
  "near_axis_dogleg_tolerance": null,
  "minimum_route_backtrack": null
}
```

`minimum_clearance` controls non-blocking proximity warnings. `label_fit_tolerance` absorbs small antialiasing/rasterization overflow in official fallback images. `material_overlap_depth` and `material_overlap_ratio` suppress incidental subpixel contacts; a collision must satisfy both thresholds before it is a hard failure.

Every exception field is an ID-to-reason object. Pair exceptions use a stable normalized key with IDs sorted lexically and joined by `|`:

```json
"allowed_edge_text_crossings": {
  "edge_id|weight_annotation_id": "The annotation intentionally labels this projection route."
}
```

Do not add an exception merely to obtain `PASS`. First inspect the official detail export and prefer repairing the geometry. `WARN` remains a review queue and does not require an exception when the reviewer confirms it is harmless; recurring intentional warnings may be recorded to keep future audits focused.

## Granularity contracts

Use a granularity contract for every Level-2/Level-3, operator/FLOPs, or implementation region whose leaf-node detail matters:

```json
"granularity_contracts": {
  "detail_region": {
    "mode": "operator-detail",
    "allowed_composites": {
      "fused_node": {
        "classification": "fused-operation",
        "evidence": "code/config confirmed",
        "source": "modeling_example.py:420",
        "reason": "One fused source-level call."
      },
      "module_node": {
        "classification": "expanded-elsewhere",
        "evidence": "code/config confirmed",
        "detail_target": "runtime_region",
        "reason": "Canonical expansion is shown in the target region."
      }
    },
    "node_exclusions": {
      "decorative_cell": "Non-semantic visual marker."
    }
  }
}
```

Valid modes are `module-summary`, `operator-detail`, and `implementation-detail`. Compiler-generated contracts also record the integer hierarchy `level`; strict delivery uses it to reconcile Level-0 overview regions and applicable Level-1 template sequences. Valid composite classifications are `fused-operation`, `module-boundary`, and `expanded-elsewhere`. `fused-operation` is legal only for an `implementation-detail` execution leaf; it cannot suppress logical member nodes in `operator-detail`.

For an implementation-level `fused-operation`, provide `source` and keep its mapping to logical operator IDs in the architecture contract. For `expanded-elsewhere`, provide an existing `detail_target` cell ID. Every exception requires `evidence` and `reason`. `node_exclusions` is an ID-to-reason object rather than a broad list.

The auditor scans every ordinary node geometrically contained by an `operator-detail` region. A label containing two or more recognized operator terms fails unless its cell ID is registered in `allowed_composites`. This is a generic backstop; the required human node-classification pass remains broader than label heuristics. See [granularity-contract.md](granularity-contract.md).

## Vertical-flow contracts

Generated compiler-path manifests include every region, even a region with zero or one semantic block:

```json
"vertical_flow_contracts": {
  "region:model": {
    "direction": "bottom-to-top",
    "sequences": [
      {"id": "main", "nodes": ["node:input", "node:block", "node:output"]}
    ]
  }
}
```

For a parallel Q/K/V-style branch, record one complete sequence per lane; shared input, branch, merge, or output nodes may appear in more than one sequence. Horizontal separation between lanes is legal, but every adjacent pair within each sequence must rise. Do not use an empty contract, exception, or macro `child_direction` to legitimize a horizontal small-block chain.

The vertical-flow audit also measures the clear horizontal gap between each adjacent pair. Its allowance is the larger of the absolute floor and the configured endpoint-width ratio. This deliberately ignores ordinary center offsets between overlapping/nearby lanes while rejecting a shared sequence stretched across most of a large region. A genuine distant side lane needs an exact, reasoned pair exception; Q/K/V or alternative branches placed adjacently do not.

## Semantic entries

The auditor checks entry completeness and referenced cell existence. The ledger remains human-authored because code cannot infer model truth from box geometry.

```json
"node_semantics": {
  "mixer": {
    "kind": "parameterized-operation",
    "evidence": "code/config confirmed",
    "source": "modeling_example.py:420"
  }
}
```

Useful `kind` values include `module`, `parameterized-operation`, `vector-operation`, `io-operation`, `cache`, `recurrent-state`, `declared-boundary`, and `junction`. Use the evidence statuses defined by the main style specification.

## Render regions

`render.detail_regions` is a review ledger, not currently an automatic crop instruction. Each entry identifies a semantically complete region that must be inspected in the 4800 px export:

```json
{
  "name": "mixer implementation",
  "anchor_cells": ["mixer_region"],
  "checks": ["text fit", "branch routing", "shape labels"]
}
```

Prefer `anchor_cells` over fragile pixel coordinates. Temporary crops may be produced for inspection, but should not become canonical artifacts.

## Rendered SVG fields

- `label_fit_tolerance`: rasterization tolerance for visible label ink outside its node; defaults to `0.5` px.
- `endpoint_interior_margin`: inset used to detect a rendered route that enters or re-enters its own source/target; defaults to `2` px.
- `allowed_label_arrow_overlaps`, `allowed_endpoint_reentries`, `allowed_label_at_bends`, `route_quality_exclusions`, and `route_degree_exclusions`: ID-to-reason exceptions. Normally keep these empty; an exception must describe a real visual convention, not suppress a crowded route.
- `near_axis_dogleg_tolerance`: optional rendered-pixel override; when omitted, the rendered audit uses 75% of the smaller rendered endpoint height.
- `minimum_route_backtrack`: optional rendered-pixel visibility floor; when omitted, the rendered audit uses the larger of 2 px and 5% of the smaller rendered endpoint height.
