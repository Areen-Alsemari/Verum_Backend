"""Route lengths recomputed from polyline vertices.

Each route length is computed three ways that must agree: from the polyline vertices, from the
stated route length of the contract, and from the sum of the route's edge lengths. The vertex
computation is written out directly from the raw data and does not call the package, which is tested
against it separately. The total over distinct edges is 985 m.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import Topology
from verum.graph import load_route_geometry, point_at, polyline_length

Raw = dict[str, Any]


def _raw_geometry(root: Path) -> Raw:
    loaded: Raw = json.loads((root / "config" / "route_geometry.json").read_text(encoding="utf-8"))
    return loaded


def _length_from_vertices(vertices: list[list[float]]) -> float:
    total = 0.0
    for a, b in zip(vertices, vertices[1:], strict=False):
        total += math.sqrt(sum((q - p) ** 2 for p, q in zip(a, b, strict=True)))
    return total


def test_every_route_has_a_polyline(root: Path, topology: Topology) -> None:
    """Every route of the topology has a polyline. Independent: yes, because the two sets are
    compared with each other.
    """
    assert set(_raw_geometry(root)["routes"]) == set(topology.route_lengths_m)


@pytest.mark.parametrize(
    "route",
    [
        "R-MAIN",
        "R-101",
        "R-102",
        "R-103",
        "S-101",
        "S-102",
        "S-103",
        "S-HEADER",
        "P-A",
        "P-B",
        "D-MAIN",
    ],
)
def test_polyline_length_equals_stated_length_and_edge_sum(
    root: Path, topology: Topology, route: str
) -> None:
    """The polyline length of each route equals the stated route length and the sum of its edge
    lengths. Independent: yes, because the length is computed directly from the raw vertices.
    """
    vertices = _raw_geometry(root)["routes"][route]["vertices"]
    from_vertices = _length_from_vertices(vertices)
    edge_sum = math.fsum(e.length_m for e in topology.edges if e.route_id == route)
    assert math.isclose(from_vertices, topology.route_lengths_m[route], abs_tol=1e-9)
    assert math.isclose(from_vertices, edge_sum, abs_tol=1e-9)


def test_package_polyline_length_matches_the_direct_computation(root: Path) -> None:
    """The package function gives the same polyline length as the direct computation. Independent:
    yes, because the reference is written out from the raw data.
    """
    geometry = load_route_geometry()
    raw = _raw_geometry(root)["routes"]
    for route, vertices in geometry.routes.items():
        assert math.isclose(
            polyline_length(vertices), _length_from_vertices(raw[route]["vertices"]), abs_tol=1e-12
        )


def test_total_of_distinct_edges_is_985_m(root: Path, topology: Topology) -> None:
    """The total length of the distinct edges is 985 m and equals the total over routes.
    Independent: yes, because the value is the documented total.
    """
    routes = _raw_geometry(root)["routes"]
    assert math.isclose(sum(e.length_m for e in topology.edges), 985.0, abs_tol=1e-9)
    assert math.isclose(
        sum(_length_from_vertices(r["vertices"]) for r in routes.values()), 985.0, abs_tol=1e-9
    )


def test_edge_end_nodes_sit_where_cumulative_edge_length_puts_them(topology: Topology) -> None:
    """Each edge end node lies at the point along the route polyline given by the cumulative edge
    length. Independent: no, because the point is found with the package function that is under test
    elsewhere.
    """
    geometry = load_route_geometry()
    for route, vertices in geometry.routes.items():
        distance = 0.0
        for edge in (e for e in topology.edges if e.route_id == route):
            distance += edge.length_m
            expected = point_at(vertices, distance)
            actual = geometry.node_position(edge.to_node)
            assert all(
                math.isclose(a, b, abs_tol=1e-6) for a, b in zip(actual, expected, strict=True)
            ), (
                route,
                edge.edge_id,
                actual,
                expected,
            )


def test_edge_start_nodes_match_the_first_vertex_of_each_route(topology: Topology) -> None:
    """The start node of the first edge of each route is the first vertex of the route. Independent:
    yes, because the two sources are compared with each other.
    """
    geometry = load_route_geometry()
    for route, vertices in geometry.routes.items():
        first = next(e for e in topology.edges if e.route_id == route)
        assert geometry.node_position(first.from_node) == vertices[0]


def test_node_elevations_match_the_contract(topology: Topology) -> None:
    """The node elevations of the geometry equal the edge elevations of the contract. Independent:
    yes, because the two sources are compared with each other.
    """
    geometry = load_route_geometry()
    for edge in topology.edges:
        assert math.isclose(geometry.node_position(edge.from_node)[2], edge.z_from_m, abs_tol=1e-9)
        assert math.isclose(geometry.node_position(edge.to_node)[2], edge.z_to_m, abs_tol=1e-9)


def test_tank_nozzles_lie_on_the_shell(topology: Topology) -> None:
    """The tank nozzles lie on the tank shell at the contract radius. Independent: yes, because the
    radius is the contract diameter over two.
    """
    geometry = load_route_geometry()
    for tank in topology.tanks:
        radius = tank.dimensions_m["diameter_m"] / 2
        cx, cy, _ = geometry.nodes[tank.tank_id]
        for kind in ("receipt_nozzle", "outlet_nozzle"):
            x, y, _ = geometry.node_position(f"{tank.tank_id}:{kind}")
            assert math.isclose(math.hypot(x - cx, y - cy), radius, abs_tol=1e-9)


def test_nozzle_heights_match_the_contract(topology: Topology) -> None:
    """The nozzle heights equal the inlet and outlet heights of the contract. Independent: yes,
    because the two sources are compared with each other.
    """
    geometry = load_route_geometry()
    for tank in topology.tanks:
        assert (
            geometry.node_position(f"{tank.tank_id}:receipt_nozzle")[2]
            == tank.dimensions_m["inlet_z_m"]
        )
        assert (
            geometry.node_position(f"{tank.tank_id}:outlet_nozzle")[2]
            == tank.dimensions_m["outlet_z_m"]
        )


def test_receipt_and_suction_headers_share_plan_position_but_not_elevation() -> None:
    """The receipt and suction headers share a plan position but sit at 1.0 m and 0.5 m of
    elevation. Independent: yes, because the values are the documented elevations.
    """
    nodes = load_route_geometry().nodes
    (rx, ry, rz), (sx, sy, sz) = nodes["RECEIPT_HEADER"], nodes["SUCTION_HEADER"]
    assert (rx, ry) == (sx, sy)
    assert (rz, sz) == (1.0, 0.5)


def test_point_at_rejects_a_distance_beyond_the_route() -> None:
    """Asking for a point beyond the end of a route is rejected. Independent: yes, because the
    expected outcome is the validation rule.
    """
    vertices = load_route_geometry().routes["S-HEADER"]
    with pytest.raises(ValueError):
        point_at(vertices, 35.5)
