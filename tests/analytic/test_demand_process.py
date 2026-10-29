"""The downstream demand factor: Ornstein-Uhlenbeck statistics, reproducibility, bounds.

Inputs: ``DemandProcess`` built from named streams, and the S0-F episode. Outputs: pass/fail.
Key assumptions:
    * Specified values (decision D23): standard deviation of log f_d 0.05, correlation time
      1800 s, clip to [0.8, 1.25], stream ``demand``, grid of one second.
    * Sampling error. For a stationary OU series of length T the sample mean has standard
      deviation sigma sqrt(2 tau / T), and the sample variance has relative standard
      deviation sqrt(2 tau / T); with T = 8e6 s and tau = 1800 s these are 1.06e-3 and
      0.0212. Tolerances are four standard deviations. The autocorrelation at lag k must be
      exp(-k/tau); its sampling variance for an AR(1) series is (Bartlett)
      [(1 + phi^2)(1 - phi^(2k))/(1 - phi^2) - 2 k phi^(2k)] / N, phi = exp(-1/tau), which is
      0.0142 squared at k = 900 s and N = 8e6.
Independence: the targets are the specified values and the sampling-error formulas above
(hand derivation), not outputs of the code under test.

Source: ``docs/design_decisions.md`` D23.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from _series import Series
from verum.rng import RandomStreams
from verum.sim.demand import DemandProcess

SIGMA, TAU, F_MIN, F_MAX = 0.05, 1800.0, 0.8, 1.25
LONG = 8_000_000


def _process(seed: int, duration: float = 3600.0, enabled: bool = True) -> DemandProcess:
    return DemandProcess(enabled, RandomStreams(seed), duration, SIGMA, TAU, F_MIN, F_MAX)


@pytest.fixture(scope="module")
def long_log() -> np.ndarray:
    return _process(20261101, float(LONG)).log_path


def test_mean_and_variance_match_the_specified_values(long_log: np.ndarray) -> None:
    sampling_sd = SIGMA * math.sqrt(2.0 * TAU / LONG)
    assert sampling_sd == pytest.approx(1.06e-3, rel=0.01)
    assert abs(float(long_log.mean())) < 4.0 * sampling_sd
    relative = float(long_log.var()) / SIGMA**2 - 1.0
    assert abs(relative) < 4.0 * math.sqrt(2.0 * TAU / LONG)


def test_the_autocorrelation_decays_with_the_correlation_time(long_log: np.ndarray) -> None:
    x = long_log - long_log.mean()
    for lag_s, expected in ((900, math.exp(-0.5)), (1800, math.exp(-1.0)), (3600, math.exp(-2.0))):
        r = float(np.dot(x[:-lag_s], x[lag_s:]) / np.dot(x, x))
        phi = math.exp(-1.0 / TAU)
        variance = (
            (1 + phi**2) * (1 - phi ** (2 * lag_s)) / (1 - phi**2) - 2 * lag_s * phi ** (2 * lag_s)
        ) / LONG
        assert r == pytest.approx(expected, abs=4.0 * math.sqrt(variance)), lag_s


def test_the_same_seed_reproduces_and_another_seed_differs() -> None:
    a, b = _process(7), _process(7)
    assert np.array_equal(a.log_path, b.log_path)
    assert not np.array_equal(a.log_path, _process(8).log_path)


def test_an_extra_stream_does_not_change_the_process() -> None:
    plain = _process(7).log_path
    streams = RandomStreams(7)
    streams.stream("sensor_noise").standard_normal(1000)  # a draw on another stream first
    streams.stream("faults")
    other = DemandProcess(True, streams, 3600.0, SIGMA, TAU, F_MIN, F_MAX).log_path
    assert np.array_equal(plain, other)


def test_the_factor_is_clipped_and_linear_in_the_logarithm_between_grid_points() -> None:
    wide = DemandProcess(True, RandomStreams(3), 20000.0, 0.5, TAU, F_MIN, F_MAX)
    values = [wide.factor(float(t)) for t in range(0, 20000, 7)]
    assert min(values) >= F_MIN and max(values) <= F_MAX
    assert min(values) == F_MIN and max(values) == F_MAX  # a large sigma reaches both clips
    p = _process(5)
    mid = p.unclipped_log(10.5)
    assert mid == pytest.approx(0.5 * (p.log_path[10] + p.log_path[11]), abs=1e-15)
    assert p.factor(10.5) == pytest.approx(math.exp(mid), rel=1e-15)


def test_a_disabled_process_is_exactly_one_and_draws_nothing() -> None:
    streams = RandomStreams(7)
    p = DemandProcess(False, streams, 3600.0, SIGMA, TAU, F_MIN, F_MAX)
    assert p.factor(0.0) == p.factor(1234.5) == 1.0 and p.unclipped_log(99.0) == 0.0
    assert "demand" not in streams._streams  # noqa: SLF001


def test_s0f_stores_the_factor_in_the_hidden_boundary_state(series: dict[str, Series]) -> None:
    s = series["S0-F"]
    process = _process(s.episode["seed"], 3600.0)
    rows = [r for r in s.boundary if r["side"] is None]
    assert len(rows) >= 3600
    for r in rows[::97]:
        assert r["demand_process"] is True
        assert r["downstream_factor"] == process.factor(r["t_sim_s"])
        assert r["log_downstream_factor"] == process.unclipped_log(r["t_sim_s"])
        assert r["boundary_law_coefficient_m"] == pytest.approx(
            10.060889 * r["downstream_factor"], rel=1e-9
        )
    factors = [r["downstream_factor"] for r in rows]
    assert F_MIN <= min(factors) and max(factors) <= F_MAX
    assert np.std(np.log(factors)) > 0.005  # it moves; one hour is two correlation times


def test_other_scenarios_keep_the_factor_at_one(series: dict[str, Series]) -> None:
    for sid in ("S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-G"):
        assert {r["downstream_factor"] for r in series[sid].boundary} == {1.0}, sid
        assert all(r["demand_process"] is False for r in series[sid].boundary)


def test_s0f_delivery_flow_responds_to_the_factor_with_the_hand_slope(
    series: dict[str, Series],
) -> None:
    """The flow depends on f_d and on the falling tank level; separate them by least squares.

    Hand derivation: at the duty point the head balance is pump(Q) = static + loss(Q) +
    c f_d (Q/300)^2, so dQ/df = -c (Q/300)^2 / S with S the slope of loss + law - pump with
    respect to Q (central difference of the reference module, TK-102 reference fittings).
    The level coefficient is +1/S per metre. A plain correlation with f_d alone is only about
    -0.8 because the level falls 0.44 m in the hour, a trend of the same size as the
    factor's effect (2 m3/h); the regression on both removes it.
    Independent: the slope uses the separate reference implementation of the friction law.
    """
    import _reference_hydraulics as ref

    s = series["S0-F"]
    flow = {t: q for t, side, _st, q, _ph, _m in s.pump["P-101A"] if side is None}
    level = {t: lv for t, side, lv, _v, _f in s.tank["TK-102"] if side is None}
    factor = {r["t_sim_s"]: r["downstream_factor"] for r in s.boundary if r["side"] is None}
    times = [t for t in sorted(flow) if t >= 60.0]
    y = np.array([flow[t] for t in times])
    design = np.column_stack(
        [np.ones(len(times)), [factor[t] for t in times], [level[t] for t in times]]
    )
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    c, segments = 10.060889, ref.tank2_reference_fittings_segments()
    q = float(y.mean())
    h = 1e-6

    def net(x: float) -> float:
        return ref.path_loss(x, segments) + c * (x * 3600 / 300) ** 2 - ref.pump_head(x)

    slope = (net(q + h) - net(q - h)) / (2 * h)
    assert coef[1] == pytest.approx(-c * (q * 3600 / 300) ** 2 / slope, rel=0.05)
    assert coef[2] == pytest.approx(1.0 / slope, rel=0.05)
    assert float(np.corrcoef(design[:, 1], y - coef[2] * design[:, 2])[0, 1]) < -0.99
    assert 0.5 < (y.max() - y.min()) * 3600.0 < 20.0  # m3/h: a few percent of the duty flow
