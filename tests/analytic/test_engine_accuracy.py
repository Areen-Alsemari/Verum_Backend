"""Engine accuracy: receipt rise, trajectories, step halving and the crossing time.

Inputs: the written scenarios (S0-A, S0-B, S0-C, REJ-2), the hydraulic model and
independent integrations with ``scipy.integrate.solve_ivp``. Outputs: pass/fail.

Derivations (hand arithmetic):
    * S0-B. The receipt flow starts at 0 and follows q(t) = Q (1 - exp(-t/tau)),
      Q = 600 m3/h, tau = 2 s. The volume received in time T is
      Q T - Q tau (1 - exp(-T/tau)), so after 3600 s it is 600 m3 - 0.33333 m3 (the
      transient deficit Q tau = 600/3600 x 2). With A = 706.858 m2 on the floating branch,
      the level rise is (600 - 0.33333)/706.858 = 0.848826 - 0.000472 = 0.848354 m. The
      engine adds the trapezoid error of the Heun stage average, (dt^2/12) q'(0) / A =
      1.0e-5 m at dt = 1 s.
    * Accuracy target (decision D17): level error <= 0.025 mm = 2.5e-5 m.
    * REJ-2. From 7.3 m to the stored minimum 7.1946 m the level falls 0.1054 m, i.e.
      74.5 m3; at about 305 m3/h (0.0847 m3/s) that takes about 880 s.
Independence: the S0-B reference is a closed-form expression (independent). The S0-A,
S0-C and REJ-2 references integrate the same steady flow function (the production
hydraulic model) with an adaptive RK45 scheme, so they are independent in the time
integration only, not in the hydraulics. The step-halving study uses the S0-B closed
form for the order, and the RK45 reference for S0-A.

Source: decisions D3, D17; ``revised/01_facility_tanks_topology.md`` section 5 (E6).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from _series import Series
from verum.graph import Lineup
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    ReceiptBoundary,
    SteadyInputs,
    pumping_minimum_level,
)
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import EpisodeResult
from verum.sim.scenario import load_scenario
from verum.tanks import TankGeometry, load_tank_geometry
from verum.truth import NullSink

RHO = 750.0
TARGET = 2.5e-5  # level error target, decision D17 (0.025 mm)
SAMPLES = [600.0 * k for k in range(1, 7)]
SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"


@pytest.fixture(scope="module")
def geometry() -> TankGeometry:
    return load_tank_geometry()


def _volumes_at(series: Series, tank: str, times: list[float]) -> list[float]:
    at = {t: v for t, side, _lvl, v, _f in series.tank[tank] if side != "pre_event"}
    return [at[t] for t in times]


def _lineup(mode_name: str, model: HydraulicModel) -> Lineup:
    mode = load_lineup_table(model.topology).mode(mode_name)
    return Lineup(mode.open_valves, mode.running_pumps)


# --- S0-B ----------


def test_s0b_level_rise_with_the_receipt_ramp_correction(
    series: dict[str, Series], geometry: TankGeometry
) -> None:
    start = geometry.volume_m3(9.0, RHO)
    end = _volumes_at(series["S0-B"], "TK-101", [3600.0])[0]
    area = geometry.area_m2
    rise = (end - start) / area
    ideal = 600.0 / area  # 0.848826 m, a constant 600 m3/h for one hour
    deficit = (600.0 / 3600.0) * 2.0  # Q tau, m3
    assert ideal == pytest.approx(0.848826, abs=1e-6)
    assert deficit / area == pytest.approx(0.000472, abs=1e-6)
    assert rise == pytest.approx(ideal - deficit / area, abs=TARGET)
    assert ideal - rise == pytest.approx(0.000472, abs=TARGET)
    # The level at the end lies on the floating branch: the rise is a volume over a constant area.
    assert geometry.roof_state(9.0 + rise, RHO) == "floating"


def test_s0b_receipt_flow_follows_the_first_order_response(series: dict[str, Series]) -> None:
    flows = {t: q for t, side, q in series["S0-B"].edge["E001"] if side != "pre_event"}
    for t in (0.0, 1.0, 2.0, 4.0, 10.0):
        expected = (600.0 / 3600.0) * (1.0 - math.exp(-t / 2.0))
        assert flows[t] == pytest.approx(expected, rel=1e-6, abs=1e-9)
    assert flows[3600.0] == pytest.approx(600.0 / 3600.0, rel=1e-9)


# --- S0-A and S0-C against an independent integration ----------


def test_s0a_trajectory_matches_an_adaptive_integration(
    model: HydraulicModel, series: dict[str, Series], geometry: TankGeometry
) -> None:
    lineup = _lineup("DELIVER_101_A", model)

    def rhs(_t: float, y: Any) -> list[float]:
        inputs = SteadyInputs(
            lineup, {"TK-101": geometry.level_m(y[0], RHO)}, SCENARIO, 25.0,
            fitting_profile="reference_fittings", delivery=DeliveryBoundary(),
        )  # fmt: skip
        return [model.solve(inputs).tank_net_inflow_m3s["TK-101"]]

    sol = solve_ivp(
        rhs,
        [0.0, 3600.0],
        [geometry.volume_m3(9.0, RHO)],
        method="RK45",
        rtol=1e-10,
        atol=1e-7,
        t_eval=SAMPLES,
    )
    engine = _volumes_at(series["S0-A"], "TK-101", SAMPLES)
    errors = [
        abs(geometry.level_m(a, RHO) - geometry.level_m(b, RHO))
        for a, b in zip(engine, sol.y[0], strict=True)
    ]
    assert max(errors) <= TARGET
    # Hand check: about 311 m3/h delivered for one hour (the 312.5 m3/h duty point, falling slowly).
    drawn = geometry.volume_m3(9.0, RHO) - engine[-1]
    assert 305.0 < drawn < 315.0


def test_s0c_trajectories_match_an_adaptive_integration(
    model: HydraulicModel, series: dict[str, Series], geometry: TankGeometry
) -> None:
    lineup = _lineup("RECEIVE_101_DELIVER_102_A", model)

    def rhs(t: float, y: Any) -> list[float]:
        q = 600.0 * (1.0 - math.exp(-t / 2.0))
        levels = {
            "TK-101": geometry.level_m(y[0], RHO),
            "TK-102": geometry.level_m(y[1], RHO),
            "TK-103": 5.0,
        }
        inputs = SteadyInputs(
            lineup, levels, SCENARIO, 25.0, fitting_profile="reference_fittings",
            receipt=ReceiptBoundary(flow_m3h=q), delivery=DeliveryBoundary(),
        )  # fmt: skip
        r = model.solve(inputs)
        return [r.tank_net_inflow_m3s["TK-101"], r.tank_net_inflow_m3s["TK-102"]]

    y0 = [geometry.volume_m3(9.0, RHO), geometry.volume_m3(7.0, RHO)]
    sol = solve_ivp(rhs, [0.0, 3600.0], y0, method="RK45", rtol=1e-10, atol=1e-7, t_eval=SAMPLES)
    for i, tank in enumerate(("TK-101", "TK-102")):
        engine = _volumes_at(series["S0-C"], tank, SAMPLES)
        errors = [
            abs(geometry.level_m(a, RHO) - geometry.level_m(b, RHO))
            for a, b in zip(engine, sol.y[i], strict=True)
        ]
        assert max(errors) <= TARGET, tank


# --- step halving ----------


def _final_volume(model: HydraulicModel, sid: str, dt: float) -> float:
    cfg0 = load_sim_config()
    cfg = dataclasses.replace(
        cfg0,
        parameters={
            **cfg0.parameters,
            "time_step_s": ParamValue.selected(dt, "s", "DESIGN", "TEST-STEP-HALVING"),
        },
    )
    engine = Engine(
        model, load_lineup_table(model.topology), load_scenario(sid), cfg, NullSink(), "EP-STUDY"
    )
    outcome = engine.run()
    assert outcome.rejection is None and outcome.final_t == 3600.0
    return outcome.final_volumes["TK-101"]


@pytest.fixture(scope="module")
def halving(model: HydraulicModel, geometry: TankGeometry) -> dict[float, dict[str, float]]:
    """Level error of the final state of S0-B (closed form) and S0-A (adaptive reference)."""
    area = geometry.area_m2
    exact_b = (
        geometry.volume_m3(9.0, RHO) + 600.0 - (600.0 / 3600.0) * 2.0 * (1.0 - math.exp(-1800.0))
    )
    lineup = _lineup("DELIVER_101_A", model)

    def rhs(_t: float, y: Any) -> list[float]:
        inputs = SteadyInputs(
            lineup,
            {"TK-101": geometry.level_m(y[0], RHO)},
            SCENARIO,
            25.0,
            fitting_profile="reference_fittings",
            delivery=DeliveryBoundary(),
        )
        return [model.solve(inputs).tank_net_inflow_m3s["TK-101"]]

    ref_a = solve_ivp(
        rhs,
        [0.0, 3600.0],
        [geometry.volume_m3(9.0, RHO)],
        method="RK45",
        rtol=1e-10,
        atol=1e-7,
        t_eval=[3600.0],
    ).y[0][0]
    table = {}
    for dt in (2.0, 1.0, 0.5, 0.25):
        table[dt] = {
            "S0-A": (_final_volume(model, "S0-A", dt) - ref_a) / area,
            "S0-B": (_final_volume(model, "S0-B", dt) - exact_b) / area,
        }
    return table


def test_s0b_step_halving_shows_second_order_and_meets_the_target_at_one_second(
    halving: dict[float, dict[str, float]],
) -> None:
    errors = {dt: abs(v["S0-B"]) for dt, v in halving.items()}
    orders = [math.log2(errors[a] / errors[b]) for a, b in ((2.0, 1.0), (1.0, 0.5), (0.5, 0.25))]
    assert all(1.8 <= p <= 2.2 for p in orders), orders
    assert min(orders) >= 0.8  # decision D8: observed order of at least 0.8 on three grids
    assert (
        errors[1.0] <= TARGET < errors[2.0]
    )  # 1 s is the largest step of the grid that meets the target
    assert errors[0.25] < errors[0.5] < errors[1.0]


def test_s0b_error_matches_the_hand_trapezoid_estimate(
    halving: dict[float, dict[str, float]],
) -> None:
    # (dt^2/12) q'(0) / A with q'(0) = Q/tau and A = 706.858 m2.
    for dt, row in halving.items():
        estimate = (dt**2 / 12.0) * (600.0 / 3600.0 / 2.0) / 706.858347
        assert abs(row["S0-B"]) == pytest.approx(estimate, rel=0.05)


def test_s0a_is_smooth_enough_that_every_step_meets_the_target(
    halving: dict[float, dict[str, float]],
) -> None:
    assert all(abs(row["S0-A"]) <= TARGET for row in halving.values())
    # S0-A errors sit at the solver-noise level (below 1e-8 m): no order is claimed.
    assert all(abs(row["S0-A"]) < 1e-8 for row in halving.values())


# --- REJ-2 ----------


def test_rej2_crossing_time_matches_an_independent_integration(
    model: HydraulicModel,
    episodes: dict[str, EpisodeResult],
    geometry: TankGeometry,
) -> None:
    rejection = episodes["REJ-2"].outcome.rejection
    assert rejection is not None
    minimum = pumping_minimum_level("TK-101", 45.0, "reference_fittings", 4.0).value
    lineup = _lineup("DELIVER_101_A", model)

    def rhs(_t: float, y: Any) -> list[float]:
        inputs = SteadyInputs(
            lineup,
            {"TK-101": geometry.level_m(y[0], RHO)},
            SCENARIO,
            45.0,
            fitting_profile="reference_fittings",
            delivery=DeliveryBoundary(),
        )
        return [model.solve(inputs).tank_net_inflow_m3s["TK-101"]]

    def crossing(_t: float, y: Any) -> float:
        return float(geometry.level_m(y[0], RHO) - minimum)

    crossing.terminal = True  # type: ignore[attr-defined]
    crossing.direction = -1  # type: ignore[attr-defined]
    sol = solve_ivp(
        rhs,
        [0.0, 3600.0],
        [geometry.volume_m3(7.3, RHO)],
        method="RK45",
        rtol=1e-10,
        atol=1e-7,
        events=crossing,
    )
    t_ref = float(sol.t_events[0][0])
    assert 878.0 < t_ref < 884.0  # hand estimate: 74.5 m3 at about 0.0847 m3/s
    # The crossing time error follows from the level error target: 2.5e-5 m / (4.3e-4 m/s) = 0.06 s.
    assert rejection["t_sim_s"] == pytest.approx(t_ref, abs=0.06)
    assert rejection["gate"] == "SG0"
    assert minimum == pytest.approx(7.1946, abs=1e-4)
    assert np.isfinite(t_ref)
