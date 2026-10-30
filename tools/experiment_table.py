"""Published-experiment comparison table for rungs R12 and R13 (Jensen et al. 2018).

Inputs: ``tests/data/jensen_2018_experiments.json`` and the test-only valve of
``tests/_experiment_cases.py``. Outputs: ``local/results/experiments.json`` and a printed table of
the engine, the paper's quasi-steady model and the measurement for every checked quantity, with the
deviations in percent; the first ``phase_invalid`` window of each run.
Assumptions: as in ``tests/analytic/test_transient_experiments.py`` (task-statement numbers, not
verified against the paper; fitted closure exponent; Haaland friction in place of Colebrook).
Source: ``docs/design_decisions.md`` D56, D57.
"""

from __future__ import annotations

import json
import sys
from typing import Any

sys.path.insert(0, "tests")

import _experiment_cases as ex  # noqa: E402
from verum.hydraulics import HydraulicModel  # noqa: E402


def dev(a: float, b: float) -> float:
    return 100.0 * (a - b) / b


def r12(model: HydraulicModel, data: dict[str, Any], name: str) -> dict[str, Any]:
    case, pub = data["experiments"][name], data["published_head_at_valve_m"]
    period = 4.0 * case["L_m"] / case["a_m_s"]
    surge = case["a_m_s"] * case["u0_m_s"] / ex.G
    engine, t, h = ex.head_at_valve(model, case, 14.0 * period)
    idx = ex.peaks(t, h, case["H_res_m"], surge)
    out: dict[str, Any] = {"phase_windows": engine.phase.windows, "n_peaks": len(idx)}
    rows = {
        "maximum": (float(h.max()), "paper_quasi_steady_maximum", "measured_maximum"),
        "third": (float(h[idx[2]]), "paper_quasi_steady_third_peak", "measured_third_peak"),
        "tenth": (float(h[idx[9]]), "paper_quasi_steady_tenth_peak", "measured_tenth_peak"),
        "frequency_hz": (ex.frequency_hz(t, idx), "paper_quasi_steady_frequency_hz",
                         "measured_frequency_hz"),
    }  # fmt: skip
    for key, (value, paper_key, meas_key) in rows.items():
        paper, meas = pub[paper_key][name], pub[meas_key][name]
        out[key] = {
            "engine": value, "paper": paper, "measured": meas,
            "dev_vs_paper_percent": dev(value, paper), "dev_vs_measured_percent": dev(value, meas),
        }  # fmt: skip
    out["four_L_over_a_hz"] = case["a_m_s"] / (4.0 * case["L_m"])
    return out


def r13(model: HydraulicModel, data: dict[str, Any], name: str) -> dict[str, Any]:
    case, pub = data["experiments"][name], data["published_head_at_valve_m"]
    engine, t, h = ex.head_at_valve(model, case, 6.0 * 4.0 * case["L_m"] / case["a_m_s"])
    first = engine.phase.windows[0][0] if engine.phase.windows else None
    sel = t < first if first is not None else t > -1
    peak = float(h[sel].max())
    measured = pub["measured_first_peak_exp5_exp6"][name]
    return {
        "first_peak_engine": peak, "t_of_peak_s": float(t[sel][h[sel].argmax()]),
        "measured": measured, "dev_percent": dev(peak, measured), "first_window_s": first,
        "n_windows": len(engine.phase.windows),
    }  # fmt: skip


def main() -> None:
    model, data = HydraulicModel.load(), ex.load()
    out = {n: r12(model, data, n) for n in ("exp1", "exp2", "exp3")}
    out.update({n: r13(model, data, n) for n in ("exp5", "exp6")})
    with open("local/results/experiments.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
