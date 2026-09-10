# Overview and cross-level contracts

Read this reference for every hierarchy master or paired delivery. Hierarchy levels describe
reader-facing detail, not merely source-code containment depth. A valid Level 0 must remain
useful when every deeper region is hidden.

## Level responsibilities

- **Level 0 — model synopsis:** show the input/front end, main backbone, repetition or fixed
  cadence, model-defining layer families and state paths, genuine model-level side branches,
  final normalization/readout, and outputs. Do not collapse a heterogeneous backbone into one
  generic `Decoder Stack xN` block whose small subtitle carries the entire architecture.
- **Level 1 — representative compositions:** show one complete path for every materially
  different repeated layer template or major branch composition. Shared prefixes and suffixes
  may align, but attention/mixer, residual, normalization, FFN/MoE, and state differences must
  remain visible.
- **Level 2 — logical operator definition:** expand one named component into mathematical and
  tensor/view operations with shapes on edges.
- **Level 3 — implementation detail:** show kernels, runtime modes, cache/state layouts,
  communication, dispatch, or backend fusion implementing a Level-2 definition.

Level 0 is an editorial architecture synopsis grounded in evidence. It is not a marketing
diagram and does not invent features for symmetry. For example, expose MTP or a vision tower
only when the selected checkpoint contains it; otherwise expose that model's own distinguishing
components.

## Level 0 overview contract

Every hierarchy view containing a Level-0 region declares `overview_contract`:

```json
{
  "overview_contract": {
    "status": "pass",
    "method": "standalone-reader-review",
    "level0_region_ids": ["model"],
    "spine_nodes": ["input", "embedding", "backbone", "final_norm", "head", "output"],
    "facets": {
      "input": ["input"],
      "input-adapter": ["embedding"],
      "backbone": ["backbone"],
      "output": ["final_norm", "head", "output"]
    },
    "signature_components": [
      {
        "id": "hybrid-mixer-schedule",
        "display_text": "Local mixer x3 + global attention x1",
        "level0_nodes": ["backbone"],
        "level1_nodes": ["local_layer", "global_layer"],
        "evidence": ["config", "forward"]
      }
    ],
    "checks": [
      "standalone-model-identity",
      "heterogeneous-backbone-summary",
      "model-level-branch-coverage",
      "output-readout-coverage"
    ],
    "findings": ["Level 0 identifies the fixed hybrid cadence without opening Level 1."]
  }
}
```

`spine_nodes` is an actual Level-0 tensor path. The required `input`, `backbone`, and `output`
facets map to visible Level-0 nodes; add model-specific facets such as `input-adapter`,
`recurrent-state`, `auxiliary-head`, or `modality-tower` when evidence requires them.

Each `signature_components` entry names text that is visibly present in its mapped Level-0
nodes. Map every Level-1 node that owns an expanded Level-2/3 definition. One Level-0 node may
summarize several related components, but its visible lines must name them; an invisible IR
claim does not satisfy the overview.

Review Level 0 alone at the primary reading scale. A technically complete input-to-output chain
still fails when removing the detail regions leaves no way to identify the model's distinctive
backbone, layer families, state mechanism, or model-level branches.

## Level 1 template coverage

If a Level-1 region declares `operator_sequences`, map every sequence exactly once:

```json
{
  "template_coverage_contract": {
    "status": "pass",
    "method": "template-family-review",
    "regions": {
      "decoder_templates": [
        {
          "sequence_id": "local_dense_layer",
          "summary": "Local attention + dense FFN",
          "level0_nodes": ["backbone"],
          "evidence": ["config", "forward"]
        },
        {
          "sequence_id": "global_moe_layer",
          "summary": "Global attention + sparse MoE",
          "level0_nodes": ["backbone"],
          "evidence": ["config", "forward"]
        }
      ]
    },
    "checks": [
      "distinct-template-families",
      "complete-template-paths",
      "level0-summary-mapping"
    ],
    "findings": ["Both fixed layer families have complete Level-1 paths and visible Level-0 summaries."]
  }
}
```

Do not represent a fixed schedule as a runtime decision. For a periodic cadence, show one
representative period plus its repetition. For an irregular list of fixed layer indices, show a
named fixed schedule and the count of each family, then use Level 1 for the full template
comparison.

## Cross-level interface closure

Every `kind: expand` relation declares one `cross_level_interface_contracts` entry. This record
does not turn the hierarchy arrow into tensor flow; it proves that the parent summary and child
detail describe the same interface:

```json
{
  "cross_level_interface_contracts": {
    "expand_attention": {
      "parent_shape": "[B,S,D]",
      "child_shape": "[N,D]",
      "mapping": "N=B*S",
      "display_node": "attention_detail_input",
      "display_text": "N=B*S",
      "status": "code-confirmed",
      "evidence": ["forward"]
    }
  }
}
```

Equal shapes use `mapping: identity`. Different shapes require a concrete mapping and must show
that mapping on a boundary node in the parent or child region. A detail may not silently change
`[B,S,D]` into `[N,D]`, change head layout, or introduce packed axes simply because its backend
uses flattened tokens. If the conversion is a material executable operation, also include the
corresponding reshape/flatten node in the logical operator sequence.

## Operator display contract

Strict operator-detail projects declare `operator_display_contract` and review every
operator-detail region:

```json
{
  "operator_display_contract": {
    "status": "pass",
    "method": "reader-shape-parameter-review",
    "reviewed_region_ids": ["attention_detail"],
    "activation_shape_placement": "tensor-edges",
    "parameter_shape_placement": "external-annotations-or-structured-ir",
    "source_symbol_placement": "structured-ir-or-secondary-line",
    "checks": [
      "operator-names",
      "activation-shapes-on-edges",
      "parameter-shapes-outside-blocks",
      "source-symbols-outside-primary-label"
    ],
    "findings": ["Removed activation shapes and weight dimensions from operator boxes."]
  }
}
```

Use these visual roles consistently:

- operator block: reader-facing semantic role plus common operation name;
- incoming/outgoing tensor edge: activation name and shape;
- external red annotation or structured IR: parameter/weight shape;
- `source_symbols` or an optional subordinate line: exact code identifier.

An operator block may include a short semantic qualifier such as `causal`, `per-head`, `Top-16`,
or `kernel=4`; it may not contain activation shapes such as `[B,S,D]` or parameter dimensions
such as `7168 -> 896`. Interface, cache, and persistent-state nodes may show their boundary
shape because the stored/interface tensor is their identity.

`op_type: custom` is not an escape hatch for a fused or poorly understood sequence. It requires
a concrete `definition`, mathematical `formula`, and `atomicity_reason`. Otherwise decompose it
into standard operators or mark a real module boundary as `expanded-elsewhere`.
