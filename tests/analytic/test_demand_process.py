"""The downstream demand factor: Ornstein-Uhlenbeck statistics, reproducibility and bounds.

The factor is checked against its specified standard deviation, correlation time, clip range and
named stream, with sampling-error tolerances of four standard deviations. The targets and tolerances
are derived by hand in the "Demand process" section of the verification notes.

See D23.
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
    """The sample mean and variance of the log factor match the specified values within four
    sampling standard deviations. Independent: yes, because the targets are the specified values and
    a hand-derived sampling error.
    """
    sampling_sd = SIGMA * math.sqrt(2.0 * TAU / LONG)
    assert sampling_sd == pytest.approx(1.06e-3, rel=0.01)
    assert abs(float(long_log.mean())) < 4.0 * sampling_sd
    relative = float(long_log.var()) / SIGMA**2 - 1.0
    assert abs(relative) < 4.0 * math.sqrt(2.0 * TAU / LONG)


def test_the_autocorrelation_decays_with_the_correlation_time(long_log: np.ndarray) -> None:
    """The autocorrelation at lags of half, one and two correlation times equals exp(-lag/tau)
    within the Bartlett sampling error. Independent: yes, because the target is a closed-form
    expression.
    """
    x = long_log - long_log.mean()
    for lag_s, expected in ((900, math.exp(-0.5)), (1800, math.exp(-1.0)), (3600, math.exp(-2.0))):
        r = float(np.dot(x[:-lag_s], x[lag_s:]) / np.dot(x, x))
        phi = math.exp(-1.0 / TAU)
        variance = (
            (1 + phi**2) * (1 - phi ** (2 * lag_s)) / (1 - phi**2) - 2 * lag_s * phi ** (2 * lag_s)
        ) / LONG
        assert r == pytest.approx(expected, abs=4.0 * math.sqrt(variance)), lag_s


def test_the_same_seed_reproduces_and_another_seed_differs() -> None:
    """The same seed gives the same path and a different seed gives a different one. Independent:
    yes, because only equality of outputs is compared.
    """
    a, b = _process(7), _process(7)
    assert np.array_equal(a.log_path, b.log_path)
    assert not np.array_equal(a.log_path, _process(8).log_path)


def test_an_extra_stream_does_not_change_the_process() -> None:
    """Drawing from other named streams first leaves the demand path unchanged. Independent: yes,
    because the path is compared with one built without the other draws.
    """
    plain = _process(7).log_path
    streams = RandomStreams(7)
    streams.stream("sensor_noise").standard_normal(1000)  # a draw on another stream first
    streams.stream("faults")
    other = DemandProcess(True, streams, 3600.0, SIGMA, TAU, F_MIN, F_MAX).log_path
    assert np.array_equal(plain, other)


def test_the_factor_is_clipped_and_linear_in_the_logarithm_between_grid_points() -> None:
    """The factor stays within its clip range, reaches both clips for a large sigma, and its
    logarithm is linear between grid points. Independent: yes, because the expected values follow
    from the stored grid points.
    """
    wide = DemandProcess(True, RandomStreams(3), 20000.0, 0.5, TAU, F_MIN, F_MAX)
    values = [wide.factor(float(t)) for t in range(0, 20000, 7)]
    assert min(values) >= F_MIN and max(values) <= F_MAX
    assert min(values) == F_MIN and max(values) == F_MAX  # a large sigma reaches both clips
    p = _process(5)
    mid = p.unclipped_log(10.5)
    assert mid == pytest.approx(0.5 * (p.log_path[10] + p.log_path[11]), abs=1e-15)
    assert p.factor(10.5) == pytest.approx(math.exp(mid), rel=1e-15)


def test_a_disabled_process_is_exactly_one_and_draws_nothing() -> None:
    """A disabled process gives exactly one and touches no random stream. Independent: yes, because
    the expected value is the constant one.
    """
    streams = RandomStreams(7)
    p = DemandProcess(False, streams, 3600.0, SIGMA, TAU, F_MIN, F_MAX)
    assert p.factor(0.0) == p.factor(1234.5) == 1.0 and p.unclipped_log(99.0) == 0.0
    assert "demand" not in streams._streams  # noqa: SLF001


def test_s0f_stores_the_factor_in_the_hidden_boundary_state(series: dict[str, Series]) -> None:
    """The scenario with the demand process writes the factor, its logarithm and the scaled
    boundary-law coefficient into the hidden boundary rows. Independent: no, because the factor is
    recomputed with the same process class.
    """
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
    """Scenarios without a demand process keep the factor at one in every boundary row. Independent:
    yes, because the expected value is the constant one.
    """
    for sid in ("S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-G"):
        assert {r["downstream_factor"] for r in series[sid].boundary} == {1.0}, sid
        assert all(r["demand_process"] is False for r in series[sid].boundary)


def test_s0f_delivery_flow_responds_to_the_factor_with_the_hand_slope(
    series: dict[str, Series],
) -> None:
    """The delivery flow responds to the factor with the slope derived by hand, after the falling
    tank level is removed by regression. The derivation is in the "Demand process" section of the
    verification notes. Independent: yes, because the slope uses the separate reference
    implementation of the friction law.
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
