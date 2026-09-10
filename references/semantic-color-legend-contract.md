# Model Sketcher semantic color and Legend contract

The semantic palette is a data contract, not decoration. The compiler owns the
Draw.io color values; project code must not choose arbitrary per-node colors.

## Canonical palette

| IR `visual_class` | Legend label | Fill | Border | Meaning |
|---|---|---|---|---|
| `conditional` | 条件执行 | `#FFFFFF` | `#111111`, dashed | Genuine runtime control condition |
| `tensor-op` | Tensor Op | `#DAE8FC` | `#6C8EBF` | Projection, GEMM, convolution, embedding, einsum/matmul |
| `vector-op` | Vector Op | `#FFE6CC` | `#D79B00` | Normalization, activation, elementwise/reduction math |
| `io-op` | IO Op | `#FFF2CC` | `#D6B656` | Shape/view, split/concat, indexing, cast/quantization |
| `communication` | 通信 | `#D5E8D4` | `#82B366` | Collective communication |
| `composite-op` | 组合操作 | `#F8CECC` | `#B85450` | A reviewed module/composite boundary, not a hidden operator chain |
| `residual-op` | 残差操作 | `#F5F5F5` | `#666666` | Residual or hyper-connection operation/boundary |
| `cache` | Cache | `#B0E3E6` | `#0E8992` | Cache access operators or persistent cache/recurrent state |

Color and glyph are separate contracts. Persistent `kind: cache`/`kind: state` objects and the Cache legend swatch use the canonical slanted-storage parallelogram. An operator whose `op_type` is `cache-read`, `cache-write`, `cache-update`, or `state-update` keeps the same cache color but uses the ordinary rounded operator rectangle. This distinction prevents an action from masquerading as storage.

`TP 拆分` is the ninth Legend entry but is a modifier, not an exclusive fill
class. Set `"visual_modifiers": ["tp-partition"]`; the compiler keeps the
node's base semantic fill and changes its text to `#FF0000`. This reproduces
the reference behavior in which a sharded projection/weight remains blue as a
Tensor Op while its TP-specific label is red. The Legend swatch itself is white
with a `#111111` border and red text.

## Resolution rules

The compiler deterministically infers unambiguous classes from `kind` and
`operator_contract.op_type`. An explicit `visual_class` is required whenever
the default would lose material meaning, and is recommended for module-summary
nodes. When it differs from the inferred class, add a non-empty
`visual_class_reason`; a `tp-partition` modifier likewise requires
`visual_modifier_reason`. Both remain attached to a node that already cites
source evidence. The validator rejects explicit classes outside these semantic bounds:

- linear, convolution, embedding, and matmul are `tensor-op`;
- normalization, activation, elementwise math, and reductions are `vector-op`;
- view/shape transforms, split/concat, indexing, quantization and ordinary
  routing are `io-op`;
- collectives are `communication`;
- cache reads/writes/updates and persistent state are `cache`;
- an add may be `residual-op` only when its role is genuinely residual;
- a runtime `where` may be `conditional` only when it represents control
  selection rather than ordinary elementwise selection;
- modules default to `composite-op`, but a module that is exactly one tensor
  operation may explicitly use `tensor-op`;
- `custom` is the escape hatch for source-backed operations whose definition
  makes another canonical class more accurate. It is not permission to invent
  a new color.

Do not classify by model family, hierarchy level, region, or aesthetic balance.
Qwen, Kimi, GLM, attention, MoE and recurrent mixer identities are not colors.

## Legend gate

Every final hierarchy master or end-to-end master has exactly one compiler-owned
Legend titled `Legend / 图例`. It always carries all nine reference entries in
the canonical two-row order, including unused entries, so diagrams remain
comparable. Focused crops inherit the master Legend and need not duplicate it.

The generated manifest records the palette, resolved class and modifiers for
every semantic node, and all ten Legend cell IDs (title plus nine entries). The
static audit fails when:

- the Legend or any entry is missing, duplicated by ID, renamed, or recolored;
- the manifest palette differs from the canonical Model Sketcher palette;
- a node fill, border, font color, or dashed state disagrees with its class;
- a persistent state or Cache legend swatch loses the slanted-storage glyph, or a cache operation incorrectly acquires it;
- semantic-style coverage differs from the node-semantic ledger;
- the strict delivery manifest omits the semantic-style gate.

Visual review still checks color perception after official export, but it may
not waive a static palette failure.
