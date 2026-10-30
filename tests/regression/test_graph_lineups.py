"""Connectivity of the pipe network under valve and pump lineups.

The tank is not an edge, and a connection through a tank must be requested and appears in the path
as a tank link. Pipes and open valves are bidirectional, check valves and pumps are one-way, and a
closed valve blocks every edge that touches it.
"""

from __future__ import annotations

import pytest

from verum.contracts import ContractError, Topology
from verum.graph import (
    DISTRIBUTION_BOUNDARY,
    RECEIPT_BOUNDARY,
    TANK_LINK,
    Lineup,
    Network,
)

RECEIVE_101 = Lineup.of({"XV-R000", "XV-R101"})
DELIVER_101_A = Lineup.of({"XV-S101", "XV-PAI", "XV-PAO"}, {"P-101A"})
ALL_VALVES = {
    "XV-R000", "XV-R101", "XV-R102", "XV-R103", "XV-S101", "XV-S102", "XV-S103",
    "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO",
}  # fmt: skip
ALL_OPEN = Lineup.of(ALL_VALVES, {"P-101A", "P-101B"})


@pytest.fixture(scope="module")
def network(topology: Topology) -> Network:
    return Network.from_topology(topology)


def test_receive_101_connects_the_receipt_boundary_to_tk101_only(network: Network) -> None:
    """The receipt lineup for tank TK-101 connects the receipt boundary to that tank only and
    activates its five edges. Independent: yes, because the expected edges are read from the
    topology by hand.
    """
    assert network.connected_terminals(RECEIPT_BOUNDARY, RECEIVE_101) == {"TK-101:receipt_nozzle"}
    assert network.active_edges(RECEIVE_101) == {"E001", "E002", "E003", "E-R101a", "E-R101b"}


def test_receive_101_does_not_reach_the_other_tanks(network: Network) -> None:
    """The receipt lineup for tank TK-101 does not reach the other tanks. Independent: yes, because
    the expected outcome follows from the closed valves.
    """
    for tank in ("TK-102", "TK-103"):
        assert not network.connected(RECEIPT_BOUNDARY, f"{tank}:receipt_nozzle", RECEIVE_101)


def test_deliver_101_with_pump_a_runs_through_pump_a_only(network: Network) -> None:
    """A delivery from tank TK-101 with pump A runs through the pump A branch and not the pump B
    branch. Independent: yes, because the expected edges are read from the topology by hand.
    """
    assert network.connected_terminals("TK-101:outlet_nozzle", DELIVER_101_A) == {
        DISTRIBUTION_BOUNDARY
    }
    active = network.active_edges(DELIVER_101_A)
    assert active == {
        "E-S101a", "E-S101b", "E-SH", "E-PA0", "E-PA1", "E-PA2", "E-PA3", "E-PA4", "E-D1", "E-D2",
    }  # fmt: skip
    assert not any(e.startswith("E-PB") for e in active)


def test_deliver_101_with_pump_b_runs_through_pump_b_only(network: Network) -> None:
    """A delivery from tank TK-101 with pump B runs through the pump B branch and not the pump A
    branch. Independent: yes, because the expected edges are read from the topology by hand.
    """
    lineup = Lineup.of({"XV-S101", "XV-PBI", "XV-PBO"}, {"P-101B"})
    active = network.active_edges(lineup)
    assert {"E-PB0", "E-PB1", "E-PB2", "E-PB3", "E-PB4"} <= active
    assert not any(e.startswith("E-PA") for e in active)


def test_a_stopped_pump_blocks_the_branch(network: Network) -> None:
    """A stopped pump blocks its branch. Independent: yes, because the expected outcome is the pump
    rule.
    """
    lineup = Lineup.of({"XV-S101", "XV-PAI", "XV-PAO"}, set())
    assert network.active_edges(lineup) == frozenset()
    assert not network.connected("TK-101:outlet_nozzle", DISTRIBUTION_BOUNDARY, lineup)


def test_a_closed_pump_outlet_valve_blocks_the_branch(network: Network) -> None:
    """A closed pump outlet valve blocks the branch. Independent: yes, because the expected outcome
    is the valve rule.
    """
    lineup = Lineup.of({"XV-S101", "XV-PAI"}, {"P-101A"})
    assert not network.connected("TK-101:outlet_nozzle", DISTRIBUTION_BOUNDARY, lineup)


def test_no_flow_back_through_the_check_valve_or_pump(network: Network) -> None:
    """Flow can pass the check valve and pump forwards but not backwards. Independent: yes, because
    the expected outcome is the one-way rule.
    """
    # Flow from the distribution side towards the suction side is blocked
    # even with every valve open: pumps and check valves are one-way.
    assert not network.connected(DISTRIBUTION_BOUNDARY, "TK-101:outlet_nozzle", ALL_OPEN)
    assert network.connected("TK-101:outlet_nozzle", DISTRIBUTION_BOUNDARY, ALL_OPEN)


def test_receipt_branches_carry_flow_in_both_directions(network: Network) -> None:
    """With two receipt inlets open the tanks are connected in both directions, because the receipt
    branches have no check valve. Independent: yes, because the expected outcome is the
    bidirectional rule.
    """
    both = Lineup.of({"XV-R000", "XV-R101", "XV-R102"})
    assert network.connected("TK-101:receipt_nozzle", "TK-102:receipt_nozzle", both)
    assert network.connected("TK-102:receipt_nozzle", "TK-101:receipt_nozzle", both)


def test_receipt_and_suction_headers_are_never_joined_by_pipe(network: Network) -> None:
    """The receipt header and the suction header are never joined by pipe in any lineup.
    Independent: yes, because the expected outcome is the topology rule.
    """
    for lineup in (Lineup.of(), RECEIVE_101, DELIVER_101_A, ALL_OPEN):
        assert not network.connected("RECEIPT_HEADER", "SUCTION_HEADER", lineup)
        assert not network.connected("SUCTION_HEADER", "RECEIPT_HEADER", lineup)


def test_headers_join_only_through_a_tank(network: Network) -> None:
    """The two headers are joined only through a tank, with exactly one tank link in the path.
    Independent: yes, because the expected outcome is the topology rule.
    """
    path = network.path("RECEIPT_HEADER", "SUCTION_HEADER", ALL_OPEN, through_tanks=True)
    assert path is not None
    assert sum(1 for arc in path if arc[2] == TANK_LINK) == 1


def test_receipt_boundary_never_reaches_distribution_boundary_without_a_tank(
    network: Network,
) -> None:
    """The receipt boundary never reaches the distribution boundary without passing a tank.
    Independent: yes, because the expected outcome is the topology rule.
    """
    for lineup in (Lineup.of(), RECEIVE_101, DELIVER_101_A, ALL_OPEN):
        assert not network.connected(RECEIPT_BOUNDARY, DISTRIBUTION_BOUNDARY, lineup)


def test_every_path_from_receipt_to_distribution_passes_a_tank(network: Network) -> None:
    """Every path from the receipt boundary to the distribution boundary passes a tank link.
    Independent: yes, because the expected outcome is the topology rule.
    """
    path = network.path(RECEIPT_BOUNDARY, DISTRIBUTION_BOUNDARY, ALL_OPEN, through_tanks=True)
    assert path is not None
    assert any(arc[2] == TANK_LINK for arc in path)
    assert network.connected_terminals(RECEIPT_BOUNDARY, Lineup.of(ALL_VALVES)) <= {
        f"TK-{n}:receipt_nozzle" for n in (101, 102, 103)
    }


def test_the_graph_is_unchanged_by_queries(topology: Topology, network: Network) -> None:
    """Queries leave the graph with its 28 edges and 29 nodes. Independent: yes, because the counts
    are the audited values.
    """
    network.active_edges(ALL_OPEN)
    assert len(topology.edges) == 28
    assert len(topology.nodes) == 29


def test_idle_lineup_has_no_active_edge(network: Network) -> None:
    """A lineup with every valve closed and no pump has no active edge. Independent: yes, because
    the expected outcome is the empty set.
    """
    assert network.active_edges(Lineup.of()) == frozenset()


def test_unknown_valve_is_rejected(network: Network) -> None:
    """A lineup that names an unknown valve or pump is rejected. Independent: yes, because the
    expected outcome is the validation rule.
    """
    with pytest.raises(ContractError):
        network.active_edges(Lineup.of({"XV-R999"}))
    with pytest.raises(ContractError):
        network.active_edges(Lineup.of(set(), {"P-101C"}))
