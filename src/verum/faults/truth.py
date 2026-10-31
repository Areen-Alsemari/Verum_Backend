"""Hidden fault-truth rows and instance identifiers of an episode.

One row per fault follows the audited fault-truth schema, which is not modified. The instance
identifier is built from the episode and the fault index, so no scenario name or seed enters it. The
mechanism names the variant and, for a valve restriction, its mode; the mode and the activity are
also listed in the episode record because the vendored schema stays as it is. The physical parameter
is the one the injector changes, with its baseline value and its value at severity one. Rows are
hidden truth and are never served.

See D60 to D65.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from verum.faults import spec as fs

SCHEMA_VERSION = "0.5.0"

# (physical parameter, unit, baseline value, mapping text, decision) by fault type and variant
PARAMETERS: dict[tuple[str, str], tuple[str, str, float, str, str]] = {
    (fs.LEAK, "orifice"): ("leak_area", "m2", 0.0, "A(s) = s A1", "D60"),
    (fs.RESTRICTION, "restriction"): (
        "valve_opening_ceiling", "1", 1.0, "ceiling(s) = 1 - s (1 - a1)", "D61",
    ),
    (fs.PUMP, "head_scale"): ("pump_head_scale", "1", 1.0, "scale(s) = 1 - s (1 - h1)", "D62"),
    (fs.SENSOR, "bias"): ("reading_offset_fraction_of_span", "1", 0.0, "offset(s) = s b1", "D63"),
    (fs.SENSOR, "drift"): (
        "reading_drift_fraction_of_span_per_hour", "1/h", 0.0, "offset(t) = d1 (t - t_on)", "D63",
    ),
    (fs.SENSOR, "stuck"): ("reading_frozen", "1", 0.0, "reading(t) = reading(t_on)", "D63"),
    (fs.MISROUTING, "closed_but_open"): (
        "valve_opening_floor", "1", 0.0, "floor(s) = s", "D64",
    ),
    (fs.MISROUTING, "open_but_stuck"): (
        "valve_opening_ceiling", "1", 1.0, "ceiling(s) = 1 - s (1 - a1)", "D64",
    ),
}  # fmt: skip


def parameter_value(spec: fs.FaultSpec, t: float) -> float:
    """The physical parameter of a fault at time ``t``: its baseline plus the severity times the
    difference between its value at severity one and its baseline."""
    base = PARAMETERS[(spec.fault_type, spec.variant)][2]
    return base + spec.severity(t) * (spec.magnitude - base)


def parameter_name(spec: fs.FaultSpec) -> tuple[str, str]:
    """Name and unit of the physical parameter that a fault changes."""
    name, unit = PARAMETERS[(spec.fault_type, spec.variant)][:2]
    return name, unit


def instance_ids(episode_id: str, specs: Sequence[fs.FaultSpec]) -> list[str]:
    return [f"FI-{episode_id}-{i:02d}" for i in range(len(specs))]


def _param(value: float, unit: str, decision: str) -> dict[str, Any]:
    return {
        "value": value, "unit": unit, "status": "provisional", "evidence_tag": "SIM",
        "provenance_id": f"VERUM-DD-{decision}-v1.0",
    }  # fmt: skip


def _mechanism(spec: fs.FaultSpec) -> str:
    return spec.variant if spec.fault_mode is None else f"{spec.variant}_{spec.fault_mode}"


def fault_truth_rows(episode_id: str, specs: Sequence[fs.FaultSpec]) -> list[dict[str, Any]]:
    rows = []
    for ident, spec in zip(instance_ids(episode_id, specs), specs, strict=True):
        name, unit, base, mapping, decision = PARAMETERS[(spec.fault_type, spec.variant)]
        location = None
        if spec.fault_type == fs.LEAK:
            location = {"edge_id": spec.asset_id, "fraction": spec.position}
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "dataset": "fault_truth",
            "episode_id": episode_id,
            "fault_type": spec.fault_type,
            "fault_instance_id": ident,
            "causal_parent_fault_instance_id": None,
            "asset_id": spec.asset_id,
            "location": location,
            "onset_t_sim_s": spec.onset_s,
            "mechanism": _mechanism(spec),
            "mechanism_status": "provisional",
            "severity_trajectory": {
                "type": "piecewise_linear",
                "time_basis": "seconds_since_onset",
                "knots": spec.knots(),
                "interpolation": "linear",
                "outside_support": "hold_last",
            },
            "physical_parameter_modified": {
                "name": name,
                "unit": unit,
                "baseline_value": _param(base, unit, decision),
                "fault_value_at_severity_one": _param(spec.magnitude, unit, decision),
                "mapping": mapping,
            },
            "conserved_quantity_effects": (
                [{"quantity": "liquid_mass", "effect": "sink", "ledger_line": "spill"}]
                if spec.fault_type == fs.LEAK
                else []
            ),
            "hidden": True,
        })  # fmt: skip
    return rows
