"""Windowed use of the transient engine: a short window equals the continuous run (T1).

Inputs: the S0u-E isolation (XV-R000 over 10 s, XV-R101 over 30 s, 600 m3/h received into
TK-101 at 12.98 m) run (a) from a steady start 2 s before the first command, and (b) from the
same steady state but with the command given 20 s into a continuous run. Outputs: pass/fail.
Key assumptions:
    * The proposed rule (docs/transient_engine.md): a transient window starts from the steady
      state of the rigid-column engine at the start of the window, a little before the first
      command, and ends when the pressures have settled; the equivalence below is what makes
      that start legitimate, because the state before the command is stationary.
    * The command instants are placed half a step after a step boundary in both runs, so that
      the same step applies the command and no comparison depends on a rounding of the clock.
    * Independent: equality of two runs of the same engine is the property tested; it shows
      that the start-up of a window carries no memory of the earlier steady period.

Source: ``docs/design_decisions.md`` D47; ``docs/transient_engine.md``.
"""

from __future__ import annotations

import numpy as np
import pytest

from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import Probe, ValveEvent

LEVELS = {"TK-101": 12.98, "TK-102": 7.0, "TK-103": 5.0}


def _run(
    model: HydraulicModel, command_step: int, tail_s: float
) -> tuple[TransientEngine, np.ndarray]:
    probe = TransientSpec(lineup=load_lineup_table(model.topology).mode("RECEIVE_101").lineup,
                          tank_levels_m=LEVELS)  # fmt: skip
    dt = TransientEngine(model, probe).dt
    t0 = (command_step + 0.5) * dt
    spec = TransientSpec(
        lineup=probe.lineup, tank_levels_m=LEVELS, receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0,
        valve_events=(ValveEvent("XV-R000", t0, 0.0, 10.0), ValveEvent("XV-R101", t0, 0.0, 30.0)),
    )  # fmt: skip
    e = TransientEngine(model, spec)
    rec = e.run(t0 + tail_s, [Probe("pt001", "E002", 0.0)])
    return e, rec["pt001.H"]


def test_a_two_second_window_reproduces_the_continuous_run_on_t1(model: HydraulicModel) -> None:
    dt = TransientEngine(
        model,
        TransientSpec(
            lineup=load_lineup_table(model.topology).mode("RECEIVE_101").lineup,
            tank_levels_m=LEVELS,
        ),
    ).dt
    window_steps = round(2.0 / dt)
    offset = round(18.0 / dt)
    windowed, h_w = _run(model, window_steps, 12.0)
    continuous, h_c = _run(model, window_steps + offset, 12.0)
    assert len(h_c) - offset == len(h_w)
    shift = offset * dt
    valid = int((windowed.phase.windows[0][0]) / dt)  # nothing after the first window is usable
    # 1e-6 m of head is 0.007 Pa, four orders below the 50 Pa budget of decision D8; the
    # difference is the round-off of the clock and of the start-up drift (about 2e-9 m)
    assert np.max(np.abs(h_c[offset:][:valid] - h_w[:valid])) < 1e-6
    assert len(windowed.phase.windows) == len(continuous.phase.windows) > 0
    for (a, b), (c, d) in zip(windowed.phase.windows, continuous.phase.windows, strict=True):
        assert c - shift == pytest.approx(a, abs=1e-9) and d - shift == pytest.approx(b, abs=1e-9)
    assert windowed.ledger.residual_m3 == pytest.approx(continuous.ledger.residual_m3, abs=1e-9)
