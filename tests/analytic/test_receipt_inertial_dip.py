"""Inertial head of the receipt column after a set-point step: hand values and the transient engine.

A set-point step makes the head at the PT-001 tap jump by the inertance of the downstream column
times dQ/dt, and the rigid-column engine is compared in the mean with the transient engine, which
resolves the elastic oscillation. The comparison is between two models of the same equations and is
not validation against measurement. The derivations and the choice of window are in the "Receipt
inertial dip" section of the verification notes.

See D22 and D36.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

import _reference_hydraulics as ref
from _series import Series, load_series
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import Probe

RHO, G, PATM, TAU = 750.0, 9.80665, 101325.0, 2.0
A300, A200 = math.pi * ref.D300**2 / 4, math.pi * ref.D200**2 / 4
LAMBDA_E001 = 30.0 / (G * A300)
LAMBDA_E002 = 15.0 / (G * A300)
LAMBDA_TAP = 105.0 / (G * A300) + 45.0 / (G * A200)
LAMBDA_DOWN = 120.0 / (G * A300) + 45.0 / (G * A200)
# (diameter, length, fitting K) of the edges from the start of E002 to the tank nozzle.
DOWNSTREAM = (
    (ref.D300, 15.0, 1.0),
    (ref.D300, 105.0, 0.4),
    (ref.D200, 36.0, 0.6),
    (ref.D200, 9.0, 1.4),
)
SAMPLES = (1.0, 2.0, 4.0)
WINDOW_S = 2.0


def head300(p_abs: float, q: float) -> float:
    return 1.0 + (p_abs - PATM) / (RHO * G) + 0.5 * (q / A300) ** 2 / G


def downstream_loss(q: float) -> float:
    return sum(ref.loss(q, d, length, k) for d, length, k in DOWNSTREAM)


class Case:
    """Rows of one episode around a set-point step, indexed by time and side."""

    def __init__(
        self, s: Series, t_step: float, q_set_m3h: float, calibrate_at: tuple[float, str | None]
    ):
        self.t_step, self.q_set = t_step, q_set_m3h / 3600.0
        self.q = {(t, side): v for t, side, v in s.edge["E001"]}
        self.e001 = {(t, side): (a, b) for t, side, a, b in s.edge_p["E001"]}
        self.e002 = {(t, side): (a, b) for t, side, a, b in s.edge_p["E002"]}
        self.level = {(t, side): lv for t, side, lv, _v, _f in s.tank["TK-101"]}
        self.tap = {
            (t, side): float(h or 0.0) for t, side, h in s.head["PIPELINE_RECEIPT_BOUNDARY"]
        }
        q0 = self.q[calibrate_at]
        h0 = head300(self.e002[calibrate_at][0] or 0.0, q0)
        self.z = h0 - self.level[calibrate_at] - downstream_loss(q0)

    def rate(self, key: tuple[float, str | None]) -> float:
        return (self.q_set - self.q[key]) / TAU

    def pt001_head(self, key: tuple[float, str | None]) -> float:
        return head300(self.e002[key][0] or 0.0, self.q[key])

    def predicted(self, key: tuple[float, str | None], qdot: float) -> float:
        return self.z + self.level[key] + downstream_loss(self.q[key]) + LAMBDA_DOWN * qdot


def check_grid_rows(c: Case) -> None:
    for dt in SAMPLES:
        key = (c.t_step + dt, None)
        flow, qdot = c.q[key], c.rate(key)
        (p1, p1b), (p2, p2b) = c.e001[key], c.e002[key]
        assert p1 is not None and p1b is not None and p2 is not None and p2b is not None
        qd1 = (
            head300(p1, flow) - head300(p1b, flow) - ref.loss(flow, ref.D300, 30.0, 0.0)
        ) / LAMBDA_E001
        qd2 = (
            head300(p2, flow) - head300(p2b, flow) - ref.loss(flow, ref.D300, 15.0, 1.0)
        ) / LAMBDA_E002
        assert qd1 == pytest.approx(qdot, abs=2e-6), dt
        assert qd2 == pytest.approx(qdot, abs=2e-6), dt
        assert c.pt001_head(key) == pytest.approx(c.predicted(key, qdot), abs=2e-3), dt


def check_event_rows(c: Case, qdot_before: float, qdot_after: float) -> None:
    pre, post = (c.t_step, "pre_event"), (c.t_step, "post_event")
    assert c.q[pre] == c.q[post]  # the flow is continuous across the command
    jump = LAMBDA_DOWN * (qdot_after - qdot_before)
    assert c.pt001_head(post) - c.pt001_head(pre) == pytest.approx(jump, abs=1e-3)
    assert c.tap[post] - c.tap[pre] == pytest.approx(
        LAMBDA_TAP * (qdot_after - qdot_before), abs=1e-3
    )
    assert c.pt001_head(pre) == pytest.approx(c.predicted(pre, qdot_before), abs=2e-3)
    assert c.pt001_head(post) == pytest.approx(c.predicted(post, qdot_after), abs=2e-3)


def test_lambda_down_by_hand() -> None:
    """The inertance downstream of the tap is 311.64 s2/m2 and a step of 150 m3/h/s gives a dip of
    95.5 kPa. Independent: yes, because the values are hand arithmetic.
    """
    assert LAMBDA_DOWN == pytest.approx(311.64, abs=0.01)
    assert LAMBDA_TAP == pytest.approx(290.45, abs=0.01)
    assert LAMBDA_DOWN * 150.0 / 3600.0 * RHO * G == pytest.approx(95.5e3, rel=2e-3)


def test_step_down_dip_and_the_jump_at_the_command(series: dict[str, Series]) -> None:
    """After a set-point step down the head dips at the command as the hand value and the flow rate
    follows the first-order law. Independent: yes, because the inertance and the rate come from hand
    values and the controller law.
    """
    c = Case(series["S0-G"], 1200.0, 300.0, (1199.0, None))
    check_grid_rows(c)
    check_event_rows(c, 0.0, -150.0 / 3600.0)


def test_start_up_rise_and_the_jump_at_the_command(series: dict[str, Series]) -> None:
    """At start-up the head jumps at the command as the hand value for a rate of Q_set / tau.
    Independent: yes, because the inertance and the rate come from hand values and the controller
    law.
    """
    c = Case(series["S0-B"], 0.0, 600.0, (0.0, "pre_event"))
    check_grid_rows(c)
    check_event_rows(c, 0.0, 600.0 / TAU / 3600.0)


@pytest.fixture(scope="module")
def step_up(tmp_path_factory: pytest.TempPathFactory, model: HydraulicModel) -> Series:
    base = load_scenario("S0-G")
    scenario = dataclasses.replace(
        base,
        duration_s=110.0,
        receipt_flow_m3h=300.0,
        receipt_setpoint_m3h=300.0,
        schedule=[{"t_s": 100.0, "command": "receipt_setpoint", "value_m3h": 600.0}],
    )
    out = tmp_path_factory.mktemp("step_up")
    result = run_episode("S0-G", out, model, scenario)
    assert not result.rejected
    return load_series(result.directory)


def test_step_up_rise_and_the_jump_at_the_command(step_up: Series) -> None:
    """After a set-point step up the head rises at the command as the hand value. Independent: yes,
    because the inertance and the rate come from hand values and the controller law.
    """
    c = Case(step_up, 100.0, 600.0, (99.0, None))
    check_grid_rows(c)
    check_event_rows(c, 0.0, 300.0 / TAU / 3600.0)


def moc_window_mean_barg(
    model: HydraulicModel,
    level_m: float,
    flow_m3h: float,
    to_m3h: float,
    centres: tuple[float, ...],
) -> dict[float, float]:
    lineup = load_lineup_table(model.topology).mode("RECEIVE_101").lineup
    spec = TransientSpec(
        lineup=lineup,
        tank_levels_m={"TK-101": level_m, "TK-102": 7.0, "TK-103": 5.0},
        fitting_profile="reference_fittings",
        receipt_flow_m3h=flow_m3h,
        receipt_setpoint_m3h=flow_m3h,
        setpoint_events=((10.0, to_m3h),),
    )
    engine = TransientEngine(model, spec)
    rec = engine.run(10.0 + max(centres) + 2.0, [Probe("pt", "E002", 0.0)], stride=1)
    t = rec["t"] - 10.0
    z = engine.z[engine.point_index("E002", 0.0)]
    p = engine.rho * engine.g * (rec["pt.H"] - z)
    half = WINDOW_S / 2.0
    return {c: float(p[(t >= c - half) & (t <= c + half)].mean()) / 1e5 for c in centres}


@pytest.mark.parametrize(
    ("label", "key", "t_step", "flow", "to", "side_level"),
    [
        ("step_down", "S0-G", 1200.0, 600.0, 300.0, "pre_event"),
        ("start_up", "S0-B", 0.0, 0.0, 600.0, "pre_event"),
    ],
)
def test_rigid_column_agrees_with_the_transient_engine_in_the_mean(
    series: dict[str, Series],
    model: HydraulicModel,
    label: str,
    key: str,
    t_step: float,
    flow: float,
    to: float,
    side_level: str,
) -> None:
    """The rigid-column pressure after a step agrees with the mean of the transient-engine pressure
    over a 2 s window within 10 percent of the dip. Independent: no, because the transient engine is
    a separate model of the same equations and not validation against measurement.
    """
    s = series[key]
    level = next(
        lv for t, side, lv, _v, _f in s.tank["TK-101"] if t == t_step and side == side_level
    )
    moc = moc_window_mean_barg(model, level, flow, to, SAMPLES)
    rigid = {
        t: p
        for t, side, p, _b in s.edge_p["E002"]
        if side is None and p is not None and t - t_step in SAMPLES
    }
    q = {t: v for t, side, v in s.edge["E001"] if side is None and t - t_step in SAMPLES}
    for dt in SAMPLES:
        qdot = (to / 3600.0 - q[t_step + dt]) / TAU
        dip_bar = LAMBDA_DOWN * abs(qdot) * RHO * G / 1e5
        rigid_barg = (rigid[t_step + dt] - PATM) / 1e5
        assert abs(moc[dt] - rigid_barg) <= 0.10 * dip_bar, (
            label,
            dt,
            moc[dt],
            rigid_barg,
            dip_bar,
        )


def test_rigid_column_agrees_with_the_transient_engine_for_a_step_up(
    step_up: Series, model: HydraulicModel
) -> None:
    """For a step up the rigid-column pressure agrees with the windowed mean of the transient engine
    within 10 percent of the dip. Independent: no, because the transient engine is a separate model
    of the same equations and not validation against measurement.
    """
    level = next(
        lv for t, side, lv, _v, _f in step_up.tank["TK-101"] if t == 100.0 and side == "pre_event"
    )
    moc = moc_window_mean_barg(model, level, 300.0, 600.0, SAMPLES)
    rigid = {t: p for t, side, p, _b in step_up.edge_p["E002"] if side is None and p is not None}
    q = {t: v for t, side, v in step_up.edge["E001"] if side is None}
    for dt in SAMPLES:
        qdot = (600.0 / 3600.0 - q[100.0 + dt]) / TAU
        dip_bar = LAMBDA_DOWN * abs(qdot) * RHO * G / 1e5
        assert abs(moc[dt] - (rigid[100.0 + dt] - PATM) / 1e5) <= 0.10 * dip_bar, dt
