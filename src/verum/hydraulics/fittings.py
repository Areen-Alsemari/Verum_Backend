"""Loss coefficients assigned to edges for a fitting profile.

A bend belongs to the edge whose arc-length interval contains it, closed at the start and open at
the end, so a bend exactly on a node falls to the downstream edge. An element in a node (valve,
check valve, meter, tank outlet) is charged to the edge that starts at that node, and a tank inlet
to the edge that ends at the receipt nozzle. Isolation valves in the active set are open, because
partial opening is outside the steady model.

See D15.
"""

from __future__ import annotations

from collections.abc import Collection

from verum.contracts.topology import Edge, Topology
from verum.graph import RouteGeometry, bend_arclengths
from verum.hydraulics.config import FittingProfile

METERS = frozenset({"RECEIPT_METER", "DELIVERY_METER"})


def bends_per_edge(topology: Topology, geometry: RouteGeometry) -> dict[str, int]:
    """Number of polyline bends contained in each edge."""
    counts = {e.edge_id: 0 for e in topology.edges}
    for route, vertices in geometry.routes.items():
        edges = [e for e in topology.edges if e.route_id == route]
        bounds: list[tuple[float, float, str]] = []
        start = 0.0
        for edge in edges:
            bounds.append((start, start + edge.length_m, edge.edge_id))
            start += edge.length_m
        for position in bend_arclengths(vertices):
            owner = next(
                (eid for lo, hi, eid in bounds if lo - 1e-9 <= position < hi - 1e-9), bounds[-1][2]
            )
            counts[owner] += 1
    return counts


def _element_k(edge: Edge, profile: FittingProfile) -> float:
    k = 0.0
    start, end = edge.from_node, edge.to_node
    if start.startswith("XV-"):
        k += profile.k("open_isolation_valve")
    if start.startswith("CV-"):
        k += profile.k("open_check_valve")
    if start in METERS:
        k += profile.k("meter")
    if start.endswith(":outlet_nozzle"):
        k += profile.k("tank_outlet")
    if end.endswith(":receipt_nozzle"):
        k += profile.k("tank_inlet")
    return k


def edge_loss_coefficients(
    topology: Topology,
    geometry: RouteGeometry,
    profile: FittingProfile,
    edge_ids: Collection[str],
    bends: dict[str, int] | None = None,
) -> dict[str, float]:
    """Total K for each requested edge under the profile."""
    bends = bends if bends is not None else bends_per_edge(topology, geometry)
    result: dict[str, float] = {}
    for edge in topology.edges:
        if edge.edge_id in edge_ids:
            result[edge.edge_id] = bends[edge.edge_id] * profile.k("per_bend") + _element_k(
                edge, profile
            )
    return result
