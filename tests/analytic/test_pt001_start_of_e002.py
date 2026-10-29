"""Observed PT-001 at the start of E002 and the hidden end-of-E002 value (decision D36 v2).

Inputs: the written episodes S0-B, S0-G, S0u-D, S0u-E and a slow-closure run. Outputs:
pass/fail.

Derivations (hand arithmetic):
    * Lambda_up for E001 only: 30 m of DN300 (bore 0.30318 m, area 0.0721923 m2):
      30 / (9.80665 x 0.0721923) = 42.37 s2/m2. With E002 (15 m) it is 63.56 s2/m2.
    * Observed PT-001 (start of E002): H_source - loss(E001) - Lambda_E001 dQ/dt. E001 has no
      local loss, so loss(E001) is the friction of 30 m of DN300.
    * Open flow state: dQ/dt = 0. Capped and decelerating: H_source is the cap head 136.96 m
      and the head is the cap - loss(E001) + Lambda_E001 |dQ/dt|.
    * Hidden node value at the end of E002: H_source - loss(E001, E002) - Lambda_(E001+E002)
      dQ/dt, labelled ``end_of_E002_lambda_E001_E002`` in the node row.
    * Identity: with the same dQ/dt along the column, (H_from - H_to - loss)/Lambda is the same
      number for E001 and E002 at every row.
Independence: Lambda and the losses are hand values (the losses from the separate reference
implementation of the friction law); the identity compares written quantities.

Source: ``docs/design_decisions.md`` D36 version 2.
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
LAMBDA_E001 = 30.0 / (G * A300)
LAMBDA_E002 = 15.0 / (G * A300)
H_CAP = 1.0 + 1.0e6 / (RHO * G)


def head(p_abs: float, q: float) -> float:
    return 1.0 + (p_abs - PATM) / (RHO * G) + 0.5 * (q / A300) ** 2 / G


def test_lambda_for_e001_by_hand() -> None:
    assert LAMBDA_E001 == pytest.approx(42.37, abs=0.01)
    assert LAMBDA_E001 + LAMBDA_E002 == pytest.approx(63.56, abs=0.01)


def test_open_flow_observed_head_is_the_source_head_less_the_loss_of_e001(
    series: dict[str, Series],
) -> None:
    s = series["S0-G"]
    q = {t: v for t, side, v in s.edge["E001"] if side is None}
    e001 = {t: p for t, side, p, _to in s.edge_p["E001"] if side is None}
    e002 = {t: p for t, side, p, _to in s.edge_p["E002"] if side is None}
    for t in (100.0, 600.0, 1100.0):
        h_source = head(e001[t] or 0.0, q[t])
        loss_e001 = ref.loss(q[t], ref.D300, 30.0, 0.0)
        assert head(e002[t] or 0.0, q[t]) == pytest.approx(h_source - loss_e001, abs=1e-6), t


def test_the_hidden_node_value_keeps_both_edges_and_is_labelled(series: dict[str, Series]) -> None:
    s = series["S0-G"]
    q = {t: v for t, side, v in s.edge["E001"] if side is None}
    tap = {t: h for t, side, h in s.head["PIPELINE_RECEIPT_BOUNDARY"] if side is None}
    e001 = {t: p for t, side, p, _to in s.edge_p["E001"] if side is None}
    t = 600.0
    expected = head(e001[t] or 0.0, q[t]) - ref.loss(q[t], ref.D300, 30.0, 0.0)
    expected -= ref.loss(q[t], ref.D300, 15.0, 1.0)
    assert tap[t] == pytest.approx(expected, abs=1e-6)
    import gzip
    import json

    with gzip.open(s.directory / "hydraulic_state.jsonl.gz", "rt") as handle:
        node = next(
            json.loads(line)
            for line in handle
            if '"PIPELINE_RECEIPT_BOUNDARY"' in line and '"node_state"' in line
        )
    assert node["payload"]["anchor"] == "end_of_E002_lambda_E001_E002"


def test_capped_decelerating_observed_head_is_the_cap_less_loss_plus_the_e001_inertia(
    model: HydraulicModel,
) -> None:
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
        if r["side"] is None and r["record_type"] == "edge_state"
    }
    for t in (1975.0, 1985.0, 1995.0):
        q = rows[(t, "E001")]["flow_m3s"]
        qdot = (rows[(t + 1, "E001")]["flow_m3s"] - rows[(t - 1, "E001")]["flow_m3s"]) / 2
        observed = head(rows[(t, "E002")]["p_from_pa_abs"], q)
        expected = H_CAP - ref.loss(q, ref.D300, 30.0, 0.0) + LAMBDA_E001 * abs(qdot)
        assert qdot < 0.0
        assert observed == pytest.approx(expected, abs=0.02), t


def test_the_same_rate_of_change_holds_along_e001_and_e002_at_every_row(
    series: dict[str, Series],
) -> None:
    checked = 0
    for sid in ("S0-B", "S0-G", "S0u-D", "S0u-E"):
        s = series[sid]
        q = {(t, side): v for t, side, v in s.edge["E001"]}
        e001 = {(t, side): (a, b) for t, side, a, b in s.edge_p["E001"]}
        e002 = {(t, side): (a, b) for t, side, a, b in s.edge_p["E002"]}
        for key, (p1, _p1b) in e001.items():
            p2, p2b = e002[key]
            if p1 is None or p2 is None or p2b is None or q[key] == 0.0:
                continue  # a closed path is a dead leg with one head, not a flowing column
            flow = q[key]
            qd1 = (
                head(p1, flow) - head(p2, flow) - ref.loss(flow, ref.D300, 30.0, 0.0)
            ) / LAMBDA_E001
            qd2 = (
                head(p2, flow) - head(p2b, flow) - ref.loss(flow, ref.D300, 15.0, 1.0)
            ) / LAMBDA_E002
            assert qd1 == pytest.approx(qd2, abs=2e-6), (sid, key)
            checked += 1
    assert checked > 10000
