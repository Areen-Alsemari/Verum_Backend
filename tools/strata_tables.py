"""Pumping-minimum tables per atmosphere and volatility class, and the summary tables of the report.

Inputs: the plant model. Outputs: ``config/pumping_minimum_levels_<atmosphere>_<class>_fd0p8.json``
(only with ``--write``), ``local/results/strata_tables.md`` and a printed comparison of the
computed tables with those in ``config/``. Run as ``python tools/strata_tables.py [--write]
[--profile v2]``; with ``--profile v2`` the factor is the worst case of decision D73 (the lower
bound in ``config/sim.json``), the files are ``..._fd0p6502.json`` (new files, decision D51), and
the output is ``local/results/strata_tables_v2.md`` with the change against the v1 tables.
Assumptions: delivery from one tank with pump A at the worst-case downstream factor 0.8; a cell is
the lowest tank level in 1.8 to 12 m that passes the phase and NPSH screen, found by bisection to
1e-5 m, and 'never' (an unresolved record) if no level passes; reference initial levels 9, 7 and 5 m
for TK-101, TK-102 and TK-103.
Source: ``docs/design_decisions.md`` D7, D24, D46, D51, D52 (grid and baseline), D73; serves the
tables of the Phase 5b and Phase 6b reports.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir
from verum.graph import Lineup
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    SteadyInputs,
    load_boundary_law_coefficient,
)
from verum.hydraulics.pumping_minimum import stratum_filename
from verum.sim.config import load_sim_config

TANKS = ("TK-101", "TK-102", "TK-103")
INITIAL = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
PROFILES = ("pipe_only", "reference_fittings")
TEMPS = (25.0, 35.0, 40.0, 45.0)
COEFFS = (2.5, 4.0, 6.0)
ATMOSPHERES = ("coastal", "inland")
VOLATILITY = ("RVP_9_0", "RVP_9_5", "RVP10")
SOURCE = "tools/strata_tables.py"
NEVER_REASON = "no level in the normal range 1.8 to 12 m passes the phase and NPSH screen"
Levels = dict[str, dict[str, dict[str, dict[str, dict[str, Any]]]]]


def passes(
    model: HydraulicModel,
    vol: str,
    tank: str,
    level: float,
    profile: str,
    temp: float,
    coeff: float,
    f_d: float = 0.8,
) -> bool:
    n = tank[3:]
    law = load_boundary_law_coefficient(profile).value * f_d
    inputs = SteadyInputs(
        Lineup.of({f"XV-S{n}", "XV-PAI", "XV-PAO"}, {"P-101A"}),
        {tank: level},
        vol,
        temp,
        fitting_profile=profile,
        delivery=DeliveryBoundary(law_coefficient_m=law),
        npsh3_coefficient_m=coeff,
    )
    return model.solve(inputs).phase.status == "OK"


def minimum(
    model: HydraulicModel,
    vol: str,
    tank: str,
    profile: str,
    temp: float,
    coeff: float,
    f_d: float = 0.8,
) -> float | None:
    """Lowest passing level in 1.8 to 12 m, or None if none passes."""
    if passes(model, vol, tank, 1.8, profile, temp, coeff, f_d):
        return 1.8
    if not passes(model, vol, tank, 12.0, profile, temp, coeff, f_d):
        return None
    lo, hi = 1.8, 12.0
    while hi - lo > 1e-5:
        mid = (lo + hi) / 2
        lo, hi = (
            (lo, mid) if passes(model, vol, tank, mid, profile, temp, coeff, f_d) else (mid, hi)
        )
    return round(hi + 5e-5, 4)


def record(value: float | None, provenance: str = "VERUM-PHASE5-STRATA-FD0P8") -> dict[str, Any]:
    if value is None:
        return {
            "value": None, "unit": "m", "status": "unresolved", "evidence_tag": "OPEN",
            "unresolved_reason": NEVER_REASON,
        }  # fmt: skip
    return {
        "value": value, "unit": "m", "status": "provisional", "evidence_tag": "CALC",
        "provenance_id": provenance,
    }  # fmt: skip


def table(model: HydraulicModel, vol: str, f_d: float = 0.8) -> Levels:
    levels: Levels = {}
    provenance = (
        "VERUM-PHASE5-STRATA-FD0P8"
        if f_d == 0.8
        else f"VERUM-PHASE6B-STRATA-FD{f_d:g}".replace(".", "P")
    )
    for tank in TANKS:
        for temp in TEMPS:
            for profile in PROFILES:
                for coeff in COEFFS:
                    cell = record(minimum(model, vol, tank, profile, temp, coeff, f_d), provenance)
                    levels.setdefault(tank, {}).setdefault(f"{temp:g}", {}).setdefault(profile, {})[
                        f"{coeff:g}"
                    ] = cell
    return levels


def document(
    atmosphere: str, vol: str, patm: float, levels: Levels, f_d: float = 0.8
) -> dict[str, Any]:
    decisions = "D24 v2, D46 v3, D51" if f_d == 0.8 else "D24 v2, D46 v3, D51, D73"
    return {
        "schema_version": "1.0.0",
        "label": f"atmosphere {atmosphere}, volatility class {vol}, downstream factor {f_d:g} "
        f"(decisions {decisions})",
        "description": "Pumping-minimum tank level of a delivery computed at the worst-case "
        f"downstream factor f_d = {f_d:g}.",
        "atmosphere_stratum": atmosphere,
        "volatility_class": vol,
        "downstream_factor": f_d,
        "atmosphere_pa_abs": patm,
        "source": SOURCE,
        "levels": levels,
    }


def value(levels: Levels, tank: str, temp: float) -> float | None:
    v = levels[tank][f"{temp:g}"]["reference_fittings"]["4"]["value"]
    return None if v is None else float(v)


def fmt(v: float | None) -> str:
    return "never" if v is None else f"{v:.3f}"


def markdown(results: dict[tuple[str, str], Levels], f_d: float = 0.8) -> list[str]:
    head = "| atmosphere | tank | 25 C | 35 C | 40 C | 45 C |"
    out = [f"# Strata and volatility tables (f_d = {f_d:g})", ""]
    out += ["## Baseline: RVP_9_0, NPSH3 4 m, reference_fittings: minimum level (m)", "", head]
    out += ["| --- | --- | --- | --- | --- | --- |"]
    for atm in ATMOSPHERES:
        for tank in TANKS:
            row = " | ".join(fmt(value(results[(atm, "RVP_9_0")], tank, t)) for t in TEMPS)
            out.append(f"| {atm} | {tank} | {row} |")
    for vol in ("RVP_9_0", "RVP10"):
        title = f"## Reference initial levels 9 / 7 / 5 m ({vol}, NPSH3 4 m, reference_fittings)"
        out += ["", title + ": pass (P) or fail (F) per tank", ""]
        out += ["| atmosphere | 25 C | 35 C | 40 C | 45 C |", "| --- | --- | --- | --- | --- |"]
        for atm in ATMOSPHERES:
            cells = [marks(results[(atm, vol)], t) for t in TEMPS]
            out.append(f"| {atm} | " + " | ".join(cells) + " |")
    out += ["", "## RVP10: minimum level (m), NPSH3 4 m, reference_fittings", "", head]
    out += ["| --- | --- | --- | --- | --- | --- |"]
    for atm in ATMOSPHERES:
        for tank in TANKS:
            row = " | ".join(fmt(value(results[(atm, "RVP10")], tank, t)) for t in TEMPS)
            out.append(f"| {atm} | {tank} | {row} |")
    out += ["", "## Number of 'never' cells (of 72 per file: 3 tanks x 4 temperatures x 2 profiles"]
    out[-1] += " x 3 NPSH3 coefficients)"
    out += [""]
    out += ["| volatility | coastal | inland | total (of 144) |", "| --- | --- | --- | --- |"]
    for vol in VOLATILITY:
        n = {atm: never(results[(atm, vol)]) for atm in ATMOSPHERES}
        out.append(f"| {vol} | {n['coastal']} | {n['inland']} | {sum(n.values())} |")
    return out


def marks(levels: Levels, temp: float) -> str:
    """Pass (P) or fail (F) of each reference initial level at one temperature."""
    parts = []
    for tank in TANKS:
        m = value(levels, tank, temp)
        parts.append(f"{tank[3:]}:{'P' if m is not None and INITIAL[tank] >= m else 'F'}")
    return " ".join(parts)


def never(levels: Levels) -> int:
    return sum(
        1
        for per_tank in levels.values()
        for per_temp in per_tank.values()
        for per_profile in per_temp.values()
        for cell in per_profile.values()
        if cell["value"] is None
    )


def compare_with_config(atmosphere: str, vol: str, new: dict[str, Any]) -> bool:
    """True if the stored table has the same levels (the source label is not compared)."""
    path = config_dir() / stratum_filename(atmosphere, vol)
    old = json.loads(path.read_text(encoding="utf-8"))
    return bool(old["levels"] == new["levels"])


def change_against_v1(results: dict[tuple[str, str], Levels]) -> list[str]:
    """Decision D73: how the pumping minimum rises from f_d = 0.8 to the v2 worst case."""
    out = ["", "## Change against the tables at f_d = 0.8", ""]
    out += ["| atmosphere | volatility | cells | changed | newly never | largest rise (m) |"]
    out += ["| --- | --- | --- | --- | --- | --- |"]
    for (atm, vol), new in sorted(results.items()):
        old = json.loads((config_dir() / stratum_filename(atm, vol)).read_text("utf-8"))["levels"]
        cells = changed = newly = 0
        rise = 0.0
        for tank, per_temp in new.items():
            for temp, per_profile in per_temp.items():
                for profile, per_coeff in per_profile.items():
                    for coeff, cell in per_coeff.items():
                        before, after = old[tank][temp][profile][coeff]["value"], cell["value"]
                        cells += 1
                        if before != after:
                            changed += 1
                        if before is not None and after is None:
                            newly += 1
                        elif before is not None and after is not None:
                            rise = max(rise, after - before)
        out.append(f"| {atm} | {vol} | {cells} | {changed} | {newly} | {rise:.4f} |")
    return out


def main(write: bool, profile: str = "v1") -> None:
    f_d = 0.8 if profile == "v1" else load_sim_config()["demand_total_factor_min_v2"]
    base = HydraulicModel.load()
    results: dict[tuple[str, str], Levels] = {}
    for atm in ATMOSPHERES:
        model = base.for_stratum(atm)
        for vol in VOLATILITY:
            levels = table(model, vol, f_d)
            results[(atm, vol)] = levels
            doc = document(atm, vol, model.patm, levels, f_d)
            if profile == "v1":
                same = compare_with_config(atm, vol, doc)
                print(atm, vol, "same levels as config:", same, flush=True)
            if write:
                path = Path("config") / stratum_filename(atm, vol, profile)
                path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    lines = markdown(results, f_d)
    if profile == "v2":
        lines += change_against_v1(results)
    name = "strata_tables.md" if profile == "v1" else "strata_tables_v2.md"
    Path("local/results", name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main("--write" in sys.argv, "v2" if "v2" in sys.argv else "v1")
