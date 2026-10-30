"""The dead-leg window of decision D54 in the ESD isolation S0u-E.

Inputs: the written episode S0u-E (XV-R000 and XV-R101 close at the high-high trip; E001 and E002
stay isolated from the pipeline side at the pressure they held). Outputs: pass/fail.

Derivations (hand arithmetic):
    * Decision D39: an isolated segment relaxes to the head across its closed valve,
      ``H = H_t + (H_0 - H_t) exp(-dt / tau)``, tau = 60 s. For E001 and E002 (same elevation, 1 m)
      the head difference is the pressure difference over rho g, so the gap in pressure decays as
      ``g(t) = g_0 exp(-(t - t_0) / 60)``. The target is the pressure of E003 beyond the closed
      XV-R000, which is constant after the closure.
    * Decision D54: the window opens when the gap exceeds 0.5 bar and closes when it is below
      0.05 bar. From the rows: g at 2968 s is about 11.8 bar, so the window opens at the closure
      and closes at ``t_0 + 60 ln(g_0 / 0.05 bar)`` = 2967.33 + 60 x 5.46 = about 3295 s, to within
      the 1 s rows of the grid.
Independence: the prediction uses the written pressures of E001 and E003 and the time constant of
D39; the window times come from the engine's window logic.

Source: ``docs/design_decisions.md`` D39 and D54.
"""

from __future__ import annotations

import math

import pytest

from _series import Series

TAU_S = 60.0
BAR = 1.0e5


def test_the_dead_leg_window_follows_the_relaxation_law(series: dict[str, Series]) -> None:
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
    kinds = {w["kind"] for w in series["S0u-E"].windows}
    assert "dead_leg_unvalidated" in kinds
    assert series["S0u-E"].episode["dataset_tier"] == "restricted_benchmark"


def test_no_other_shipped_scenario_has_a_dead_leg_window(series: dict[str, Series]) -> None:
    for sid, s in series.items():
        if sid != "S0u-E":
            assert all(w["kind"] != "dead_leg_unvalidated" for w in s.windows), sid
