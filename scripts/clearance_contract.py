"""Clearances that both the layout translator and the Draw.io audit must agree on."""

from __future__ import annotations


def minimum_route_node_clearance(ordinary_font: float) -> float:
    """Smallest gap a route may keep while running parallel beside a node."""
    return round(max(16.0, float(ordinary_font) * 1.2), 2)


def minimum_route_region_boundary_clearance(ordinary_font: float) -> float:
    """Smallest gap a region's own route may keep from that region's border."""
    return round(max(24.0, float(ordinary_font) * 2.0), 2)
