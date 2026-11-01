"""Canonical initial roof-constraint truth for the coupled withdrawal model.

Support elevation is derived from the declared initial liquid level and existing deck draft.
The physical input records a restraint, not a material strength or a secondary seal failure.
All generated cases stay restricted research until the bounded mechanism is qualified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from verum.sim.scenario import Scenario
from verum.tanks.hangup import RoofHangup

MODEL = "held_roof_withdrawal_v1"


def scenario_record(scenario: Scenario) -> dict[str, Any]:
    record = asdict(scenario)
    record["initial"] = {
        "mode": record.pop("initial_mode"), "tank_levels_m": record.pop("tank_levels_m"),
        "receipt_flow_m3h": record.pop("receipt_flow_m3h"),
        "receipt_setpoint_m3h": record.pop("receipt_setpoint_m3h"),
    }
    return record


def constraint_records(constraints: Mapping[str, RoofHangup]) -> dict[str, Any]:
    return {tank: asdict(constraint) for tank, constraint in sorted(constraints.items())}


def truth_rows(
    episode: str, constraints: Mapping[str, RoofHangup], first_index: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (tank, constraint) in enumerate(sorted(constraints.items()), first_index):
        def param(value: float, tag: str) -> dict[str, Any]:
            return {"value": value, "unit": "m", "status": "provisional",
                    "evidence_tag": tag, "provenance_id": "VERUM-DD-D126-v1.0"}

        rows.append({
            "schema_version": "0.5.0", "dataset": "fault_truth", "episode_id": episode,
            "fault_type": "ROOF_LANDING_ABNORMAL", "fault_instance_id": f"FI-{episode}-{index:02d}",
            "causal_parent_fault_instance_id": None, "asset_id": tank, "onset_t_sim_s": 0.,
            "mechanism": MODEL, "mechanism_status": "provisional",
            "severity_trajectory": {"type": "piecewise_linear",
                                    "time_basis": "seconds_since_onset", "knots": [[0., 1.]],
                                    "interpolation": "linear", "outside_support": "hold_last"},
            "physical_parameter_modified": {
                "name": "roof_support_elevation", "unit": "m",
                "baseline_value": param(constraint.base_geometry.support_height_m, "DESIGN"),
                "fault_value_at_severity_one": param(
                    constraint.calibration.support_height_m, "CALC"),
                "mapping": "fixed underside = initial liquid level - design draft; withdrawal only",
            },
            "conserved_quantity_effects": [], "hidden": True,
        })
    return rows
