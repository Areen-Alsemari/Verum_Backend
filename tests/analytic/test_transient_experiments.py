"""Rungs R12 and R13: the transient engine against the water-hammer experiments of Jensen et al.

Inputs: ``tests/data/jensen_2018_experiments.json`` (parameters and published results, supplied in
the task statement and NOT verified against the paper, whose full text could not be retrieved) and a
test-only valve (``tests/_experiment_cases.py``). Outputs: pass/fail.

Setup: one reservoir, one pipe, the valve at the end; the wave speed is set directly; 24 reaches
with Courant number one; quasi-steady Darcy friction (Haaland with the laminar blend, whereas the
paper uses Colebrook, and the first-order scheme with friction at the old point). The closure
exponent m is a fitted value of the authors, not a measurement.

Acceptance tolerances, fixed BEFORE the first run and not to be widened:
    R12, experiments 1 to 3, against the quasi-steady model of the paper: maximum head at the valve
    within 1 percent; third peak within 2 percent; tenth peak within 3 percent; frequency (mean
    over peaks 1 to 10) within 1 percent. Against measurement: the maximum within 3.5 percent.
    Later peaks and the frequency against measurement are reported by
    ``tools/experiment_table.py`` and are not tested: quasi-steady friction is known to
    overestimate the decay of the later peaks, so the engine is expected to lie above the measured
    third and tenth peaks. No ``phase_invalid`` window is expected in experiments 1 to 3.
    R13, experiments 5 and 6, first peak only, up to the first ``phase_invalid`` window: within 5
    percent of the measured first peak. The window is expected after the first peak (the lower
    reflection takes the head below the vapor pressure), and its time is reported.
A tolerance that is missed is a finding to investigate; it is not widened to pass.

Result of the first run: all tolerances are met except the frequency of experiment 2 against the
paper (-1.7 percent). The engine's value equals the closed form a / (4 L) to 0.1 percent for all
three experiments, so the difference lies in the published figure or in a parameter of the task
statement. The comparison with the paper's frequency is therefore made for experiments 1 and 3
(1 percent), and for experiment 2 two tests state the finding: the engine equals a / (4 L) within
0.5 percent, and the published value lies 1.5 to 1.8 percent above a / (4 L). The 1 percent
tolerance was not widened.

Independence: the published results come from a different code and from measurement; the engine
shares nothing with them except the equations of the valve. This checks the numerical method for
these pipes, not the facility model.

Source: ``docs/design_decisions.md`` D56; Jensen et al. 2018, Fluids 3(3) 64.
"""

from __future__ import annotations

import numpy as np
import pytest

import _experiment_cases as ex
from verum.hydraulics import HydraulicModel
from verum.transient import TransientEngine

DATA = ex.load()
PUB = DATA["published_head_at_valve_m"]
SURGE = {k: v["a_m_s"] * v["u0_m_s"] / ex.G for k, v in DATA["experiments"].items()}


def run(
    model: HydraulicModel, name: str, periods: float = 14.0
) -> tuple[TransientEngine, np.ndarray, np.ndarray, np.ndarray]:
    case = DATA["experiments"][name]
    period = 4.0 * case["L_m"] / case["a_m_s"]
    engine, t, h = ex.head_at_valve(model, case, periods * period)
    idx = ex.peaks(t, h, case["H_res_m"], SURGE[name])
    return engine, t, h, idx


@pytest.mark.parametrize("name", ["exp1", "exp2", "exp3"])
def test_r12_peaks_against_the_paper_quasi_steady_model(model: HydraulicModel, name: str) -> None:
    engine, _t, h, idx = run(model, name)
    assert len(idx) >= 10
    assert engine.phase.windows == []
    assert h.max() == pytest.approx(PUB["paper_quasi_steady_maximum"][name], rel=0.01)
    assert h[idx[2]] == pytest.approx(PUB["paper_quasi_steady_third_peak"][name], rel=0.02)
    assert h[idx[9]] == pytest.approx(PUB["paper_quasi_steady_tenth_peak"][name], rel=0.03)


@pytest.mark.parametrize("name", ["exp1", "exp3"])
def test_r12_frequency_against_the_paper_quasi_steady_model(
    model: HydraulicModel, name: str
) -> None:
    _engine, t, _h, idx = run(model, name)
    published = PUB["paper_quasi_steady_frequency_hz"][name]
    assert ex.frequency_hz(t, idx) == pytest.approx(published, rel=0.01)


def test_r12_the_published_frequency_of_experiment_2_is_above_the_closed_form() -> None:
    """Documented data: the paper's 3.32 Hz is 1.5 to 1.8 percent above a / (4 L) = 1282 /
    (4 x 98.11) = 3.267 Hz for the stated length and wave speed, while its frequencies for
    experiments 1 and 3 agree with a / (4 L) to 0.1 percent. A quasi-steady friction model does
    not raise the fundamental frequency of a reservoir-valve pipe above a / (4 L), so the figure
    comes from a parameter of the paper's run that the task statement does not give or from the
    way the frequency was read. This test records the data; it does not test the engine."""
    case = DATA["experiments"]["exp2"]
    closed_form = case["a_m_s"] / (4.0 * case["L_m"])
    excess = PUB["paper_quasi_steady_frequency_hz"]["exp2"] / closed_form - 1.0
    assert 0.015 <= excess <= 0.018
    for other in ("exp1", "exp3"):
        c = DATA["experiments"][other]
        ratio = PUB["paper_quasi_steady_frequency_hz"][other] / (c["a_m_s"] / (4.0 * c["L_m"]))
        assert abs(ratio - 1.0) < 0.001


@pytest.mark.parametrize("name", ["exp1", "exp2", "exp3"])
def test_r12_frequency_is_the_closed_form_four_l_over_a(model: HydraulicModel, name: str) -> None:
    """Hand: the fundamental of a reservoir-closed-valve pipe is a / (4 L): 1386 / 30.684 =
    45.17 Hz, 1282 / 392.44 = 3.267 Hz, 1275 / 60.88 = 20.94 Hz (independent of the scheme)."""
    case = DATA["experiments"][name]
    _engine, t, _h, idx = run(model, name)
    closed_form = case["a_m_s"] / (4.0 * case["L_m"])
    assert ex.frequency_hz(t, idx) == pytest.approx(closed_form, rel=0.005)


@pytest.mark.parametrize("name", ["exp1", "exp2", "exp3"])
def test_r12_first_peak_against_measurement(model: HydraulicModel, name: str) -> None:
    _engine, _t, h, _idx = run(model, name, periods=3.0)
    assert h.max() == pytest.approx(PUB["measured_maximum"][name], rel=0.035)


@pytest.mark.parametrize("name", ["exp5", "exp6"])
def test_r13_first_peak_before_the_first_phase_window(model: HydraulicModel, name: str) -> None:
    case = DATA["experiments"][name]
    engine, t, h = ex.head_at_valve(model, case, 6.0 * 4.0 * case["L_m"] / case["a_m_s"])
    assert engine.phase.windows, "a window is expected after the first reflection"
    first = engine.phase.windows[0][0]
    valid = t < first
    assert valid.any() and np.isfinite(h[valid]).all()
    assert h[valid].max() == pytest.approx(PUB["measured_first_peak_exp5_exp6"][name], rel=0.05)
    # the first peak must come before the window, not be cut by it
    assert t[valid][np.argmax(h[valid])] < first - 1e-6
