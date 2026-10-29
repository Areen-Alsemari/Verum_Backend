"""The sixteen lineups: table content, rejected combinations and transitions.

Inputs: ``config/lineups.json``, the topology contract and an independent
transcription of the audited lineup table written out in this module.
Outputs: pass/fail.
Key assumptions:
    * The expected valve and pump states below were typed from the audited
      table, not generated from the configuration file, so a parsing error in
      the file would be caught.
    * The expected active edges are built from route membership (which edges
      belong to the receipt, suction, pump and delivery routes), and the
      package's active-edge result is also compared with an exhaustive
      simple-path search, which is a different algorithm.
    * The transition rules beyond the two documented chains are a proposal;
      the tests state them.

Source: ``revised/01_facility_tanks_topology.md`` section 6.2.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from verum.contracts import ContractError, Topology
from verum.graph import Lineup, Network
from verum.lineups import (
    BOTH_PUMPS,
    MULTIPLE_OUTLETS,
    NOT_IN_TABLE,
    THREE_INLETS,
    UNKNOWN_ELEMENT,
    LineupController,
    LineupRejected,
    LineupTable,
    TransitionRejected,
    load_lineup_table,
    source_tank,
    step_allowed,
)
from verum.lineups.table import parse_lineup_table

R000 = "XV-R000"
EXPECTED: dict[str, tuple[set[str], set[str]]] = {
    "IDLE": (set(), set()),
    "RECEIVE_101": ({R000, "XV-R101"}, set()),
    "DELIVER_101_A": ({"XV-S101", "XV-PAI", "XV-PAO"}, {"P-101A"}),
    "DELIVER_101_B": ({"XV-S101", "XV-PBI", "XV-PBO"}, {"P-101B"}),
    "RECEIVE_102": ({R000, "XV-R102"}, set()),
    "DELIVER_102_A": ({"XV-S102", "XV-PAI", "XV-PAO"}, {"P-101A"}),
    "DELIVER_102_B": ({"XV-S102", "XV-PBI", "XV-PBO"}, {"P-101B"}),
    "RECEIVE_103": ({R000, "XV-R103"}, set()),
    "DELIVER_103_A": ({"XV-S103", "XV-PAI", "XV-PAO"}, {"P-101A"}),
    "DELIVER_103_B": ({"XV-S103", "XV-PBI", "XV-PBO"}, {"P-101B"}),
    "RECEIVE_101_DELIVER_102_A": ({R000, "XV-R101", "XV-S102", "XV-PAI", "XV-PAO"}, {"P-101A"}),
    "RECEIVE_101_DELIVER_101_A": ({R000, "XV-R101", "XV-S101", "XV-PAI", "XV-PAO"}, {"P-101A"}),
    "RECEIVE_101_102": ({R000, "XV-R101", "XV-R102"}, set()),
    "CHANGEOVER_HOLD": (set(), set()),
    "MAINTENANCE_ISOLATED": (set(), set()),
    "SWITCH_RECEIPT_HOLD": (set(), set()),
}
ALL_CLOSED = {"IDLE", "CHANGEOVER_HOLD", "MAINTENANCE_ISOLATED", "SWITCH_RECEIPT_HOLD"}
HOLDS = {"CHANGEOVER_HOLD", "SWITCH_RECEIPT_HOLD"}


@pytest.fixture(scope="module")
def table(topology: Topology) -> LineupTable:
    return load_lineup_table(topology)


@pytest.fixture(scope="module")
def network(topology: Topology) -> Network:
    return Network.from_topology(topology)


def test_there_are_sixteen_modes(table: LineupTable) -> None:
    assert set(table.modes) == set(EXPECTED)
    assert len(table.modes) == 16


@pytest.mark.parametrize("name", list(EXPECTED))
def test_mode_states_match_the_transcribed_table(table: LineupTable, name: str) -> None:
    valves, pumps = EXPECTED[name]
    assert table.modes[name].open_valves == valves
    assert table.modes[name].running_pumps == pumps


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_mode_classifies_to_itself(table: LineupTable, topology: Topology, name: str) -> None:
    valves, pumps = EXPECTED[name]
    assert name in table.classify(valves, pumps, topology)


def test_four_modes_share_the_all_closed_state(table: LineupTable, topology: Topology) -> None:
    assert set(table.classify(set(), set(), topology)) == ALL_CLOSED


@pytest.mark.parametrize("name", list(EXPECTED))
def test_modes_satisfy_the_baseline_invariants(table: LineupTable, name: str) -> None:
    mode = table.modes[name]
    assert len(mode.running_pumps) <= 1
    assert len(mode.open_valves & {"XV-S101", "XV-S102", "XV-S103"}) <= 1
    assert len(mode.open_valves & {"XV-R101", "XV-R102", "XV-R103"}) < 3
    inlets = mode.open_valves & {"XV-R101", "XV-R102", "XV-R103"}
    assert mode.receiving == bool(inlets)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_a_running_pump_has_both_isolation_valves_open(table: LineupTable, name: str) -> None:
    mode = table.modes[name]
    for pump, pair in (("P-101A", {"XV-PAI", "XV-PAO"}), ("P-101B", {"XV-PBI", "XV-PBO"})):
        assert (pump in mode.running_pumps) == (pair <= mode.open_valves)
        assert not (pump not in mode.running_pumps and mode.open_valves & pair)


def _route_edges(topology: Topology, *routes: str) -> set[str]:
    return {e.edge_id for e in topology.edges if e.route_id in routes}


def _expected_active(topology: Topology, name: str) -> set[str]:
    valves, pumps = EXPECTED[name]
    edges: set[str] = set()
    inlets = [v for v in valves if v.startswith("XV-R1")]
    if inlets:
        edges |= _route_edges(topology, "R-MAIN", *[f"R-{v[-3:]}" for v in inlets])
    outlets = [v for v in valves if v.startswith("XV-S1")]
    if outlets and pumps:
        branch = "P-A" if "P-101A" in pumps else "P-B"
        edges |= _route_edges(topology, f"S-{outlets[0][-3:]}", "S-HEADER", branch, "D-MAIN")
    return edges


@pytest.mark.parametrize("name", list(EXPECTED))
def test_active_edges_match_route_membership(
    table: LineupTable, network: Network, topology: Topology, name: str
) -> None:
    assert network.active_edges(table.modes[name].lineup) == _expected_active(topology, name)


def _simple_path_edges(network: Network, lineup: Lineup) -> set[str]:
    arcs = network.arcs(lineup)
    out: dict[str, list[tuple[str, str, str]]] = {}
    for arc in arcs:
        out.setdefault(arc[0], []).append(arc)
    found: set[str] = set()

    def walk(node: str, goal: str, seen: set[str], trail: list[str]) -> None:
        if node == goal:
            found.update(trail)
            return
        for _, nxt, edge in out.get(node, []):
            if nxt not in seen:
                walk(nxt, goal, seen | {nxt}, [*trail, edge])

    for a, b in itertools.permutations(sorted(network.terminals), 2):
        walk(a, b, {a}, [])
    return found


@pytest.mark.parametrize("name", list(EXPECTED))
def test_active_edges_agree_with_exhaustive_simple_path_search(
    table: LineupTable, network: Network, name: str
) -> None:
    lineup = table.modes[name].lineup
    assert network.active_edges(lineup) == _simple_path_edges(network, lineup)


@pytest.mark.parametrize("name", [n for n in EXPECTED if n not in ALL_CLOSED])
def test_receipt_and_suction_headers_are_not_connected_in_any_mode(
    table: LineupTable, network: Network, name: str
) -> None:
    lineup = table.modes[name].lineup
    assert not network.connected("RECEIPT_HEADER", "SUCTION_HEADER", lineup)
    assert not network.connected("PIPELINE_RECEIPT_BOUNDARY", "DISTRIBUTION_BOUNDARY", lineup)


REJECTED = [
    (
        "both pumps",
        {"XV-S101", "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO"},
        {"P-101A", "P-101B"},
        BOTH_PUMPS,
    ),
    ("both pumps idle valves", set(), {"P-101A", "P-101B"}, BOTH_PUMPS),
    ("three inlets", {R000, "XV-R101", "XV-R102", "XV-R103"}, set(), THREE_INLETS),
    (
        "three inlets with delivery",
        {R000, "XV-R101", "XV-R102", "XV-R103", "XV-S101"},
        set(),
        THREE_INLETS,
    ),
    ("two outlets", {"XV-S101", "XV-S102"}, set(), MULTIPLE_OUTLETS),
    (
        "three outlets with pump",
        {"XV-S101", "XV-S102", "XV-S103", "XV-PAI", "XV-PAO"},
        {"P-101A"},
        MULTIPLE_OUTLETS,
    ),
    (
        "two outlets, pump running",
        {"XV-S101", "XV-S103", "XV-PBI", "XV-PBO"},
        {"P-101B"},
        MULTIPLE_OUTLETS,
    ),
    ("inlets 101 and 103", {R000, "XV-R101", "XV-R103"}, set(), NOT_IN_TABLE),
    ("inlets 102 and 103", {R000, "XV-R102", "XV-R103"}, set(), NOT_IN_TABLE),
    ("receipt main only", {R000}, set(), NOT_IN_TABLE),
    ("inlet without main valve", {"XV-R101"}, set(), NOT_IN_TABLE),
    ("pump without valves", set(), {"P-101A"}, NOT_IN_TABLE),
    ("pump A on pump B valves", {"XV-S101", "XV-PBI", "XV-PBO"}, {"P-101A"}, NOT_IN_TABLE),
    ("pump with only inlet valve", {"XV-S101", "XV-PAI"}, {"P-101A"}, NOT_IN_TABLE),
    ("outlet without pump", {"XV-S101"}, set(), NOT_IN_TABLE),
    ("isolation valves without pump", {"XV-S101", "XV-PAI", "XV-PAO"}, set(), NOT_IN_TABLE),
    ("delivery with main valve", {R000, "XV-S101", "XV-PAI", "XV-PAO"}, {"P-101A"}, NOT_IN_TABLE),
    (
        "receive 102 with delivery 101",
        {R000, "XV-R102", "XV-S101", "XV-PAI", "XV-PAO"},
        {"P-101A"},
        NOT_IN_TABLE,
    ),
    (
        "receive 101 and 102 with delivery",
        {R000, "XV-R101", "XV-R102", "XV-S103", "XV-PAI", "XV-PAO"},
        {"P-101A"},
        NOT_IN_TABLE,
    ),
    ("unknown valve", {"XV-R999"}, set(), UNKNOWN_ELEMENT),
    ("unknown pump", set(), {"P-101C"}, UNKNOWN_ELEMENT),
    ("removed control valve", {"CV-201"}, set(), UNKNOWN_ELEMENT),
]


@pytest.mark.parametrize(
    ("name", "valves", "pumps", "reason"), REJECTED, ids=[r[0] for r in REJECTED]
)
def test_rejected_combinations(
    table: LineupTable,
    topology: Topology,
    name: str,
    valves: set[str],
    pumps: set[str],
    reason: str,
) -> None:
    with pytest.raises(LineupRejected) as caught:
        table.classify(valves, pumps, topology)
    assert caught.value.reason == reason


def test_every_open_valve_subset_is_either_a_mode_or_rejected(
    table: LineupTable, topology: Topology
) -> None:
    valves = sorted(v for v in topology.nodes if v.startswith("XV-"))
    accepted = 0
    for r in range(len(valves) + 1):
        for subset in itertools.combinations(valves, r):
            for pumps in (set(), {"P-101A"}, {"P-101B"}, {"P-101A", "P-101B"}):
                try:
                    names = table.classify(set(subset), pumps, topology)
                except LineupRejected:
                    continue
                accepted += 1
                assert all(table.modes[n].open_valves == set(subset) for n in names)
    # 13 distinct valve/pump states carry the 16 modes (four share the all-closed state).
    assert accepted == 13


def test_unknown_mode_name_is_rejected(table: LineupTable) -> None:
    with pytest.raises(LineupRejected):
        table.mode("RECEIVE_104")


def test_table_is_cross_checked_against_the_topology(
    topology: Topology, raw_topology: dict[str, Any]
) -> None:
    # The topology contract does not carry lineups, so the table file is the only source.
    assert "lineups" not in raw_topology
    bad = {
        "hold_states": [],
        "modes": {"X": {"open_valves": ["XV-NOPE"], "running_pumps": []}},
    }
    with pytest.raises(ContractError):
        parse_lineup_table(bad, topology)
    with pytest.raises(ContractError):
        parse_lineup_table({"modes": {}, "hold_states": ["MISSING"]}, topology)


# --- transitions ---------------------------------------------------------------------

DOCUMENTED_CHAINS = [
    ("RECEIVE_101", "SWITCH_RECEIPT_HOLD", "RECEIVE_102"),
    ("RECEIVE_102", "SWITCH_RECEIPT_HOLD", "RECEIVE_103"),
    ("RECEIVE_103", "SWITCH_RECEIPT_HOLD", "RECEIVE_101"),
    ("DELIVER_101_A", "CHANGEOVER_HOLD", "DELIVER_101_B"),
    ("DELIVER_102_B", "CHANGEOVER_HOLD", "DELIVER_102_A"),
    ("DELIVER_103_A", "CHANGEOVER_HOLD", "DELIVER_103_B"),
]


@pytest.mark.parametrize(("start", "hold", "end"), DOCUMENTED_CHAINS)
def test_documented_chains_are_valid(table: LineupTable, start: str, hold: str, end: str) -> None:
    controller = LineupController(table, start)
    assert controller.request(hold) == hold
    assert controller.request(end) == end
    assert controller.current == end


DIRECT = [
    ("RECEIVE_101", "RECEIVE_102"),
    ("RECEIVE_101", "RECEIVE_101_102"),
    ("DELIVER_101_A", "DELIVER_101_B"),
    ("DELIVER_101_A", "DELIVER_102_A"),
    ("RECEIVE_101", "DELIVER_101_A"),
    ("RECEIVE_101", "RECEIVE_101_DELIVER_101_A"),
    ("IDLE", "RECEIVE_101"),
    ("IDLE", "DELIVER_101_A"),
    ("MAINTENANCE_ISOLATED", "RECEIVE_101"),
    ("RECEIVE_101", "IDLE"),
    ("DELIVER_101_A", "IDLE"),
    ("DELIVER_101_A", "MAINTENANCE_ISOLATED"),
]


@pytest.mark.parametrize(("start", "end"), DIRECT)
def test_direct_changes_are_rejected(table: LineupTable, start: str, end: str) -> None:
    with pytest.raises(TransitionRejected):
        LineupController(table, start).request(end)


WRONG_HOLD = [
    ("RECEIVE_101", "CHANGEOVER_HOLD"),
    ("DELIVER_101_A", "SWITCH_RECEIPT_HOLD"),
]


@pytest.mark.parametrize(("start", "hold"), WRONG_HOLD)
def test_a_hold_must_serve_the_mode(table: LineupTable, start: str, hold: str) -> None:
    with pytest.raises(TransitionRejected):
        LineupController(table, start).request(hold)


def test_changeover_keeps_the_source_tank(table: LineupTable) -> None:
    controller = LineupController(table, "DELIVER_101_A")
    controller.request("CHANGEOVER_HOLD")
    with pytest.raises(TransitionRejected, match="source tank 101"):
        controller.request("DELIVER_102_A")
    assert controller.current == "CHANGEOVER_HOLD"


def test_a_start_from_rest_goes_through_a_hold(table: LineupTable) -> None:
    controller = LineupController(table)
    with pytest.raises(TransitionRejected):
        controller.request("RECEIVE_101")
    controller.request("SWITCH_RECEIPT_HOLD")
    controller.request("RECEIVE_101")
    controller.request("SWITCH_RECEIPT_HOLD")
    controller.request("IDLE")
    controller.request("MAINTENANCE_ISOLATED")
    assert controller.current == "MAINTENANCE_ISOLATED"


def test_no_step_between_two_active_modes_is_allowed(table: LineupTable) -> None:
    active = [n for n in EXPECTED if n not in ALL_CLOSED]
    assert not any(step_allowed(table, a, b) for a in active for b in active)


def test_no_step_between_idle_or_maintenance_and_an_active_mode(table: LineupTable) -> None:
    active = [n for n in EXPECTED if n not in ALL_CLOSED]
    for rest in ("IDLE", "MAINTENANCE_ISOLATED"):
        assert not any(step_allowed(table, rest, a) or step_allowed(table, a, rest) for a in active)


def test_active_modes_connect_only_to_a_serving_hold(table: LineupTable) -> None:
    for name in (n for n in EXPECTED if n not in ALL_CLOSED):
        mode = table.modes[name]
        partners = {h for h in HOLDS if step_allowed(table, name, h)}
        expected = set()
        if mode.receiving:
            expected.add("SWITCH_RECEIPT_HOLD")
        if mode.delivering:
            expected.add("CHANGEOVER_HOLD")
        assert partners == expected, name


def test_unknown_target_is_a_rejected_transition(table: LineupTable) -> None:
    with pytest.raises(TransitionRejected):
        LineupController(table).request("RECEIVE_104")


def test_source_tank_parsing() -> None:
    assert source_tank("DELIVER_103_B") == "103"
    assert source_tank("RECEIVE_101_DELIVER_102_A") == "102"
    assert source_tank("RECEIVE_101_DELIVER_101_A") == "101"
    assert source_tank("RECEIVE_101") is None
