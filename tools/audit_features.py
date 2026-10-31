"""Residual features of the agent-side audit and the calibration of their thresholds.

A run is stored as sums and counts of the observed values in 10 s blocks. From the blocks this
module forms, for windows of 60, 300 and 900 s that end on a 60 s grid, the window mean and the
least-squares slope of every tag, and from them the residual features of a lineup against a
perturbed design model. Thresholds are percentiles of the per-run maximum deviation over healthy
runs. The design pressure and flow come from interpolation tables of the plant model.

See D77 to D81.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from verum.evaluation.agent_audit import (
    GRID_S,
    N_ENDS,
    mass_balance,
    matched_mass_balance,
    window_ends,
    window_stats,
)
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    ReceiptBoundary,
    SteadyInputs,
    load_boundary_law_coefficient,
)
from verum.lineups import load_lineup_table
from verum.rng import RandomStreams
from verum.tanks import load_tank_geometry

STORE = Path("local/results/audit")
TABLES = STORE / "design_tables.npz"
START_S = 180.0
WINDOWS_S = (60, 300, 900)
TANK_TAGS = ("LT-101", "LT-102", "LT-103")
FLAT_TAGS = (
    "FT-001",
    "PT-001",
    "TT-001",
    "TT-101",
    "TT-102",
    "TT-103",
    "PT-201",
    "PT-202A",
    "PT-202B",
    "FT-201",
    "PT-203",
)
CONTINUOUS = (
    "FT-001",
    "PT-001",
    "TT-001",
    "LT-101",
    "TT-101",
    "LT-102",
    "TT-102",
    "LT-103",
    "TT-103",
    "PT-201",
    "PT-202A",
    "PT-202B",
    "FT-201",
    "PT-203",
)
LAYOUT = {  # family -> (lineup mode, delivering tank, receiving tanks)
    "A": ("DELIVER_101_A", "TK-101", ()),
    "B": ("RECEIVE_101", None, ("TK-101",)),
    "C": ("RECEIVE_101_DELIVER_102_A", "TK-102", ("TK-101",)),
    "B2": ("RECEIVE_101_102", None, ("TK-101", "TK-102")),
}
BASE_LEVELS = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
RECEIPT_FLOWS = np.arange(0.0, 701.0, 50.0)
NOMINAL = (1.0, 1.0, 1.0)


def nuisance_draws() -> list[tuple[float, float, float]]:
    """The nominal design and the five perturbed ones: head scale, K multiplier, c multiplier."""
    rng = RandomStreams(20261106).stream("audit_nuisance")
    out = [NOMINAL]
    for _ in range(5):
        head = float(rng.uniform(0.97, 1.03))
        k = math.exp(float(rng.uniform(math.log(0.5), math.log(2.0))))
        c = math.exp(float(rng.uniform(math.log(0.8), math.log(1.25))))
        out.append((head, k, c))
    return out


DRAWS = nuisance_draws()


# --- runs and window statistics ----------
@dataclass
class Run:
    sums: dict[str, np.ndarray]
    counts: dict[str, np.ndarray]
    events: dict[str, list[list[float]]]
    rejected: str | None = None


def load_run(path: Path) -> Run:
    d = np.load(path)
    if "rejected" in d:
        return Run({}, {}, {}, str(d["rejected"]))
    sums = {t: d[f"s_{t}"] for t in CONTINUOUS}
    counts = {t: d[f"c_{t}"] for t in CONTINUOUS}
    return Run(sums, counts, json.loads(str(d["events"])))


# --- design tables ----------
@lru_cache(maxsize=1)
def design() -> tuple[HydraulicModel, Any]:
    model = HydraulicModel.load().for_stratum("coastal")
    return model, load_lineup_table(model.topology)


def solve(fam: str, draw: tuple[float, float, float], levels: dict[str, float], q_in: float) -> Any:
    model, table = design()
    head, k, c = draw
    pump = model.default_pump()
    pump = dataclasses.replace(pump, h0_m=pump.h0_m * head, k_m=pump.k_m * head)
    law = load_boundary_law_coefficient("reference_fittings").value * c
    inputs = SteadyInputs(
        table.mode(LAYOUT[fam][0]).lineup,
        levels,
        "RVP_9_0",
        25.0,
        fitting_profile="reference_fittings",
        k_multiplier=k,
        receipt=ReceiptBoundary(flow_m3h=q_in),
        delivery=DeliveryBoundary(law_coefficient_m=law),
        pump=pump,
    )
    return model.solve(inputs)


def delivery_levels(fam: str) -> np.ndarray:
    return np.arange(4.0, 12.001, 0.1)


def receipt_axes(fam: str) -> list[np.ndarray]:
    axes = [RECEIPT_FLOWS, np.arange(6.0, 11.001, 0.5)]
    if fam == "B2":
        axes.append(np.arange(4.0, 9.001, 0.5))
    return axes


def build_tables() -> dict[str, np.ndarray]:
    """Tables of design delivery flow by level and of design PT-001 by flow and levels."""
    out: dict[str, np.ndarray] = {}
    for d, draw in enumerate(DRAWS):
        for fam, (_mode, deliver, receive) in LAYOUT.items():
            if deliver:
                q = 600.0 if receive else 0.0
                lv = delivery_levels(fam)
                out[f"q_{fam}_{d}"] = np.array(
                    [
                        solve(fam, draw, {**BASE_LEVELS, deliver: float(x)}, q).pump.flow_m3h
                        for x in lv
                    ]
                )
            if receive:
                axes = receipt_axes(fam)
                grid = np.full([len(a) for a in axes], np.nan)
                for idx in np.ndindex(grid.shape):
                    levels = dict(BASE_LEVELS)
                    levels["TK-101"] = float(axes[1][idx[1]])
                    if fam == "B2":
                        levels["TK-102"] = float(axes[2][idx[2]])
                    r = solve(fam, draw, levels, float(axes[0][idx[0]]))
                    grid[idx] = r.tap_pressures_pa_gauge["PIPELINE_RECEIPT_BOUNDARY"] / 1e5
                out[f"p_{fam}_{d}"] = grid
    return out


@lru_cache(maxsize=1)
def tables() -> dict[str, np.ndarray]:
    if not TABLES.exists():
        np.savez_compressed(TABLES, **build_tables())
    d = np.load(TABLES)
    return {k: d[k] for k in d}


def design_flow(fam: str, d: int, level: np.ndarray) -> np.ndarray:
    return np.interp(
        level, delivery_levels(fam), tables()[f"q_{fam}_{d}"], left=np.nan, right=np.nan
    )


@cache
def receipt_interpolator(fam: str, d: int) -> RegularGridInterpolator:
    return RegularGridInterpolator(
        tuple(receipt_axes(fam)), tables()[f"p_{fam}_{d}"], method="cubic", bounds_error=False
    )


def design_pt001(fam: str, d: int, q: np.ndarray, levels: list[np.ndarray]) -> np.ndarray:
    interp = receipt_interpolator(fam, d)
    pts = np.stack([q, *levels], axis=-1)
    return np.asarray(interp(pts))


# --- features ----------
def features(run: Run, fam: str, d: int) -> dict[tuple[int, str], np.ndarray]:
    """Feature series on the 45 window ends, for each window length, under design draw ``d``."""
    model, _ = design()
    rho_g = model.rho * model.g
    head, _k, c_mult = DRAWS[d]
    area = load_tank_geometry().area_m2
    _mode, deliver, receive = LAYOUT[fam]
    pump = model.default_pump()
    law = load_boundary_law_coefficient("reference_fittings").value * c_mult
    ends = window_ends()
    out: dict[tuple[int, str], np.ndarray] = {}
    for length in WINDOWS_S:
        stats = {t: window_stats(run.sums[t], run.counts[t], length) for t in CONTINUOUS}
        mean = {t: stats[t][0] for t in CONTINUOUS}
        slope = {t: stats[t][1] for t in CONTINUOUS}
        valid = ends - length >= START_S
        rows: dict[str, np.ndarray] = {}
        rows["mass_balance"] = mass_balance(
            mean["FT-001"], mean["FT-201"], [slope[t] for t in TANK_TAGS], area
        )
        rows["mass_balance_matched"] = matched_mass_balance(
            (run.sums["FT-001"], run.counts["FT-001"]),
            (run.sums["FT-201"], run.counts["FT-201"]),
            [(run.sums[t], run.counts[t]) for t in TANK_TAGS],
            area,
            length,
        )
        if deliver:
            h = np.array(
                [pump.head_rise_m(q) if np.isfinite(q) else np.nan for q in mean["FT-201"]]
            )
            rows["pump_consistency"] = (mean["PT-202A"] - mean["PT-201"]) * 1e5 - rho_g * head * h
            rows["delivery_law"] = (mean["PT-203"] - 2.0) * 1e5 - rho_g * law * (
                mean["FT-201"] / 300.0
            ) ** 2
            rows["delivery_flow"] = mean["FT-201"] - design_flow(fam, d, mean[f"LT-{deliver[3:]}"])
        if receive:
            lv = [mean[f"LT-{t[3:]}"] for t in receive]
            q = mean["FT-001"]
            p = design_pt001(fam, d, np.where(np.isfinite(q), q, 0.0), lv)
            rows["receipt_law"] = np.where(q > 50.0, (mean["PT-001"] - p) * 1e5, np.nan)
        for tag in CONTINUOUS:
            if tag in TANK_TAGS:
                prev = np.concatenate((np.full(int(length / GRID_S), np.nan), mean[tag]))[:N_ENDS]
                rows[f"trend:{tag}"] = np.where(
                    ends - 2 * length >= START_S, mean[tag] - prev, np.nan
                )
            else:
                rows[f"trend:{tag}"] = slope[tag]
        for name, series in rows.items():
            out[(length, name)] = np.where(valid, series, np.nan)
    return out


def dependent(name: str) -> bool:
    """Whether the feature changes with the design draw."""
    return name in ("pump_consistency", "delivery_law", "delivery_flow", "receipt_law")


def contact_changes(
    events: dict[str, list[list[float]]], onset_s: float
) -> list[tuple[float, str]]:
    """Time and tag of every change of a contact or run status after the onset."""
    out = []
    for tag, rows in events.items():
        before = [v for t, v in rows if t <= onset_s]
        state = before[-1] if before else None
        for t, v in rows:
            if t > onset_s and v != state:
                out.append((t, tag))
                state = v
    return sorted(out)


# --- calibration ----------
