"""Transient engine: grid refinement, steady equivalence, the check valve and restart.

The checks cover three-grid convergence, steady equivalence on the reference lineups, check-valve
closure and reverse-volume accounting, bit-identical restart, agreement of the friction factor and
valve law with the steady package, the series-element root, and import isolation. The slow-limit
check is in a separate module. The expected behaviour is derived in the "Transient engine:
refinement, equivalence and restart" section of the verification notes.

See D43 to D47.
"""

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest

from _hydraulic_cases import INITIAL_LEVELS, deliver_lineup, receive_lineup
from _transient_cases import G, reservoir_pipe_valve
from verum.hydraulics import HydraulicModel
from verum.hydraulics.friction import friction_factor
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import Probe, ValveEvent
from verum.transient.elements import series_flow
from verum.transient.friction import darcy_factor

WAVE_SPEED, DT0, REACHES0 = 1078.2, 0.001, 200
LENGTH = REACHES0 * WAVE_SPEED * DT0  # a' = a on every grid, so only the step size changes
BUDGET_PA, BUDGET_FLOW_M3S = 50.0, 0.02 / 3600.0  # decision D8


def _closure(model: HydraulicModel, refine: int) -> tuple[TransientEngine, dict[str, np.ndarray]]:
    e = reservoir_pipe_valve(
        model, LENGTH, 100.0, 1.5, k_local=1.0, friction=True,
        events=(ValveEvent("XV-1", 0.1, 0.0, 1.0),), dt=DT0 / refine, speeds={300: WAVE_SPEED},
    )  # fmt: skip
    return e, e.run(1.0, [Probe("v", "P1", 1.0)])


def test_r5_three_grids_converge_at_first_order_within_the_d8_budget(model: HydraulicModel) -> None:
    """Three grids of 200 to 800 reaches converge at about first order, and the error of the finest
    grid is below the conservation budget. Independent: yes, because a convergence property is
    checked and not a value of the code.
    """
    series = []
    for refine in (1, 2, 4):
        _, rec = _closure(model, refine)
        ts = np.linspace(0.2, 0.1 + 0.85, 40)
        series.append((np.interp(ts, rec["t"], rec["v.H"]), np.interp(ts, rec["t"], rec["v.Q"])))
    for index, budget in ((0, BUDGET_PA / (750.0 * G)), (1, BUDGET_FLOW_M3S)):
        d12 = float(np.max(np.abs(series[0][index] - series[1][index])))
        d23 = float(np.max(np.abs(series[1][index] - series[2][index])))
        order = math.log2(d12 / d23)
        assert order >= 0.8, (index, order)
        assert d23 / (2.0**order - 1.0) < budget, (index, d23)


def test_r5_unrefined_error_is_reported_against_the_finest_grid(model: HydraulicModel) -> None:
    """The shipped step differs from the finest grid by less than ten times the head budget, which
    is recorded in the engine document. Independent: yes, because the finest grid is the reference
    for a convergence statement about this case.
    """
    _, coarse = _closure(model, 1)
    _, fine = _closure(model, 4)
    ts = np.linspace(0.2, 0.95, 40)
    err = np.max(
        np.abs(np.interp(ts, coarse["t"], coarse["v.H"]) - np.interp(ts, fine["t"], fine["v.H"]))
    )
    assert err * 750.0 * G < 10.0 * BUDGET_PA


REFERENCE_LINEUPS = {
    "receive_101": (receive_lineup("TK-101"), 300.0),
    "receive_102_103": (receive_lineup("TK-102", "TK-103"), 300.0),
    "deliver_101_A": (deliver_lineup("TK-101", "A"), 0.0),
    "deliver_103_B": (deliver_lineup("TK-103", "B"), 0.0),
}


@pytest.mark.parametrize("name", sorted(REFERENCE_LINEUPS))
def test_r9_time_stepping_holds_the_steady_solution_at_every_edge_end(
    model: HydraulicModel, name: str
) -> None:
    """Starting from the steady solve, three seconds of time stepping keep every edge end on the
    steady heads and flows. Independent: no, because the two solvers share the boundary definitions
    and only the fixed point of the characteristic equations is tested.
    """
    lineup, receipt = REFERENCE_LINEUPS[name]
    spec = TransientSpec(
        lineup=lineup, tank_levels_m=dict(INITIAL_LEVELS), fitting_profile="reference_fittings",
        receipt_flow_m3h=receipt, receipt_setpoint_m3h=receipt,
    )  # fmt: skip
    e = TransientEngine(model, spec)
    assert e.steady is not None
    start = {
        (ed.edge_id, end): e.end_state(ed.edge_id, end) for ed in e.edges for end in ("from", "to")
    }
    e.run(3.0)
    rho_g = e.rho * e.g
    for ed in e.edges:
        ends = e.steady.edge_end_pressures_pa_gauge.get(ed.edge_id)
        for end, z, p in (
            ("from", ed.z_from_m, None if ends is None else ends[0]),
            ("to", ed.z_to_m, None if ends is None else ends[1]),
        ):
            head, flow = e.end_state(ed.edge_id, end)
            if p is not None:
                assert head == pytest.approx(z + p / rho_g, abs=1e-6), (ed.edge_id, end)
            assert head == pytest.approx(start[(ed.edge_id, end)][0], abs=1e-6)
            assert flow == pytest.approx(e.steady.edge_flows_m3s[ed.edge_id], abs=1e-9)
    moving = max(abs(f) for f in e.steady.edge_flows_m3s.values())
    assert moving > 0.01  # the lineup carries flow


def _stop_case(model: HydraulicModel, delay: float) -> TransientEngine:
    spec = TransientSpec(
        lineup=deliver_lineup("TK-101", "A"), tank_levels_m=dict(INITIAL_LEVELS),
        fitting_profile="reference_fittings", pump_stops=((1.0, "P-101A"),),
        check_valve_delay_s=delay,
    )  # fmt: skip
    return TransientEngine(model, spec)


def test_r10_check_valve_blocks_reverse_flow_after_its_closure_delay(model: HydraulicModel) -> None:
    """After a pump stop the check valve closes a delay after the flow reverses, passes nothing
    while closed, and the reverse volume it accounts grows with the delay. Independent: yes, because
    the reverse volume is integrated from the probed flow and not from the valve counter.
    """
    volumes = []
    for delay in (0.05, 0.3, 1.0):
        e = _stop_case(model, delay)
        cv = e.checks["CV-PA"]
        down, up = e.point_index("E-PA3", 0.0), e.point_index("E-PA2", 1.0)
        flows: list[float] = []
        while cv.closed_at_s is None and e.t < 12.0:
            e.step()
            flows.append(float(e.q[down]))
        assert cv.closed_at_s is not None and not cv.open
        passed = np.array(flows[:-1])  # the closing step itself passes nothing
        assert np.any(passed < 0.0)
        assert flows[-1] == 0.0
        forward = np.flatnonzero(passed >= 0.0)
        start = (forward[-1] + 2) * e.dt  # time of the first sample of the final reversal
        assert cv.closed_at_s - start == pytest.approx(delay, abs=3 * e.dt)
        assert cv.reverse_volume_m3 == pytest.approx(-float(passed[passed < 0.0].sum()) * e.dt)
        for _ in range(int(0.2 / e.dt)):
            e.step()
            if cv.open:
                break
            assert e.q[down] == 0.0 and e.q[up] == 0.0
        volumes.append(cv.reverse_volume_m3)
    assert volumes[0] < volumes[1] < volumes[2]


def _checkpoint_case(model: HydraulicModel) -> TransientEngine:
    spec = TransientSpec(
        lineup=receive_lineup("TK-101"), tank_levels_m=dict(INITIAL_LEVELS),
        fitting_profile="reference_fittings", receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0, valve_events=(ValveEvent("XV-R000", 0.5, 0.0, 2.0),),
    )  # fmt: skip
    return TransientEngine(model, spec)


def test_r11_runs_are_deterministic_and_a_restart_is_bit_identical(model: HydraulicModel) -> None:
    """Two runs of a case give identical arrays, and a run split at 1.2 s through a checkpoint
    matches the continuous run. Independent: yes, because equality is the property.
    """
    a, b = _checkpoint_case(model), _checkpoint_case(model)
    probes = [Probe("p", "E002", 1.0)]
    full_a, full_b = a.run(2.5, probes), b.run(2.5, probes)
    assert np.array_equal(a.h, b.h) and np.array_equal(a.q, b.q)
    assert np.array_equal(full_a["p.H"], full_b["p.H"])
    first = _checkpoint_case(model)
    first.run(1.2, probes)
    state = first.get_state()
    second = _checkpoint_case(model)
    second.set_state(state)
    second.run(2.5, probes)
    assert second.t == pytest.approx(a.t, abs=1e-12)
    assert np.array_equal(second.h, a.h) and np.array_equal(second.q, a.q)
    assert second.ledger == a.ledger and second.phase.windows == a.phase.windows


def test_darcy_factor_equals_the_steady_packages_law() -> None:
    """The vectorised friction factor equals the steady package's law in the laminar, transitional
    and turbulent ranges. Independent: yes, because the steady module is separate.
    """
    d, rho, mu, rough = 0.30318, 750.0, 5e-4, 4.5e-5
    for v in (0.001, 0.2, 0.6, 1.0, 2.5, 6.0):
        re = rho * v * d / mu
        ours = float(darcy_factor(np.array([v]), np.array([d]), rho, mu, rough)[0])
        assert ours == pytest.approx(friction_factor(re, rough / d), rel=1e-12), v


def test_valve_law_scale_is_k_over_two_g_a_squared(model: HydraulicModel) -> None:
    """The extra loss of a part-open valve is (K(alpha) - K_open) v^2 / 2g with the velocity in the
    edge that leaves the valve. Independent: yes, because the value is hand arithmetic from the
    steady law.
    """
    e = reservoir_pipe_valve(model, 100.0, 100.0, 1.0)
    e.alpha["XV-1"] = 0.4
    e._set_valve("XV-1")
    k = e.series_index["XV-1"]
    area = math.pi * e.edges[1].inner_diameter_m ** 2 / 4.0
    q = 0.05
    expected = model.valve_extra_k(0.4) * (q / area) ** 2 / (2.0 * G)
    assert float(e.k2[k]) * q * q == pytest.approx(expected, rel=1e-12)


def test_series_flow_is_exact_for_a_vanishing_quadratic_term() -> None:
    """The series-element root tends to W / B as the quadratic term vanishes and satisfies the
    equation for a large one. Independent: yes, because the reference is a closed form.
    """
    bs, w = np.array([20.0, 20.0, 20.0]), np.array([3.0, 3.0, -3.0])
    k2 = np.array([0.0, 1e-16, 1e-16])
    q = series_flow(bs, w, np.zeros(3), k2, np.zeros(3, dtype=bool))
    assert q == pytest.approx([0.15, 0.15, -0.15], rel=1e-12)
    big = series_flow(bs[:1], w[:1], np.zeros(1), np.array([100.0]), np.zeros(1, dtype=bool))
    assert 20.0 * big[0] + 100.0 * big[0] ** 2 == pytest.approx(3.0, rel=1e-12)


def test_the_transient_package_imports_neither_truth_nor_gateway_nor_engine() -> None:
    """A fresh interpreter that imports the transient package loads neither the truth store, the
    gateway nor the rigid-column engine. Independent: yes, because the check inspects the loaded
    modules.
    """
    code = (
        "import sys, verum.transient;"
        "bad=[m for m in sys.modules if m.startswith(('verum.truth','verum.api','verum.sim'))];"
        "print(bad)"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"
