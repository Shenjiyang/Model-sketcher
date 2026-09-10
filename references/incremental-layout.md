# Incremental layout and region stability

Read this reference when revising an existing compiler-path project or preserving manual layout work.

Incremental means impact-controlled, not immutable. Semantic dependencies may invalidate earlier summaries, shapes, edges, or regions. Preserve unrelated work by default, while allowing affected content to adapt for correctness and routing clarity.

## Policies

`project-state.json` may assign one policy per region:

- `preserve`: retain existing geometry when possible; an affected region may reflow internally while keeping its origin. Report any movement of existing cells.
- `adaptive`: allow an affected region to be regenerated and repositioned.
- `derived`: regenerate the region from its dependencies, typically for summaries.
- `frozen`: reject a change that invalidates the region. Use only when the user explicitly requires it.

Unspecified regions default to `adaptive`. Never infer `frozen` merely because a region passed review.

Backend capability: the global ELK planner currently rejects `preserve` and
`frozen` policies rather than claiming to enforce them. The impact analyzer
retains these concepts for change detection. Migrate an old native project
explicitly: retain evidence/review, select adaptive reflow only when allowed,
and regenerate geometry. Do not silently discard a user-required freeze.
For unchanged architecture, a matching previous layout plus exact overrides
supports visual-only refinement without another ELK run. After semantic changes,
regenerate an ELK base; the old incremental native planner has been removed.

## Change modes

- `patch`: labels, evidence, or non-structural node properties changed.
- `regional-reflow`: nodes, edges, ownership, or operator sequences changed.
- `full-rebuild`: project view or another declared global contract changed.
- `no-op`: the semantic IR is unchanged.

Run `plan_change_impact.py` before incremental layout. It propagates changes through downstream consumers and ownership ancestors, records affected and preserved regions, and blocks invalidation of an explicitly frozen region.

## Overrides

Keep reviewed manual geometry in `layout_overrides`, keyed by stable IDs. Region and node overrides replace only the named box fields; edge overrides replace only named route fields. Apply overrides after automatic layout so regeneration does not silently erase deliberate micro-adjustments. Remove an override when it conflicts with corrected semantics or produces an audit failure, and record the reason.

Hierarchy arrows are also derived after final node/region movement. When the centered automatic shaft would cover a real node, tensor/relation edge, or rendered label, record only the necessary `layout_overrides.hierarchy_arrows.<expand_relation_id>` fields in `project-state.json`; do not hand-edit the compiled XML or keep an untracked change only in generated `layout.json`. The allowed fields are `x`, `y`, `w`, and `h`. Direction remains derived from the registered physical attachment/child placement and cannot be changed by a corridor override. The compiler still verifies the unchanged semantic parent, attachment mode and ID, owning-region membership, anchor label, size, direction, attachment/child centerline and boundary contact, and perpendicular corridor overlap. Shape-aware static and rendered audits must prove the visible arrow polygon is clear. Regeneration reapplies the recorded override after automatic derivation.

An incremental run must still execute the full static audit. At visual review, focus on affected regions and cross-region edges, then verify that preserved regions did not move or become occluded.
