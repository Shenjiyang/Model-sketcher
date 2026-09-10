"""Display-only edge wrapping shared by geometry and compiled labels."""

import re

from validate_architecture_ir import edge_display_label


def _wrap_name(name: str, max_columns: int) -> list[str]:
    pieces = re.findall(r"[^_\s-]+[_-]?|\s+", name)
    lines, current = [], ""
    for piece in pieces:
        if current and len(current + piece) > max_columns:
            lines.append(current.rstrip())
            current = piece.lstrip()
        else:
            current += piece
    if current:
        lines.append(current.rstrip())
    return lines or [name]


def visual_edge_label(edge: dict, max_columns: int = 26, *, edge_id: str | None = None) -> str:
    """Keep short labels intact, wrap long names, never split tensor shapes."""
    if max_columns < 1:
        raise ValueError("max_columns must be positive")
    tensor = edge.get("tensor")
    if isinstance(tensor, dict) and edge_id is not None and tensor.get("name") == edge_id:
        return str(tensor.get("shape", ""))
    text = edge_display_label(edge).replace("\\n", "\n")
    if len(text) <= max_columns or "\n" in text:
        return text
    tensor = edge.get("tensor")
    if isinstance(tensor, dict):
        name, shape = str(tensor.get("name", "")).strip(), str(tensor.get("shape", "")).strip()
        return "\n".join([*_wrap_name(name, max_columns), shape]).strip()
    return "\n".join(_wrap_name(text, max_columns))
