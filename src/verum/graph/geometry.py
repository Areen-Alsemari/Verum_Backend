"""Node coordinates and route polylines, with independent length checks.

Inputs: ``config/route_geometry.json`` (node coordinates and one polyline per
route). Outputs: ``RouteGeometry`` and functions
that measure polylines and locate points along them.
Key assumptions:
    * The topology contract carries no coordinates, so the geometry comes from
      a separate file with its own provenance (design values, provisional).
    * Tank nozzle coordinates are not listed as assets; they are the polyline
      ends at the tank (the last vertex of a receipt route, the first vertex of
      a suction route).
    * A route length is the sum of segment lengths in three dimensions. It is
      computed here from the vertices and never read from the contract; the
      contract value and the sum of the route's edge lengths are only compared
      against it.

Source: ``revised/01_facility_tanks_topology.md`` sections 3.2, 3.3 and 7.2
(equation E9, route length).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir

FILENAME: Final = "route_geometry.json"

Point = tuple[float, float, float]


@dataclass(frozen=True)
class RouteGeometry:
    """Coordinates in metres on the site datum (tank bottom z = 0)."""

    provenance_id: str
    nodes: dict[str, Point]
    routes: dict[str, tuple[Point, ...]]

    def node_position(self, node: str) -> Point:
        """Coordinates of a topology node, including derived tank nozzles."""
        if node in self.nodes:
            return self.nodes[node]
        return self._nozzle(node)

    def _nozzle(self, node: str) -> Point:
        tank, _, kind = node.partition(":")
        suffix = tank[3:]
        if kind == "receipt_nozzle":
            return self.routes[f"R-{suffix}"][-1]
        if kind == "outlet_nozzle":
            return self.routes[f"S-{suffix}"][0]
        raise KeyError(node)


def segment_lengths(vertices: tuple[Point, ...]) -> list[float]:
    """Euclidean lengths of consecutive polyline segments."""
    return [math.dist(a, b) for a, b in zip(vertices, vertices[1:], strict=False)]


def polyline_length(vertices: tuple[Point, ...]) -> float:
    """Total length of a polyline."""
    return math.fsum(segment_lengths(vertices))


def point_at(vertices: tuple[Point, ...], distance: float) -> Point:
    """Point at arc length ``distance`` from the first vertex."""
    remaining = distance
    for start, end, length in zip(vertices, vertices[1:], segment_lengths(vertices), strict=False):
        if remaining <= length + 1e-12:
            t = 0.0 if length == 0 else remaining / length
            return (
                start[0] + t * (end[0] - start[0]),
                start[1] + t * (end[1] - start[1]),
                start[2] + t * (end[2] - start[2]),
            )
        remaining -= length
    raise ValueError(f"distance {distance} exceeds the polyline length")


def bend_arclengths(vertices: tuple[Point, ...]) -> list[float]:
    """Arc lengths of the interior vertices at which the direction changes.

    A collinear vertex is not a bend. The route's first and last vertices are
    ends, not bends.
    """
    lengths = segment_lengths(vertices)
    bends: list[float] = []
    travelled = 0.0
    for i in range(1, len(vertices) - 1):
        travelled += lengths[i - 1]
        before = [
            (b - a) / lengths[i - 1] for a, b in zip(vertices[i - 1], vertices[i], strict=True)
        ]
        after = [(b - a) / lengths[i] for a, b in zip(vertices[i], vertices[i + 1], strict=True)]
        if any(abs(p - q) > 1e-9 for p, q in zip(before, after, strict=True)):
            bends.append(travelled)
    return bends


def _point(raw: list[float]) -> Point:
    if len(raw) != 3:
        raise ContractError("route geometry: a vertex needs three coordinates")
    return (float(raw[0]), float(raw[1]), float(raw[2]))


def parse_route_geometry(raw: dict[str, Any]) -> RouteGeometry:
    """Validate a decoded geometry file."""
    provenance = raw.get("provenance_id")
    if not isinstance(provenance, str) or not provenance:
        raise ContractError("route geometry: provenance_id is required")
    if raw.get("status") != "provisional" or raw.get("evidence_tag") != "DESIGN":
        raise ContractError("route geometry: expected status provisional and tag DESIGN")
    if raw.get("unit") != "m":
        raise ContractError("route geometry: unit must be m")
    nodes = {n: (float(c["x"]), float(c["y"]), float(c["z"])) for n, c in raw["nodes"].items()}
    routes = {r: tuple(_point(v) for v in body["vertices"]) for r, body in raw["routes"].items()}
    return RouteGeometry(provenance_id=provenance, nodes=nodes, routes=routes)


def load_route_geometry(directory: Path | None = None) -> RouteGeometry:
    """Load the geometry file from ``config/``."""
    path = (directory or config_dir()) / FILENAME
    try:
        return parse_route_geometry(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ContractError(f"cannot read {path}: {exc!r}") from exc
