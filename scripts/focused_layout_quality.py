"""Rank disposable ELK candidates with existing route checks, not acceptance."""

import xml.etree.ElementTree as ET

from audit_drawio import PageAudit


def candidate_quality(problem: dict, layout: dict) -> dict:
    model = ET.Element("mxGraphModel")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    for node_id, box in layout["nodes"].items():
        cell = ET.SubElement(root, "mxCell", id="node:" + node_id,
                             vertex="1", parent="1", style="shape=rectangle;")
        ET.SubElement(cell, "mxGeometry", {"as": "geometry", "x": str(box["x"]),
                      "y": str(box["y"]), "width": str(box["w"]), "height": str(box["h"])})
    for edge_id, route in layout["edges"].items():
        declared = problem["edges"][edge_id]
        style = f"endArrow=block;fontSize={problem.get('edge_label_font', 14)};"
        for role, prefix in (("source", "exit"), ("target", "entry")):
            port = route[role + "_port"]
            side, position = port["side"], port["position"]
            x, y = {"north": (position, 0), "south": (position, 1),
                    "west": (0, position), "east": (1, position)}[side]
            style += f"{prefix}X={x};{prefix}Y={y};{prefix}Perimeter=0;"
        cell = ET.SubElement(root, "mxCell", id="edge:" + edge_id, edge="1", parent="1",
                             source="node:" + declared["source"], target="node:" + declared["target"],
                             value=declared.get("label", {}).get("text", ""), style=style)
        position = route.get("label_position", {"x": 0, "y": 0})
        geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry",
                                 "x": str(position["x"]), "y": str(position["y"])})
        points = ET.SubElement(geometry, "Array", {"as": "points"})
        for x, y in route.get("waypoints", []):
            ET.SubElement(points, "mxPoint", x=str(x), y=str(y))
    config = {}
    region_ids = set()
    if problem.get("operator_sequences"):
        region_id = "region:focused"
        region_ids.add(region_id)
        boxes = list(layout["nodes"].values())
        x, y = min(box["x"] for box in boxes), min(box["y"] for box in boxes)
        w = max(box["x"] + box["w"] for box in boxes) - x
        h = max(box["y"] + box["h"] for box in boxes) - y
        cell = ET.SubElement(root, "mxCell", id=region_id, vertex="1", parent="1", style="container=1;")
        ET.SubElement(cell, "mxGeometry", {"as": "geometry", "x": str(x), "y": str(y),
                                         "width": str(w), "height": str(h)})
        config = {
            "regions": [region_id],
            "region_content_contracts": {region_id: ["node:" + key for key in layout["nodes"]]},
            "require_compact_execution_geometry": True,
            "maximum_parallel_lane_gap": float(problem.get("ordinary_node_font", 18)) * 6,
            "vertical_flow_contracts": {region_id: {"direction": "bottom-to-top", "sequences": [
                {"id": sequence.get("id", str(index)), "nodes": ["node:" + key for key in sequence["nodes"]]}
                for index, sequence in enumerate(problem["operator_sequences"])
            ]}},
        }
    audit = PageAudit("candidate", model, config)
    audit.prepare()
    audit.check_node_overlaps(region_ids, set(), set())
    # Exclude the synthetic scoring envelope from route-border checks.
    audit.check_routes(set(), set(), region_ids)
    audit.check_vertical_flow_contracts(region_ids)
    audit.check_compact_execution_geometry(region_ids, set(), set())
    bends = sum(len(route.get("waypoints", [])) for route in layout["edges"].values())
    area = layout["canvas"]["width"] * layout["canvas"]["height"]
    return {"score": [len(audit.errors), len(audit.warnings), bends, area],
            "route_errors": audit.errors, "route_warnings": audit.warnings,
            "scope": "candidate route preflight only; strict and rendered acceptance still required"}
