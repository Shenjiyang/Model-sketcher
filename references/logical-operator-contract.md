# Logical operator and tensor-shape contract

Read this reference before creating or substantially revising any `operator-detail` or `implementation-detail` region. Its purpose is to keep implementation fusion from erasing the mathematical and tensor operations expected in a detailed architecture figure.

## Source evidence does not choose the drawing leaf

Executable source determines operation order, parameter sharing, packed weights, fusion boundaries, runtime branches, and state behavior. It does not automatically determine the smallest visible operator. A single function or fused kernel may implement several logical tensor operations.

Use these stable abstraction levels:

- `module-summary` shows named modules and repeated compositions.
- `operator-detail` stops at logical tensor operators that independently affect mathematics, parameters, tensor shape, state, routing, or FLOPs.
- `implementation-detail` shows kernels, fusion, cache layout, collectives, and prefill/decode execution choices.

In `operator-detail`, normally show normalization, parameterized projection, convolution, split/chunk/concatenate, reshape/view/transpose/repeat, positional transformation, matmul, scale/mask, softmax or activation, elementwise multiply/add, reduction, routing/top-k, dispatch/combine, and cache/state updates as separate nodes. Do not decompose into scalar instructions, loads/stores, Python bookkeeping, or a shape-neutral `contiguous` unless the requested analysis depends on them.

Enable `project.require_logical_operator_contracts` for every new compiler-path project and every substantial detail migration. This is a migration gate, not a stylistic opt-out: an older project that has not enabled it must be reported as logical-operator/shape-contract debt and cannot claim review under this standard.

Each `operator-detail` region declares `"operator_standard": "logical-tensor-ops"`. Each ordinary operator/module leaf in that region declares one `operator_contract.classification`:

- `atomic-operator`: one logical tensor operation.
- `view-transform`: one zero-arithmetic shape or layout transformation.
- `packed-parameterized-op`: one real parameterized operation that produces a packed tensor and reaches an explicit split/chunk/slice/unbind through zero or more view transforms.
- `expanded-elsewhere`: a named boundary whose logical internals appear in a concrete detail region; declare `detail_region` and `reason`. From an `operator-detail` region, the target must also be `operator-detail`; an `implementation-detail` kernel/cache/runtime expansion cannot substitute for missing logical operators.

Do not classify a multi-operation fused sequence as `atomic-operator`. A distinctive name such as `attention core`, `recurrent core`, or `expert core` is not proof that it is atomic. Expand it to the selected tensor-operator stopping level or mark it `expanded-elsewhere`.

Every non-expanded operator also declares an `op_type` and `shape_rule`. Use a specific common type such as `rmsnorm`, `linear`, `reshape`, `matmul`, `softmax`, `routing`, `cache-update`, or `all-to-all`; use `custom` only with a short `definition`. The supported shape rules are:

- `preserve`: known input and output shapes are identical.
- `transform`: one logical input-to-output shape transformation.
- `multi-input`: the operation consumes at least two tensor edges.
- `multi-output`: the operation produces at least two tensor edges.
- `stateful`: a cache or state transition participates in the result.
- `custom`: the ordinary rules cannot describe the relationship without losing important semantics.

Every rule except `preserve` includes a human-reviewable `shape_equation`. Common operator types also constrain the rule: for example, linear/convolution/reshape are transformations, matmul/add/multiply/concatenate are multi-input, split/chunk/unbind are multi-output, and cache/state updates are stateful. This is an explicit dimensional claim, not a request for the validator to perform unrestricted symbolic algebra. For `transform`, `multi-input`, and `multi-output`, the validator requires an input/output separator and checks that every known direct incoming shape appears on the left and every known direct outgoing shape appears on the right. Repeated equal-shape inputs or outputs must appear with matching multiplicity, so one `[B,S,D]` token cannot falsely close two independent branches. The independent source review still checks the mathematical equation itself; the machine check deliberately does not pretend to prove unrestricted symbolic algebra.

Every operator-detail leaf, including an `expanded-elsewhere` boundary, also declares a lower-kebab `semantic_role` and non-empty exact `source_symbols`. Its node label is reader-facing terminology, not the source identifier. Read [operator-naming-contract.md](operator-naming-contract.md) for the naming grammar, evidence priority, and required `operator_naming_review`.

When a visible operation owns learned weights or affine parameters, keep their dimensions in node `parameter_shapes` as `name: shape` strings such as `W_qkv: [D,3D]` or `gamma: [D]`. Linear, convolution, embedding, and normalization-family leaves require this field unless the cited implementation is genuinely parameterless and the node records a source-backed `parameterless_reason`. The validator checks the field shape and declared symbols; the ASCII generator prints it beneath the operator ledger entry. This remains an external/structured annotation contract and must not be folded into the primary operator label.

## Fusion and packed parameters

Represent logical operators and physical fusion independently. When one source call or backend kernel covers several logical operations, keep the logical nodes and add an `execution_fusions` record:

```json
"execution_fusions": [
  {
    "id": "norm_gate_fusion",
    "label": "Fused norm + gate execution",
    "operators": ["pre_norm", "gate_proj", "silu", "gate_mul"],
    "evidence": ["forward"],
    "source": "modeling.py:420",
    "owner_region": "gate_detail",
    "topology": "connected",
    "visualization": "boundary"
  }
]
```

The topology contract reports fusion separately. Use `topology: connected` when member operators form one connected tensor subgraph, or `parallel` when they share a real external producer or consumer. Use `visualization: boundary` only when all members and `owner_region` are the same operator-detail region; the compiler generates a labeled dashed boundary around the members. For a cross-region or separately owned backend fusion, use `visualization: implementation-node`, set `owner_region` to that node's `implementation-detail` region, and declare the reciprocal mapping:

```json
"implementation_contract": {
  "classification": "fused-operation",
  "implements": ["norm_gate_fusion"]
}
```

Never replace all members with one ordinary operator box in `operator-detail`. Fusion membership may span logical regions only when the implementation node makes the physical ownership explicit.

A packed projection is one real parameterized operation, not several invented projections. Show its packed result and semantic split explicitly:

```text
input [B,S,D]
      |
Packed QKV projection
      | packed_qkv [B,S,Hq*Dq+Hk*Dk+Hv*Dv]
Split / slice
  | Q [B,S,Hq,Dq]   | K [B,S,Hk,Dk]   | V [B,S,Hv,Dv]
```

Its node contract declares a `decomposition_path` beginning at the packed operation and ending at a `view-transform` whose `op_type` is `split`, `chunk`, `slice`, or `unbind`. Intermediate path members, when needed, are non-splitting view transforms such as reshape, view, transpose, or permute. This permits `packed projection -> reshape -> split` without permitting arithmetic to hide inside the decomposition path.

Each of at least two `packed_outputs` binds a semantic branch to a real outgoing edge:

```json
{
  "name": "q",
  "edge": "split_to_q",
  "consumer": "q_consumer",
  "shape": "[B,S,Hq,Dh]"
}
```

The edge must leave the final unpack node, target the named consumer, and carry the same tensor name and shape. Apply the same grammar to gate/up projections, combined latent projections, or other packed matrices.

## Structured tensor edges

Transient tensors live on edges. Every tensor edge touching an `operator-detail` or `implementation-detail` region declares:

```json
"tensor": {
  "name": "q_heads",
  "shape": "[B,S,Hq,Dh]",
  "status": "code-confirmed",
  "evidence": ["forward"],
  "dtype": "bf16",
  "layout": "BSHD",
  "domain": "token",
  "constraints": ["D = Hq*Dh"],
  "material": true
}
```

Only `name`, `shape`, `status`, and the evidence/uncertainty fields are universally required. One edge name identifies one tensor; do not hide tuple outputs behind names such as `K,V` or `gate + up`. Add `dtype`, `layout`, `domain`, and `constraints` when they materially distinguish paths. `material` defaults to true; set it false only for a genuinely non-material bookkeeping edge. Valid statuses are `code-confirmed`, `config-confirmed`, `report-confirmed`, `inferred`, `backend-dependent`, and `unknown`. Confirmed statuses must cite matching evidence roles; the last three require a reason. Unknown or backend-dependent dimensions stay explicit rather than disappearing. A claimed `complete-hierarchy` may not leave a material detail tensor at shape `?`.

Shapes are `scalar`, `?`, or bracketed symbolic dimensions such as `[B,S,D]`. Declare every symbolic name in a project-level `shape_symbols` dictionary; arbitrary undeclared tokens are invalid. In particular, explain transitions between model domains such as `[B,S,D]` and flattened-token `[N,D]`, including whether `N=B*S`, a packed sum of sequence lengths, or a decode-token count. Label shapes immediately before and after split, reshape, transpose, head replication, expert dispatch/combine, cache update, and collective communication.

## Review gates

Reject the semantic contract before layout when:

- a source-level fused call is used to hide its logical member operations;
- a packed projection has no explicit packed result and split node;
- a packed-output declaration is not backed by the named edge, consumer, tensor name, and tensor shape;
- an `operator-detail` leaf contains multiple ordinary logical operations;
- a logical operator lacks incoming or outgoing tensor flow, except for separately typed interfaces/cache/state boundaries;
- a tensor edge in a detail region lacks a structured name, shape, evidence status, or uncertainty reason;
- a material tensor remains shape-unknown under a complete-hierarchy claim;
- sibling regions at the same declared detail level use different stopping rules without an explicit different granularity;
- a reader cannot trace shapes through every branch, merge, residual add, cache/state boundary, and batch/token-domain transition;
- an implementation fusion cannot be mapped back to the logical operator IDs it covers.
- a primary operator label exposes a private source identifier, uses an opaque core/kernel name, conflicts with its `op_type`, lacks a semantic role/source-symbol mapping, or was not included in the author naming review.

Geometry begins only after the logical operator sequence, execution-fusion mapping, and tensor-shape flow pass review. Label keyword checks and lightweight shape checks are backstops: they do not discover a missing source operation, prove a free-form shape equation, or decide that an unfamiliar named kernel is logically atomic. Keep the source-to-inventory and sibling-granularity review as human gates.

Strict logical-operator validation also requires source coverage and its independent source-reread reconciliation. Do not grandfather an older IR: migrate its inventory, nodes, sequences, and edges before it can pass again.
