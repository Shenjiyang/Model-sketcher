"""Canonical DeepSeek V4 semantic palette and node-class resolution."""

from __future__ import annotations


SEMANTIC_PALETTE = {
    "conditional": {
        "label": "条件执行", "fillColor": "#FFFFFF", "strokeColor": "#111111",
        "fontColor": "#000000", "dashed": "1",
    },
    "tensor-op": {
        "label": "Tensor Op", "fillColor": "#DAE8FC", "strokeColor": "#6C8EBF",
        "fontColor": "#000000", "dashed": "0",
    },
    "vector-op": {
        "label": "Vector Op", "fillColor": "#FFE6CC", "strokeColor": "#D79B00",
        "fontColor": "#000000", "dashed": "0",
    },
    "io-op": {
        "label": "IO Op", "fillColor": "#FFF2CC", "strokeColor": "#D6B656",
        "fontColor": "#000000", "dashed": "0",
    },
    "communication": {
        "label": "通信", "fillColor": "#D5E8D4", "strokeColor": "#82B366",
        "fontColor": "#000000", "dashed": "0",
    },
    "composite-op": {
        "label": "组合操作", "fillColor": "#F8CECC", "strokeColor": "#B85450",
        "fontColor": "#000000", "dashed": "0",
    },
    "residual-op": {
        "label": "残差操作", "fillColor": "#F5F5F5", "strokeColor": "#666666",
        "fontColor": "#000000", "dashed": "0",
    },
    "cache": {
        "label": "Cache", "fillColor": "#B0E3E6", "strokeColor": "#0E8992",
        "fontColor": "#000000", "dashed": "0",
    },
}

TP_PARTITION_MODIFIER = {
    "label": "TP 拆分", "fontColor": "#FF0000",
    "legend_fillColor": "#FFFFFF", "legend_strokeColor": "#111111",
    "legend_dashed": "0",
}
VISUAL_MODIFIERS = {"tp-partition"}

SEMANTIC_GLYPHS = {
    "operator": {"shape": "rounded-rectangle", "style": "rounded=1;arcSize=6;"},
    "storage": {
        "shape": "slanted-storage",
        "style": "shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1;rounded=0;",
    },
}

TENSOR_OPS = {"linear", "convolution", "embedding", "matmul", "einsum"}
VECTOR_OPS = {
    "rmsnorm", "layernorm", "normalization", "rope", "positional-transform",
    "scale", "mask", "softmax", "sigmoid", "silu", "gelu", "activation",
    "multiply", "subtract", "divide", "power", "sqrt", "exp", "log", "clamp",
    "reduce", "sum", "mean", "max", "pooling", "dropout", "scan", "cumsum",
    "sample", "loss",
}
IO_OPS = {
    "split", "chunk", "slice", "unbind", "concatenate", "reshape", "view",
    "transpose", "permute", "repeat", "broadcast", "gather", "scatter", "topk",
    "sort", "index", "pad", "cast", "load", "store", "format-conversion",
    "quantize", "dequantize",
}
COMMUNICATION_OPS = {"all-to-all", "all-reduce", "all-gather", "reduce-scatter"}
CACHE_OPS = {"cache-read", "cache-write", "cache-update"}
CONTEXTUAL_OPS = {"add", "where", "routing", "dispatch", "combine", "state-update", "custom"}


def inferred_visual_class(node: dict) -> str | None:
    """Infer only classes that are unambiguous from structural semantics."""
    kind = node.get("kind")
    if kind == "junction":
        return None
    if kind == "interface":
        return "io-op"
    if kind in {"cache", "state"}:
        return "cache"
    if kind == "module":
        return "composite-op"
    contract = node.get("operator_contract")
    op_type = contract.get("op_type") if isinstance(contract, dict) else None
    if op_type in TENSOR_OPS:
        return "tensor-op"
    if op_type in VECTOR_OPS:
        return "vector-op"
    if op_type in IO_OPS:
        return "io-op"
    if op_type in COMMUNICATION_OPS:
        return "communication"
    if op_type in CACHE_OPS:
        return "cache"
    if op_type == "add":
        role = str(contract.get("semantic_role", "")) if isinstance(contract, dict) else ""
        return "residual-op" if any(token in role for token in ("residual", "hyper-connection")) else "vector-op"
    if op_type == "where":
        return "vector-op"
    if op_type in {"routing", "dispatch", "combine"}:
        return "io-op"
    if op_type == "state-update":
        return "cache"
    if op_type == "custom":
        return "composite-op"
    return "io-op" if kind == "operator" else None


def allowed_visual_classes(node: dict) -> set[str]:
    """Return the narrow set of defensible classes for an explicit override."""
    kind = node.get("kind")
    if kind == "junction":
        return set()
    if kind == "interface":
        return {"io-op", "conditional"}
    if kind == "cache":
        return {"cache"}
    if kind == "state":
        return {"cache", "residual-op"}
    if kind == "module":
        return {"composite-op", "tensor-op", "residual-op", "conditional"}
    contract = node.get("operator_contract")
    op_type = contract.get("op_type") if isinstance(contract, dict) else None
    inferred = inferred_visual_class(node)
    if kind == "operator" and op_type is None:
        return set(SEMANTIC_PALETTE)
    if op_type in TENSOR_OPS:
        return {"tensor-op"}
    if op_type in VECTOR_OPS:
        return {"vector-op"}
    if op_type in IO_OPS:
        return {"io-op"}
    if op_type in COMMUNICATION_OPS:
        return {"communication"}
    if op_type in CACHE_OPS:
        return {"cache"}
    if op_type == "add":
        return {"vector-op", "residual-op"}
    if op_type == "where":
        return {"vector-op", "conditional"}
    if op_type in {"routing", "dispatch", "combine"}:
        return {"io-op", "composite-op"}
    if op_type == "state-update":
        return {"cache", "residual-op"}
    if op_type == "custom":
        return set(SEMANTIC_PALETTE)
    return {inferred} if inferred else set()


def resolve_visual_class(node: dict) -> str | None:
    return node.get("visual_class") or inferred_visual_class(node)


def semantic_glyph(node: dict) -> str:
    """Use a storage glyph only for persistent state, never for cache operations."""
    return "storage" if node.get("kind") in {"cache", "state"} else "operator"


def semantic_style(
    visual_class: str,
    modifiers: list[str] | None = None,
    glyph: str = "operator",
) -> str:
    palette = SEMANTIC_PALETTE[visual_class]
    if glyph not in SEMANTIC_GLYPHS:
        raise ValueError(f"unknown semantic glyph: {glyph!r}")
    font_color = TP_PARTITION_MODIFIER["fontColor"] if "tp-partition" in (modifiers or []) else palette["fontColor"]
    return (
        SEMANTIC_GLYPHS[glyph]["style"] + "whiteSpace=wrap;html=1;"
        f"fillColor={palette['fillColor']};strokeColor={palette['strokeColor']};"
        f"fontColor={font_color};dashed={palette['dashed']};"
    )
