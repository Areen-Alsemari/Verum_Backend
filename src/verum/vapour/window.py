"""Complete-input routine estimates for the representative Verum IFRT inventory.

The window binds timestamps, sampled level decreases and explicit equipment classifications.
It rejects missing penetrations, incompatible classes and unsupported operating regimes.
A calculated total retains unresolved uncertainty and is not a calibrated plant prediction.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from verum.contracts import load_topology
from verum.contracts.paths import config_dir
from verum.params import ParamValue, UnresolvedParameter
from verum.provenance import canonical_json, config_hash
from verum.tanks.geometry import load_tank_parameters
from verum.vapour.model import FITTINGS, TANKS
from verum.vapour.routine import (
    RoutineFactors,
    _value,
    cumulative_fall,
    seam_factor,
    standing_components_kg,
    uncontrolled_fitting_factor,
    withdrawal_kg,
)

RIMS = ("mechanical_shoe_shoe_secondary", "mechanical_shoe_rim_secondary")
CLASSES = {
    "access_hatch": {
        "hatch_bolted_gasketed",
        "hatch_unbolted_gasketed",
        "hatch_unbolted_ungasketed",
    },
    "gauge_well": {
        "automatic_float_well_bolted_gasketed",
        "automatic_float_well_unbolted_ungasketed",
        "slotted_guidepole_gasketed",
    },
    "vacuum_breaker": {"vacuum_breaker_weighted_gasketed"},
    "suspension": set(),
}


def _param(parameters: dict[str, Any], name: str) -> ParamValue:
    if name not in parameters:
        raise UnresolvedParameter(f"missing routine input: {name}")
    return ParamValue.from_mapping(parameters[name])


def _inventory(
    rows: list[dict[str, Any]],
    factors: RoutineFactors,
) -> tuple[list[tuple[ParamValue, str]], ParamValue]:
    counts = dict.fromkeys(FITTINGS, 0.0)
    known: list[tuple[ParamValue, str]] = []
    extra = 0.0
    for row in rows:
        group, key = row["group"], row["classification"]
        if group not in counts or not isinstance(row.get("basis"), str) or not row["basis"].strip():
            raise ValueError("every fitting row needs a known inventory group and selection basis")
        count = ParamValue.from_mapping(row["count"])
        n = _value(count, "1", positive=True)
        if not n.is_integer():
            raise ValueError("fitting counts must be integers")
        counts[group] += n
        if key == "uncontrolled_well":
            if row.get("uncontrolled") is not True:
                raise ValueError("uncontrolled correlation requires explicit uncontrolled status")
            extra += n * uncontrolled_fitting_factor(
                _param(row, "exposed_area"),
                _param(row, "well_height"),
                factors,
                uncontrolled=True,
            )
        elif key not in CLASSES[group]:
            raise UnresolvedParameter(f"no matched {group} classification: {key}")
        else:
            known.append((count, key))
    if counts != FITTINGS:
        raise UnresolvedParameter(
            f"complete M1 fitting counts required: {FITTINGS}; received {counts}"
        )
    return known, ParamValue.selected(
        extra, "lbmol/yr", "CALC", "EPA-2026-equation-2-17-explicit-inventory"
    )


def estimate_window(document: dict[str, Any]) -> dict[str, Any]:
    """Estimate one constant-condition, fully floating gasoline window with complete inputs."""
    if document["tank_id"] not in TANKS:
        raise ValueError("tank must exist in the representative facility")
    if any(
        document.get(k) is not True
        for k in (
            "maintained",
            "freely_vented",
            "constant_conditions",
            "roof_follows_liquid",
        )
    ):
        raise ValueError(
            "routine estimate requires declared normal constant freely vented conditions"
        )
    if (
        not isinstance(document.get("property_profile"), str)
        or not document["property_profile"].strip()
    ):
        raise UnresolvedParameter("a named product/property profile is required")
    if any(not isinstance(document.get(k), str) for k in ("window_start_utc", "window_end_utc")):
        raise UnresolvedParameter("both window timestamps must be supplied explicitly")
    times = [
        datetime.fromisoformat(document[k].replace("Z", "+00:00"))
        for k in ("window_start_utc", "window_end_utc")
    ]
    if any(t.utcoffset() is None for t in times):
        raise ValueError("window timestamps must state their UTC offset")
    duration = (times[1] - times[0]).total_seconds()
    factors = RoutineFactors()
    if duration < factors.value("minimum_estimation_days") * 86400.0:
        raise ValueError("routine window must meet the declared minimum 30-day convention")
    inputs = document["parameters"]
    if document.get("level_interpolation") != "piecewise_linear":
        raise ValueError("a piecewise-linear level trajectory must be declared explicitly")
    levels = [(float(t), float(h)) for t, h in document["level_samples_s_m"]]
    # Validate the original numbers before conversion, so boolean samples do not become floats.
    fall = cumulative_fall(document["level_samples_s_m"])
    if levels[0][0] != 0.0 or levels[-1][0] != duration:
        raise ValueError("level samples must cover exactly the requested window")
    maximum_interval = _value(_param(inputs, "maximum_level_interval"), "s", positive=True)
    if any(b[0] - a[0] > maximum_interval for a, b in zip(levels, levels[1:], strict=False)):
        raise ValueError("level recording interval exceeds its declared resolution")
    geometry = load_tank_parameters()
    density = _param(inputs, "liquid_density")
    rho = _value(density, "kg/m3", positive=True)
    threshold = (
        geometry["roof_support_height_m"].value + geometry["roof_areal_mass_kg_m2"].value / rho
    )
    tank = next(t for t in load_topology().tanks if t.tank_id == document["tank_id"])
    minimum = tank.dimensions_m["normal_min_level_m"]
    maximum = tank.dimensions_m["normal_max_level_m"]
    if any(h < threshold or not minimum <= h <= maximum for _, h in levels):
        raise ValueError("routine window leaves the floating normal operating envelope")
    if not isinstance(document.get("seam_basis"), str) or not document["seam_basis"].strip():
        raise UnresolvedParameter("seam construction needs an explicit selection basis")
    rim_key = document["rim_classification"]
    if document.get("rim_fit_class") != "average":
        raise UnresolvedParameter(
            "this register supports only explicitly selected average-fitting seals"
        )
    if rim_key not in RIMS:
        raise UnresolvedParameter("M1 has a secondary seal; its attachment must be classified")
    if not isinstance(document.get("rim_basis"), str) or not document["rim_basis"].strip():
        raise UnresolvedParameter("rim attachment classification needs an explicit basis")
    known, extra = _inventory(document["fittings"], factors)
    rim_factors = RoutineFactors(config_dir() / "extensions" / "ap42_rim_v1.json")
    rim = rim_factors.parameters[rim_key]
    seam = seam_factor(
        document["seam_construction"],
        _param(inputs, "seam_length"),
        ParamValue.selected(
            math.pi * geometry["deck_diameter_m"].value ** 2 / 4,
            "m2",
            "CALC",
            "M1-circular-deck-area",
        ),
        geometry["shell_diameter_m"],
        factors,
    )
    fraction = ParamValue.selected(
        duration / (86400.0 * factors.value("reference_year_days")),
        "1",
        "CALC",
        "D127-window-duration-explicit-365-day-basis",
    )
    result = standing_components_kg(
        _param(inputs, "vapour_pressure"),
        _param(inputs, "atmosphere"),
        _param(inputs, "vapour_molecular_mass"),
        fraction,
        geometry["shell_diameter_m"],
        rim,
        known,
        ParamValue.selected(seam, "lbmol/yr", "CALC", "EPA-2026-equation-2-18"),
        factors,
        maintained=True,
        freely_vented=True,
        continuously_floating=True,
        extra_fitting_coefficient=extra,
    )
    working = withdrawal_kg(
        ParamValue.selected(fall, "m", "CALC", "EPA-2026-equation-2-20-recorded-level-decreases"),
        geometry["shell_diameter_m"],
        density,
        ParamValue.selected(0.0, "m", "DESIGN", "M1-section-3.1-no-internal-columns"),
        document["shell_condition"],
        factors,
    )
    result |= {
        "withdrawal_kg": working,
        "total_kg": result["standing_components_kg"] + working,
        "window_duration_s": duration,
        "window_start_utc": document["window_start_utc"],
        "window_end_utc": document["window_end_utc"],
        "tank_id": document["tank_id"],
        "property_profile": document["property_profile"],
        "recorded_level_fall_m": fall,
        "input_sha256": hashlib.sha256(canonical_json(document).encode()).hexdigest(),
        "config_hash": config_hash(),
        "rim_factor_hash": rim_factors.hash,
        "inventory_completeness": "M1_counts_checked_classifications_caller_declared",
        "geometry_sha256": hashlib.sha256(
            canonical_json(json.loads((config_dir() / "tank_geometry.json").read_text())).encode()
        ).hexdigest(),
        "limits": [
            "representative_M1_geometry_and_mass",
            "classifications_need_review",
            "constant_vapour_properties",
            "sampling_may_miss_unrecorded_cycles",
            "no_landed_or_damaged_roof",
            "not_a_VOC_observation",
        ],
    }
    return result
