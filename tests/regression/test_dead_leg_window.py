"""The dead-leg window in the emergency isolation scenario.

After the high-high trip the receipt segments stay isolated at the pressure they held and relax
towards the pressure beyond the closed valve with a time constant of 60 s. The window opens when the
gap exceeds 0.5 bar and closes below 0.05 bar, which the derivation in the "Dead-leg window" section
of the verification notes puts at about 3295 s.

See D39 and D54.
"""

from __future__ import annotations

import math

import pytest

from _series import Series

TAU_S = 60.0
BAR = 1.0e5


def test_the_dead_leg_window_follows_the_relaxation_law(series: dict[str, Series]) -> None:
    """The dead-leg window opens at the closure and closes when the pressure gap, decaying with a 60
    s time constant, falls below 0.05 bar. Independent: yes, because the prediction uses the written
    pressures and the time constant, while the window times come from the engine's window logic.
    """
    s = series["S0u-E"]
    window = next(w for w in s.windows if w["kind"] == "dead_leg_unvalidated")
    collapse = next(w for w in s.windows if w["kind"] == "flow_collapse")
    assert window["reason"] == "dead_leg_held_pressure_unvalidated"
    assert window["element_id"] == "E001" and window["ratio"] is None
    assert window["t_start_s"] == collapse["t_end_s"]  # opens as the path closes
    p1 = {t: p for t, side, p, _b in s.edge_p["E001"] if side is None}
    target = {t: p for t, side, p, _b in s.edge_p["E003"] if side is None}
    t_row = math.ceil(window["t_start_s"])
    gap = {t: (p1[t] or 0.0) - (target[t] or 0.0) for t in (t_row, t_row + 30.0, t_row + 90.0)}
    assert gap[t_row] > 0.5 * BAR  # the opening condition holds at the first row
    for dt in (30.0, 90.0):  # the held pressure relaxes with tau = 60 s
        assert gap[t_row + dt] / gap[t_row] == pytest.approx(math.exp(-dt / TAU_S), rel=2e-3)
    g0 = gap[t_row] * math.exp((t_row - window["t_start_s"]) / TAU_S)
    predicted_end = window["t_start_s"] + TAU_S * math.log(g0 / (0.05 * BAR))
    assert predicted_end - 1.0 <= window["t_end_s"] <= predicted_end + 1.0


def test_the_window_makes_the_episode_restricted(series: dict[str, Series]) -> None:
    """A dead-leg window makes the dataset tier of the episode restricted benchmark. Independent:
    yes, because the expected tier is the stated rule.
    """
    kinds = {w["kind"] for w in series["S0u-E"].windows}
    assert "dead_leg_unvalidated" in kinds
    assert series["S0u-E"].episode["dataset_tier"] == "restricted_benchmark"


def test_no_other_shipped_scenario_has_a_dead_leg_window(series: dict[str, Series]) -> None:
    """No other shipped scenario has a dead-leg window. Independent: yes, because the check reads
    the written windows.
    """
    for sid, s in series.items():
        if sid != "S0u-E":
            assert all(w["kind"] != "dead_leg_unvalidated" for w in s.windows), sid
