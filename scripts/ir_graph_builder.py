"""Small authoring helpers: layout lanes never manufacture data dependencies."""


def add_lane(data, region_id, lane_id, node_ids):
    """Record existing source-backed execution order; do not create tensor edges."""
    members = list(node_ids)
    if not members or any(n not in data["nodes"] for n in members):
        raise ValueError("lane members must name existing nodes")
    region = data["regions"][region_id]
    if any(data["nodes"][n].get("region") != region_id for n in members):
        raise ValueError("lane members must belong to the region")
    sequences = region.setdefault("operator_sequences", [])
    if any(s["id"] == lane_id for s in sequences):
        raise ValueError("duplicate lane ID")
    sequences.append({"id": lane_id, "nodes": members})


def add_tensor_edge(data, edge_id, source, target, tensor):
    """Require an explicit producer, consumer and tensor record for each dependency."""
    if source not in data["nodes"] or target not in data["nodes"]:
        raise ValueError("edge endpoints must name existing nodes")
    if not isinstance(tensor, dict) or not all(tensor.get(k) for k in ("name", "shape", "status")):
        raise ValueError("tensor name, shape and evidence status are required")
    edges = data.setdefault("edges", {})
    if edge_id in edges:
        raise ValueError("duplicate edge ID")
    edges[edge_id] = {"source": source, "target": target, "kind": "tensor", "tensor": dict(tensor)}
