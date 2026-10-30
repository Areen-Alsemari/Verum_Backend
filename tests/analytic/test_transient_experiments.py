"""The transient engine against the water-hammer experiments of Jensen et al.

One reservoir, one pipe and a valve at the end are run with 24 reaches at Courant number one. The
parameters and published results were supplied in the task statement and are not verified against
the paper, and the closure exponent is a fitted value of the authors. The acceptance tolerances were
fixed before the first run and are not widened. The tolerances and findings are in the "Transient
engine against published experiments" section of the verification notes.

See D56.
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
    """For experiments 1 to 3 the maximum, third and tenth head peaks at the valve agree with the
    quasi-steady model of the paper within 1, 2 and 3 percent, and no invalid window opens.
    Independent: yes, because the published results come from a different code.
    """
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
    """For experiments 1 and 3 the oscillation frequency agrees with the paper within 1 percent.
    Independent: yes, because the published results come from a different code.
    """
    _engine, t, _h, idx = run(model, name)
    published = PUB["paper_quasi_steady_frequency_hz"][name]
    assert ex.frequency_hz(t, idx) == pytest.approx(published, rel=0.01)


def test_r12_the_published_frequency_of_experiment_2_is_above_the_closed_form() -> None:
    """The published frequency of experiment 2 lies 1.5 to 1.8 percent above a / (4 L), while those
    of experiments 1 and 3 agree with it. Independent: yes, because the test records published data
    and does not test the engine.
    """
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
    """The engine frequency equals a / (4 L) within 0.5 percent for each experiment. Independent:
    yes, because the reference is a closed form that does not depend on the scheme.
    """
    case = DATA["experiments"][name]
    _engine, t, _h, idx = run(model, name)
    closed_form = case["a_m_s"] / (4.0 * case["L_m"])
    assert ex.frequency_hz(t, idx) == pytest.approx(closed_form, rel=0.005)


@pytest.mark.parametrize("name", ["exp1", "exp2", "exp3"])
def test_r12_first_peak_against_measurement(model: HydraulicModel, name: str) -> None:
    """The first head peak agrees with the measured maximum within 3.5 percent. Independent: yes,
    because the reference is a measurement.
    """
    _engine, _t, h, _idx = run(model, name, periods=3.0)
    assert h.max() == pytest.approx(PUB["measured_maximum"][name], rel=0.035)


@pytest.mark.parametrize("name", ["exp5", "exp6"])
def test_r13_first_peak_before_the_first_phase_window(model: HydraulicModel, name: str) -> None:
    """For experiments 5 and 6 the first peak, up to the first invalid window, agrees with the
    measured peak within 5 percent, and the window opens after the first reflection. Independent:
    yes, because the reference is a measurement.
    """
    case = DATA["experiments"][name]
    engine, t, h = ex.head_at_valve(model, case, 6.0 * 4.0 * case["L_m"] / case["a_m_s"])
    assert engine.phase.windows, "a window is expected after the first reflection"
    first = engine.phase.windows[0][0]
    valid = t < first
    assert valid.any() and np.isfinite(h[valid]).all()
    assert h[valid].max() == pytest.approx(PUB["measured_first_peak_exp5_exp6"][name], rel=0.05)
    # the first peak must come before the window, not be cut by it
    assert t[valid][np.argmax(h[valid])] < first - 1e-6
