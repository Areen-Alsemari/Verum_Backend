"""Topology contract: loader behaviour and structural invariants.

The positive tests pin the audited configuration, and the negative tests show that the loader
rejects each kind of corruption. The graph view is directed from the start node to the end node, and
the receipt and suction headers are not connected by any edge.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest

from verum.contracts import ContractError, Topology
from verum.contracts.topology import parse_topology
from verum.graph import Network

PUMP_DIRECT = ("P-101A", "P-101B")


def test_counts_and_total(topology: Topology) -> None:
    """The contract has 28 edges and 11 routes and a total length of 985 m. Independent: yes,
    because the values are the audited ones.
    """
    assert len(topology.edges) == 28
    assert len(topology.route_lengths_m) == 11
    assert math.isclose(topology.total_length_m, 985.0, abs_tol=1e-9)


def test_edge_identifiers_follow_the_documented_order(topology: Topology) -> None:
    """The edge identifiers start with E001, E002, E003 and end with E-D1, E-D2. Independent: yes,
    because the order is the documented one.
    """
    assert topology.edge_ids[:3] == ("E001", "E002", "E003")
    assert topology.edge_ids[-2:] == ("E-D1", "E-D2")


def test_assets(topology: Topology) -> None:
    """The tanks, pumps and excluded assets equal the documented sets. Independent: yes, because the
    expected sets are written out in the test.
    """
    assert topology.tank_ids == ("TK-101", "TK-102", "TK-103")
    assert topology.pumps == PUMP_DIRECT
    assert set(topology.excluded_assets) == {"CV-201", "ZT-201"}


def test_each_nominal_size_has_one_inner_diameter(topology: Topology) -> None:
    """Edges of one nominal size share one inner diameter. Independent: yes, because the check
    groups the edges by size.
    """
    by_size: dict[str, set[float]] = {}
    for edge in topology.edges:
        by_size.setdefault(edge.nominal_size, set()).add(edge.inner_diameter_m)
    assert all(len(diameters) == 1 for diameters in by_size.values())
    assert set(by_size) == {"DN200", "DN250", "DN300"}


@pytest.mark.parametrize("tank", ["TK-101", "TK-102", "TK-103"])
def test_every_tank_and_pump_is_connected(topology: Topology, tank: str) -> None:
    """Every tank and pump is reachable from the receipt boundary or the tank outlets. Independent:
    yes, because the expected outcome follows from the topology.
    """
    network = Network.from_topology(topology)
    assert network.reachable("PIPELINE_RECEIPT_BOUNDARY", f"{tank}:receipt_nozzle")
    for pump in PUMP_DIRECT:
        assert network.reachable(f"{tank}:outlet_nozzle", pump)
        assert network.reachable(pump, "DISTRIBUTION_BOUNDARY")


def test_receipt_and_suction_headers_stay_separate(topology: Topology) -> None:
    """The receipt header and the suction header are not connected by any edge. Independent: yes,
    because the expected outcome is the topology rule.
    """
    network = Network.from_topology(topology)
    assert not network.reachable("RECEIPT_HEADER", "SUCTION_HEADER")
    assert not network.reachable("SUCTION_HEADER", "RECEIPT_HEADER")


def test_pump_branches_are_alternatives(topology: Topology) -> None:
    """The two pump branches are not connected to each other. Independent: yes, because the expected
    outcome is the topology rule.
    """
    network = Network.from_topology(topology)
    assert not network.reachable("P-101A", "P-101B")
    assert not network.reachable("P-101B", "P-101A")


def test_check_valves_sit_between_pump_and_discharge(topology: Topology) -> None:
    """Each check valve is the first node after its pump. Independent: yes, because the expected
    pairs are written out in the test.
    """
    for pump, check in (("P-101A", "CV-PA"), ("P-101B", "CV-PB")):
        first = next(e for e in topology.edges if e.from_node == pump)
        assert first.to_node == check


def _mutated(raw: dict[str, Any], change: Any) -> dict[str, Any]:
    clone = copy.deepcopy(raw)
    change(clone)
    return clone


def _drop_edge(c: dict[str, Any]) -> None:
    c["edges"].pop()


def _stale_count(c: dict[str, Any]) -> None:
    c["edge_count"] = 30


def _duplicate_id(c: dict[str, Any]) -> None:
    c["edges"][1]["edge_id"] = c["edges"][0]["edge_id"]


def _wrong_length(c: dict[str, Any]) -> None:
    c["edges"][0]["length_m"] = 31.0


def _two_diameters(c: dict[str, Any]) -> None:
    c["edges"][3]["inner_diameter_m"] = 0.2


def _unknown_route(c: dict[str, Any]) -> None:
    c["edges"][0]["route_id"] = "R-XYZ"


def _missing_key(c: dict[str, Any]) -> None:
    del c["edges"][0]["z_from_m"]


def _zero_length(c: dict[str, Any]) -> None:
    c["edges"][0]["length_m"] = 0.0
    c["route_lengths_m"]["R-MAIN"] = 120.0


def _excluded_asset_as_node(c: dict[str, Any]) -> None:
    c["edges"][17]["to_node"] = "CV-201"


@pytest.mark.parametrize(
    "change",
    [
        _drop_edge,
        _stale_count,
        _duplicate_id,
        _wrong_length,
        _two_diameters,
        _unknown_route,
        _missing_key,
        _zero_length,
        _excluded_asset_as_node,
    ],
)
def test_loader_rejects_corrupted_contract(raw_topology: dict[str, Any], change: Any) -> None:
    """The loader rejects each kind of corrupted contract. Independent: yes, because the corruptions
    are written out in the test.
    """
    with pytest.raises(ContractError):
        parse_topology(_mutated(raw_topology, change))
