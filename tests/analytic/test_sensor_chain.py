"""Sensor chain on synthetic truth: lag, window mean, event samples, noise, dropout and clipping.

Synthetic node arrays are passed through the chain and compared with closed forms for the lag, the
window mean and the event samples, and with binomial and normal sampling bounds for the noise and
dropout. Pressure readings are referenced to the site atmosphere, so only the absolute-referenced
readings differ between strata. The derivations are in the "Sensor chain" section of the
verification notes.

See D27 to D32.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from verum.rng import RandomStreams
from verum.sensors import adapter, chain, load_sensor_config

CFG = load_sensor_config()


def nodes(t: list[float], x: list[float], jump: list[bool] | None = None) -> chain.Nodes:
    return chain.Nodes(np.array(t), np.array(x), np.array(jump or [False] * len(t)))


def test_lag_step_response_matches_the_closed_form() -> None:
    """A unit step through the first-order lag gives 1 - exp(-(t - t0)/tau). Independent: yes,
    because the reference is a closed form.
    """
    n = nodes([0.0, 10.0, 10.0, 40.0], [0.0, 0.0, 1.0, 1.0], [False, False, True, False])
    y = chain.lag_response(n, 2.0)
    for t in (10.0, 11.0, 12.0, 14.0, 20.0, 40.0):
        assert chain.value_at(n, y, 2.0, t) == pytest.approx(
            1.0 - math.exp(-(t - 10.0) / 2.0) if t > 10 else 0.0, abs=1e-12
        )


def test_lag_ramp_response_matches_the_closed_form() -> None:
    """A ramp through the first-order lag gives t - tau (1 - exp(-t/tau)). Independent: yes, because
    the reference is a closed form.
    """
    ts = [float(k) for k in range(0, 21)]
    n = nodes(ts, ts)
    y = chain.lag_response(n, 3.0)
    for t in (1.0, 4.5, 10.0, 17.3):
        assert chain.value_at(n, y, 3.0, t) == pytest.approx(
            t - 3.0 * (1.0 - math.exp(-t / 3.0)), abs=1e-12
        )


def test_window_mean_of_a_ramp_is_the_ramp_at_the_window_centre() -> None:
    """The trailing window mean of a ramp is the ramp value at the centre of the window.
    Independent: yes, because the reference is a closed form.
    """
    ts = [float(k) for k in range(0, 101)]
    n = nodes(ts, ts)
    y = chain.lag_response(n, 0.0)
    for t in (30.0, 55.5, 100.0):
        assert chain.trailing_mean(n, y, 0.0, t, 30.0) == pytest.approx(t - 15.0, abs=1e-12)
    assert chain.trailing_mean(n, y, 0.0, 10.0, 30.0) == pytest.approx(5.0)  # window starts at 0


def test_a_sample_at_an_event_time_reads_the_post_event_state() -> None:
    """A sample at an event time reads the post-event value, a sample just before reads the
    pre-event value, and the lag state is continuous across the event. Independent: yes, because the
    expected values follow from the event rule.
    """
    n = nodes([0.0, 5.0, 5.0, 10.0], [0.0, 0.0, 1.0, 1.0], [False, False, True, False])
    y = chain.lag_response(n, 0.0)
    assert chain.value_at(n, y, 0.0, 4.999) == pytest.approx(0.0)
    assert chain.value_at(n, y, 0.0, 5.0) == 1.0
    assert chain.value_at(n, y, 0.0, 5.001) == pytest.approx(1.0)
    lagged = chain.lag_response(n, 1.0)
    assert chain.value_at(n, lagged, 1.0, 5.0) == pytest.approx(0.0)  # state is continuous
    assert chain.value_at(n, lagged, 1.0, 6.0) == pytest.approx(1.0 - math.exp(-1.0))


def test_the_sample_phase_is_a_hash_of_the_tag_inside_its_interval() -> None:
    """The sample phase of a tag lies inside its interval, differs between tags and is reproducible.
    Independent: yes, because only the range and uniqueness are checked.
    """
    phases = {tag: chain.sample_phase(tag, 5.0) for tag in ("LT-101", "LT-102", "LT-103", "TT-001")}
    assert all(0.0 <= p < 5.0 for p in phases.values()) and len(set(phases.values())) == 4
    assert chain.sample_phase("LT-101", 5.0) == phases["LT-101"]


def _run(
    tag: str, truth: float | list[float], duration: float, seed: int = 1
) -> list[dict[str, Any]]:
    spec = CFG.tags[tag]
    if isinstance(truth, float):
        n = nodes([0.0, duration], [truth, truth])
    else:
        n = nodes([0.0, duration], truth)
    return adapter._continuous(CFG, spec, n, RandomStreams(seed), "EP-T", duration).observations


@pytest.mark.parametrize(
    ("tag", "truth", "sigma_label"),
    [
        ("LT-101", 9.0, "level"),
        ("FT-001", 400.0, "flow"),
        ("PT-001", 5.0, "pressure"),
        ("TT-001", 25.0, "temperature"),
    ],
)
def test_noise_has_zero_mean_and_the_specified_deviation(
    tag: str, truth: float, sigma_label: str
) -> None:
    """Over many samples the reading has the truth as its mean and the specified deviation plus
    quantisation, within sampling bounds. Independent: yes, because the bounds are hand derived,
    although the random draws come from the code under test.
    """
    spec = CFG.tags[tag]
    assert spec.interval_s
    rows = _run(tag, truth, 40000.0 * spec.interval_s)
    values = np.array([r["value"] for r in rows if r["value"] is not None])
    sigma = CFG.sigma(sigma_label)
    step = (spec.range_hi - spec.range_lo) / 65535  # type: ignore[operator]
    var = sigma**2 + step**2 / 12.0
    n = len(values)
    assert abs(values.mean() - truth) < 4.0 * math.sqrt(var / n) + step / 2
    assert values.std() == pytest.approx(math.sqrt(var), abs=4.0 * math.sqrt(var / (2 * n)))
    # quantisation: every value lies on the lattice lo + k step
    k = (values - spec.range_lo) / step
    assert np.max(np.abs(k - np.round(k))) < 1e-6


def test_dropout_rate_is_binomial_and_does_not_depend_on_the_truth() -> None:
    """The number of lost samples is consistent with a binomial law, and the lost indices do not
    depend on the truth values. Independent: yes, because the bounds are hand derived, although the
    draws come from the code under test.
    """
    n = 400000
    a = _run("PT-001", 5.0, float(n))
    b = _run("PT-001", [0.0, 9.0], float(n))  # a ramp instead of a constant
    lost_a = [i for i, r in enumerate(a) if r["availability_status"] == "missing_sample"]
    lost_b = [i for i, r in enumerate(b) if r["availability_status"] == "missing_sample"]
    assert lost_a == lost_b  # the draws are independent of the content
    mean, sd = n * 0.0005, math.sqrt(n * 0.0005 * 0.9995)
    assert abs(len(lost_a) - mean) < 4.0 * sd
    row = a[lost_a[0]]
    assert row["value"] is None and row["quality_flag"] == "bad"


def test_clipping_flags_a_real_overrange_but_not_noise_at_zero() -> None:
    """A reading far above the range is clipped and flagged suspect, while noise below zero at a
    zero truth is clipped without a flag. Independent: yes, because the expectations follow from the
    clipping rule.
    """
    over = _run("PT-001", 15.0, 600.0)  # 15 barg against a 10 barg range
    measured = [r for r in over if r["value"] is not None]
    assert all(r["value"] == 10.0 and r["quality_flag"] == "suspect" for r in measured)
    zero = _run("FT-001", 0.0, 4000.0)  # half the noisy samples are below the range
    values = [r["value"] for r in zero if r["value"] is not None]
    assert 0.0 in values and min(values) == 0.0
    suspect = sum(r["quality_flag"] == "suspect" for r in zero if r["value"] is not None)
    # Only a reading more than 3 sigma below zero is flagged: P(Z > 3) = 0.00135 per sample.
    n = len(values)
    assert suspect < n * 0.00135 + 5.0 * math.sqrt(n * 0.00135)
    assert suspect < 0.01 * n  # nothing like the half that noise alone would clip


def test_a_negative_gauge_value_in_the_inland_stratum_is_not_clipped() -> None:
    """A slightly negative gauge pressure in the inland stratum is within the transmitter range and
    is not clipped. Independent: yes, because the gauge value is hand arithmetic.
    """
    abs_pa, inland = 90000.0, 94300.0
    gauge = adapter._convert("pressure_pa_abs", abs_pa, inland)
    assert gauge == pytest.approx(-0.043)
    rows = _run("PT-201", gauge or 0.0, 600.0)  # PT-201 range is -1 to 5 barg
    values = np.array([r["value"] for r in rows if r["value"] is not None])
    assert values.min() < 0.0 and all(
        r["quality_flag"] == "good" for r in rows if r["value"] is not None
    )
    assert abs(values.mean() + 0.043) < 0.001
    clipped = _run("PT-001", gauge or 0.0, 600.0)  # range 0 to 10: the negative part is clipped
    assert min(r["value"] for r in clipped if r["value"] is not None) == 0.0


def test_the_strata_differ_only_in_absolute_referenced_pressure_readings() -> None:
    """The two atmosphere strata differ by 0.07025 bar in pressure readings and not at all in level,
    flow or temperature. Independent: yes, because the difference is hand arithmetic.
    """
    sea, high = 101325.0, 94300.0
    p = 250000.0
    high_gauge = adapter._convert("pressure_pa_abs", p, high)
    sea_gauge = adapter._convert("pressure_pa_abs", p, sea)
    assert high_gauge is not None and sea_gauge is not None
    diff = high_gauge - sea_gauge
    assert diff == pytest.approx((sea - high) / 1e5) == pytest.approx(0.07025)
    for field, value in (("level_m", 9.0), ("flow_m3s", 0.08), ("temperature_K", 298.15)):
        assert adapter._convert(field, value, sea) == adapter._convert(field, value, high)


def test_an_extra_tag_does_not_change_the_draws_of_another() -> None:
    """Drawing from the streams of other tags first leaves the readings of a tag unchanged.
    Independent: yes, because the readings are compared with a run without the other draws.
    """
    alone = _run("LT-101", 9.0, 600.0, seed=5)
    streams = RandomStreams(5)
    for other in ("LT-102", "FT-001", "PT-001"):
        streams.stream(f"sensor/{other}/noise").standard_normal(777)
    spec = CFG.tags["LT-101"]
    again = adapter._continuous(
        CFG, spec, nodes([0.0, 600.0], [9.0, 9.0]), streams, "EP-T", 600.0
    ).observations
    assert again == alone
    assert _run("LT-101", 9.0, 600.0, seed=5) == alone  # same seed and config: identical
    assert _run("LT-101", 9.0, 600.0, seed=6) != alone


def test_the_valve_contact_has_hysteresis_and_the_initial_state() -> None:
    """The valve open contact asserts at an opening of 0.98, releases below 0.97 and starts in the
    state of the first sample. Independent: yes, because the thresholds are the stated contact
    values.
    """
    def series(alphas: list[float]) -> list[tuple[float, str | None, dict[str, float]]]:
        return [(float(i), None, {"position_frac": a}) for i, a in enumerate(alphas)]

    on, off = CFG["contact_open_alpha"], CFG["contact_open_alpha"] - CFG["contact_hysteresis"]
    assert (on, off) == (0.98, 0.97)
    # opens at 0.98 (between samples 2 and 3), stays on at 0.975, releases below 0.97
    changes = adapter._contact_changes(series([0.0, 0.5, 0.97, 0.99, 0.975, 0.972, 0.96]), on, off)
    assert changes[0] == (0.0, 0)  # the initial state is the first change
    assert changes[1][1] == 1 and 2.0 < changes[1][0] < 3.0
    assert changes[1][0] == pytest.approx(2.0 + (0.98 - 0.97) / (0.99 - 0.97))
    assert changes[2][1] == 0 and 5.0 < changes[2][0] < 6.0
    assert len(changes) == 3  # no chatter at 0.975 and 0.972
