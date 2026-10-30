"""Stale-field tests over the machine-readable contracts.

The shipped contracts must contain none of the references that the audit removed. Each removed
reference, when reintroduced into a mutated copy, must be detected by the stale-reference detector
and, where it applies, rejected by the loaders. Only the machine-readable contracts are scanned,
because the prose documents still describe the removed items in their history sections.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from verum.contracts import ContractError, Topology
from verum.contracts.sensors import parse_sensor_contract
from verum.contracts.stale import assert_no_stale_references, stale_findings
from verum.contracts.topology import parse_topology

Raw = dict[str, Any]
Mutation = Callable[[Raw, Raw, Raw], None]


def test_shipped_contracts_are_clean(raw_topology: Raw, raw_sensors: Raw, raw_policy: Raw) -> None:
    """The shipped contracts contain no stale reference. Independent: yes, because the expected
    finding list is empty.
    """
    assert stale_findings(raw_topology, raw_sensors, raw_policy) == []
    assert_no_stale_references(raw_topology, raw_sensors, raw_policy)


def _add_sensor(tag: str) -> Mutation:
    def apply(topology: Raw, sensors: Raw, policy: Raw) -> None:
        sensors["sensors"][tag] = copy.deepcopy(sensors["sensors"]["PT-203"])

    return apply


def _ref(tag: str, **changes: str) -> Mutation:
    def apply(topology: Raw, sensors: Raw, policy: Raw) -> None:
        sensors["sensors"][tag]["measured_variable_ref"].update(changes)

    return apply


def _drop_edge(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["edges"].pop()


def _extra_edge(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["edges"].append({**topology["edges"][-1], "edge_id": "E-D3"})


def _header_and_list_edited_together(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["edges"].pop()
    topology["edge_count"] = 27


def _stale_header_only(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["edge_count"] = 30


def _control_valve_node(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["edges"][-2]["to_node"] = "CV-201"


def _control_valve_in_pumps(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["pumps"].append("ZT-201")


def _forget_exclusions(topology: Raw, sensors: Raw, policy: Raw) -> None:
    topology["excluded_nonbaseline_assets"] = []


def _forget_sensor_exclusions(topology: Raw, sensors: Raw, policy: Raw) -> None:
    sensors["nonbaseline_excluded"] = ["CV-201"]


def _policy_forgets_control_valve(topology: Raw, sensors: Raw, policy: Raw) -> None:
    policy["no_baseline_control_valve"] = None


# Mutations that edit the sensor contract so that a loader can reject them.
SENSOR_MAPPINGS: dict[str, Mutation] = {
    "sensor references CV-201": _ref("PT-203", element_id="CV-201"),
    "sensor references ZT-201": _ref("PT-203", element_id="ZT-201"),
    "PT-001 on edge_state.pressure": _ref("PT-001", field="pressure"),
    "PT-203 on node_state.pressure": _ref("PT-203", field="pressure"),
    "PT-202A on edge_state.pressure": _ref("PT-202A", field="pressure"),
    "XV-R000 on valve_state.position_frac": _ref(
        "XV-R000", record_type="valve_state", field="position_frac"
    ),
    "XV-PAO on position_frac field": _ref("XV-PAO", field="position_frac"),
    "XV-S101 on valve_state": _ref("XV-S101", record_type="valve_state"),
    "LSHH-101 on tank level": _ref(
        "LSHH-101", record_type="tank_state", element_id="TK-101", field="level_m"
    ),
    "LSHH-102 on level field": _ref("LSHH-102", field="level_m"),
}
# Mutations that edit the graph so that a loader can reject them.
GRAPH_MUTATIONS: dict[str, Mutation] = {
    "edge removed": _drop_edge,
    "edge added": _extra_edge,
    "stale edge_count header": _stale_header_only,
    "CV-201 in the graph": _control_valve_node,
    "ZT-201 among the pumps": _control_valve_in_pumps,
}
# Mutations only the detector can see (they are consistent in themselves).
DETECTOR_ONLY: dict[str, Mutation] = {
    "CV-201 declared as a sensor": _add_sensor("CV-201"),
    "ZT-201 declared as a sensor": _add_sensor("ZT-201"),
    "PT-101 declared": _add_sensor("PT-101"),
    "PT-102 declared": _add_sensor("PT-102"),
    "PT-103 declared": _add_sensor("PT-103"),
    "AT-101 declared": _add_sensor("AT-101"),
    "AT-102 declared": _add_sensor("AT-102"),
    "AT-103 declared": _add_sensor("AT-103"),
    "header and list edited together": _header_and_list_edited_together,
    "topology exclusions removed": _forget_exclusions,
    "sensor exclusions removed": _forget_sensor_exclusions,
    "policy no longer names CV-201": _policy_forgets_control_valve,
}
ALL_MUTATIONS: dict[str, Mutation] = {**SENSOR_MAPPINGS, **GRAPH_MUTATIONS, **DETECTOR_ONLY}


@pytest.mark.parametrize("name", list(ALL_MUTATIONS))
def test_detector_flags_reintroduced_reference(
    name: str, raw_topology: Raw, raw_sensors: Raw, raw_policy: Raw
) -> None:
    """Each reintroduced stale reference is flagged by the detector and raises in the strict check.
    Independent: yes, because the mutations are written out in the test.
    """
    ALL_MUTATIONS[name](raw_topology, raw_sensors, raw_policy)
    assert stale_findings(raw_topology, raw_sensors, raw_policy)
    with pytest.raises(ValueError, match="stale references present"):
        assert_no_stale_references(raw_topology, raw_sensors, raw_policy)


@pytest.mark.parametrize("name", list(SENSOR_MAPPINGS))
def test_sensor_loader_rejects_stale_mapping(
    name: str, raw_topology: Raw, raw_sensors: Raw, raw_policy: Raw, topology: Topology
) -> None:
    """The sensor loader rejects each reintroduced stale mapping. Independent: yes, because the
    mutations are written out in the test.
    """
    SENSOR_MAPPINGS[name](raw_topology, raw_sensors, raw_policy)
    with pytest.raises(ContractError):
        parse_sensor_contract(raw_sensors, topology)


@pytest.mark.parametrize("name", list(GRAPH_MUTATIONS))
def test_topology_loader_rejects_stale_graph(
    name: str, raw_topology: Raw, raw_sensors: Raw, raw_policy: Raw
) -> None:
    """The topology loader rejects each reintroduced stale graph element. Independent: yes, because
    the mutations are written out in the test.
    """
    GRAPH_MUTATIONS[name](raw_topology, raw_sensors, raw_policy)
    with pytest.raises(ContractError):
        parse_topology(raw_topology)
