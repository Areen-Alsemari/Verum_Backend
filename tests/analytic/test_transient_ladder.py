"""Verification ladder of the transient engine on idealised networks.

Small networks of a tank, a pipe, a valve and a second tank are compared with closed forms: the
Joukowsky rise and arrival times, the square wave and its period, Michaud's peak for a prescribed
linear flow, the Darcy-Weisbach profile and the decay of a perturbation, the Riemann solution at a
tee, and the bound on the mass residual. The closed forms are in the "Transient engine: idealised
verification ladder" section of the verification notes.

See D43 and D45.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from _transient_cases import A300, D300, G, edge, instant_closure, reservoir_pipe_valve
from verum.graph import Lineup
from verum.hydraulics import HydraulicModel
from verum.hydraulics.friction import friction_factor
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import NetworkDef, Probe

L, V0, H_RES = 200.0, 0.3, 100.0


@pytest.fixture(scope="module")
def mdl(model: HydraulicModel) -> HydraulicModel:
    return model


def _closure_run(
    model: HydraulicModel, t_end: float, t_close: float = 0.1
) -> tuple[TransientEngine, float, dict[str, np.ndarray]]:
    e = reservoir_pipe_valve(model, L, H_RES, V0, events=(instant_closure(t_close),))
    a = e.grid[0].wave_speed_m_s
    probes = [Probe("valve", "P1", 1.0), Probe("mid", "P1", 0.5), Probe("res", "P1", 0.0)]
    rec = e.run(t_end, probes)
    return e, a, rec


def test_r1_joukowsky_rise_and_arrival_times(model: HydraulicModel) -> None:
    """After an instantaneous closure the head at the valve rises by a v0 / g and the wave reaches
    the midpoint and the reservoir at L/(2a) and L/a. Independent: yes, because the reference is a
    closed form.
    """
    e, a, rec = _closure_run(model, 0.1 + 1.9 * 2 * L / 1078.0)
    dt, t = e.dt, rec["t"]
    h0 = H_RES - V0**2 / (2 * G)
    t_close = math.ceil(0.1 / dt) * dt
    rise = a * V0 / G
    assert rise == pytest.approx(33.0, abs=0.2)  # 1078 x 0.3 / 9.81, by hand
    window = (t >= t_close) & (t < t_close + 2 * L / a - 3 * dt)
    assert np.allclose(rec["valve.H"][window], h0 + rise, rtol=0, atol=1e-6)
    # arrival times of the front at the midpoint and the reservoir end (within one step)
    mid_t = t[np.argmax(rec["mid.H"] > h0 + 0.5 * rise)]
    assert mid_t - t_close == pytest.approx(L / (2 * a), abs=2 * dt)
    res_flow = rec["res.Q"]
    first_change = t[np.argmax(np.abs(res_flow - V0 * A300) > 1e-6 * V0 * A300)]
    assert first_change - t_close == pytest.approx(L / a, abs=2 * dt)
    assert np.allclose(rec["valve.H"][t < t_close - dt], h0, atol=1e-9)  # nothing before closure


def test_r2_square_wave_with_period_four_l_over_a(model: HydraulicModel) -> None:
    """The head at the closed valve is a square wave of amplitude a v0 / g with period 4L/a.
    Independent: yes, because the reference is a closed form.
    """
    e, a, rec = _closure_run(model, 0.1 + 4.5 * 2 * L / 1078.0)
    dt, t = e.dt, rec["t"]
    h0 = H_RES - V0**2 / (2 * G)
    rise = a * V0 / G
    t_close = math.ceil(0.1 / dt) * dt
    half = 2 * L / a
    for k, sign in enumerate((+1, -1, +1, -1)):
        centre = t_close + (k + 0.5) * half
        sel = (t > centre - 0.4 * half) & (t < centre + 0.4 * half)
        assert np.allclose(rec["valve.H"][sel], h0 + sign * rise, atol=1e-6), k
    crossings = t[1:][np.diff(np.sign(rec["valve.H"] - h0)) != 0]
    crossings = crossings[crossings > t_close + dt]
    assert np.diff(crossings)[:3] == pytest.approx([half, half, half], abs=3 * dt)
    assert 4 * L / a == pytest.approx(2 * half)


def test_r3_prescribed_linear_flow_peaks_at_michauds_value(model: HydraulicModel) -> None:
    """For a prescribed linear flow reduction over five round trips the head at the valve is a
    triangle wave with Michaud's peak 2 L v0 / (g Tc). Independent: yes, because the reference is a
    closed form.
    """
    a = reservoir_pipe_valve(model, L, H_RES, V0).grid[0].wave_speed_m_s
    tau, tc, t0 = 2 * L / a, 5 * 2 * L / a, 0.05

    def flow(t: float) -> float:
        return V0 * A300 * min(max(1.0 - (t - t0) / tc, 0.0), 1.0)

    e = reservoir_pipe_valve(model, L, H_RES, V0, flow_schedule=flow)
    rec = e.run(t0 + 0.99 * tc, [Probe("valve", "P1", 1.0)])
    h0 = H_RES - V0**2 / (2 * G)
    p = 2 * L * V0 / (G * tc)
    window = (rec["t"] > t0 + 0.05) & (rec["t"] < t0 + 0.99 * tc)
    rise = rec["valve.H"][window] - h0
    step = p * e.dt / tau  # change of the triangle wave in one time step
    assert np.max(rise) == pytest.approx(p, abs=3 * step + 0.003)  # 0.003 m: velocity-head term
    assert np.min(rise) == pytest.approx(0.0, abs=3 * step + 0.003)
    up = np.flatnonzero((rise[:-1] < p / 2) & (rise[1:] >= p / 2))
    spacing = np.diff(rec["t"][window][up])
    assert len(spacing) >= 2 and spacing == pytest.approx(2 * tau, abs=4 * e.dt)


def _friction_start(
    model: HydraulicModel, v0: float, k_local: float
) -> tuple[tuple[float, float], float]:
    """Steady losses (m) of the pipes P1 and P2 and the Darcy factor at velocity v0."""
    re = model.rho * v0 * D300 / model.mu
    f = friction_factor(re, model.roughness / D300)
    head = v0**2 / (2 * G)
    return ((f * L / D300 + k_local) * head, f * 5.0 / D300 * head), f


def test_r4_steady_friction_profile_is_stationary(model: HydraulicModel) -> None:
    """A steady flow started on the Darcy-Weisbach profile with a local loss stays on it within 1
    percent of the loss. Independent: yes, because the reference is a closed form, with the friction
    factor from the steady package.
    """
    v0, k_local = 1.0, 2.0
    loss, _ = _friction_start(model, v0, k_local)
    e = _friction_case(model, v0, k_local, loss, None)
    h_start = e.h.copy()
    e.run(0.04)
    assert np.abs(e.h - h_start).max() < 0.01 * sum(loss)


def _friction_case(
    model: HydraulicModel, v0: float, k_local: float, loss: tuple[float, float], flow_law: object
) -> TransientEngine:
    base = reservoir_pipe_valve(model, L, H_RES, v0, k_local=k_local, friction=True)
    hz = H_RES - v0**2 / (2 * G)
    q0 = v0 * A300
    net = NetworkDef(
        edges=base.net.edges, k=base.net.k, pumps=(), node_z={},
        initial={"P1": (hz, hz - loss[0], q0), "P2": (hz - loss[0], hz - sum(loss), q0)},
    )  # fmt: skip
    spec = TransientSpec(
        lineup=Lineup(frozenset({"XV-1"}), frozenset()),
        tank_levels_m={"T1": H_RES, "T2": H_RES - sum(loss)},
        wave_speeds={300: 1078.2},
        flow_schedules=None if flow_law is None else {"XV-1": flow_law},  # type: ignore[dict-item]
    )
    return TransientEngine(model, spec, net)


def test_r4_oscillation_decays_at_the_linearised_rate(model: HydraulicModel) -> None:
    """A 1 percent flow step produces a square wave whose plateaus decay at the linearised rate f v0
    / (2 D), within 15 percent. Independent: yes, because the reference is a closed form, with the
    friction factor from the steady package.
    """
    v0, k_local = 1.0, 0.0
    loss, f = _friction_start(model, v0, k_local)
    t_step = 0.05

    def law(t: float) -> float:
        return v0 * A300 * (1.0 if t < t_step else 0.99)

    e = _friction_case(model, v0, k_local, loss, law)
    a = e.grid[0].wave_speed_m_s
    half = 2 * L / a
    rec = e.run(t_step + 6.5 * half, [Probe("valve", "P1", 1.0)])
    t, dev = rec["t"], rec["valve.H"] - rec["valve.H"][0]
    t_on = math.ceil(t_step / e.dt) * e.dt
    plateaus = [
        float(np.mean(dev[(t > t_on + (k + 0.25) * half) & (t < t_on + (k + 0.75) * half)]))
        for k in range(6)
    ]
    lam = f * v0 / (2 * D300) + k_local * v0 / (2 * L)
    assert plateaus[0] > 0 > plateaus[1]
    ratio = abs(plateaus[4] / plateaus[2])
    assert ratio == pytest.approx(math.exp(-lam * 2 * half), rel=0.15)


def _tee(model: HydraulicModel, d2: float, d3: float, delta: float = 10.0) -> TransientEngine:
    h0 = 100.0
    net = NetworkDef(
        edges=(
            edge("PA", "T1:outlet_nozzle", "J", 100.0),
            edge("PB", "J", "T2:receipt_nozzle", 100.0, d2),
            edge("PC", "J", "T3:receipt_nozzle", 100.0, d3),
        ),
        k={"PA": 0.0, "PB": 0.0, "PC": 0.0},
        pumps=(),
        node_z={},
        initial={"PA": (h0 + delta, h0 + delta, 0.0), "PB": (h0, h0, 0.0), "PC": (h0, h0, 0.0)},
    )
    spec = TransientSpec(
        lineup=Lineup(frozenset(), frozenset()),
        tank_levels_m={"T1": h0 + delta, "T2": h0, "T3": h0},
        friction_off=True,
        wave_speeds={300: 1078.2, 250: 1082.8, 200: 1089.2},
    )
    return TransientEngine(model, spec, net)


@pytest.mark.parametrize("d2,d3", [(D300, D300), (0.20274, 0.25446)])
def test_r6_junction_matches_the_riemann_solution(
    model: HydraulicModel, d2: float, d3: float
) -> None:
    """A head step arriving at a tee gives the junction head and branch flows of the Riemann
    solution, and mass is conserved at every step. Independent: yes, because the reference is a
    closed form of the wave relations.
    """
    e = _tee(model, d2, d3)
    y = [G * g.area_m2 / g.wave_speed_m_s for g in e.grid]
    expected = 100.0 + 10.0 * y[0] / sum(y)
    probes = [Probe("a", "PA", 1.0), Probe("b", "PB", 0.0), Probe("c", "PC", 0.0)]
    rec = e.run(0.05, probes)
    mass = rec["a.Q"] - rec["b.Q"] - rec["c.Q"]
    assert np.abs(mass).max() < 1e-12
    v_max = max(float(np.max(np.abs(rec["a.Q"]))) / e.grid[0].area_m2, 1e-12)
    for name in ("a", "b", "c"):
        assert np.abs(rec[f"{name}.H"][2:] - expected).max() < 3 * v_max**2 / (2 * G)
    if d2 == D300:
        assert expected == pytest.approx(100.0 + 10.0 / 3.0)
        assert y[1] * 3.333 / (y[0] * 6.667) == pytest.approx(0.5, rel=1e-3)


def _leak_case(model: HydraulicModel, leak: tuple[str, float] | None) -> TransientEngine:
    net = NetworkDef(
        edges=(
            edge("PA", "T1:outlet_nozzle", "J", 100.0),
            edge("PB", "J", "T2:receipt_nozzle", 100.0),
        ),
        k={"PA": 0.0, "PB": 0.0}, pumps=(), node_z={"J": 0.0},
        initial={"PA": (100.0, 100.0, 0.0), "PB": (100.0, 100.0, 0.0)},
    )  # fmt: skip
    spec = TransientSpec(
        lineup=Lineup(frozenset(), frozenset()), tank_levels_m={"T1": 100.0, "T2": 60.0},
        friction_off=True, wave_speeds={300: 1078.2}, leak=leak,
    )  # fmt: skip
    return TransientEngine(model, spec, net)


@pytest.mark.parametrize("leak", [None, ("J", 0.002)])
def test_r7_ledger_residual_is_bounded_by_one_step_of_end_flow(
    model: HydraulicModel, leak: tuple[str, float] | None
) -> None:
    """With and without a leak sink the mass residual stays below one step of the largest end flow
    and does not accumulate. Independent: yes, because the bound is a property of the scheme and not
    of the engine output.
    """
    e = _leak_case(model, leak)
    residuals, qmax = [], 0.0
    for _ in range(2000):
        e.step()
        residuals.append(e.ledger.residual_m3)
        qmax = max(qmax, float(np.abs(e.q).max()))
    bound = 2 * e.dt * qmax
    assert np.abs(residuals).max() < bound
    assert np.abs(residuals[1000:]).max() < np.abs(residuals[:1000]).max() + bound
    if leak is not None:
        assert e.ledger.leak_m3 > 0


def test_r7_ledger_closes_through_an_instantaneous_closure(model: HydraulicModel) -> None:
    """Through an instantaneous closure with reflections the mass residual stays within one step of
    flow. Independent: yes, because the bound is a property of the scheme.
    """
    e = reservoir_pipe_valve(model, L, H_RES, 1.0, events=(instant_closure(0.1),))
    worst, qmax = 0.0, 0.0
    for _ in range(1600):
        e.step()
        worst = max(worst, abs(e.ledger.residual_m3))
        qmax = max(qmax, float(np.abs(e.q).max()))
    assert worst < 2 * e.dt * qmax
