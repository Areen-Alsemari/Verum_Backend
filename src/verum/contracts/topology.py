"""Loader and structural validator for ``topology_contract.json``.

Inputs: the topology contract (28 pipe edges, 11 routes, three tanks, two
pumps).

Outputs: an immutable ``Topology`` with typed ``Edge`` records.

Key assumptions:
    * The edge list is the physical graph. Route lengths are checksums over the
      edges that share a ``route_id``, not additional pipes. The total pipe
      length is therefore the sum over distinct edges (985 m); it includes both
      alternative pump branches and is not the length of one flow path.
    * Edges that share a nominal size must share an inner diameter; the loader
      does not hold a diameter table of its own.
    * Receipt and suction headers are distinct nodes and stay distinct.
    * The expected counts (28 edges, 11 routes) come from the contract's own
      ``edge_count`` and ``route_count`` and are cross-checked against the
      edge list, so a truncated list cannot pass with a matching header.

Source: ``topology_contract.json``; ``revised/01_facility_tanks_topology.md``
sections 7.1 and 7.2; ``VERUM_INTEGRATION_README.md`` section B.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir

FILENAME = "topology_contract.json"
_EDGE_KEYS = frozenset(
    {
        "edge_id",
        "from_node",
        "to_node",
        "route_id",
        "length_m",
        "nominal_size",
        "inner_diameter_m",
        "z_from_m",
        "z_to_m",
        "provenance",
    }
)


@dataclass(frozen=True)
class Edge:
    """One physical pipe segment; flow is signed relative to from -> to."""

    edge_id: str
    from_node: str
    to_node: str
    route_id: str
    length_m: float
    nominal_size: str
    inner_diameter_m: float
    z_from_m: float
    z_to_m: float
    provenance: str


@dataclass(frozen=True)
class Tank:
    """Tank geometry and level thresholds, all in metres, as declared."""

    tank_id: str
    dimensions_m: dict[str, float]


@dataclass(frozen=True)
class Topology:
    """The validated physical configuration."""

    edges: tuple[Edge, ...]
    route_lengths_m: dict[str, float]
    tanks: tuple[Tank, ...]
    pumps: tuple[str, ...]
    excluded_assets: tuple[str, ...]

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(e.edge_id for e in self.edges)

    @property
    def nodes(self) -> frozenset[str]:
        return frozenset(n for e in self.edges for n in (e.from_node, e.to_node))

    @property
    def total_length_m(self) -> float:
        """Sum over distinct pipe edges, including both alternative pump branches."""
        return math.fsum(e.length_m for e in self.edges)

    @property
    def tank_ids(self) -> tuple[str, ...]:
        return tuple(t.tank_id for t in self.tanks)

    def edge(self, edge_id: str) -> Edge:
        for candidate in self.edges:
            if candidate.edge_id == edge_id:
                return candidate
        raise KeyError(edge_id)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(f"topology contract: {message}")


def _parse_edge(raw: dict[str, Any]) -> Edge:
    _require(set(raw) == _EDGE_KEYS, f"edge fields differ from the expected set: {sorted(raw)}")
    edge = Edge(**raw)
    _require(edge.length_m > 0, f"{edge.edge_id} has non-positive length")
    _require(edge.inner_diameter_m > 0, f"{edge.edge_id} has non-positive inner diameter")
    _require(edge.from_node != edge.to_node, f"{edge.edge_id} starts and ends at one node")
    return edge


def _check_route_lengths(edges: tuple[Edge, ...], declared: dict[str, float]) -> None:
    sums: dict[str, float] = defaultdict(float)
    for edge in edges:
        sums[edge.route_id] += edge.length_m
    _require(set(sums) == set(declared), "route ids differ between edges and route_lengths_m")
    for route, length in declared.items():
        _require(
            math.isclose(sums[route], length, abs_tol=1e-9), f"route {route} sums to {sums[route]}"
        )


def _check_diameters(edges: tuple[Edge, ...]) -> None:
    seen: dict[str, float] = {}
    for edge in edges:
        known = seen.setdefault(edge.nominal_size, edge.inner_diameter_m)
        _require(known == edge.inner_diameter_m, f"{edge.nominal_size} has two inner diameters")


def _parse_tanks(raw: dict[str, dict[str, float]]) -> tuple[Tank, ...]:
    return tuple(Tank(tank_id=name, dimensions_m=dict(dims)) for name, dims in raw.items())


def parse_topology(contract: dict[str, Any]) -> Topology:
    """Validate a decoded topology contract and return it as a ``Topology``."""
    edges = tuple(_parse_edge(raw) for raw in contract.get("edges", []))
    _require(len(edges) == contract.get("edge_count"), "edge_count differs from the edge list")
    _require(len({e.edge_id for e in edges}) == len(edges), "duplicate edge_id")
    declared = contract.get("route_lengths_m", {})
    _require(
        len(declared) == contract.get("route_count"), "route_count differs from route_lengths_m"
    )
    _check_route_lengths(edges, declared)
    _check_diameters(edges)
    topology = Topology(
        edges=edges,
        route_lengths_m=dict(declared),
        tanks=_parse_tanks(contract.get("tanks", {})),
        pumps=tuple(contract.get("pumps", [])),
        excluded_assets=tuple(contract.get("excluded_nonbaseline_assets", [])),
    )
    used = topology.nodes | set(topology.edge_ids) | set(topology.pumps) | set(topology.tank_ids)
    _require(not set(topology.excluded_assets) & used, "an excluded asset is used in the graph")
    return topology


def load_topology(directory: Path | None = None) -> Topology:
    """Load and validate the topology contract from ``config/``."""
    path = (directory or config_dir()) / FILENAME
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return parse_topology(decoded)
