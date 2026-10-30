"""Positive and negative cases for the six backend-proposed hidden-dataset schemas.

Inputs: ``schemas/hydraulic_state|solver_diagnostics|mass_ledger|events|episode|
simulation_rejected.schema.json`` and hand-built rows. Outputs: pass/fail.
Key assumptions: these schemas are proposals (version 0.7.0, ``x-status`` marker) for
review by the schema owner; every row carries ``hidden = true``; the structural checks
here say nothing about physical plausibility.

Source: ``revised/05_simulation_validation_dataset.md`` sections 7.4.8 and 7.5.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from verum.contracts import PROPOSED_SCHEMA_NAMES, load_schema, validator

Doc = dict[str, Any]
BASE = {"schema_version": "0.7.0", "episode_id": "EP-0123456789AB", "hidden": True}

PAYLOADS: dict[str, Doc] = {
    "node_state": {
        "pressure_pa_abs": 250000.0,
        "hydraulic_head_m": 30.0,
        "pressure_basis": "Pa_abs",
        "reference_edge": "E-SH",
    },
    "edge_state": {
        "flow_m3s": 0.083,
        "velocity_m_s": 2.5,
        "p_from_pa_abs": 3.0e5,
        "p_to_pa_abs": None,
        "fluid_temperature_K": 298.15,
    },
    "tank_state": {
        "level_m": 9.0,
        "volume_m3": 6343.25,
        "net_inflow_m3s": 0.0,
        "temperature_K": 298.15,
        "roof_state": "floating",
    },
    "valve_state": {
        "element_class": "isolation",
        "commanded_open": True,
        "position_frac": 1.0,
        "physically_closed": False,
        "flow_m3s": 0.08,
        "delta_p_pa": 1200.0,
        "check_state": None,
        "k_loss": 0.1,
    },
    "pump_state": {
        "run_state": "running",
        "speed_ratio": 1.0,
        "flow_m3s": 0.083,
        "head_m": 42.0,
        "shaft_power_W": 34000.0,
        "NPSHa_m": 10.0,
        "NPSH3_m": 4.0,
        "NPSH_margin_ratio": 2.5,
        "domain_valid": True,
        "phase_validity_status": "OK",
    },
    "protection_state": {
        "state": "NORMAL",
        "trip_latched": False,
        "signal_source": "independent_detector",
        "true_level_m": 9.0,
        "independent_level_m": 9.0,
    },
}


def _state(kind: str) -> Doc:
    return {
        **BASE,
        "dataset": "hydraulic_state",
        "t_sim_s": 12.0,
        "record_type": kind,
        "element_id": "X-1",
        "side": None,
        "payload": copy.deepcopy(PAYLOADS[kind]),
    }


DIAG: Doc = {
    **BASE,
    "dataset": "solver_diagnostics",
    "t_sim_s": 5.0,
    "side": None,
    "iterations": 3,
    "max_mass_residual_kg_s": 1e-7,
    "convergence_ok": True,
    "phase_validity_status": "OK",
    "domain_valid": True,
    "flow_model": "inertial",
    "active_validity_window_ids": ["VW-0001"],
}
BOUNDARY: Doc = {
    **BASE,
    "dataset": "boundary_state",
    "t_sim_s": 5.0,
    "side": None,
    "demand_process": True,
    "downstream_factor": 1.02,
    "log_downstream_factor": 0.0198,
    "boundary_law_coefficient_m": 10.26,
    "reservoir_pressure_pa_gauge": 200000.0,
    "atmosphere_stratum": "coastal",
    "atmosphere_pa_abs": 101325.0,
}
WINDOW: Doc = {
    **BASE,
    "dataset": "validity_windows",
    "window_id": "VW-0001",
    "kind": "flow_collapse",
    "element_id": "XV-R000",
    "t_start_s": 2978.8,
    "t_end_s": 2978.99,
    "reason": "flow_collapse_within_wave_criterion",
    "ratio": 0.514,
    "round_trip_s": 0.3609,
}
LEDGER: Doc = {
    **BASE,
    "dataset": "mass_ledger",
    "t_sim_s": 5.0,
    "side": "post_event",
    "scope": "network",
    "liquid_kg": 1.0e7,
    "cumulative_received_kg": 100.0,
    "cumulative_delivered_kg": 50.0,
    "cumulative_spill_kg": 0.0,
    "residual_kg": 1e-6,
    "tolerance_kg": 1e-3,
    "closed": True,
}
EVENT: Doc = {
    **BASE,
    "dataset": "events",
    "sequence_index": 3,
    "t_sim_s": 600.0,
    "event_type": "valve_move",
    "actor": "simulator_truth",
    "asset_id": "XV-R101",
    "payload": {"phase": "start"},
}
EPISODE: Doc = {
    **BASE,
    "dataset": "episode",
    "scenario_id": "S0-A",
    "seed": 1,
    "config_hash": "a" * 64,
    "lockfile_hash": "b" * 64,
    "solver_version": "path-dynamics-radau-1",
    "dataset_tier": "analytic_verification",
    "step_size_s": 1.0,
    "duration_s": 3600.0,
    "temperature_c": 25.0,
    "fitting_profile": "reference_fittings",
    "healthy_envelope": True,
    "fluid_density_kg_m3": 750.0,
    "initial_tank_levels_m": {"TK-101": 9.0},
    "tolerances": {"mass_conservation_kg_s": 4.2e-4},
    "atmosphere_stratum": "coastal",
    "volatility_class": "RVP_9_0",
    "atmosphere_pa_abs": 101325.0,
    "demand_process": False,
    "events_evaluated": 3,
    "validity_windows": [
        {
            k: v
            for k, v in WINDOW.items()
            if k
            in (
                "window_id",
                "kind",
                "element_id",
                "t_start_s",
                "t_end_s",
                "reason",
                "ratio",
                "round_trip_s",
            )
        }
    ],
    "protection_crossings": [
        {"t_sim_s": 848.23, "tank": "TK-101", "threshold": "high_alarm", "level_m": 12.5}
    ],
    "pipe_inventory_constant": True,
    "status": "completed",
    "fault_instance_ids": [],
}
FAULT_SPEC: Doc = {
    "schema_version": "0.7.0",
    "hidden": True,
    "dataset": "fault_spec",
    "fault_type": "PIPE_LEAK",
    "variant": "orifice",
    "asset_id": "E-PA3",
    "onset_s": 900.0,
    "ramp_s": 300.0,
    "magnitude": 5e-4,
    "position": 0.5,
    "discharge_coefficient": 0.62,
    "peak_severity": 1.0,
}
REJECTED: Doc = {
    **BASE,
    "dataset": "simulation_rejected",
    "scenario_id": "REJ-1",
    "gate": "SG0",
    "t_sim_s": 0.0,
    "parameter": "pumping_minimum_level[TK-103,45C,reference_fittings,NPSH3=4m]",
    "detail": "below",
    "value": 5.0,
    "limit": 8.7486,
}


def _edit(doc: Doc, path: str, value: Any) -> Doc:
    clone = copy.deepcopy(doc)
    *parents, leaf = path.split(".")
    node = clone
    for key in parents:
        node = node[key]
    if value is _DROP:
        del node[leaf]
    else:
        node[leaf] = value
    return clone


_DROP = object()

POSITIVE: list[tuple[str, str, Doc]] = [
    *[("hydraulic_state", f"state:{k}", _state(k)) for k in PAYLOADS],
    ("hydraulic_state", "state:pre_event", _edit(_state("tank_state"), "side", "pre_event")),
    ("hydraulic_state", "state:post_event", _edit(_state("tank_state"), "side", "post_event")),
    ("solver_diagnostics", "diag", DIAG),
    (
        "solver_diagnostics",
        "diag without window",
        _edit(_edit(DIAG, "active_validity_window_ids", []), "flow_model", "inactive"),
    ),
    ("boundary_state", "boundary", BOUNDARY),
    ("boundary_state", "boundary without process", _edit(BOUNDARY, "demand_process", False)),
    ("validity_windows", "window", WINDOW),
    (
        "validity_windows",
        "branched window",
        {
            **WINDOW,
            "kind": "branched_lineup",
            "reason": "rigid_column_unavailable",
            "ratio": None,
            "round_trip_s": None,
        },
    ),
    ("mass_ledger", "network", LEDGER),
    (
        "mass_ledger",
        "tank",
        {
            **LEDGER,
            "scope": "TK-101",
            "cumulative_received_kg": None,
            "cumulative_delivered_kg": None,
            "residual_kg": None,
            "tolerance_kg": None,
            "closed": None,
        },
    ),
    ("events", "event", EVENT),
    ("episode", "episode", EPISODE),
    ("fault_spec", "leak", FAULT_SPEC),
    ("simulation_rejected", "rejected", REJECTED),
]
NEGATIVE: list[tuple[str, str, Doc]] = [
    *[
        (d["dataset"], f"{d['dataset']}: hidden false", _edit(d, "hidden", False))
        for d in (_state("tank_state"), DIAG, LEDGER, EVENT, EPISODE, REJECTED)
    ],
    *[
        (d["dataset"], f"{d['dataset']}: hidden absent", _edit(d, "hidden", _DROP))
        for d in (_state("tank_state"), DIAG, LEDGER, EVENT, EPISODE, REJECTED)
    ],
    *[
        (d["dataset"], f"{d['dataset']}: extra field", _edit(d, "fault_type", "PIPE_LEAK"))
        for d in (_state("tank_state"), DIAG, LEDGER, EVENT, EPISODE, REJECTED)
    ],
    *[
        (d["dataset"], f"{d['dataset']}: wrong major version", _edit(d, "schema_version", "1.0.0"))
        for d in (_state("tank_state"), DIAG, LEDGER, EVENT, EPISODE, REJECTED)
    ],
    (
        "hydraulic_state",
        "unknown record type",
        _edit(_state("tank_state"), "record_type", "leak_state"),
    ),
    ("hydraulic_state", "bad side", _edit(_state("tank_state"), "side", "during")),
    ("hydraulic_state", "negative time", _edit(_state("tank_state"), "t_sim_s", -1.0)),
    (
        "hydraulic_state",
        "payload does not match its type",
        {**_state("tank_state"), "payload": PAYLOADS["edge_state"]},
    ),
    ("hydraulic_state", "string flow", _edit(_state("edge_state"), "payload.flow_m3s", "0.083")),
    (
        "hydraulic_state",
        "missing payload field",
        _edit(_state("edge_state"), "payload.p_from_pa_abs", _DROP),
    ),
    (
        "hydraulic_state",
        "wrong pressure basis",
        _edit(_state("node_state"), "payload.pressure_basis", "Pa_gauge"),
    ),
    (
        "hydraulic_state",
        "signal source not the placeholder",
        _edit(_state("protection_state"), "payload.signal_source", "measured"),
    ),
    (
        "hydraulic_state",
        "unknown protection state",
        _edit(_state("protection_state"), "payload.state", "TRIPPED"),
    ),
    (
        "hydraulic_state",
        "unknown phase status",
        _edit(_state("pump_state"), "payload.phase_validity_status", "MAYBE"),
    ),
    (
        "hydraulic_state",
        "unknown roof state",
        _edit(_state("tank_state"), "payload.roof_state", "sunk"),
    ),
    ("solver_diagnostics", "negative iterations", _edit(DIAG, "iterations", -1)),
    (
        "hydraulic_state",
        "old process-level name",
        _edit(
            _edit(_state("protection_state"), "payload.true_level_m", _DROP),
            "payload.process_level_m",
            9.0,
        ),
    ),
    ("solver_diagnostics", "unknown flow model", _edit(DIAG, "flow_model", "steady")),
    ("solver_diagnostics", "window ids as text", _edit(DIAG, "active_validity_window_ids", "VW-1")),
    ("solver_diagnostics", "old ratio field", _edit(DIAG, "quasi_steady_ratio", 1.0)),
    ("boundary_state", "factor below the clip", _edit(BOUNDARY, "downstream_factor", 0.5)),
    ("boundary_state", "factor above the clip", _edit(BOUNDARY, "downstream_factor", 1.3)),
    ("boundary_state", "unknown stratum", _edit(BOUNDARY, "atmosphere_stratum", "mountain")),
    ("boundary_state", "missing log factor", _edit(BOUNDARY, "log_downstream_factor", _DROP)),
    ("validity_windows", "no reason", _edit(WINDOW, "reason", _DROP)),
    ("validity_windows", "unknown reason", _edit(WINDOW, "reason", "because")),
    ("validity_windows", "unknown kind", _edit(WINDOW, "kind", "valve_leak")),
    ("validity_windows", "open window", _edit(WINDOW, "t_end_s", None)),
    ("episode", "unknown stratum", _edit(EPISODE, "atmosphere_stratum", "mountain")),
    ("episode", "unknown volatility class", _edit(EPISODE, "volatility_class", "RVP_12")),
    ("episode", "windows without reason", _edit(EPISODE, "validity_windows", [{"window_id": "x"}])),
    ("mass_ledger", "unknown scope", _edit(LEDGER, "scope", "TK-104")),
    ("mass_ledger", "missing residual", _edit(LEDGER, "residual_kg", _DROP)),
    ("events", "unknown event type", _edit(EVENT, "event_type", "fault_onset")),
    ("events", "unknown actor", _edit(EVENT, "actor", "agent")),
    ("events", "negative sequence", _edit(EVENT, "sequence_index", -1)),
    ("episode", "short hash", _edit(EPISODE, "config_hash", "abc")),
    ("episode", "pipe inventory not constant", _edit(EPISODE, "pipe_inventory_constant", False)),
    ("episode", "unreleased tier", _edit(EPISODE, "dataset_tier", "production_candidate")),
    ("episode", "unknown status", _edit(EPISODE, "status", "running")),
    ("episode", "fault ids absent", _edit(EPISODE, "fault_instance_ids", _DROP)),
    ("fault_spec", "unknown variant", _edit(FAULT_SPEC, "variant", "pinhole")),
    ("fault_spec", "unknown field", {**FAULT_SPEC, "severity_label": "high"}),
    ("fault_spec", "severity above one", _edit(FAULT_SPEC, "peak_severity", 1.5)),
    ("fault_spec", "ramp of zero", _edit(FAULT_SPEC, "ramp_s", 0.0)),
    ("simulation_rejected", "unknown gate", _edit(REJECTED, "gate", "SG9")),
    ("simulation_rejected", "empty parameter", _edit(REJECTED, "parameter", "")),
    ("simulation_rejected", "no gate", _edit(REJECTED, "gate", _DROP)),
]


@pytest.mark.parametrize(
    ("schema", "name", "doc"), POSITIVE, ids=[f"{s}:{n}" for s, n, _ in POSITIVE]
)
def test_valid_rows_are_accepted(schema: str, name: str, doc: Doc) -> None:
    assert validator(schema).is_valid(doc)


@pytest.mark.parametrize(
    ("schema", "name", "doc"), NEGATIVE, ids=[f"{s}:{n}" for s, n, _ in NEGATIVE]
)
def test_invalid_rows_are_rejected(schema: str, name: str, doc: Doc) -> None:
    assert not validator(schema).is_valid(doc)


@pytest.mark.parametrize("schema", PROPOSED_SCHEMA_NAMES)
def test_each_schema_has_positive_and_negative_cases(schema: str) -> None:
    assert any(s == schema for s, _, _ in POSITIVE) and any(s == schema for s, _, _ in NEGATIVE)


@pytest.mark.parametrize("schema", PROPOSED_SCHEMA_NAMES)
def test_each_schema_is_a_marked_proposal(schema: str) -> None:
    doc = load_schema(schema)
    assert doc["x-status"] == "backend-proposed" and doc["$id"] == f"urn:verum:{schema}:0.7.0"
    assert doc["properties"]["schema_version"]["pattern"] == "^0\\.7\\.[0-9]+$"


def test_every_record_type_has_a_payload_definition() -> None:
    schema = load_schema("hydraulic_state")
    assert set(schema["$defs"]) == set(PAYLOADS) == set(schema["properties"]["record_type"]["enum"])
