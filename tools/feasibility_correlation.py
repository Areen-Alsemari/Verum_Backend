"""Correlation between fluid temperature and initial tank level implied by the feasible band.

Inputs: the stored pumping-minimum tables of the baseline combination (volatility class RVP_9_0,
NPSH3 4 m, reference_fittings, f_d 0.8) for each atmosphere stratum. Outputs: a printed table, per
atmosphere and tank, of the minimum levels at 25, 35, 40 and 45 C, the slope of the minimum level
with temperature and the Pearson correlation of temperature and initial level.
Assumptions: decision D35, the temperature is drawn equally likely from the four strata and the
initial level uniformly from the feasible band between the pumping minimum of that temperature and
12 m, independently otherwise; the correlation is therefore a consequence of the band alone.
Source: ``docs/design_decisions.md`` D35, D51; serves the dataset card.
"""

from __future__ import annotations

import json

import numpy as np

from verum.contracts.paths import config_dir

TEMPS = np.array([25.0, 35.0, 40.0, 45.0])
TANKS = ("TK-101", "TK-102", "TK-103")
TOP_M = 12.0
FLOOR_M = 1.8


def minimum_levels(atmosphere: str, tank: str) -> np.ndarray:
    path = config_dir() / f"pumping_minimum_levels_{atmosphere}_RVP_9_0_fd0p8.json"
    levels = json.loads(path.read_text(encoding="utf-8"))["levels"][tank]
    return np.array(
        [levels[f"{t:g}"]["reference_fittings"]["4"]["value"] for t in TEMPS], dtype=float
    )


def correlation(minimum: np.ndarray) -> float:
    """Pearson correlation of T and the level, level uniform on [minimum(T), 12] m."""
    low = np.maximum(minimum, FLOOR_M)
    mean_level = (low + TOP_M) / 2.0
    variance_in_band = (TOP_M - low) ** 2 / 12.0
    cov = np.mean((TEMPS - TEMPS.mean()) * (mean_level - mean_level.mean()))
    var_t = np.mean((TEMPS - TEMPS.mean()) ** 2)
    var_l = np.mean(variance_in_band) + np.mean((mean_level - mean_level.mean()) ** 2)
    return float(cov / np.sqrt(var_t * var_l))


def main() -> None:
    print("| atmosphere | tank | 25 C | 35 C | 40 C | 45 C | slope m/C | correlation |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for atmosphere in ("coastal", "inland"):
        for tank in TANKS:
            m = minimum_levels(atmosphere, tank)
            slope = float(np.polyfit(TEMPS, m, 1)[0])
            cells = " | ".join(f"{v:.3f}" for v in m)
            print(f"| {atmosphere} | {tank} | {cells} | {slope:.3f} | {correlation(m):.2f} |")


if __name__ == "__main__":
    main()
