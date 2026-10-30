"""Arithmetic checksums of the topology contract.

The route sums and the total pipe length are recomputed from the edge list with exact decimal
arithmetic and compared with the declared values. A route length is the sum over the edges that
share a route, and the 985 m total counts each distinct edge once and includes both alternative pump
branches, so it is not the length of one flow path.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

EXPECTED_ROUTES = {
    "R-MAIN": 150,
    "R-101": 45,
    "S-101": 60,
    "R-102": 80,
    "S-102": 90,
    "R-103": 115,
    "S-103": 120,
    "S-HEADER": 35,
    "P-A": 20,
    "P-B": 20,
    "D-MAIN": 250,
}


def _route_sums(raw: dict[str, Any]) -> dict[str, Decimal]:
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for edge in raw["edges"]:
        sums[edge["route_id"]] += Decimal(str(edge["length_m"]))
    return sums


def test_route_sums_match_audited_values(raw_topology: dict[str, Any]) -> None:
    """The route sums recomputed from the edge list equal the audited values. Independent: yes,
    because the sums use exact decimal arithmetic.
    """
    assert dict(_route_sums(raw_topology)) == {k: Decimal(v) for k, v in EXPECTED_ROUTES.items()}


def test_declared_route_lengths_match_audited_values(raw_topology: dict[str, Any]) -> None:
    """The route lengths declared in the contract equal the audited values. Independent: yes,
    because the values are literals from the audit.
    """
    assert raw_topology["route_lengths_m"] == {k: float(v) for k, v in EXPECTED_ROUTES.items()}


def test_total_of_distinct_edges_is_985_m(raw_topology: dict[str, Any]) -> None:
    """The total length of the distinct edges is 985 m. Independent: yes, because the sum uses exact
    decimal arithmetic.
    """
    assert sum(Decimal(str(e["length_m"])) for e in raw_topology["edges"]) == Decimal(985)


def test_total_equals_sum_of_route_checksums(raw_topology: dict[str, Any]) -> None:
    """The total length equals the sum of the route checksums. Independent: yes, because the routes
    partition the edges.
    """
    assert sum(_route_sums(raw_topology).values()) == Decimal(985)


def test_edge_and_route_counts(raw_topology: dict[str, Any]) -> None:
    """The contract has 28 distinct edges and 11 routes. Independent: yes, because the counts are
    the audited values.
    """
    assert len(raw_topology["edges"]) == 28
    assert len({e["edge_id"] for e in raw_topology["edges"]}) == 28
    assert len(_route_sums(raw_topology)) == 11
