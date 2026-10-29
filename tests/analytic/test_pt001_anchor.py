"""Anchor of the head at the PT-001 tap (decision D36).

Inputs: the written episodes S0-G (steady receipt), S0u-E (ESD closure) and a slow-closure
run on the engine. Outputs: pass/fail.

Derivations (hand arithmetic):
    * Lambda_up. E001 (30 m) and E002 (15 m) are DN300, bore 0.30318 m, area 0.0721923 m2,
      so Lambda_up = 45 / (9.80665 x 0.0721923) = 63.56 s2/m2 (the whole column is 354.0).
    * Losses upstream. E001 has no local loss and E002 the receipt meter, K = 1.0 (hand
      count, reference fittings). loss_up(Q) = f L/D v^2/2g over 45 m + 1.0 v^2/2g.
    * Open flow state (dQ/dt = 0): head at PT-001 = H_source - loss_up, with H_source the head
      at the start of E001, read back from the written pressure at the start of E001
      (z + p/(rho g) + v^2/2g).
    * Capped, decelerating: H_source is the cap head 1 m + 1e6/(750 x 9.80665) = 136.96 m, so
      the head at PT-001 is the cap minus loss_up plus Lambda_up |dQ/dt|.
    * Identity: the head at PT-001 equals the head at the end of E002 at every row, because
      both are the source head less the same loss and inertial terms of E001 and E002.
Independence: Lambda_up, loss_up and the cap head are hand values (the loss comes from the
separate reference implementation of the friction law). The identity compares two written
quantities and is not a test of the loss law.

Source: ``docs/design_decisions.md`` D36.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

import _reference_hydraulics as ref
from _series import Series
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

RHO, G, PATM = 750.0, 9.80665, 101325.0
A300 = math.pi * ref.D300**2 / 4
LAMBDA_UP = 45.0 / (G * A300)
H_CAP = 1.0 + 1.0e6 / (RHO * G)


def loss_up(q: float) -> float:
    return ref.loss(q, ref.D300, 30.0, 0.0) + ref.loss(q, ref.D300, 15.0, 1.0)


def head_from_pressure(p_abs: float, z: float, q: float) -> float:
    """Total head from the written static absolute pressure on a DN300 edge."""
    return z + (p_abs - PATM) / (RHO * G) + 0.5 * (q / A300) ** 2 / G


def test_lambda_up_by_hand() -> None:
    assert A300 == pytest.approx(0.0721923, abs=1e-7)
    assert LAMBDA_UP == pytest.approx(63.56, abs=0.01)
    assert LAMBDA_UP < 354.0 / 5  # the upstream part is a small fraction of the whole column


def test_open_flow_head_at_pt001_is_the_source_head_less_the_upstream_loss(
    series: dict[str, Series],
) -> None:
    s = series["S0-G"]
    flow = {t: q for t, side, q in s.edge["E001"] if side is None}
    pt = {t: h for t, side, h in s.head["PIPELINE_RECEIPT_BOUNDARY"] if side is None}
    e001 = {t: p for t, side, p, _to in s.edge_p["E001"] if side is None}
    for t in (100.0, 600.0, 1100.0):
        q = flow[t]
        assert q * 3600 == pytest.approx(600.0)
        h_source = head_from_pressure(e001[t] or 0.0, 1.0, q)
        assert pt[t] == pytest.approx(h_source - loss_up(q), abs=1e-6), t


def test_the_pt001_head_equals_the_head_at_the_end_of_e002_at_every_row(
    series: dict[str, Series],
) -> None:
    checked = 0
    for sid in ("S0-B", "S0-G", "S0u-E", "S0u-D"):
        s = series[sid]
        pt = {(t, side): h for t, side, h in s.head["PIPELINE_RECEIPT_BOUNDARY"]}
        flow = {(t, side): q for t, side, q in s.edge["E002"]}
        for t, side, _from, p_to in s.edge_p["E002"]:
            h = pt[(t, side)]
            if p_to is None or h is None:
                continue
            end = head_from_pressure(p_to, 1.0, flow[(t, side)])
            assert h == pytest.approx(end, abs=1e-6), (sid, t, side)
            checked += 1
    assert checked > 10000


def test_capped_decelerating_head_is_the_cap_less_the_upstream_loss_plus_the_inertial_term(
    model: HydraulicModel,
) -> None:
    """Slow closure (2000 s stroke): under the cap, PT-001 = cap - loss_up + Lambda_up |dQ/dt|."""
    cfg0 = load_sim_config()
    cfg = dataclasses.replace(
        cfg0,
        parameters={
            **cfg0.parameters,
            "stroke_time_xv_r000_s": ParamValue.selected(2000.0, "s", "DESIGN", "TEST-SLOW"),
        },
    )
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        duration_s=2012.0,
        healthy_envelope=False,
        receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0,
        schedule=[{"t_s": 10.0, "command": "close_valves", "valves": ["XV-R000"]}],
    )
    engine = Engine(model, load_lineup_table(model.topology), scenario, cfg, ListSink(), "EP")
    assert engine.run().rejection is None
    sink: Any = engine.sink
    rows = {
        (r["t_sim_s"], r["element_id"]): r["payload"]
        for r in sink.rows["hydraulic_state"]
        if r["side"] is None and r["record_type"] in ("node_state", "edge_state")
    }
    for t in (1975.0, 1985.0, 1995.0):
        q = rows[(t, "E001")]["flow_m3s"]
        qdot = (rows[(t + 1, "E001")]["flow_m3s"] - rows[(t - 1, "E001")]["flow_m3s"]) / 2
        head = rows[(t, "PIPELINE_RECEIPT_BOUNDARY")]["hydraulic_head_m"]
        expected = H_CAP - loss_up(q) + LAMBDA_UP * abs(qdot)
        assert head == pytest.approx(expected, abs=0.02), t  # qdot by central difference
        assert qdot < 0.0
