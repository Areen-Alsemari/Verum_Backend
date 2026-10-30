"""Statistics of the agent-side audit: window slopes, calibrated thresholds, margins and classes.

The checks use synthetic series with known answers, so they need no simulation run. They cover the
least-squares slope against its closed form, the calibration of the threshold and its false-alarm
rate on a separate set, the mass-balance feature on a known leak, and the ordering of the classes
and boundaries. The derivations are in the verification notes, section "Agent-side audit".

See D79 to D81.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from verum.evaluation.agent_audit import (
    BLOCK_S,
    N_ENDS,
    calibrate,
    crossing,
    deviation_maxima,
    exceedance,
    held,
    klass,
    mass_balance,
    window_ends,
    window_stats,
)

DURATION_S = 2700.0
AREA_M2 = math.pi * 15.0**2


def blocks_of(readings: np.ndarray, step_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Sum and count per 10 s block of readings taken every ``step_s`` seconds."""
    t = (np.arange(int(DURATION_S / step_s)) + 0.5) * step_s
    k = np.floor(t / BLOCK_S).astype(int)
    n = int(DURATION_S / BLOCK_S)
    return np.bincount(k, weights=readings, minlength=n), np.bincount(k, minlength=n).astype(float)


def ramp(a: float, b: float, step_s: float = 5.0) -> np.ndarray:
    t = (np.arange(int(DURATION_S / step_s)) + 0.5) * step_s
    return a + b * t


@pytest.mark.parametrize("length", [60, 300, 900])
def test_the_slope_of_a_noise_free_ramp_is_exact_for_every_window_length(length: int) -> None:
    """A ramp a + b t gives the slope b and the mean a + b (end - length / 2) in every window.

    Independent: yes, because the answer is the line itself, not a computation of the module.
    """
    sums, counts = blocks_of(ramp(7.0, -0.004), 5.0)
    mean, slope = window_stats(sums, counts, length)
    valid = np.isfinite(slope)
    assert valid.sum() == N_ENDS - length // 60 + 1
    assert np.allclose(slope[valid], -0.004, rtol=1e-9, atol=1e-12)
    expected = 7.0 - 0.004 * (window_ends() - length / 2)
    assert np.allclose(mean[valid], expected[valid], rtol=1e-9)


def test_a_window_with_too_few_readings_has_no_value() -> None:
    """A window that is more than half empty gives NaN for the mean and the slope.

    Independent: yes, because the empty stretch is built by hand.
    """
    sums, counts = blocks_of(ramp(1.0, 0.0), 5.0)
    counts[40:50] = 0.0
    sums[40:50] = 0.0  # no readings from 400 s to 500 s
    mean, slope = window_stats(sums, counts, 60)
    ends = window_ends()
    assert np.isnan(mean[ends == 480.0]).all() and np.isnan(slope[ends == 480.0]).all()
    assert np.isfinite(mean[ends == 600.0]).all()


@pytest.mark.parametrize("length", [60, 300, 900])
def test_the_slope_noise_matches_the_closed_form_of_a_regression(length: int) -> None:
    """The spread of the fitted slope is sigma over the root of the sum of squared time offsets.

    For n readings 5 s apart that sum is 25 n (n^2 - 1) / 12; averaging pairs into 10 s blocks
    changes it by under 2 percent. Independent: yes, because it is the textbook variance of a slope.
    """
    sigma, n = 0.25e-3, length // 5
    rng = np.random.default_rng(11)
    fitted = []
    for _ in range(400):
        sums, counts = blocks_of(7.0 + sigma * rng.standard_normal(int(DURATION_S / 5.0)), 5.0)
        _, slope = window_stats(sums, counts, length)
        fitted.append(slope[window_ends() == 2700.0][0])
    expected = sigma / math.sqrt(25.0 * n * (n * n - 1.0) / 12.0)
    assert np.std(fitted, ddof=1) == pytest.approx(expected, rel=0.10)
    assert abs(np.mean(fitted)) < 4.0 * expected / math.sqrt(400)


def test_the_mass_balance_of_a_known_leak_is_the_leak_flow() -> None:
    """A tank that loses 36 m3/h more than the meters show gives a mass balance of 36 m3/h.

    With 300 m3/h metered out, 36 m3/h leaking and no inflow, TK-101 falls at 336 / 3600 / 706.858
    = 1.3203e-4 m/s and the other tanks stay still.
    Independent: yes, because the leak flow is set by hand.
    """
    slope = -(300.0 + 36.0) / 3600.0 / AREA_M2
    assert slope == pytest.approx(-1.3203e-4, rel=1e-3)
    sums, counts = blocks_of(ramp(9.0, slope), 5.0)
    flat_sums, flat_counts = blocks_of(ramp(7.0, 0.0), 5.0)
    for length in (60, 300, 900):
        _, s1 = window_stats(sums, counts, length)
        _, s0 = window_stats(flat_sums, flat_counts, length)
        balance = mass_balance(np.zeros(N_ENDS), np.full(N_ENDS, 300.0), [s1, s0, s0], AREA_M2)
        ok = np.isfinite(balance)
        assert np.allclose(balance[ok], 36.0, atol=1e-6)


@pytest.mark.parametrize(("length", "expected"), [(60, 18.4), (300, 1.64), (900, 0.316)])
def test_the_mass_balance_noise_of_three_tanks_follows_the_level_noise(
    length: int, expected: float
) -> None:
    """Three levels of 0.25 mm noise give 18.4, 1.64 and 0.316 m3/h over 60, 300 and 900 s.

    Each value is sqrt(3) A sigma 3600 over the root of the sum of squared time offsets.
    Independent: yes, because the expected spread is a closed form of the noise and the window.
    """
    sigma = 0.25e-3
    rng = np.random.default_rng(5)
    values = []
    for _ in range(300):
        slopes = []
        for _tank in range(3):
            noisy = 7.0 + sigma * rng.standard_normal(int(DURATION_S / 5.0))
            slopes.append(window_stats(*blocks_of(noisy, 5.0), length)[1])
        balance = mass_balance(np.zeros(N_ENDS), np.zeros(N_ENDS), slopes, AREA_M2)
        values.append(balance[window_ends() == 2700.0][0])
    assert np.std(values, ddof=1) == pytest.approx(expected, rel=0.12)


def test_the_threshold_is_the_percentile_of_the_largest_deviation() -> None:
    """The 99th percentile of the largest of 40 normal deviations has the closed form of the normal.

    P(max |z| <= q) = (2 Phi(q) - 1)^40 = 0.99 gives q = 3.66 for unit spread.
    Independent: yes, because the percentile of a maximum of normal samples is known exactly.
    """
    windows = 40
    expected = stats.norm.ppf((1.0 + 0.99 ** (1.0 / windows)) / 2.0)
    assert expected == pytest.approx(3.66, abs=0.01)
    series = np.random.default_rng(3).standard_normal((20000, 1, windows))
    th = calibrate(series, boot=50)
    assert th.value == pytest.approx(expected, rel=0.02)
    assert th.mean == pytest.approx(0.0, abs=0.01)
    assert 0.0 < th.error < 0.1 * th.value


def test_the_same_series_and_seeds_give_the_same_threshold() -> None:
    """Calibrating the same series twice gives the same mean, threshold and error.

    Independent: no, because it compares the function with itself; it guards against hidden state.
    """
    series = np.random.default_rng(8).standard_normal((300, 1, 30))
    first, second = calibrate(series, seed=4), calibrate(series, seed=4)
    assert first == second
    assert calibrate(series, seed=5).value == first.value  # the bootstrap seed moves only the error


def test_the_false_alarm_rate_on_a_separate_healthy_set_is_near_the_target() -> None:
    """Thresholds from 1000 healthy runs alarm in about 1 percent of 20000 other healthy runs.

    The count is binomial, so 0.7 to 1.4 percent covers four standard errors and the error of the
    percentile.
    Independent: yes, because the target is set by the percentile and the check uses new draws.
    """
    rng = np.random.default_rng(21)
    th = calibrate(rng.standard_normal((1000, 1, 40)), boot=20)
    held_out = rng.standard_normal((20000, 1, 40))
    rate = float(np.mean(deviation_maxima(held_out, th.mean)[:, 0] > th.value))
    assert 0.007 <= rate <= 0.014


def test_a_deviation_of_three_thresholds_is_clear_and_of_half_is_invisible() -> None:
    """The margin is the deviation over the threshold and the class follows its size.

    Independent: yes, because the margins are written by hand.
    """
    z = exceedance(np.array([0.0, 0.5, 1.0, 2.9999, 3.0, np.nan]), 0.0, 1.0)
    assert z.tolist() == [0.0, 0.5, 1.0, 2.9999, 3.0, 0.0]
    classes = ["invisible", "invisible", "marginal", "marginal", "clear", "invisible"]
    assert [klass(m) for m in z] == classes


def test_the_held_margin_is_the_smallest_of_three_consecutive_windows() -> None:
    """A spike of one window is not held, a run of three windows is held at its smallest value.

    Independent: yes, because the series and the answer are written by hand.
    """
    z = np.array([0.0, 5.0, 0.0, 2.0, 3.0, 4.0, 0.0])
    assert held(z).tolist() == [0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0]


def test_a_boundary_follows_a_power_law_and_the_clear_one_is_the_larger() -> None:
    """For a margin m = (x / x0)^p the severity at which it reaches a level is x0 level^(1/p).

    Hence the marginal boundary (level 1) is below the clear boundary (level 3).
    Independent: yes, because the crossing of a power law is known in closed form.
    """
    x0, p = 2e-4, 1.7
    points = [(x, (x / x0) ** p) for x in (2e-5 * 1.9**k for k in range(8))]
    low, high = crossing(points, 1.0), crossing(points, 3.0)
    assert low is not None and high is not None and low < high
    assert low == pytest.approx(x0, rel=1e-9)
    assert high == pytest.approx(x0 * 3.0 ** (1.0 / p), rel=1e-9)
    assert crossing(points, 1e6) is None


def test_a_boundary_at_the_first_point_and_a_flipped_severity() -> None:
    """A margin above the level at the first point gives that point; a flipped severity keeps sign.

    Independent: yes, because both answers follow from the definition.
    """
    assert crossing([(0.02, 5.0), (0.01, 6.0)], 3.0) == 0.02
    flipped = crossing([(-0.02, 0.5), (-0.005, 2.0)], 1.0)
    assert flipped is not None and -0.02 < flipped < -0.005
