"""Valve law and actuator, operations controller, scenarios, validity and utilities.

Inputs: ``verum.hydraulics.valves``, ``verum.sim`` and ``verum.ops`` components.
Outputs: pass/fail.

Derivations (hand arithmetic, independent of the code):
    * K(alpha) = K_open (Kv_max/Kv)^2 with Kv/Kv_max = 50^(alpha-1) above alpha_c = 0.05
      and (alpha/alpha_c) 50^(alpha_c-1) below. At alpha = 1: K = 0.1. At alpha = 0.5:
      Kv ratio 50^-0.5 = 0.14142, K = 0.1 x 50 = 5.0. At alpha = 0.05: 50^-0.95 = 0.024321,
      K = 0.1 x 50^1.9 = 169.06. At alpha = 0.001 the linear branch gives Kv ratio =
      (0.001/0.05) 50^-0.95, so K = 0.1 x 50^2 x 50^1.9 = 0.1 x 50^3.9 = 4.2265e5.
    * Valve stroke: alpha moves 1/10 per second for XV-R000 and 1/30 per second for the others.
    * Rigid-column time constant of the receipt path to TK-101 at 600 m3/h: sum L/A =
      150/0.072190 + 45/0.032283 = 2077.9 + 1393.9 = 3471.8 1/m; Q0 = 0.166667 m3/s; the
      head loss comes from the independent reference module with the hand-counted K of the
      path (DN300: meter 1.0 + bend and XV-R000 0.4; DN200: two bends 0.6 + bend, XV-R101,
      tank inlet 1.4).
    * Hermite root: for a linear volume (equal end slopes) the crossing fraction is linear.

Source: decisions D4, D18, D19; ``revised/01_facility_tanks_topology.md`` section 6.2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import ContractError, Topology
from verum.hydraulics import HydraulicModel
from verum.hydraulics.valves import kv_fraction, loss_coefficient
from verum.lineups import LineupTable, TransitionRejected, load_lineup_table
from verum.ops import Command, OperationsController, ValveOrder
from verum.params import UnresolvedParameter
from verum.sim.config import load_sim_config
from verum.sim.engine import _hermite_root
from verum.sim.path import delivery_edges, receipt_edges
from verum.sim.scenario import load_scenario, parse_scenario
from verum.sim.validity import is_valid, ratio, round_trip_s, wave_speeds
from verum.sim.valves import make_valve

FIXED_SEEDS = {
    "S0-A": 20261001, "S0-B": 20261002, "S0-C": 20261003, "S0u-D": 20261004,
    "S0u-E": 20261005, "S0-F": 20261101, "S0-G": 20261007, "S0-A-inland": 20261008,
    "REJ-1": 20261011, "REJ-2": 20261012, "REJ-3": 20261013,
}  # fmt: skip

# --- valve law ----------


@pytest.mark.parametrize(
    ("alpha", "k_hand"),
    [(1.0, 0.1), (0.5, 5.0), (0.05, 0.1 * 50**1.9), (0.001, 0.1 * 50**3.9)],
)
def test_loss_coefficient_matches_hand_values(alpha: float, k_hand: float) -> None:
    assert loss_coefficient(alpha, 0.1, 0.05, 50.0) == pytest.approx(k_hand, rel=1e-12)


def test_kv_is_continuous_at_alpha_c_and_zero_at_zero() -> None:
    below = kv_fraction(0.05 - 1e-12, 0.05, 50.0)
    above = kv_fraction(0.05 + 1e-12, 0.05, 50.0)
    assert below == pytest.approx(above, rel=1e-9)
    assert kv_fraction(0.05, 0.05, 50.0) == pytest.approx(50.0**-0.95)
    assert kv_fraction(0.0, 0.05, 50.0) == 0.0
    assert loss_coefficient(0.0, 0.1, 0.05, 50.0) == float("inf")


def test_kv_increases_strictly_with_opening() -> None:
    values = [kv_fraction(i / 500, 0.05, 50.0) for i in range(0, 501)]
    assert all(b > a for a, b in zip(values, values[1:], strict=False))


def test_kv_rejects_openings_outside_the_range() -> None:
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            kv_fraction(bad, 0.05, 50.0)


# --- actuator ----------


def test_closing_valve_moves_linearly_over_its_stroke() -> None:
    valve = make_valve("XV-R101", 30.0, 0.001, True)
    assert valve.order(False, 100.0)
    for dt, expected in ((0.0, 1.0), (7.5, 0.75), (15.0, 0.5), (30.0, 0.0), (45.0, 0.0)):
        assert valve.alpha(100.0 + dt) == pytest.approx(expected, abs=1e-12)
    assert valve.motion_end_s() == 130.0
    assert valve.commanded_open is False


def test_physical_closure_is_the_closed_threshold() -> None:
    valve = make_valve("XV-R000", 10.0, 0.001, True)
    valve.order(False, 0.0)
    assert valve.threshold_time_s() == pytest.approx(9.99)
    assert not valve.is_physically_closed(9.98) and valve.is_physically_closed(9.99)
    assert valve.commanded_open is False  # the command is not the physical closure


def test_commanded_actual_and_physical_state_are_separate() -> None:
    valve = make_valve("XV-R101", 30.0, 0.001, False)
    valve.order(True, 10.0)
    assert valve.commanded_open and valve.alpha(10.0) == 0.0 and valve.is_physically_closed(10.0)
    assert valve.alpha(25.0) == pytest.approx(0.5) and not valve.is_physically_closed(25.0)


def test_a_new_order_mid_stroke_starts_from_the_actual_position() -> None:
    valve = make_valve("XV-S101", 30.0, 0.001, True)
    valve.order(False, 0.0)
    assert valve.order(True, 15.0)  # back from alpha = 0.5
    assert valve.alpha(15.0) == pytest.approx(0.5) and valve.alpha(30.0) == pytest.approx(1.0)
    assert valve.motion_end_s() == pytest.approx(30.0)


def test_an_order_to_the_present_state_does_not_start_a_motion() -> None:
    valve = make_valve("XV-S101", 30.0, 0.001, True)
    assert not valve.order(True, 5.0) and valve.threshold_time_s() is None


# --- operations controller and commands ----------


@pytest.fixture(scope="module")
def table(topology: Topology) -> LineupTable:
    return load_lineup_table(topology)


def test_commands_cannot_be_fabricated_outside_the_controller() -> None:
    with pytest.raises(PermissionError):
        Command(t_s=0.0, kind="valves")
    with pytest.raises(PermissionError):
        ValveOrder("XV-R000", True)
    with pytest.raises(PermissionError):
        Command(t_s=0.0, kind="valves", _issuer=object())


def test_the_issuing_token_is_referenced_only_inside_ops(root: Path) -> None:
    offenders = []
    for path in (root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if (
            "_make_command" in text or "_make_order" in text or "_TOKEN" in text
        ) and "verum/ops" not in path.as_posix():
            offenders.append(path.as_posix())
    assert offenders == []


def test_a_lineup_command_goes_through_the_hold_state(table: LineupTable) -> None:
    schedule = [{"t_s": 10.0, "command": "lineup", "mode": "RECEIVE_102"}]
    ops = OperationsController(table, "RECEIVE_101", schedule)
    state = {
        v: v in table.mode("RECEIVE_101").open_valves for v in ("XV-R000", "XV-R101", "XV-R102")
    }
    with pytest.raises(TransitionRejected):
        ops.resolve(ops.timed_commands[0], state, frozenset())


def test_a_hold_then_receive_resolves_to_the_valve_differences(table: LineupTable) -> None:
    schedule = [
        {"t_s": 10.0, "command": "lineup", "mode": "SWITCH_RECEIPT_HOLD"},
        {"t_s": 20.0, "command": "lineup", "mode": "RECEIVE_102"},
    ]
    ops = OperationsController(table, "RECEIVE_101", schedule)
    valves = ("XV-R000", "XV-R101", "XV-R102")
    state = {v: v in table.mode("RECEIVE_101").open_valves for v in valves}
    hold, receive = ops.timed_commands
    close = ops.resolve(hold, state, frozenset())
    assert sorted((o.valve, o.open) for o in close) == [("XV-R000", False), ("XV-R101", False)]
    state = {v: False for v in valves}
    opened = ops.resolve(receive, state, frozenset())
    assert sorted((o.valve, o.open) for o in opened) == [("XV-R000", True), ("XV-R102", True)]
    assert ops.lineup.current == "RECEIVE_102"


def test_a_lineup_change_may_not_start_or_stop_a_pump(table: LineupTable) -> None:
    ops = OperationsController(
        table, "DELIVER_101_A", [{"t_s": 1.0, "command": "lineup", "mode": "CHANGEOVER_HOLD"}]
    )
    with pytest.raises(ValueError, match="pump"):
        ops.resolve(ops.timed_commands[0], {}, frozenset({"P-101A"}))


def test_reactive_entries_become_commands_with_the_delay(table: LineupTable) -> None:
    entry = {
        "on": "ISOLATION_REQUESTED",
        "tank": "TK-101",
        "delay_s": 2.5,
        "valves": ["XV-R000", "XV-R101"],
    }
    ops = OperationsController(table, "RECEIVE_101", [entry])
    assert ops.timed_commands == ()
    (command,) = ops.react("ISOLATION_REQUESTED", "TK-101", 100.0)
    assert command.t_s == 102.5 and command.valves == (("XV-R000", False), ("XV-R101", False))
    assert ops.react("ISOLATION_REQUESTED", "TK-102", 100.0) == []
    assert ops.react("HIGH_ALARM", "TK-101", 100.0) == []


def test_an_unknown_schedule_command_is_refused(table: LineupTable) -> None:
    with pytest.raises(ValueError):
        OperationsController(table, "IDLE", [{"t_s": 1.0, "command": "start_pump"}])


# --- scenarios and configuration ----------


@pytest.mark.parametrize(
    "sid",
    [
        "S0-A",
        "S0-B",
        "S0-C",
        "S0u-D",
        "S0u-E",
        "S0-F",
        "S0-G",
        "S0-A-inland",
        "REJ-1",
        "REJ-2",
        "REJ-3",
    ],
)
def test_scenario_files_are_valid(sid: str) -> None:
    sc = load_scenario(sid)
    assert sc.fitting_profile == "reference_fittings"
    assert sc.seed == FIXED_SEEDS[sid]  # decision D41: fixed and distinct (see test_seeds)
    assert sc.duration_s == 3600.0 and sc.scenario_id == sid
    assert sc.atmosphere_stratum == ("inland" if sid == "S0-A-inland" else "coastal")
    assert sc.demand_process is (sid == "S0-F")


def test_scenario_specifics() -> None:
    assert (
        load_scenario("REJ-1").temperature_c == 45.0
        and load_scenario("REJ-1").tank_levels_m["TK-103"] == 5.0
    )
    assert load_scenario("REJ-2").tank_levels_m["TK-101"] == 6.46
    assert (
        load_scenario("S0u-E").tank_levels_m["TK-101"] == 12.3
        and not load_scenario("S0u-E").healthy_envelope
    )
    assert (
        load_scenario("S0-A").healthy_envelope
        and load_scenario("S0-A").tank_levels_m["TK-101"] == 9.0
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("seed"),
        lambda d: d.update(duration_s=0),
        lambda d: d["initial"].pop("mode"),
        lambda d: d["schedule"].append({"t_s": 1.0, "on": "X"}),
        lambda d: d.update(atmosphere_stratum="mountain"),
        lambda d: d.pop("demand_process"),
        lambda d: d["schedule"].append(
            {"t_s": 5.0, "command": "receipt_setpoint", "value_m3h": 650.0}
        ),
    ],
)
def test_bad_scenarios_are_refused(root: Path, mutate: Any) -> None:
    raw = json.loads((root / "config" / "scenarios" / "S0-A.json").read_text(encoding="utf-8"))
    mutate(raw)
    with pytest.raises(ContractError):
        parse_scenario(raw)


def test_sim_parameters_are_provisional_records() -> None:
    cfg = load_sim_config()
    for name, record in cfg.parameters.items():
        assert record.status == "provisional" and record.provenance_id, name
    assert cfg["time_step_s"] == 1.0 and cfg["receipt_controller_tau_s"] == 2.0
    assert cfg.stroke_time_s("XV-R000") == 10.0 and cfg.stroke_time_s("XV-R101") == 30.0


def test_stroke_times_agree_with_the_protection_configuration() -> None:
    cfg = load_sim_config()
    protection = json.loads(
        Path(__file__).resolve().parents[2].joinpath("config", "protection.json").read_text()
    )
    for valve, record in protection["parameters"]["stroke_time_s"].items():
        assert record["value"] == cfg.stroke_time_s(valve)


def test_closed_threshold_is_configured(model: HydraulicModel) -> None:
    assert model.config["valve_closed_alpha"] == 0.001 and model.config["valve_full_open_k"] == 0.1


def test_an_unresolved_sim_parameter_raises(tmp_path: Path, root: Path) -> None:
    import shutil

    shutil.copytree(root / "config", tmp_path / "config")
    path = tmp_path / "config" / "sim.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["parameters"]["quasi_steady_factor"] = {
        "value": None,
        "unit": "1",
        "status": "unresolved",
        "evidence_tag": "OPEN",
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(UnresolvedParameter):
        _ = load_sim_config(tmp_path / "config")["quasi_steady_factor"]


# --- validity ----------


def test_receipt_wave_round_trip_matches_the_hand_calculation(model: HydraulicModel) -> None:
    """Independent: 2 (150 m / 1078.2 m/s + 45 m / 1089.2 m/s) = 0.36087 s (PAR-PIP-007)."""
    edges = receipt_edges(model, "TK-101")
    hand = 2.0 * (150.0 / 1078.2 + 45.0 / 1089.2)
    assert round_trip_s(model, edges, wave_speeds(load_sim_config())) == pytest.approx(
        hand, rel=1e-12
    )
    assert hand == pytest.approx(0.36087, abs=1e-5)


def test_delivery_wave_round_trip_uses_each_nominal_size(model: HydraulicModel) -> None:
    """Independent: S-102 90 m and the pump leg 20 m are DN200, E-SH 35 m is DN250, D-MAIN 250 m."""
    edges = delivery_edges(model, "TK-102", "P-101A")
    hand = 2.0 * ((90.0 + 20.0 + 250.0) / 1089.2 + 35.0 / 1082.8)
    assert round_trip_s(model, edges, wave_speeds(load_sim_config())) == pytest.approx(
        hand, rel=1e-12
    )


def test_wave_speeds_are_the_screening_values_of_the_audited_package() -> None:
    assert wave_speeds(load_sim_config()) == {200: 1089.2, 250: 1082.8, 300: 1078.2}


def test_validity_rule_and_ratio() -> None:
    assert is_valid(60.0, 6.0, 10.0) and not is_valid(59.9, 6.0, 10.0)
    assert ratio(30.0, 6.0) == 5.0


def test_paths_are_made_of_contract_edges(model: HydraulicModel) -> None:
    assert receipt_edges(model, "TK-101") == ("E001", "E002", "E003", "E-R101a", "E-R101b")
    assert delivery_edges(model, "TK-102", "P-101B") == (
        "E-S102a", "E-S102b", "E-SH", "E-PB0", "E-PB1", "E-PB2", "E-PB3", "E-PB4", "E-D1", "E-D2",
    )  # fmt: skip


def test_hermite_root_is_linear_for_equal_slopes() -> None:
    # V falls from 100 to 80 over 10 s at a constant -2 per s: the root for 90 is s = 0.5.
    assert _hermite_root(100.0, 80.0, -20.0, -20.0, 90.0) == pytest.approx(0.5, abs=1e-12)
    assert _hermite_root(100.0, 80.0, -20.0, -20.0, 81.0) == pytest.approx(0.95, abs=1e-12)


def test_hermite_root_follows_a_cubic() -> None:
    # V(s) = 100 - 30 s^2 + 10 s^3 has V(0)=100, V(1)=80, slopes 0 and -30 per unit s.
    s = _hermite_root(100.0, 80.0, 0.0, -30.0 + 30.0 * 0 - 0.0, 100 - 30 * 0.6**2 + 10 * 0.6**3)
    assert 0.0 < s < 1.0
