"""Pumping-minimum table for an atmospheric pressure of 94300 Pa, compared with sea level.

The pressure is a standard-atmosphere estimate for a site near 600 m elevation, with the elevation
to be confirmed by the team. The table is a sensitivity file that never replaces the sea-level
table, and it uses the same grid and bisection as the pumping-minimum study.

See D7 and D24.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, HydraulicModel, SteadyInputs
from verum.params import ParamValue

SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"
TANKS = ("TK-101", "TK-102", "TK-103")
INITIAL = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
PROFILES = ("pipe_only", "reference_fittings")
STRATA = (25.0, 35.0, 45.0)
COEFFS = (2.5, 4.0, 6.0)
SITE_PA = 94300.0
PROVENANCE = "VERUM-PHASE3-SITE-PRESSURE-SENSITIVITY"
LABEL = (
    "sensitivity for a site near 600 m elevation, standard-atmosphere estimate, "
    "elevation from memory, to be confirmed by the team"
)
NEVER_REASON = "no level in the normal range 1.8 to 12 m passes the phase and NPSH screen"


def site_model(sea: HydraulicModel) -> HydraulicModel:
    params = dict(sea.config.parameters)
    params["atmosphere_pa_abs"] = ParamValue.selected(SITE_PA, "Pa", "SIM", PROVENANCE)
    config = dataclasses.replace(sea.config, parameters=params)
    return HydraulicModel(sea.topology, sea.geometry, sea.fluid, config)


def passes(
    model: HydraulicModel, tank: str, level: float, profile: str, temp: float, coeff: float
) -> bool:
    lineup = Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"})
    inputs = SteadyInputs(
        lineup, {tank: level}, SCENARIO, temp, fitting_profile=profile,
        delivery=DeliveryBoundary(), npsh3_coefficient_m=coeff,
    )  # fmt: skip
    return model.solve(inputs).phase.status == "OK"


def minimum(
    model: HydraulicModel, tank: str, profile: str, temp: float, coeff: float
) -> float | None:
    if passes(model, tank, 1.8, profile, temp, coeff):
        return 1.8
    if not passes(model, tank, 12.0, profile, temp, coeff):
        return None
    lo, hi = 1.8, 12.0
    while hi - lo > 1e-5:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if passes(model, tank, mid, profile, temp, coeff) else (mid, hi)
    return round(hi + 5e-5, 4)


def record(value: float | None) -> dict[str, Any]:
    if value is None:
        return {
            "value": None, "unit": "m", "status": "unresolved", "evidence_tag": "OPEN",
            "unresolved_reason": NEVER_REASON,
        }  # fmt: skip
    return {
        "value": value, "unit": "m", "status": "provisional", "evidence_tag": "CALC",
        "provenance_id": PROVENANCE,
    }  # fmt: skip


def compare(
    sea: HydraulicModel, site: HydraulicModel
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sea_levels = json.loads(Path("config/pumping_minimum_levels.json").read_text())["levels"]
    levels: dict[str, Any] = {}
    rows = []
    for tank in TANKS:
        for temp in STRATA:
            for profile in PROFILES:
                for coeff in COEFFS:
                    value = minimum(site, tank, profile, temp, coeff)
                    start = INITIAL[tank]
                    base = sea_levels[tank][f"{temp:g}"][profile][f"{coeff:g}"]["value"]
                    cell = levels.setdefault(tank, {}).setdefault(f"{temp:g}", {})
                    cell.setdefault(profile, {})[f"{coeff:g}"] = record(value)
                    rows.append({
                        "tank": tank, "temperature_c": temp, "profile": profile, "coeff": coeff,
                        "sea_level_m": base, "site_m": value,
                        "pass_1_8_sea": passes(sea, tank, 1.8, profile, temp, coeff),
                        "pass_1_8_site": passes(site, tank, 1.8, profile, temp, coeff),
                        "pass_initial_sea": passes(sea, tank, start, profile, temp, coeff),
                        "pass_initial_site": passes(site, tank, start, profile, temp, coeff),
                    })  # fmt: skip
    return levels, rows


def fmt(v: float | None) -> str:
    return "never" if v is None else f"{v:.3f}"


def markdown(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for profile in PROFILES:
        lines += [
            f"\n{profile}: minimum level (m), NPSH3 2.5 / 4 / 6 m; sea level -> 94300 Pa",
            "| tank | 25 C | 35 C | 45 C |", "| --- | --- | --- | --- |",
        ]  # fmt: skip
        for tank in TANKS:
            cells = []
            for temp in STRATA:
                r = {
                    x["coeff"]: x for x in rows
                    if x["tank"] == tank and x["temperature_c"] == temp and x["profile"] == profile
                }  # fmt: skip
                pairs = [f"{fmt(r[c]['sea_level_m'])}>{fmt(r[c]['site_m'])}" for c in COEFFS]
                cells.append(" / ".join(pairs))
            lines.append(f"| {tank} | " + " | ".join(cells) + " |")
    lines.append("\nCombinations that pass at sea level and fail at 94300 Pa:")
    for key, label in (("1_8", "at 1.8 m"), ("initial", "at the initial level")):
        bad = [x for x in rows if x[f"pass_{key}_sea"] and not x[f"pass_{key}_site"]]
        lines.append(f"- {label}: {len(bad)} of {len(rows)}")
        lines += [
            f"  - {x['tank']} {x['temperature_c']:g} C {x['profile']} NPSH3 {x['coeff']}"
            for x in bad
        ]
    never = [x for x in rows if x["site_m"] is None and x["sea_level_m"] is not None]
    lines.append(f"- minimum level became 'never': {len(never)}")
    lines += [
        f"  - {x['tank']} {x['temperature_c']:g} C {x['profile']} NPSH3 {x['coeff']} "
        f"(was {x['sea_level_m']:.3f} m)" for x in never
    ]  # fmt: skip
    return lines


def main() -> None:
    sea = HydraulicModel.load()
    levels, rows = compare(sea, site_model(sea))
    config = {
        "schema_version": "1.0.0",
        "label": LABEL,
        "description": "Pumping-minimum tank level as in pumping_minimum_levels.json, recomputed "
        "with the atmospheric pressure below. A sensitivity file: it does not replace the "
        "sea-level file.",
        "atmosphere_pa_abs": SITE_PA,
        "scenario": SCENARIO,
        "source": "tools/site_pressure_study.py",
        "levels": levels,
    }
    Path("config/pumping_minimum_levels_site_pressure.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    Path("local/results/site_pressure_study.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    lines = markdown(rows)
    Path("local/results/site_pressure_study.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
