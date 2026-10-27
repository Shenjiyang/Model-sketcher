# Typography and density contracts

Use this contract for every architecture diagram. Native font size is a project calibration, not a universal constant.

## Select the base size

Declare the intended viewport and primary reading frame first. Measure or estimate its render scale `Z = displayed pixels / native canvas units`, then choose a target apparent ordinary-node size `P` (normally 16–20 px for dense technical diagrams). Compute the starting native size instead of copying it from another canvas:

```text
F = P / Z
```

Round `F` to the nearest practical integer and validate it in the official renderer. For example, `P=18 px` at `Z≈0.67` gives `F≈27`; the same target at `Z=1.0` gives `F=18`. A large master viewed around 0.6–0.7 detail scale may therefore need a native value near 27, while a compact diagram viewed at 100% may need 17–18. Do not choose `F` from raw canvas width alone: the primary reading frame and expected zoom determine the apparent size. Never infer font size from hierarchy level.

Derive roles from the selected ordinary-node base `F`:

```text
ordinary node              F
edge/tensor label          0.72F–0.78F
weight/short annotation    0.72F–0.78F
nested region title        1.00F–1.10F
top region title           1.20F–1.30F
hierarchy label            0.74F–0.82F
```

Round the result to a small integer palette. Use one ordinary-node value across Level 0, Level 1, Level 2, and Level 3. Change it only for a semantic role or an evidenced space exception, never merely because a node sits deeper in the hierarchy.

Record `Z`, `P`, and the resulting palette in the project notes or manifest rationale. If the full-master overview and the detail-reading frame use very different scales, optimize ordinary operators for the detail frame; the overview is responsible only for hierarchy, region titles, and dominant flow.

When the primary viewing scale is known, make it machine-checkable:

```json
"primary_view_scale": 0.67,
"minimum_apparent_ordinary_font": 16,
"target_apparent_ordinary_font": 18,
"warn_role_ratio_drift": true
```

The static auditor computes `ordinary_node_font × primary_view_scale`. Falling below the declared minimum is a blocking failure; falling between the minimum and target is a visual-review warning. It also warns when the declared font-role palette drifts outside the recommended ratios below. Do not guess the scale from raw canvas width; declare the scale of the actual primary reading frame.

## Declare the calibration in the IR

Record the selected calibration in `project.typography` so the compiler, planner, and auditor all resolve the same numbers. Two equivalent forms are accepted; do not mix keys from both in one project:

```json
"typography": {
  "viewing_profile": "desktop-review",
  "ordinary_node_font": 18,
  "edge_label_font": 14,
  "annotation_font": 14,
  "region_title_font": 20,
  "hierarchy_label_font": 20,
  "primary_view_scale": 0.67,
  "minimum_apparent_ordinary_font": 16,
  "target_apparent_ordinary_font": 18
}
```

or the ratio form, which derives every role from one native base using the recommended bands above (undeclared roles keep the reference ratio of the absolute form):

```json
"typography": {
  "viewing_profile": "desktop-review",
  "native_base_size": 18,
  "role_ratios": {
    "node_label": 1.0,
    "edge_label": 0.78,
    "annotation": 0.78,
    "region_title": 1.11
  },
  "primary_view_scale": 0.67
}
```

Known roles are `node_label`, `edge_label`, `annotation`, `region_title`, and `hierarchy_label`; the `viewing_profile` string is carried into the manifest as provenance. Absolute keys win when both forms would apply. A partial absolute form may declare only the sizes that differ from the reference calibration (ordinary 18, edge 14, annotation 14, region title 20, hierarchy 20); undeclared roles keep the reference value and `annotation_font` follows `edge_label_font` when omitted.

## Hierarchy arrow labels

An expand label may sit on its arrow or beside it, controlled by `hierarchy_label_placement` in `project.typography` (`auto` default, `on-shape`, or `beside`). With `auto` or `on-shape`, the planner first tries to keep the wrapped label ink inside the arrow: the cross-section may grow toward 128/160/192/256 thickness, clamped to the parent∩child corridor band and re-centered inside it, but the label ink may cover at most 45% of the arrow polygon (an ink dimension above 90% of the box also fails). If no thickness in budget fits, `auto` moves the label to the freer shaft flank as a separate text cell (`expand:<edge>.label`) and `on-shape` keeps the grown arrow and requires a rendered occlusion exception. `beside` always uses the companion cell. A companion cell must stay clear of its own arrow polygon in the rendered SVG; residual overlap with other geometry is a planner finding, not a silent placement.

A beside label runs along its corridor. When an east/west arrow crosses a corridor narrower than the wrapped label, the planner rotates the companion (`horizontal=0`): the wrapped block is emitted with explicit `<br>` breaks and, once rotated, its lines stack across the corridor while its longest line runs along it; the compiled cell geometry is that rotated footprint (cross-section wide, ink length tall). An unwrapped single line is the fallback when even the wrapped cross-section would not fit. A flank narrower than the label is tried at progressively tighter wraps (down to half the natural width) before rotation, so a squeezed label shortens instead of overrunning its neighbour. Sibling expand arrows and companion cells already placed in the same corridor are obstacles too: two beside labels cannot claim the same flank, and the planner falls back to a shifted flank or a tighter wrap before it reports. Rotation is chosen only when it clears more geometry than every horizontal option. A direct arrow whose cross-section cannot fit the band with the 24px corner margin on both sides gives up thickness down to the 48px minimum before the finding is reported; on-shape arrows keep their grown cross-section. A direct arrow whose cross-section still sits closer than 24px to the child boundary corner is reported as a corridor finding; widen the overlap band or move the child region instead of accepting a corner-grazing arrow.

The rendered SVG audit enforces the budget with `maximum_hierarchy_label_occlusion` (default 0.45) against the exported singleArrow silhouette, honoring `hierarchy_label_occlusion_exceptions` as an ID-to-reason object. Draw.io exports rotated labels as an unrotated image inside a `rotate()` group, so the auditor resolves every element's accumulated transform before measuring its box.

## Size geometry from content

Start from measured rendered text and add consistent padding. Useful starting ratios are:

```text
horizontal padding         0.7F–0.9F per side
one-line node height       2.2F–2.5F
two-line node height       3.0F–3.5F
three-line node height     4.0F–4.5F
```

A content-sized ordinary node should normally devote at least 50–55% of its inner width to its longest rendered line. Wider nodes are allowed only when width carries meaning: multi-port fan-in/fan-out, a module boundary, a comparison alignment family, or a routing corridor that cannot be expressed by independent ports. Record these exceptions by cell ID.

Never stretch nodes or spread branch lanes merely to raise a region-content ratio. Density
is measured after node sizing and topology-aware compaction, not used as a target that visible
content must fill. Hierarchy-arrow shafts remain outside the execution envelope; when they
need a different exit location, use a registered owner-region egress instead of resizing the
source node or owner region.

## Size dependency gaps from labels

Do not place nodes on a loose global grid. For a direct dependency, derive the gap from the content on the edge:

```text
no edge label              0.9F–1.2F
one-line edge label        1.6F–2.1F
branch/merge corridor      2.2F–3.0F
state/cache side route     2.2F–3.7F
```

These are starting ranges, not a reason to compress through labels or arrowheads. Reserve extra distance only for an actual crossing-free lane, branch, state path, or hierarchy corridor. If exchanging ports or sibling order removes the need, use the shorter route.

## Aligned-spine precedence

When consecutive producer and consumer nodes share a centerline, preserve the direct spine. A titled region boundary is not an obstacle that justifies a dogleg, asymmetric ports, or a detour solely to avoid header text. First shorten, wrap, reposition, or, where the reading frame permits, reduce the affected region title and record the exact typography exception. Only route around the region when a direct line would still collide after those title-level repairs or would create a real branch/crossing conflict.

After any spine reroute, inspect the official Draw.io route at detail scale. The rendered audit must show that the line clears both region-title glyphs and arrowhead approaches; XML port coordinates alone are insufficient.

## Draw.io manifest

Record the project calibration so the shared auditor can enforce it:

```json
"typography_contract": {
  "ordinary_node_font": 27,
  "edge_label_font": 20,
  "annotation_font_min": 20,
  "nested_region_title_font": 27,
  "top_region_title_font": 33,
  "hierarchy_label_font": 20,
  "primary_view_scale": 0.67,
  "minimum_apparent_ordinary_font": 16,
  "target_apparent_ordinary_font": 18,
  "warn_role_ratio_drift": true,
  "minimum_text_fill_ratio": 0.5,
  "estimated_line_height_ratio": 1.0,
  "minimum_vertical_padding_ratio": 0.25,
  "node_font_exceptions": {},
  "edge_font_exceptions": {},
  "annotation_font_exceptions": {},
  "region_font_exceptions": {},
  "text_height_exceptions": {},
  "region_title_clearance_exceptions": {},
  "wide_node_exceptions": {
    "multiport_rule": "Width exposes five independent input ports."
  }
}
```

Every exception is an ID-to-reason object with a non-empty reason. Select different numeric values for a smaller or larger diagram; keep the ratios and audit procedure.

## Review gate

1. inspect the font distribution by semantic role;
2. compare equivalent nodes across every hierarchy level;
3. inspect every node flagged as unusually wide and either shrink or justify it;
4. trace direct dependencies and remove distance unsupported by a label or route;
5. render with official Draw.io and inspect at the declared primary scale;
6. revise geometry before lowering font size.
7. inspect every edge label in the official Draw.io detail export; its background may interrupt a straight line but it must not touch a node, arrowhead, region title, or another label.
8. inspect every expand-arrow label in the official export; on-shape ink may not cover its arrow beyond the occlusion budget, and a beside companion must not overlap its own arrow or other geometry.
