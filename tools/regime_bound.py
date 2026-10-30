"""Pump-domain margin over the downstream factor range of profile v2 and its lower bound.

Inputs: the plant model. Outputs: ``local/results/regime_bound.md`` and ``regime_bound.json``, and
a printed lower bound of the downstream factor. Run as ``python tools/regime_bound.py``.
Assumptions: delivery from one tank with one duty pump at the reference_fittings profile (the
profile of episodes); the pump flow is the steady flow at the factor and tank level; the margin
is the pump-domain limit Q/s = 350 m3/h minus the flow; the bound is the smallest factor at or
above 0.6 whose largest flow over every stratum, temperature, tank, pump and level in 1.8 to
12 m is at most the limit minus 5 m3/h (decision D73); the minimum stable flow is 90 m3/h
(decision D49), and the largest factor that keeps it is reported per level.
Source: ``docs/design_decisions.md`` D49, D73; serves the Phase 6b report.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from verum.graph import Lineup
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    SteadyInputs,
    load_boundary_law_coefficient,
)
from verum.hydraulics.errors import HydraulicsError

TANKS = ("TK-101", "TK-102", "TK-103")
PUMPS = ("P-101A", "P-101B")
TEMPS = (25.0, 35.0, 40.0, 45.0)
ATMOSPHERES = ("coastal", "inland")
VOLATILITY = ("RVP_9_0", "RVP_9_5", "RVP10")
PROFILE = "reference_fittings"
LIMIT = 350.0
MARGIN = 5.0
MIN_STABLE = 90.0
LOWER = 0.6
UPPER = 8.0
LEVELS = [1.8 + 0.1 * k for k in range(103)]
LEVELS = [min(round(v, 4), 12.0) for v in LEVELS]


def pump_flow(
    model: HydraulicModel, vol: str, tank: str, pump: str, temp: float, level: float, f_d: float
) -> float | None:
    """Pump flow in m3/h at the factor, or None if the pump is outside its curve."""
    n, side = tank[3:], pump[-1]
    law = load_boundary_law_coefficient(PROFILE).value * f_d
    inputs = SteadyInputs(
        Lineup.of({f"XV-S{n}", f"XV-P{side}I", f"XV-P{side}O"}, {pump}),
        {tank: level},
        vol,
        temp,
        fitting_profile=PROFILE,
        delivery=DeliveryBoundary(law_coefficient_m=law),
    )
    try:
        result = model.solve(inputs)
    except HydraulicsError:
        return None
    return None if result.pump is None else result.pump.flow_m3h


def worst_flow(
    models: dict[str, HydraulicModel], f_d: float, levels: list[float]
) -> dict[str, Any]:
    worst: dict[str, Any] = {"flow": 0.0}
    for atm, model in models.items():
        for vol in VOLATILITY:
            for tank in TANKS:
                for pump in PUMPS:
                    for temp in TEMPS:
                        for level in levels:
                            q = pump_flow(model, vol, tank, pump, temp, level, f_d)
                            q = math.inf if q is None else q
                            if q > worst["flow"]:
                                worst = {
                                    "flow": q, "atmosphere": atm, "volatility": vol, "tank": tank,
                                    "pump": pump, "temperature_c": temp, "level_m": level,
                                }  # fmt: skip
    return worst


def lower_bound(models: dict[str, HydraulicModel]) -> tuple[float, dict[str, Any]]:
    """Smallest factor in [0.6, 1] with the largest flow at most LIMIT - MARGIN."""
    at_low = worst_flow(models, LOWER, [12.0])
    if at_low["flow"] <= LIMIT - MARGIN:
        return LOWER, at_low
    lo, hi = LOWER, 1.0
    while hi - lo > 1e-6:
        mid = 0.5 * (lo + hi)
        ok = worst_flow(models, mid, [12.0])["flow"] <= LIMIT - MARGIN
        lo, hi = (lo, mid) if ok else (mid, hi)
    bound = math.ceil(hi * 1e4) / 1e4
    return bound, worst_flow(models, bound, [12.0])


def upper_limits(model: HydraulicModel) -> list[dict[str, Any]]:
    """Largest factor that keeps the minimum stable flow, per tank and level (coastal, 25 C)."""
    rows = []
    for tank in TANKS:
        for level in (1.8, 4.0, 8.0, 12.0):
            lo, hi = LOWER, 200.0
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                q = pump_flow(model, "RVP_9_0", tank, "P-101A", 25.0, level, mid)
                lo, hi = (mid, hi) if q is not None and q >= MIN_STABLE else (lo, mid)
            rows.append({"tank": tank, "level_m": level, "largest_factor": round(lo, 3)})
    return rows


def margin_table(models: dict[str, HydraulicModel], bound: float) -> list[dict[str, Any]]:
    rows = []
    for f_d in (bound, 0.8, 1.0, 1.25, 2.0, 4.0, 8.0, 10.0):
        w = worst_flow(models, f_d, [12.0])
        rows.append({"f_d": f_d, "largest_flow_m3h": w["flow"], "margin_m3h": LIMIT - w["flow"]})
    return rows


def main() -> None:
    base = HydraulicModel.load()
    models = {a: base.for_stratum(a) for a in ATMOSPHERES}
    bound, at_bound = lower_bound(models)
    at_06 = worst_flow(models, LOWER, [12.0])
    doc = {
        "lower_bound": bound, "at_0p6": at_06, "at_bound": at_bound,
        "upper": upper_limits(models["coastal"]), "margins": margin_table(models, bound),
    }  # fmt: skip
    Path("local/results/regime_bound.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    lines = [
        "# Downstream factor range of profile v2", "",
        f"Largest pump flow at f_d = 0.6 (level 12 m): {at_06['flow']:.2f} m3/h "
        f"({at_06['tank']}, {at_06['pump']}, {at_06['atmosphere']}, {at_06['volatility']}, "
        f"{at_06['temperature_c']:g} C).",
        f"Lower bound of the factor (flow at most {LIMIT - MARGIN:g} m3/h): {bound}.", "",
        "| f_d | largest flow (m3/h) | margin to 350 (m3/h) |", "| --- | --- | --- |",
    ]  # fmt: skip
    lines += [
        f"| {r['f_d']:.4f} | {r['largest_flow_m3h']:.2f} | {r['margin_m3h']:.2f} |"
        for r in doc["margins"]
    ]
    lines += ["", "| tank | level (m) | largest f_d with flow >= 90 m3/h |", "| --- | --- | --- |"]
    lines += [f"| {r['tank']} | {r['level_m']:g} | {r['largest_factor']} |" for r in doc["upper"]]
    Path("local/results/regime_bound.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
