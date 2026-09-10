# Reader-facing operator naming contract

Read this reference before creating or revising an `operator-detail` region. The diagram must explain the computation to a technical reader without requiring them to decode private variable names, while preserving exact source traceability in the IR.

## Separate identity, semantics, and display

Each logical operator contract records:

- `op_type`: the controlled mathematical/operator family used by validation;
- `semantic_role`: a concise lower-kebab role in this architecture, such as `query-projection`, `decay-gate-expansion`, `output-gate-activation`, or `recurrent-state-update`;
- `source_symbols`: the exact callable, attribute, parameter, or source expression implementing the logical operation;
- node `label`: the reader-facing paper/blog-style name shown in Draw.io.

Use the label pattern `[semantic role] + [common operator] + [necessary qualifier]`. Prefer `Decay-gate expansion projection`, `Q short causal Conv1D`, `Update-gate sigmoid`, `Per-head RMSNorm`, `Elementwise gate multiply`, `KDA gated-delta scan`, or `Recurrent-state update` over `f_b`, `g1`, `op`, `core`, or a raw function name. Preserve a useful official algorithm name, but pair it with a generic descriptor. A model-specific term such as `KDA gated-delta scan` is better than either `KDA Core` or the overly generic `Recurrent operator`.

The primary label is the first line. Do not put snake_case source identifiers there. When a visible code alias materially helps comparison, put it on a subordinate second line; always keep the exact identifier in `source_symbols` regardless of whether it is rendered.

Do not use the second line as a shape dump. Activation shapes belong to incoming and outgoing
tensor edges, and parameter dimensions belong in an external red annotation or structured IR.
For example, use `Router projection` in the block, `hidden [B,S,D]` and `router logits
[B,S,E]` on its edges, and `W_router [D,E]` beside it. Avoid labels such as `Router Projection
[7168->896]` or `Head reshape [N,H,128]`.

```json
{
  "label": "Decay-gate expansion projection",
  "operator_contract": {
    "classification": "atomic-operator",
    "op_type": "linear",
    "semantic_role": "decay-gate-expansion",
    "source_symbols": ["self.f_b_proj"],
    "shape_rule": "transform",
    "shape_equation": "[B,S,Dh] -> [B,S,H,Dh]"
  }
}
```

For an implicit expression, `source_symbols` may name the exact callable or expression token, such as `torch.sigmoid`, `x * gate`, or `forward:normalized * gate`; it must not invent a module attribute that does not exist.

## Evidence-guided mapping

Choose names in this order:

1. official paper/report terminology for the architecture role;
2. canonical model docstrings and forward semantics;
3. the operation actually performed, its shapes, parameters, and consumers;
4. inference implementation names for kernel/cache/runtime detail only.

Do not infer meaning from a short identifier alone. Trace producers, parameters, transformations, and consumers. If the evidence does not establish whether a tensor is a decay gate, update gate, or output gate, use a neutral accurate name and record the uncertainty instead of guessing.

Physical fusion never changes the reader-facing logical names. Keep `Per-head RMSNorm`, `Output-gate sigmoid`, and `Elementwise gate multiply` as logical nodes even when one fused callable implements all three; put the callable name in `execution_fusions` or implementation detail.

A project-specific formula may remain one `custom` leaf only when the contract records its
concrete formula and an `atomicity_reason`. Prefer a common mathematical name plus the official
algorithm qualifier. `Decay transform`, `state update`, or `core` without the formula is not a
reader-facing explanation and must be decomposed or expanded elsewhere.

## Author self-review

Before geometry, the diagram-author LLM performs a reader-and-source naming review and records:

```json
"operator_naming_review": {
  "status": "pass",
  "method": "reader-and-source-review",
  "reviewed_region_ids": ["mixer_detail"],
  "checks": [
    "reader-facing-labels",
    "source-symbol-traceability",
    "sibling-consistency"
  ],
  "findings": [
    "Replaced f_b Projection with Decay-gate expansion projection; retained self.f_b_proj in source_symbols."
  ]
}
```

Review every `operator-detail` region. Read labels once without source code and confirm that each block says what it does; then compare each `semantic_role` and `source_symbols` mapping with the pinned evidence. Finally compare sibling regions so the same operation family uses consistent terminology. The user is the final acceptance owner, not the first-line terminology debugger; ask them only about genuine evidence ambiguity or presentation preference.

## Machine gate boundary

The validator rejects missing roles/symbols, snake_case in primary labels, opaque names such as `KDA Core`, and high-confidence `label`/`op_type` conflicts. It intentionally does not maintain a universal natural-language dictionary or guess model semantics. A machine PASS proves contract consistency, not that an arbitrary semantic translation is true; the source-first reconciliation and author self-review remain required.
