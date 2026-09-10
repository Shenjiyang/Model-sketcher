# Strict delivery contract

Use this contract for every new editable Draw.io architecture project. It turns the evidence-first workflow into a fail-closed gate so a permissive project manifest cannot claim completion.

Strict compiler-path delivery includes generated gates for detail information gain, runtime variants, state lifecycles, and semantic glyphs. Their registries may be empty only when the corresponding Level-2/3 expansion, implementation-detail region, or cache/state node is absent.

## Required project artifacts

Keep these beside the diagram or in its project source directory:

1. `architecture.json`, the semantic source of truth;
2. an evidence record that identifies version-matched sources, claim status, and unresolved conflicts;
3. a generated topology contract containing the level tree, ownership tree, call/reuse relationships, reading direction, repetition boundaries, and expansion registry;
4. `topology-review.json`, an independent, digest-bound review of the architecture, generated ASCII, and pinned sources;
5. a shape ledger containing producer, consumer, shape transition, parameter dimensions, state/cache lifetime, and evidence status;
6. the editable `.drawio`;
7. its `*.audit.json` manifest;
8. official Draw.io overview, detail, and SVG acceptance exports produced only after the contract and static audits pass.

A single temporary low-scale official diagnostic export may be used immediately after compile to reject a bad macro composition. Keep it outside the canonical deliverables, label it diagnostic, and never use it as rendered or manual acceptance. Follow [layout-failure-recovery.md](layout-failure-recovery.md) when the first static audit is large or concentrated.

Do not draw Level-2 or Level-3 geometry until the semantic records and independent topology review pass. The review is event-triggered: obtain it for a cold start, a semantic topology revision, a pinned-source revision, or an explicit recheck. Reuse the same review for layout coordinates, ports, routes, hierarchy corridors, typography, colors, density, and rendering while its architecture, generated ASCII, and source digests remain current. A high-level diagram may mark an unverified child as `not yet expanded`; it must not invent an operator summary to fill the space.

## Required manifest gate

Start from `assets/strict-audit-template.json`; replace every placeholder and keep the strict booleans enabled. Its important fields are:

```json
{
  "schema_version": 1,
  "workflow_contract": {
    "output_view": "hierarchy-master",
    "contains_detail_regions": true,
    "architecture_file": "sources/architecture.json",
    "evidence_file": "sources/model-evidence.md",
    "topology_contract_file": "sources/model-topology.md",
    "topology_review_file": "sources/topology-review.json",
    "shape_ledger_file": "sources/model-shapes.md",
    "evidence_sources": [
      {"role": "checkpoint-config", "path": "references/model/config.json", "revision": "checkpoint-id", "claims": ["dimensions", "layer cadence"]},
      {"role": "canonical-model", "path": "references/model/modeling.py", "revision": "commit-id", "claims": ["forward order", "branches", "state updates"]}
    ]
  },
  "defaults": {
    "require_fixed_ports": true,
    "require_port_geometry_contracts": true,
    "expected_ports": {},
    "require_registered_edge_label_positions": true,
    "expected_edge_label_positions": {},
    "line_jump_crossings": {},
    "maximum_line_jumps_per_edge": 3,
    "line_jump_count_exceptions": {},
    "require_semantic_coverage": true,
    "require_granularity_contracts": true,
    "require_logical_operator_contracts": true,
    "require_source_coverage": true,
    "require_reader_facing_labels": true,
    "require_overview_contract": true,
    "overview_contract": {"replace_from_generated_manifest": true},
    "require_template_coverage_contract": true,
    "template_coverage_contract": {"replace_from_generated_manifest": true},
    "require_cross_level_interface_contracts": true,
    "cross_level_interface_contracts": {"replace_from_generated_manifest": true},
    "require_operator_display_contract": true,
    "operator_display_contract": {"replace_from_generated_manifest": true},
    "require_semantic_style_contract": true,
    "require_compact_execution_geometry": true,
    "semantic_style_contract": {"replace_from_generated_manifest": true},
    "regions": [],
    "granularity_contracts": {},
    "node_semantics": {}
  },
  "render": {
    "overview_width": 2560,
    "detail_width": 4800,
    "detail_regions": [
      {"name": "detail A", "anchor_cells": ["region_a"], "checks": ["text fit", "routing", "ownership"]},
      {"name": "detail B", "anchor_cells": ["region_b"], "checks": ["text fit", "routing", "ownership"]}
    ]
  }
}
```

Every evidence source must identify its role and the claims it supports. Valid roles are `checkpoint-config`, `canonical-model`, `official-report`, `inference-implementation`, and `supporting-analysis`. Strict delivery requires at least one checkpoint config and one executable model source (`canonical-model` preferred; a version-matched inference implementation is supporting evidence when canonical code is unavailable). Prefer a reproducible revision or checkpoint identifier; record `unknown` explicitly when one is unavailable. A performance-estimator descriptor alone is never executable model evidence.

Strict final delivery also requires a current schema-v3 finalized independent topology review, all four summary/display gates, `require_logical_operator_contracts: true`, `require_source_coverage: true`, `require_view_projection_contracts: true`, a named `semantic_view`, `require_reader_facing_labels: true`, `require_port_geometry_contracts: true`, `require_registered_edge_label_positions: true`, `require_semantic_style_contract: true`, and `require_compact_execution_geometry: true`. The delivery auditor first revalidates the full architecture and required source files, then binds the review to the canonical semantic digest of `architecture.json`, exact generated topology-contract bytes, every pinned evidence file, and the controlled-finalizer receipt. It rejects self-authored, placeholder, duplicate, incomplete, blocking, unfinalized, edited-after-finalization, or stale reviews; source inventory must close every path and source-operation ID, and semantic/reconstruction results must close every applicable check and region. The generated manifest carries the validated overview, template coverage, cross-level interface, and operator-display contracts from the IR. Hierarchy/paired delivery requires a non-empty overview; operator-detail delivery requires a non-empty operator-display contract; cross-level contract IDs must match the hierarchy-anchor registry exactly. This prevents a project from bypassing semantic validation and later declaring delivery PASS with geometry alone. An older IR may remain readable as migration input, but it cannot compile or claim strict final PASS until the IR and generated manifest are migrated.

## Required commands

Before official rendering:

```bash
python3 scripts/audit_delivery_contract.py model.drawio --manifest model.audit.json
```

Then run the official renderer. It repeats the strict contract preflight and refuses a permissive manifest:

```bash
python3 scripts/render_drawio.py model.drawio --manifest model.audit.json \
  --drawio-bin /path/to/drawio/AppRun --output-dir /tmp/model-review
```

`--legacy-project` exists only to inspect an older diagram while migrating it. A run using that flag cannot be reported as strict-delivery PASS or final visual acceptance.

After export, inspect the full overview and every declared detail region. Machine PASS never replaces this review. Do not copy previews into the canonical project location until the rendered audit passes and manual inspection finds no clipping, ambiguous ownership, avoidable detours, overlapping labels, or excessive dead space.
