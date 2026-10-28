"""Sensor contract: counts, references and tap locations.

Inputs: ``config/canonical_sensor_contract.json`` and
``config/topology_contract.json``.

Outputs: pass/fail.
Key assumptions: the reference checks are computed here from the raw JSON,
independently of the loader, so a loader defect cannot hide a bad reference.
The vocabulary below restates the typed hidden-state definitions.

Source: ``canonical_sensor_contract.json``; ``verum_preflight.py``
(``check_sensor_refs``); ``VERUM_INTEGRATION_README.md`` section B.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from verum.contracts import ContractError, SensorContract, Topology
from verum.contracts.sensors import parse_sensor_contract

WITHHELD_TAGS = {"YS-201A", "YS-201B", "IT-201A", "IT-201B", "VT-201A", "VT-201B"}
VOCABULARY = {
    "edge_state": {"flow_m3s", "fluid_temperature_K", "p_from_pa_abs", "p_to_pa_abs"},
    "node_state": {"pressure_pa_abs"},
    "tank_state": {"level_m", "temperature_K"},
    "valve_contact_state": {"open_contact", "closed_contact"},
    "protection_state": {"trip_latched"},
    "pump_state": {"run_state"},
}


def _existing_elements(raw_topology: dict[str, Any]) -> dict[str, set[str]]:
    nodes = {n for e in raw_topology["edges"] for n in (e["from_node"], e["to_node"])}
    tanks = set(raw_topology["tanks"])
    return {
        "edge_state": {e["edge_id"] for e in raw_topology["edges"]},
        "node_state": {"RECEIPT_HEADER", "PUMP_SUCTION_TEE", "DISTRIBUTION_BOUNDARY"},
        "tank_state": tanks,
        "valve_contact_state": {n for n in nodes if n.startswith("XV-")},
        "protection_state": {f"LSHH-{t[3:]}" for t in tanks},
        "pump_state": set(raw_topology["pumps"]),
    }


def test_tag_counts(raw_sensors: dict[str, Any]) -> None:
    statuses = [s["status"] for s in raw_sensors["sensors"].values()]
    assert len(statuses) == 36
    assert statuses.count("emit") == 30
    assert statuses.count("withheld") == 6


def test_withheld_tags_are_the_motor_and_vibration_channels(sensors: SensorContract) -> None:
    assert set(sensors.withheld_tags) == WITHHELD_TAGS
    assert len(sensors.emitted_tags) == 30
    assert not WITHHELD_TAGS & set(sensors.emitted_tags)


def test_every_reference_is_allowed_and_existing(
    raw_sensors: dict[str, Any], raw_topology: dict[str, Any]
) -> None:
    elements = _existing_elements(raw_topology)
    for tag, entry in raw_sensors["sensors"].items():
        ref = entry["measured_variable_ref"]
        if entry["status"] == "withheld":
            continue
        assert ref["record_type"] in VOCABULARY, tag
        assert ref["element_id"] in elements[ref["record_type"]], tag
        assert ref["field"] in VOCABULARY[ref["record_type"]], tag


def test_withheld_tags_have_no_reference(
    sensors: SensorContract, raw_sensors: dict[str, Any]
) -> None:
    for tag in sensors.withheld_tags:
        assert sensors.sensors[tag].ref is None
        assert raw_sensors["sensors"][tag]["measured_variable_ref"] is None


def test_emitted_tags_all_have_a_reference(sensors: SensorContract) -> None:
    assert all(sensors.sensors[t].ref is not None for t in sensors.emitted_tags)


@pytest.mark.parametrize("tag", sorted(WITHHELD_TAGS))
def test_loader_rejects_a_reference_on_a_withheld_tag(
    raw_sensors: dict[str, Any], topology: Topology, tag: str
) -> None:
    raw_sensors["sensors"][tag]["measured_variable_ref"] = {
        "record_type": "pump_state",
        "element_id": "P-101A",
        "field": "run_state",
    }
    with pytest.raises(ContractError):
        parse_sensor_contract(raw_sensors, topology)


def test_loader_rejects_an_emitted_tag_without_reference(
    raw_sensors: dict[str, Any], topology: Topology
) -> None:
    raw_sensors["sensors"]["FT-001"]["measured_variable_ref"] = None
    with pytest.raises(ContractError):
        parse_sensor_contract(raw_sensors, topology)


@pytest.mark.parametrize("field", ["torque_Nm", "shaft_power_W", "speed_rpm", "speed_ratio"])
def test_pump_fields_other_than_run_state_cannot_be_referenced(
    raw_sensors: dict[str, Any], topology: Topology, field: str
) -> None:
    raw_sensors["sensors"]["P-101A"]["measured_variable_ref"]["field"] = field
    with pytest.raises(ContractError):
        parse_sensor_contract(raw_sensors, topology)


def test_receipt_pressure_tap_is_upstream_of_the_isolation_valve(sensors: SensorContract) -> None:
    ref = sensors.sensors["PT-001"].ref
    assert ref is not None
    assert (ref.record_type, ref.element_id, ref.field) == ("edge_state", "E002", "p_from_pa_abs")


@pytest.mark.parametrize(("tag", "edge"), [("PT-202A", "E-PA2"), ("PT-202B", "E-PB2")])
def test_pump_pressure_taps_are_before_the_check_valve(
    sensors: SensorContract, topology: Topology, tag: str, edge: str
) -> None:
    ref = sensors.sensors[tag].ref
    assert ref is not None
    assert (ref.record_type, ref.element_id, ref.field) == ("edge_state", edge, "p_from_pa_abs")
    assert topology.edge(edge).to_node.startswith("CV-")


def test_boundary_and_suction_pressure_use_absolute_node_pressure(sensors: SensorContract) -> None:
    for tag, node in (("PT-201", "PUMP_SUCTION_TEE"), ("PT-203", "DISTRIBUTION_BOUNDARY")):
        ref = sensors.sensors[tag].ref
        assert ref is not None
        assert (ref.record_type, ref.element_id, ref.field) == (
            "node_state",
            node,
            "pressure_pa_abs",
        )


def test_valve_tags_map_to_contact_state(sensors: SensorContract) -> None:
    valves = [t for t in sensors.sensors if t.startswith("XV-")]
    assert len(valves) == 11
    for tag in valves:
        ref = sensors.sensors[tag].ref
        assert ref is not None
        assert ref.record_type == "valve_contact_state"
        assert ref.element_id == tag


def test_high_high_switches_use_protection_state(sensors: SensorContract) -> None:
    for tank in ("101", "102", "103"):
        ref = sensors.sensors[f"LSHH-{tank}"].ref
        assert ref is not None
        assert (ref.record_type, ref.element_id) == ("protection_state", f"LSHH-{tank}")


def _set_ref(tag: str, **changes: str) -> Any:
    def apply(contract: dict[str, Any]) -> None:
        contract["sensors"][tag]["measured_variable_ref"].update(changes)

    return apply


@pytest.mark.parametrize(
    "change",
    [
        _set_ref("FT-001", record_type="flow_state"),
        _set_ref("FT-001", element_id="E999"),
        _set_ref("FT-001", field="velocity_m_s"),
        _set_ref("LT-101", element_id="TK-999"),
        _set_ref("PT-203", element_id="CV-201"),
        _set_ref("XV-R101", element_id="XV-R999"),
        _set_ref("LSHH-101", element_id="LSHH-999"),
        _set_ref("P-101A", element_id="P-101C"),
        _set_ref("PT-201", element_id="E-SH"),
    ],
)
def test_loader_rejects_bad_reference(
    raw_sensors: dict[str, Any], topology: Topology, change: Any
) -> None:
    clone = copy.deepcopy(raw_sensors)
    change(clone)
    with pytest.raises(ContractError):
        parse_sensor_contract(clone, topology)


def test_loader_rejects_unknown_status(raw_sensors: dict[str, Any], topology: Topology) -> None:
    raw_sensors["sensors"]["FT-001"]["status"] = "maybe"
    with pytest.raises(ContractError):
        parse_sensor_contract(raw_sensors, topology)
