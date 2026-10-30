"""Integrator checks: tolerance halving and an independent stiff solver.

Halving the tolerances of the implicit integrator must change the final tank levels by less than the
accuracy target. The right-hand side of the emergency closure is also integrated with a different
method (LSODA) and compared in flow along the collapse and in the delivered volume. The two checks
concern the numerics and not the model.

See D17 and D22.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from sim_helpers import esd_timeline
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim import dynamics as dyn
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import NullSink

TARGET = 2.5e-5
AREA = 706.858347


def _engine(model: HydraulicModel, scale: float = 1.0) -> Engine:
    cfg0 = load_sim_config()
    cfg = dataclasses.replace(
        cfg0,
        parameters={
            **cfg0.parameters,
            "integrator_rtol": ParamValue.selected(
                cfg0["integrator_rtol"] * scale, "1", "DESIGN", "TEST-TOLERANCE"
            ),
            "integrator_atol_m3s": ParamValue.selected(
                cfg0["integrator_atol_m3s"] * scale, "m3/s", "DESIGN", "TEST-TOLERANCE"
            ),
        },
    )
    scenario = dataclasses.replace(load_scenario("S0u-E"), duration_s=3000.0)
    return Engine(model, load_lineup_table(model.topology), scenario, cfg, NullSink(), "EP")


@pytest.mark.slow
def test_halving_the_radau_tolerances_changes_the_levels_by_less_than_the_target(
    model: HydraulicModel,
) -> None:
    """Halving the Radau tolerances changes the final tank levels by less than the 2.5e-5 m accuracy
    target. Independent: yes, because the comparison is between two runs of the same model at
    different tolerances.
    """
    base, halved = _engine(model).run(), _engine(model, 0.5).run()
    assert base.rejection is None and halved.rejection is None
    geometry = _engine(model).geometry
    for tank in base.final_volumes:
        d_level = abs(
            geometry.level_m(base.final_volumes[tank], 750.0)
            - geometry.level_m(halved.final_volumes[tank], 750.0)
        )
        assert d_level < TARGET, (tank, d_level)
        assert d_level < TARGET * 1e-3  # in practice far below the target
    assert base.crossings == halved.crossings or all(
        abs(a["t_sim_s"] - b["t_sim_s"]) < 1e-6
        for a, b in zip(base.crossings, halved.crossings, strict=True)
    )


@pytest.mark.slow
def test_lsoda_and_radau_agree_on_the_esd_closure_flow_and_volume(model: HydraulicModel) -> None:
    """LSODA and Radau agree on the flow and the delivered volume over the 10 s closure stroke.
    Independent: yes, because the two integration methods are independent, though the right-hand
    side is shared.
    """
    engine = _engine(model)
    timeline = esd_timeline()
    engine.run(until=timeline["request"])  # the closure is ordered at this instant
    st = engine.state
    assert st.t == pytest.approx(timeline["request"]) and st.valves["XV-R000"].target == 0.0
    t_end = timeline["closed"]
    plan = engine._plan(st.t, t_end)  # noqa: SLF001
    assert plan.receipt is not None
    rhs = dyn.make_rhs(plan.receipt, None, st.valves)
    y0 = (st.receipt_flow_m3h / 3600.0, 0.0, 0.0, 0.0)
    radau = dyn.advance(rhs, st.t, t_end, y0, 1e-9, 1e-12)
    lsoda = solve_ivp(
        rhs, (st.t, t_end), list(y0), method="LSODA", rtol=1e-10, atol=1e-13, dense_output=True,
        max_step=0.05,
    )  # fmt: skip
    assert lsoda.success
    for t in (st.t + 1.0, t_end - 1.0, t_end - 0.4, t_end - 0.3, t_end - 0.2, t_end - 0.1, t_end):
        q_r, q_l = float(radau.dense(t)[0]), float(lsoda.sol(t)[0])
        assert q_r == pytest.approx(q_l, abs=2e-6), t  # m3/s, about 0.007 m3/h
    volume_radau, volume_lsoda = radau.y1[2], float(lsoda.y[2, -1])
    assert abs(volume_radau - volume_lsoda) * 1.0 / AREA < TARGET * 1e-2  # as a level, m
    assert volume_radau == pytest.approx(volume_lsoda, abs=1e-6)
    assert np.isfinite(volume_radau) and 1.6 < volume_radau < 1.7  # 600 m3/h for about 10 s
