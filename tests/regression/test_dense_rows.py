"""Truth rows every 0.1 s inside validity windows and during valve strokes.

From the start of a stroke to its end, and inside any validity window, every multiple of 0.1 s has a
row, and elsewhere only the 1 s grid and the event instants have rows. The rows between grid
instants come from the dense solution of the integrator, so the step scheme is unchanged and the
0.19 s flow collapse of the isolation scenario is resolved.

See D34.
"""

from __future__ import annotations

import math

from _series import Series


def _times(s: Series, edge: str) -> list[float]:
    return sorted({t for t, side, _q in s.edge[edge] if side != "pre_event"})


def _multiples(a: float, b: float) -> list[float]:
    """Multiples of 0.1 s in the open interval (a, b), by integer arithmetic."""
    first = math.floor(a * 10 + 1e-9) + 1
    return [k / 10 for k in range(first, math.ceil(b * 10 - 1e-9)) if a < k / 10 < b]


def test_every_tenth_of_a_second_has_a_row_during_the_esd_strokes(
    series: dict[str, Series],
) -> None:
    """During the emergency closure strokes every multiple of 0.1 s has a row. Independent: yes,
    because the expected times are arithmetic on the stroke times of 10 s and 30 s.
    """
    s = series["S0u-E"]
    times = set(_times(s, "E001"))
    trip = next(e["t_sim_s"] for e in s.events if e["payload"].get("kind") == "HIGH_HIGH_TRIP")
    start = math.floor(trip) + 1.0  # the closure is ordered at the next update
    for t in _multiples(start, start + 10.0):
        if abs(t - round(t)) > 1e-9:
            assert t in times, t  # integers are grid rows anyway
        else:
            assert t in times
    assert len([t for t in times if start < t < start + 10.0]) >= 99


def test_no_pair_of_rows_spans_more_than_a_tenth_of_a_second_in_the_window(
    series: dict[str, Series],
) -> None:
    """Inside the flow-collapse window no two consecutive rows are more than 0.1 s apart.
    Independent: yes, because the window is read from the episode record.
    """
    s = series["S0u-E"]
    window = next(w for w in s.windows if w["kind"] == "flow_collapse")
    times = sorted({t for t, side, _q in s.edge["E001"] if side != "pre_event"})
    inside = [t for t in times if window["t_start_s"] - 0.1 <= t <= window["t_end_s"] + 0.1]
    assert len(inside) >= 3
    assert all(b - a <= 0.1 + 1e-9 for a, b in zip(inside, inside[1:], strict=False))
    flows = {t: q for t, side, q in s.edge["E001"] if side != "pre_event"}
    assert max(flows[t] for t in inside) * 3600 < 600.0  # the rows already show the fall
    assert flows[inside[-1]] * 3600 < 100.0  # the collapse is inside the rows


def test_the_slow_stroke_of_s0ud_has_rows_every_tenth_and_the_rest_the_grid(
    series: dict[str, Series],
) -> None:
    """The 30 s stroke has a row every 0.1 s, and the rest of the episode keeps the 1 s grid.
    Independent: yes, because the expected times are arithmetic on the stroke time.
    """
    s = series["S0u-D"]
    times = _times(s, "E001")
    stroke = [t for t in times if 600.0 < t < 630.0]
    assert len(stroke) >= 299  # XV-R101 moves for 30 s
    outside = [t for t in times if 700.0 < t < 1190.0]
    assert all(abs(t - round(t)) < 1e-9 for t in outside)  # steady stretch: 1 s grid only


def test_a_steady_episode_keeps_the_one_second_grid(series: dict[str, Series]) -> None:
    """A steady episode keeps the 1 s grid with 3601 rows. Independent: yes, because the expected
    count is arithmetic on the duration.
    """
    times = _times(series["S0-A"], "E001")
    assert all(abs(t - round(t)) < 1e-9 for t in times)
    assert len(times) == 3601


def test_dense_rows_keep_the_ledger_closed(series: dict[str, Series]) -> None:
    """The network ledger stays closed on the dense rows. Independent: yes, because the check reads
    the written closure flags.
    """
    rows = [r for r in series["S0u-E"].ledger if r["scope"] == "network" and r["side"] is None]
    assert any(abs(r["t_sim_s"] - round(r["t_sim_s"])) > 1e-6 for r in rows)
    assert all(r["closed"] for r in rows)
