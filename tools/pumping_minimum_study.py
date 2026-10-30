"""Operating points, loss-multiplier sensitivity and pumping-minimum levels at the reference class.

Delivery is from one tank with pump A at the profile value of the boundary coefficient, with the
reference property class and sea-level atmosphere. A level is the lowest tank level between 1.8 and
12 m that passes the phase and NPSH screen, found by bisection to 1e-5 m, and is recorded as
unresolved if none passes. The monotonicity of the screen in the level is checked on a 0.25 m grid.
The derived levels are written to the configuration.

See D2, D7, D11, D15 and D35.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, HydraulicModel, SteadyInputs
from verum.hydraulics.result import SteadyResult

SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"
TANKS = ("TK-101", "TK-102", "TK-103")
INITIAL = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
PROFILES = ("pipe_only", "reference_fittings")
STRATA = (25.0, 35.0, 45.0)
COEFFS = (2.5, 4.0, 6.0)
NEVER_REASON = "no level in the normal range 1.8 to 12 m passes the phase and NPSH screen"
MODEL = HydraulicModel.load()


def lineup(tank: str) -> Lineup:
    return Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"})


def solve(
    tank: str, level: float, profile: str = "pipe_only", mult: float = 1.0, temp: float = 25.0,
    coeff: float | None = None,
) -> SteadyResult:  # fmt: skip
    inputs = SteadyInputs(
        lineup(tank), {tank: level}, SCENARIO, temp, fitting_profile=profile, k_multiplier=mult,
        delivery=DeliveryBoundary(law_coefficient_m=None), npsh3_coefficient_m=coeff,
    )  # fmt: skip
    return MODEL.solve(inputs)


def passes(tank: str, level: float, profile: str, temp: float, coeff: float) -> bool:
    return solve(tank, level, profile, temp=temp, coeff=coeff).phase.status == "OK"


def minimum(tank: str, profile: str, temp: float, coeff: float) -> float | None:
    if passes(tank, 1.8, profile, temp, coeff):
        return 1.8
    if not passes(tank, 12.0, profile, temp, coeff):
        return None
    lo, hi = 1.8, 12.0
    while hi - lo > 1e-5:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if passes(tank, mid, profile, temp, coeff) else (mid, hi)
    return round(hi + 5e-5, 4)


def operating_points() -> list[dict[str, Any]]:
    rows = []
    for profile in PROFILES:
        for tank in TANKS:
            for label, level in (("initial", INITIAL[tank]), ("1.8 m", 1.8)):
                r = solve(tank, level, profile)
                assert r.pump is not None
                rows.append({
                    "profile": profile, "tank": tank, "level_m": level, "case": label,
                    "flow_m3h": r.pump.flow_m3h, "head_m": r.pump.head_rise_m,
                    "shaft_kw": r.pump.shaft_power_w / 1000,
                    "pt203_barg": r.tap_pressures_pa_gauge["DISTRIBUTION_BOUNDARY"] / 1e5,
                    "pt201_barg": r.tap_pressures_pa_gauge["PUMP_SUCTION_TEE"] / 1e5,
                    "npsha_m": r.phase.npsha_m, "npsh3_m": r.phase.npsh3_m,
                    "ratio": r.phase.margin_ratio, "status": r.phase.status,
                })  # fmt: skip
    return rows


def k_multiplier_sensitivity() -> list[dict[str, Any]]:
    rows = []
    for profile in PROFILES:
        for tank in TANKS:
            for _label, level in (("initial", INITIAL[tank]), ("1.8 m", 1.8)):
                flows = {}
                for m in (0.5, 1.0, 2.0):
                    pump = solve(tank, level, profile, mult=m).pump
                    assert pump is not None
                    flows[m] = pump.flow_m3h
                rows.append({
                    "profile": profile, "tank": tank, "level_m": level, "flows": flows,
                    "delta_half_pct": 100 * (flows[0.5] / flows[1.0] - 1),
                    "delta_double_pct": 100 * (flows[2.0] / flows[1.0] - 1),
                })  # fmt: skip
    return rows


def minimum_table() -> tuple[dict[tuple[str, float, str, float], float | None], int]:
    violations, table = 0, {}
    for tank in TANKS:
        for temp in STRATA:
            for profile in PROFILES:
                for coeff in COEFFS:
                    grid = [passes(tank, 1.8 + 0.25 * i, profile, temp, coeff) for i in range(41)]
                    violations += sum(
                        1 for a, b in zip(grid, grid[1:], strict=False) if a and not b
                    )
                    table[(tank, temp, profile, coeff)] = minimum(tank, profile, temp, coeff)
    return table, violations


def record(value: float | None) -> dict[str, Any]:
    if value is None:
        return {
            "value": None, "unit": "m", "status": "unresolved", "evidence_tag": "OPEN",
            "unresolved_reason": NEVER_REASON,
        }  # fmt: skip
    return {
        "value": value, "unit": "m", "status": "provisional", "evidence_tag": "CALC",
        "provenance_id": "VERUM-PHASE2-STUDY-PUMPING-MINIMUM",
    }  # fmt: skip


def config_document(table: dict[tuple[str, float, str, float], float | None]) -> dict[str, Any]:
    levels: dict[str, Any] = {}
    for (tank, temp, profile, coeff), value in table.items():
        cell = levels.setdefault(tank, {}).setdefault(f"{temp:g}", {}).setdefault(profile, {})
        cell[f"{coeff:g}"] = record(value)
    return {
        "schema_version": "1.0.0",
        "description": "Pumping-minimum tank level: the lowest level in 1.8 to 12 m at which the "
        "solved delivery operating point passes the phase and NPSH screen (margin ratio 1.3). "
        "Separate from, and does not replace, the 1.8 m geometry minimum. Levels are for the duty "
        "pump A with the delivery boundary law of D2 version 3.0.",
        "scenario": SCENARIO,
        "source": "tools/pumping_minimum_study.py; decisions D2 v3.0, D7 v2.0, D11, D15",
        "levels": levels,
    }


def print_tables(points: list[dict[str, Any]], table: dict[Any, float | None]) -> None:
    print("| profile | tank | level m | Q m3/h | head m | shaft kW | PT-203 | PT-201 | status |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for x in points:
        print(
            f"| {x['profile']} | {x['tank']} | {x['level_m']} | {x['flow_m3h']:.2f} | "
            f"{x['head_m']:.3f} | {x['shaft_kw']:.2f} | {x['pt203_barg']:.3f} | "
            f"{x['pt201_barg']:.3f} | {x['status']} |"
        )
    for profile in PROFILES:
        print(f"\n{profile}: minimum level (m) by NPSH3 coefficient 2.5 / 4 / 6 m")
        print("| tank | 25 C | 35 C | 45 C |\n| --- | --- | --- | --- |")
        for tank in TANKS:
            cells = []
            for temp in STRATA:
                vals = [table[(tank, temp, profile, c)] for c in COEFFS]
                cells.append(" / ".join("never" if v is None else f"{v:.3f}" for v in vals))
            print(f"| {tank} | " + " | ".join(cells) + " |")


def main() -> None:
    points = operating_points()
    sensitivity = k_multiplier_sensitivity()
    table, violations = minimum_table()
    print_tables(points, table)
    print(f"\nmonotonicity violations on the 0.25 m grid: {violations}")
    out = {
        "operating_points": points, "k_multiplier": sensitivity,
        "monotonicity_violations_on_0.25_m_grid": violations,
        "pumping_minimum": [
            {"tank": k[0], "temperature_c": k[1], "profile": k[2], "npsh3_coefficient_m": k[3],
             "minimum_level_m": v}
            for k, v in table.items()
        ],
    }  # fmt: skip
    Path("config/pumping_minimum_levels.json").write_text(
        json.dumps(config_document(table), indent=2) + "\n", encoding="utf-8"
    )
    Path("local/results/phase2_studies.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
