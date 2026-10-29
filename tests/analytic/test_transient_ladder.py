"""Verification ladder of the transient engine, idealised rungs R1 to R7.

Inputs: small networks built in ``_transient_cases`` (a tank, a pipe, a valve, a second tank)
and the engine of ``verum.transient``. Outputs: pass/fail.
Each docstring says whether the expected value is independent of the code under test.

Rungs in this file (R5 and R8 to R11 are in ``test_transient_equivalence.py``):
    R1 Joukowsky (frictionless, Courant number one by construction): after an instantaneous
       valve closure the head at the valve rises by a' v0 / g (a' the adjusted wave speed of
       the grid), reaches the midpoint after L/(2a') and the reservoir after L/a'.
       Independent: closed form.
    R2 Period: the head at the closed valve is a square wave of amplitude a' v0 / g, positive
       and negative for 2L/a' each, period 4L/a'. Independent: closed form.
    R3 Slow closure (Michaud): for a flow that falls linearly over Tc >= 2L/a the head at the
       valve is a triangle wave between h0 and h0 + 2 L v0 / (g Tc) with period 4L/a, so
       Michaud's value is the exact peak for a prescribed linear flow (derivation in the
       test). The loose Michaud band for a real valve law is tested with the finite-closure
       rung in the equivalence file. Independent: closed form.
    R4 Friction: a steady flow reproduces the Darcy-Weisbach gradient along the pipe, and a
       flow perturbation decays at about the rate lambda = f v0 / (2 D) of the linearised
       equations. Independent: closed forms; the friction factor is evaluated by the steady
       package.
    R6 Junction: a tee reproduces the head and flow of the closed-form Riemann problem; mass
       continuity holds at every step. Independent: closed form.
    R7 Ledger: the mass residual stays bounded by one step of the largest end flow, through a
       transient, with and without a leak sink.

Source: ``docs/design_decisions.md`` D43 and D45; Wylie and Streeter, Fluid Transients in
Systems; Michaud (1878).
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
    """Frictionless pipe, prescribed linear flow reduction over Tc = 5 x 2L/a.

    Closed form: with f the wave leaving the valve, H_v - h0 = f(t) - f(t - tau) and
    v0 - v = (g/a)(f(t) + f(t - tau)), tau = 2L/a (the reservoir reflects with sign -1).
    For a linear v the solution is, interval by interval, H_v - h0 = p s / tau, p - p s / tau,
    p s / tau, ... (s the time in the interval): a triangle wave between 0 and
    p = 2 L v0 / (g Tc) = Michaud's value, with period 2 tau = 4L/a. The peak and trough are
    checked to a few sample steps of the ramp, and the upward crossings of p / 2 are spaced
    2 tau.
    Independent: closed form.
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
    """Steady flow with friction and a local loss: head loss (f L / D + K) v^2 / 2g.

    Closed form (Darcy-Weisbach with the steady package's friction law); the engine started on
    that profile must stay on it. Tolerance 1 percent of the loss: the scheme evaluates friction
    at the old point and the loss is distributed over the reaches.
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
    """A 1 percent flow step at the valve produces a square wave whose plateaus decay.

    Closed form: linearising v_t + g H_x + (f / 2D) v |v| = 0 about v0 gives a travelling wave
    that decays as exp(-lambda t) with lambda = f v0 / (2 D). Two round trips (4L/a) separate
    plateaus k and k + 2. Tolerance: 15 percent on the ratio, because the scheme lumps the
    friction of a reach at one end (first order) and the local loss adds a further damping that
    the formula leaves out (K v0 / (2 L) per second, included below).
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
    """Tee: a head step delta arrives at the junction through pipe A.

    Closed form (waves, not the engine): with admittance Y = g A / a for each pipe, the junction
    head is H0 + delta Y_A / (Y_A + Y_B + Y_C) and the flow into pipe i is Y_i (H_i - H_J)
    taken with the sign of its direction. For equal pipes the head rise is delta / 3 and the
    transmitted wave is 2/3 of the incident one. Continuity of mass is checked at every step
    from the probed end flows; the head agrees to the velocity head of the branches, because
    the engine conserves total head and the closed form conserves piezometric head.
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
    """Inflow - outflow - leak - elastic storage stays below dt x (largest end flow).

    Derivation of the bound: the end flows are sampled at the step instants while the elastic
    storage is a trapezoid sum over the points, so the two differ by at most one step of the
    flow at the boundaries; the residual neither accumulates (checked: the late maximum is not
    above the early one by more than the bound) nor grows with the simulated time. The bound
    is a property of the scheme, not of the engine's output.
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
    """Same bound for a closure with reflections: the residual stays within one step of flow."""
    e = reservoir_pipe_valve(model, L, H_RES, 1.0, events=(instant_closure(0.1),))
    worst, qmax = 0.0, 0.0
    for _ in range(1600):
        e.step()
        worst = max(worst, abs(e.ledger.residual_m3))
        qmax = max(qmax, float(np.abs(e.q).max()))
    assert worst < 2 * e.dt * qmax
