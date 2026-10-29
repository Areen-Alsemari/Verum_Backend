"""Row builders: turn an engine snapshot into the typed truth records.

Inputs: a ``Snapshot`` (state at one instant) and the model. Outputs: row
dictionaries for the hydraulic-state, solver-diagnostic, boundary-state and mass-ledger
datasets.
Key assumptions:
    * Pressures are written in Pa absolute (gauge plus the configured atmosphere);
      a pressure that the solve could not determine is ``null``, never zero.
    * ``side`` is ``null`` for a grid row and ``pre_event`` / ``post_event`` for the
      two rows written at an event time.
    * Protection rows carry ``signal_source = "independent_detector"``: the high-high trip is
      decided on the detector signal of the engine (decision D33), not on the true level.
    * Every row carries ``hidden = true`` and the schema version 0.7.0.

Source: ``revised/05_simulation_validation_dataset.md`` section 7.4.8;
``schemas/hydraulic_state.schema.json`` and the other proposed schemas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from verum.hydraulics import HydraulicModel, SteadyResult
from verum.hydraulics.valves import loss_coefficient

SCHEMA_VERSION = "0.7.0"
SIGNAL_SOURCE = "independent_detector"
# Decision D36 version 2: the tap value of the supply node is the head at the end of E002; the
# observed PT-001 is the start of E002 (edge row of E002, p_from).
ANCHORS = {"PIPELINE_RECEIPT_BOUNDARY": "end_of_E002_lambda_E001_E002"}
CHECK_VALVES = ("CV-PA", "CV-PB")
VALVES = (
    "XV-R000", "XV-R101", "XV-R102", "XV-R103", "XV-S101", "XV-S102", "XV-S103",
    "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO",
)  # fmt: skip
PUMPS = ("P-101A", "P-101B")


@dataclass(frozen=True)
class ValveView:
    alpha: float
    commanded_open: bool
    physically_closed: bool


@dataclass(frozen=True)
class Snapshot:
    t: float
    result: SteadyResult
    volumes: dict[str, float]
    levels: dict[str, float]
    roof: dict[str, str]
    valves: dict[str, ValveView]
    protection: dict[str, tuple[str, bool, float, float]]
    running: frozenset[str]
    iterations: int
    max_residual_kg_s: float
    ledger: dict[str, Any]
    window_ids: tuple[str, ...] = ()
    mode: str = "inactive"
    boundary: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)


def _env(dataset: str, episode: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "dataset": dataset, "episode_id": episode}


def _state_row(
    episode: str,
    snap: Snapshot,
    side: str | None,
    rtype: str,
    element: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = _env("hydraulic_state", episode)
    row.update(
        t_sim_s=snap.t,
        record_type=rtype,
        element_id=element,
        side=side,
        payload=payload,
        hidden=True,
    )
    return row


def _abs(gauge: float | None, patm: float) -> float | None:
    return None if gauge is None else gauge + patm


def hydraulic_rows(
    model: HydraulicModel, episode: str, snap: Snapshot, side: str | None, temperature_k: float
) -> list[dict[str, Any]]:
    r, rows = snap.result, []
    patm = r.atmosphere_pa_abs
    for edge in model.topology.edges:
        q = r.edge_flows_m3s[edge.edge_id]
        ends = r.edge_end_pressures_pa_gauge.get(edge.edge_id)
        payload: dict[str, Any] = {
            "flow_m3s": q,
            "velocity_m_s": q / (math.pi * edge.inner_diameter_m**2 / 4),
            "p_from_pa_abs": _abs(ends[0], patm) if ends else None,
            "p_to_pa_abs": _abs(ends[1], patm) if ends else None,
            "fluid_temperature_K": temperature_k,
        }
        rows.append(_state_row(episode, snap, side, "edge_state", edge.edge_id, payload))
    for node, ref in model.config.tap_reference_edges.items():
        gauge = r.tap_pressures_pa_gauge.get(node)
        payload = {
            "pressure_pa_abs": _abs(gauge, patm),
            "hydraulic_head_m": r.tap_heads_m.get(node, r.node_heads_m.get(node)),
            "pressure_basis": "Pa_abs",
            "reference_edge": ref,
            "anchor": ANCHORS.get(node),
        }
        rows.append(_state_row(episode, snap, side, "node_state", node, payload))
    for tank in model.topology.tank_ids:
        payload = {
            "level_m": snap.levels[tank],
            "volume_m3": snap.volumes[tank],
            "net_inflow_m3s": r.tank_net_inflow_m3s[tank],
            "temperature_K": temperature_k,
            "roof_state": snap.roof[tank],
        }
        rows.append(_state_row(episode, snap, side, "tank_state", tank, payload))
    rows += _valve_rows(model, episode, snap, side)
    rows += _pump_rows(model, episode, snap, side)
    for tank, (state, latched, level, detector_level) in snap.protection.items():
        payload = {
            "state": state,
            "trip_latched": latched,
            "signal_source": SIGNAL_SOURCE,
            "true_level_m": level,
            "independent_level_m": detector_level,
        }
        rows.append(_state_row(episode, snap, side, "protection_state", tank, payload))
    return rows


def _valve_rows(
    model: HydraulicModel, episode: str, snap: Snapshot, side: str | None
) -> list[dict[str, Any]]:
    r, rows = snap.result, []
    c = model.config
    for valve in VALVES:
        view = snap.valves[valve]
        inbound = next((e for e in model.topology.edges if e.to_node == valve), None)
        outbound = next((e for e in model.topology.edges if e.from_node == valve), None)
        dp = None
        if (
            inbound
            and outbound
            and inbound.edge_id in r.edge_end_pressures_pa_gauge
            and outbound.edge_id in r.edge_end_pressures_pa_gauge
        ):
            dp = (
                r.edge_end_pressures_pa_gauge[inbound.edge_id][1]
                - r.edge_end_pressures_pa_gauge[outbound.edge_id][0]
            )
        flow = r.edge_flows_m3s[outbound.edge_id] if outbound else 0.0
        k = (
            None
            if view.alpha <= 0.0
            else loss_coefficient(
                view.alpha, c["valve_full_open_k"], c["valve_alpha_c"], c["valve_rangeability"]
            )
        )
        payload: dict[str, Any] = {
            "element_class": "isolation",
            "commanded_open": view.commanded_open,
            "position_frac": view.alpha,
            "physically_closed": view.physically_closed,
            "flow_m3s": flow,
            "delta_p_pa": dp,
            "check_state": None,
            "k_loss": k,
        }
        rows.append(_state_row(episode, snap, side, "valve_state", valve, payload))
    for check in CHECK_VALVES:
        outbound = next(e for e in model.topology.edges if e.from_node == check)
        inbound = next(e for e in model.topology.edges if e.to_node == check)
        flow = r.edge_flows_m3s[outbound.edge_id]
        dp = None
        if (
            inbound.edge_id in r.edge_end_pressures_pa_gauge
            and outbound.edge_id in r.edge_end_pressures_pa_gauge
        ):
            dp = (
                r.edge_end_pressures_pa_gauge[inbound.edge_id][1]
                - r.edge_end_pressures_pa_gauge[outbound.edge_id][0]
            )
        check_payload: dict[str, Any] = {
            "element_class": "check",
            "commanded_open": None,
            "position_frac": None,
            "physically_closed": None,
            "flow_m3s": flow,
            "delta_p_pa": dp,
            "check_state": "open" if flow > 0 else "closed",
            "k_loss": None,
        }
        rows.append(_state_row(episode, snap, side, "valve_state", check, check_payload))
    return rows


def _pump_rows(
    model: HydraulicModel, episode: str, snap: Snapshot, side: str | None
) -> list[dict[str, Any]]:
    r, rows = snap.result, []
    for pump in PUMPS:
        running = pump in snap.running
        point = r.pump if r.pump is not None and r.pump.pump == pump else None
        payload: dict[str, Any]
        if point is None:
            payload = {
                "run_state": "running" if running else "stopped",
                "speed_ratio": 1.0 if running else 0.0,
                "flow_m3s": 0.0,
                "head_m": None,
                "shaft_power_W": None,
                "NPSHa_m": None,
                "NPSH3_m": None,
                "NPSH_margin_ratio": None,
                "domain_valid": True,
                "phase_validity_status": "NOT_APPLICABLE",
            }
        else:
            ph = r.phase
            payload = {
                "run_state": "running",
                "speed_ratio": point.speed_ratio,
                "flow_m3s": point.flow_m3h / 3600.0,
                "head_m": point.head_rise_m,
                "shaft_power_W": point.shaft_power_w,
                "NPSHa_m": ph.npsha_m,
                "NPSH3_m": ph.npsh3_m,
                "NPSH_margin_ratio": ph.margin_ratio,
                "domain_valid": True,
                "phase_validity_status": ph.status,
            }
        rows.append(_state_row(episode, snap, side, "pump_state", pump, payload))
    return rows


def diagnostic_row(episode: str, snap: Snapshot, side: str | None) -> dict[str, Any]:
    row = _env("solver_diagnostics", episode)
    row.update(
        t_sim_s=snap.t,
        side=side,
        iterations=snap.iterations,
        max_mass_residual_kg_s=snap.max_residual_kg_s,
        convergence_ok=True,
        phase_validity_status=snap.result.phase.status if snap.result.pump else "NOT_APPLICABLE",
        domain_valid=True,
        flow_model=snap.mode,
        active_validity_window_ids=list(snap.window_ids),
        hidden=True,
    )
    return row


def boundary_row(episode: str, snap: Snapshot, side: str | None) -> dict[str, Any]:
    row = _env("boundary_state", episode)
    row.update(t_sim_s=snap.t, side=side, **snap.boundary, hidden=True)
    return row


def ledger_rows(episode: str, snap: Snapshot, side: str | None) -> list[dict[str, Any]]:
    led, rows = snap.ledger, []
    base = _env("mass_ledger", episode)
    rows.append(
        {
            **base,
            "t_sim_s": snap.t,
            "side": side,
            "scope": "network",
            "liquid_kg": led["liquid_total_kg"],
            "cumulative_received_kg": led["received_kg"],
            "cumulative_delivered_kg": led["delivered_kg"],
            "cumulative_spill_kg": 0.0,
            "residual_kg": led["residual_kg"],
            "tolerance_kg": led["tolerance_kg"],
            "closed": led["closed"],
            "hidden": True,
        }
    )
    for tank, mass in led["tank_kg"].items():
        rows.append(
            {
                **base,
                "t_sim_s": snap.t,
                "side": side,
                "scope": tank,
                "liquid_kg": mass,
                "cumulative_received_kg": None,
                "cumulative_delivered_kg": None,
                "cumulative_spill_kg": 0.0,
                "residual_kg": None,
                "tolerance_kg": None,
                "closed": None,
                "hidden": True,
            }
        )
    return rows
