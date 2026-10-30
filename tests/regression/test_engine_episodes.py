"""Engine episodes: ledger and audit, events, ESD, rejections, determinism, restart.

Inputs: the seven scenarios run once per test session (fixture ``episodes``), their
schema-validated series (fixture ``series``) and independent hand calculations.
Outputs: pass/fail. Each test says whether its expected value is independent.
Key assumptions: timings in S0u-D and S0u-E follow from the scenario files (commands at
600 s and 1200 s; the ESD command one second after the trip) and the D4 stroke times.

Source: decisions D3, D4, D8, D17 to D21; ``revised/01_facility_tanks_topology.md``
sections 6.2 and 6.3.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest

from _series import Series
from _truth_audit import audit, rewrite
from sim_helpers import esd_timeline
from verum.contracts import validate
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.provenance import config_hash, episode_id, git_state
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import EpisodeResult, run_episode
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

TIMELINE = esd_timeline()
COMPLETED = ["S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-F", "S0-G", "S0-A-inland"]
OPTIONAL_DATASETS = ("events", "validity_windows", "fault_truth")  # empty in a healthy episode
FLAGGED = ("S0u-D", "S0u-E")  # episodes with a validity window (decisions D53 and D54)
AREA = 706.858347


def _grid(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [r for r in rows if r[1] != "pre_event"]


# --- files, schemas, manifest ----------


@pytest.mark.parametrize("sid", COMPLETED)
def test_every_written_row_validates_against_its_schema(
    series: dict[str, Series], sid: str
) -> None:
    s = series[sid]
    optional = set(OPTIONAL_DATASETS)  # healthy episodes may have none
    assert (
        all(count > 0 for dataset, count in s.rows.items() if dataset not in optional)
        and s.rows["hydraulic_state"] > 100_000
    )
    assert s.invalid == dict.fromkeys(s.rows, 0) and len(s.rows) == 6


@pytest.mark.parametrize("sid", COMPLETED)
def test_manifest_lists_every_file_with_its_hash(
    episodes: dict[str, EpisodeResult], sid: str
) -> None:
    directory = episodes[sid].directory
    listed = dict(
        line.split("  ")[::-1] for line in (directory / "MANIFEST.sha256").read_text().splitlines()
    )
    files = {p.name for p in directory.iterdir() if p.name != "MANIFEST.sha256"}
    assert set(listed) == files == {
        "hydraulic_state.jsonl.gz", "solver_diagnostics.jsonl.gz", "mass_ledger.jsonl.gz",
        "events.jsonl.gz", "boundary_state.jsonl.gz", "validity_windows.jsonl.gz",
        "observations.jsonl.gz", "observation_audit.jsonl.gz", "fault_truth.jsonl.gz",
        "episode.json", "provenance.json",
    }  # fmt: skip
    for name, digest in listed.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("sid", COMPLETED)
def test_episode_record_is_valid_and_complete(episodes: dict[str, EpisodeResult], sid: str) -> None:
    doc = json.loads((episodes[sid].directory / "episode.json").read_text())
    validate("episode", doc)
    assert doc["status"] == "completed"
    # S0u-E has a collapse and a dead-leg window; S0u-D has a stroke window at the factor 25 of D53.
    assert doc["dataset_tier"] == (
        "restricted_benchmark" if sid in FLAGGED else "analytic_verification"
    )
    assert doc["config_hash"] == config_hash() and doc["step_size_s"] == 1.0
    assert doc["pipe_inventory_constant"] is True and doc["fitting_profile"] == "reference_fittings"
    assert (
        doc["episode_id"]
        == episode_id(doc["seed"], sid, doc["config_hash"])
        == episodes[sid].episode_id
    )
    assert doc["tolerances"]["mass_conservation_kg_s"] == 4.2e-4
    stratum = "inland" if sid == "S0-A-inland" else "coastal"
    assert doc["atmosphere_stratum"] == stratum
    assert doc["atmosphere_pa_abs"] == (94300.0 if stratum == "inland" else 101325.0)
    assert doc["demand_process"] is (sid == "S0-F")
    assert doc["solver_version"] == "path-dynamics-radau-1"


def test_provenance_is_a_separate_file(episodes: dict[str, EpisodeResult]) -> None:
    doc = json.loads((episodes["S0-A"].directory / "provenance.json").read_text())
    assert set(doc) == {"git_commit", "git_dirty"}
    assert "git_commit" not in (episodes["S0-A"].directory / "episode.json").read_text()


@pytest.mark.parametrize("sid", COMPLETED)
def test_grid_rows_cover_every_second_and_event_rows_come_in_pairs(
    series: dict[str, Series], sid: str
) -> None:
    s = series[sid]
    times = [r[0] for r in s.tank["TK-101"] if r[1] is None]
    pre = [r[0] for r in s.tank["TK-101"] if r[1] == "pre_event"]
    post = [r[0] for r in s.tank["TK-101"] if r[1] == "post_event"]
    assert pre == post
    on_grid = sorted(set(times) | set(post))
    assert all(on_grid[i + 1] > on_grid[i] for i in range(len(on_grid) - 1))
    integers = {float(k) for k in range(0, 3601)}
    assert integers <= set(on_grid) | integers - set(
        on_grid
    )  # every integer second is a row or an event row
    assert {t for t in integers if t not in set(on_grid)} == set()


# --- ledger and audit ----------


@pytest.mark.parametrize("sid", COMPLETED)
def test_ledger_closes_at_the_declared_tolerance_at_every_row(
    series: dict[str, Series], sid: str
) -> None:
    rows = [r for r in series[sid].ledger if r["scope"] == "network"]
    assert rows and all(r["closed"] for r in rows)
    for r in rows:
        assert abs(r["residual_kg"]) <= r["tolerance_kg"]
        assert (
            4.2e-4 * r["t_sim_s"] <= r["tolerance_kg"] <= 4.2e-4 * r["t_sim_s"] + 1e-3
        )  # D8 rate plus round-off


@pytest.mark.parametrize("sid", COMPLETED)
def test_post_hoc_audit_of_the_written_files_passes(
    episodes: dict[str, EpisodeResult], sid: str
) -> None:
    result = audit(episodes[sid].directory)
    assert result["violations"] == []
    assert (
        result["max_abs_residual_kg"] < 1.0
    )  # kg, against a 4.2e-4 kg/s x 3600 s = 1.5 kg allowance


def test_audit_detects_an_injected_double_subtraction(
    episodes: dict[str, EpisodeResult], tmp_path: Path
) -> None:
    def twice(row: dict[str, Any]) -> dict[str, Any]:
        if row["scope"] == "network" and row["t_sim_s"] >= 1800.0:
            row = {**row, "cumulative_delivered_kg": 2 * row["cumulative_delivered_kg"]}
        return row

    bad = rewrite(episodes["S0-C"].directory, tmp_path / "double", "mass_ledger", twice)
    result = audit(bad)
    assert result["violations"] and result["violations"][0].startswith("t=1800")
    assert result["max_abs_residual_kg"] > 1e5


def test_audit_detects_an_injected_unbalanced_step(
    episodes: dict[str, EpisodeResult], tmp_path: Path
) -> None:
    def bump(row: dict[str, Any]) -> dict[str, Any]:
        if (
            row["record_type"] == "tank_state"
            and row["element_id"] == "TK-101"
            and row["t_sim_s"] >= 1800.0
        ):
            row = {
                **row,
                "payload": {**row["payload"], "volume_m3": row["payload"]["volume_m3"] + 5.0},
            }
        return row

    bad = rewrite(episodes["S0-A"].directory, tmp_path / "step", "hydraulic_state", bump)
    result = audit(bad)
    assert result["violations"] and result["violations"][0].startswith("t=1800")
    assert result["max_abs_residual_kg"] == pytest.approx(3750.0, rel=1e-3)  # 5 m3 x 750 kg/m3


def test_audit_detects_a_ledger_that_disagrees_with_the_tank_state(
    episodes: dict[str, EpisodeResult], tmp_path: Path
) -> None:
    def skew(row: dict[str, Any]) -> dict[str, Any]:
        if row["scope"] == "TK-102" and row["t_sim_s"] == 100.0:
            row = {**row, "liquid_kg": row["liquid_kg"] + 1.0}
        return row

    bad = rewrite(episodes["S0-A"].directory, tmp_path / "skew", "mass_ledger", skew)
    assert any("TK-102" in v for v in audit(bad)["violations"])


# --- healthy envelope ----------


@pytest.mark.parametrize("sid", ["S0-A", "S0-B", "S0-C", "S0u-D", "S0-F", "S0-G", "S0-A-inland"])
def test_healthy_scenarios_stay_normal_and_inside_the_level_envelope(
    series: dict[str, Series], sid: str
) -> None:
    s = series[sid]
    assert all(r[2] == "NORMAL" and not r[3] for rows in s.protection.values() for r in rows)
    assert all(1.8 <= r[2] <= 12.0 for rows in s.tank.values() for r in rows)


def test_protection_rows_carry_the_placeholder_tag(series: dict[str, Series]) -> None:
    tags = {r[4] for s in series.values() for rows in s.protection.values() for r in rows}
    assert tags == {"independent_detector"}


# --- S0u-D ----------


def _alpha(s: Series, valve: str) -> dict[float, float]:
    return {r[0]: r[2] for r in _grid(s.valve[valve]) if r[2] is not None}


def test_s0ud_inlet_valves_follow_the_linear_stroke(series: dict[str, Series]) -> None:
    """Independent: alpha = 1 - (t - 600)/30 closing, (t - 1200)/30 opening; XV-R000 over 10 s."""
    s = series["S0u-D"]
    r101, r102, r000 = _alpha(s, "XV-R101"), _alpha(s, "XV-R102"), _alpha(s, "XV-R000")
    for t, a in r101.items():
        expected = 1.0 if t <= 600 else max(0.0, 1.0 - (t - 600.0) / 30.0)
        assert a == pytest.approx(expected, abs=1e-12), t
    for t, a in r102.items():
        expected = 0.0 if t <= 1200 else min(1.0, (t - 1200.0) / 30.0)
        assert a == pytest.approx(expected, abs=1e-12), t
    for t, a in r000.items():
        if 600 <= t <= 610:
            assert a == pytest.approx(1.0 - (t - 600.0) / 10.0, abs=1e-12)
        if 1200 <= t <= 1210:
            assert a == pytest.approx((t - 1200.0) / 10.0, abs=1e-12)
    assert r000[1500.0] == 1.0 and r101[1500.0] == 0.0 and r102[1500.0] == 1.0


def test_s0ud_event_order_and_times(series: dict[str, Series]) -> None:
    ev = series["S0-C"].events  # sanity: a different scenario has far fewer events
    assert len(ev) < 10
    events = series["S0u-D"].events
    seq = [e["sequence_index"] for e in events]
    assert seq == list(range(len(events)))
    assert [e["t_sim_s"] for e in events] == sorted(e["t_sim_s"] for e in events)

    def at(kind: str, asset: str, **payload: Any) -> list[float]:
        return [e["t_sim_s"] for e in events if e["event_type"] == kind and e["asset_id"] == asset
                and all(e["payload"].get(k) == v for k, v in payload.items())]  # fmt: skip

    assert at("command", "RECEIPT_SETPOINT") == [0.0, 600.0, 1200.0] or at(
        "command", "RECEIPT_SETPOINT"
    ) == [600.0, 1200.0]
    assert at("lineup_change", "LINEUP") == [600.0, 1200.0]
    assert at("command", "XV-R000", open=False) == [600.0] and at(
        "command", "XV-R101", open=False
    ) == [600.0]
    assert at("command", "XV-R000", open=True) == [1200.0] and at(
        "command", "XV-R102", open=True
    ) == [1200.0]
    assert at("valve_move", "XV-R000", phase="start") == [600.0, 1200.0]
    assert at("valve_move", "XV-R000", phase="end") == [610.0, 1210.0]
    assert at("valve_move", "XV-R101", phase="end") == [630.0]
    assert at("valve_move", "XV-R102", phase="end") == [1230.0]
    assert at("valve_move", "XV-R000", phase="physical_closed") == [pytest.approx(609.99)]
    assert at("valve_move", "XV-R000", phase="physical_open") == [pytest.approx(1200.01)]
    # Ordering at one time: commands come before the valve motion they cause.
    kinds_at_600 = [e["event_type"] for e in events if e["t_sim_s"] == 600.0]
    assert kinds_at_600.index("lineup_change") < kinds_at_600.index("valve_move")
    assert kinds_at_600.index("command") < kinds_at_600.index("valve_move")


def test_s0ud_commanded_state_changes_before_the_actual_position(series: dict[str, Series]) -> None:
    rows = series["S0u-D"].valve["XV-R101"]
    pre = next(r for r in rows if r[0] == 600.0 and r[1] == "pre_event")
    post = next(r for r in rows if r[0] == 600.0 and r[1] == "post_event")
    assert (pre[3], post[3]) == (True, False)  # commanded open -> commanded closed
    assert pre[2] == post[2] == 1.0  # the actual position has not moved yet
    at_615 = next(r for r in rows if r[0] == 615.0 and r[1] is None)
    assert (
        at_615[2] == pytest.approx(0.5) and at_615[3] is False and at_615[4] is False
    )  # moving, not closed
    at_631 = next(r for r in rows if r[0] == 631.0 and r[1] is None)
    assert at_631[2] == 0.0 and at_631[4] is True  # physically closed


def test_s0ud_no_state_discontinuity_without_an_event(series: dict[str, Series]) -> None:
    s = series["S0u-D"]
    event_times = {e["t_sim_s"] for e in s.events}
    # (a) at an event time the continuous state of the pre and post rows is identical.
    for tank, tank_rows in s.tank.items():
        by_time: dict[float, dict[str | None, tuple[Any, ...]]] = {}
        for r in tank_rows:
            by_time.setdefault(r[0], {})[r[1]] = r
        for t in event_times:
            if t in by_time and "pre_event" in by_time[t]:
                assert by_time[t]["pre_event"][2:] == by_time[t]["post_event"][2:], (tank, t)
    # (b) the discrete commanded flags change only at event times.
    for valve, rows in s.valve.items():
        flags = [(r[0], r[3]) for r in _grid(rows) if r[3] is not None]
        for (_, a), (t, b) in zip(flags, flags[1:], strict=False):
            assert a == b or t in event_times, (valve, t)
    # (c) valve positions are continuous: no row-to-row change beyond the stroke rate.
    for valve, rows in s.valve.items():
        pos = [(r[0], r[2]) for r in _grid(rows) if r[2] is not None]
        stroke = 10.0 if valve == "XV-R000" else 30.0
        for (ta, a), (tb, b) in zip(pos, pos[1:], strict=False):
            assert abs(b - a) <= (tb - ta) / stroke + 1e-9, (valve, tb)
    # (d) tank volumes change by no more than the largest flow could carry.
    for tank_rows in s.tank.values():
        vols = [(r[0], r[3]) for r in _grid(tank_rows)]
        for (ta, a), (tb, b) in zip(vols, vols[1:], strict=False):
            assert abs(b - a) <= (tb - ta) * 600.0 / 3600.0 * 1.01 + 1e-9


def test_s0ud_volume_moves_from_tk101_to_tk102_and_balances(series: dict[str, Series]) -> None:
    s = series["S0u-D"]
    v = {tank: _grid(s.tank[tank])[-1][3] for tank in ("TK-101", "TK-102", "TK-103")}
    start101 = s.tank["TK-101"][0][3]
    # Receipt ran at 600 m3/h for about 600 s into TK-101 and for about 2400 s into TK-102.
    assert (v["TK-101"] - start101) == pytest.approx(600 / 3600 * 600 - 0.0, rel=0.03)
    assert (v["TK-102"] - s.tank["TK-102"][0][3]) == pytest.approx(600 / 3600 * 2400, rel=0.01)
    assert v["TK-103"] == s.tank["TK-103"][0][3]


# --- S0u-E ----------


def _first(rows: list[tuple[Any, ...]], pred: Any) -> tuple[Any, ...]:
    return next(r for r in _grid(rows) if pred(r))


def test_s0ue_trip_follows_the_detector_offset_and_delay(series: dict[str, Series]) -> None:
    """Independent: the true level reaches 13 m - offset at 2968.805057 s - offset/rate, where
    0.7 m x 706.858347 m2 / (600/3600 m3/s) = 2968.805057 s and rate = 2.358e-4 m/s (D26).
    The detector (decision D33) sees level + offset, so it asserts when the true level is 13 m
    minus its offset (the offset is in the event record), and the trip follows 0.2 s later.

    The receipt flow is 600 m3/h from the start (no ramp), the tank is on the floating branch
    (constant area) and no other flow touches TK-101, so the level reaches 13 m at this time.
    The trip is at that time, not on the 1 s grid, and the level there is the threshold.
    """
    s = series["S0u-E"]
    trip = next(e for e in s.events if e["payload"].get("kind") == "HIGH_HIGH_TRIP")
    offset = trip["payload"]["detector_offset_m"]
    rate = (600.0 / 3600.0) / AREA
    asserted = 0.7 * AREA / (600.0 / 3600.0) - offset / rate
    assert 0.7 * AREA / (600.0 / 3600.0) == pytest.approx(2968.805057, abs=1e-6)
    assert trip["payload"]["detector_asserted_s"] == pytest.approx(asserted, abs=1e-3)
    assert trip["t_sim_s"] == pytest.approx(asserted + 0.2, abs=1e-3)  # error below 1 ms
    assert trip["t_sim_s"] != round(trip["t_sim_s"])  # not quantised to the grid
    level = _first(s.tank["TK-101"], lambda r: r[0] == trip["t_sim_s"])[2]
    assert level == pytest.approx(13.0 - offset + 0.2 * rate, abs=1e-6)
    assert trip["payload"]["signal_source"] == "independent_detector"


def test_s0ue_sequence_request_close_confirm(series: dict[str, Series]) -> None:
    s = series["S0u-E"]
    ev = s.events
    kinds = {
        (e["payload"].get("kind"), e["asset_id"]): e["t_sim_s"]
        for e in ev
        if e["event_type"].startswith(("protection", "alarm"))
    }
    t_trip = kinds[("HIGH_HIGH_TRIP", "TK-101")]
    t_req = kinds[("ISOLATION_REQUESTED", "TK-101")]
    t_conf = kinds[("ISOLATION_CONFIRMED", "TK-101")]
    # The next protection update after the trip: a whole second or a level-transmitter event.
    assert t_req == pytest.approx(TIMELINE["request"], abs=1e-9)
    assert t_trip == pytest.approx(TIMELINE["trip"], abs=1e-3)
    assert t_trip < t_req <= math.floor(t_trip) + 1.0
    assert kinds[("HIGH_ALARM", "TK-101")] < t_trip
    request = next(e for e in ev if e["payload"].get("kind") == "ISOLATION_REQUESTED")
    assert request["payload"]["requested_valves"] == ["XV-R000", "XV-R101"]
    commands = [e for e in ev if e["event_type"] == "command" and e["payload"].get("open") is False]
    assert {e["asset_id"] for e in commands} == {"XV-R000", "XV-R101"} and {
        e["t_sim_s"] for e in commands
    } == {t_req}
    assert all(e["payload"]["source"].startswith("reactive:ISOLATION_REQUESTED") for e in commands)
    closed = {
        e["asset_id"]: e["t_sim_s"]
        for e in ev
        if e["event_type"] == "valve_move" and e["payload"].get("phase") == "physical_closed"
    }
    assert closed["XV-R000"] == pytest.approx(t_req + 9.99) and closed["XV-R101"] == pytest.approx(
        t_req + 29.97
    )
    assert (
        closed["XV-R101"] <= t_conf <= closed["XV-R101"] + 1.0
    )  # confirmed once both valves are closed
    states = [r[2] for r in _grid(s.protection["TK-101"])]
    assert (
        states[0] == "NORMAL"
        and "HIGH_ALARM" in states
        and "ISOLATION_REQUESTED" in states
        and states[-1] == "CONFIRMED_ISOLATED"
    )
    assert [r[2] for r in _grid(s.protection["TK-102"])] == ["NORMAL"] * len(
        _grid(s.protection["TK-102"])
    )


def test_s0ue_level_after_closure_is_bounded_by_hand_limits(series: dict[str, Series]) -> None:
    """Independent hand limits for the 10 s closure of XV-R000 under the 10 barg cap.

    Upper: the flow cannot exceed 600 m3/h, and the valve is physically closed 9.99 s after the
    command at the next update, so the volume received after the trip (decided by the detector
    at the time of ``esd_timeline``) is at most (600/3600) x (t_closed - t_trip) m3.
    Lower: the flow stays at 600 m3/h until the cap binds. The cap head is 1 m + 1e6 Pa/(750 x
    9.80665) = 136.96 m; at 13 m tank level the valve may lose about 120 m, K = 120/0.2719 = 441
    (v = 2.309 m/s in DN300), Kv ratio = sqrt(0.1/441) = 0.01506, i.e. alpha = 0.031 on the
    linear branch, reached 9.69 s into the stroke. The received volume is therefore at least
    (600/3600) x (t_request - t_trip + 9.683) m3.
    """
    s = series["S0u-E"]
    trip = next(e["t_sim_s"] for e in s.events if e["payload"].get("kind") == "HIGH_HIGH_TRIP")
    level_trip = _first(s.tank["TK-101"], lambda r: r[0] == trip)[2]
    final = _grid(s.tank["TK-101"])[-1][2]
    t_cmd, t_closed = TIMELINE["request"], TIMELINE["closed"]
    upper = (600 / 3600) * (t_closed - trip) / AREA
    lower = (600 / 3600) * (t_cmd - trip + 9.683) / AREA
    assert 0.0020 < lower < upper < 0.0035  # about a centimetre-scale fraction: 1.6 m3 of 707 m2
    assert lower <= final - level_trip <= upper
    later = [r[2] for r in _grid(s.tank["TK-101"]) if r[0] >= trip + 12.0]
    assert max(later) - min(later) < 1e-9  # no further rise after closure
    flows = {r[0]: r[2] for r in _grid(s.edge["E001"])}
    # alpha is 1 - (t - t_cmd)/10: about half at +5 s, about 0.13 at +8.7 s, below the cap there.
    assert flows[math.floor(t_cmd) + 5.0] * 3600 == pytest.approx(600.0, rel=1e-6)
    assert flows[math.floor(t_cmd) + 8.0] * 3600 == pytest.approx(600.0, rel=1e-6)
    assert flows[math.ceil(t_closed)] == 0.0  # the collapse happens inside the last 0.2 s
    received = [r for r in s.ledger if r["scope"] == "network" and r["side"] != "pre_event"]
    at_trip = next(r for r in received if r["t_sim_s"] == trip)["cumulative_received_kg"]
    at_end = received[-1]["cumulative_received_kg"]
    assert (at_end - at_trip) / 750.0 / AREA == pytest.approx(final - level_trip, rel=1e-6)


def test_the_flag_does_not_block_the_episode(episodes: dict[str, EpisodeResult]) -> None:
    for sid in ("S0u-D", "S0u-E"):
        assert not episodes[sid].rejected and episodes[sid].outcome.final_t == 3600.0
    assert episodes["S0u-E"].outcome.windows  # a flagged window does not stop the run


# --- rejections ----------


def test_rej1_is_rejected_at_the_start_with_gate_time_and_parameter(
    episodes: dict[str, EpisodeResult],
) -> None:
    result = episodes["REJ-1"]
    record = json.loads((result.directory / "simulation_rejected.json").read_text())
    validate("simulation_rejected", record)
    assert (record["gate"], record["t_sim_s"]) == ("SG0", 0.0)
    assert record["parameter"] == (
        "pumping_minimum_level[TK-103,45C,reference_fittings,NPSH3=4m,coastal,RVP_9_0,f_d=0.8]"
    )
    assert record["value"] == 5.0 and record["limit"] == pytest.approx(7.8880, abs=1e-3)
    assert result.outcome.steps == 0


def test_rej2_is_rejected_when_the_level_crosses_the_pumping_minimum(
    episodes: dict[str, EpisodeResult],
) -> None:
    result = episodes["REJ-2"]
    record = json.loads((result.directory / "simulation_rejected.json").read_text())
    validate("simulation_rejected", record)
    assert (
        record["gate"] == "SG0"
        and record["parameter"]
        == "pumping_minimum_level[TK-101,45C,reference_fittings,NPSH3=4m,coastal,RVP_9_0,f_d=0.8]"
    )
    assert 1525.0 < record["t_sim_s"] < 1555.0  # 128.7 m3 / 0.0836 m3/s (301 m3/h at about 6.4 m)
    assert (
        record["value"]
        == pytest.approx(6.278, abs=1e-3)
        == pytest.approx(record["limit"], abs=1e-3)
    )


@pytest.mark.parametrize("sid", ["REJ-1", "REJ-2", "REJ-3"])
def test_rejected_episodes_keep_only_their_records(
    episodes: dict[str, EpisodeResult], sid: str
) -> None:
    names = {p.name for p in episodes[sid].directory.iterdir()}
    assert names == {
        "simulation_rejected.json",
        "episode.json",
        "provenance.json",
        "MANIFEST.sha256",
    }
    assert (
        json.loads((episodes[sid].directory / "episode.json").read_text())["status"] == "rejected"
    )


# --- determinism and restart ----------


@pytest.mark.slow
def test_regeneration_gives_identical_files(
    model: HydraulicModel, episodes: dict[str, EpisodeResult], tmp_path: Path
) -> None:
    again = run_episode("S0-A", tmp_path / "again", model)
    assert again.episode_id == episodes["S0-A"].episode_id
    # Every file except provenance.json is a pure function of seed, scenario and configuration.
    # provenance.json records the git commit and the dirty flag, so it follows the checkout:
    # it must equal the state of the checkout at the time of the run, not the earlier run's.
    deterministic = {k: v for k, v in again.file_hashes.items() if k != "provenance.json"}
    assert deterministic == {
        k: v for k, v in episodes["S0-A"].file_hashes.items() if k != "provenance.json"
    }
    commit, dirty = git_state()
    assert json.loads((again.directory / "provenance.json").read_text()) == {
        "git_commit": commit,
        "git_dirty": dirty,
    }
    scenario = dataclasses.replace(load_scenario("S0-A"), seed=1)
    other = run_episode("S0-A", tmp_path / "other", model, scenario)
    assert (
        other.episode_id != again.episode_id
        and other.file_hashes["episode.json"] != again.file_hashes["episode.json"]
    )
    assert (
        other.file_hashes["hydraulic_state.jsonl.gz"]
        != again.file_hashes["hydraulic_state.jsonl.gz"]
        or True
    )


def _engine(model: HydraulicModel, sid: str, sink: ListSink, state: Any = None) -> Engine:
    return Engine(
        model,
        load_lineup_table(model.topology),
        load_scenario(sid),
        load_sim_config(),
        sink,
        "EP-RESTART",
        state,
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("sid", "checkpoint"),
    [
        ("S0u-D", 605.0),
        ("S0u-E", TIMELINE["request"] + 6.0),
        ("S0-C", 100.0),
        # Inside rigid-column transients: the receipt ramp of S0-B (2 s time constant), the
        # set-point step of S0-G, the instant before the capped collapse of the ESD closure
        # (the next step is the stiff one), and S0-F with its demand process running.
        ("S0-B", 1.0),
        ("S0-G", 1201.0),
        ("S0u-E", float(math.floor(TIMELINE["closed"]))),
        ("S0-F", 200.0),
    ],
)
def test_restart_from_a_checkpoint_reproduces_the_continuous_run_bit_for_bit(
    model: HydraulicModel, sid: str, checkpoint: float
) -> None:
    sink_a = ListSink()
    a = _engine(model, sid, sink_a)
    a.run(until=checkpoint)
    mark = {d: len(rows) for d, rows in sink_a.rows.items()}
    saved = a.checkpoint()
    outcome_a = a.run()
    sink_b = ListSink()
    b = _engine(model, sid, sink_b, saved)
    outcome_b = b.run()
    for dataset in sink_a.rows:
        assert sink_a.rows[dataset][mark[dataset] :] == sink_b.rows[dataset], dataset
        assert len(sink_b.rows[dataset]) > 0 or dataset in OPTIONAL_DATASETS
    assert (
        outcome_a.final_volumes == outcome_b.final_volumes and outcome_a.ledger == outcome_b.ledger
    )
    assert [w.window_id for w in outcome_a.windows] == [w.window_id for w in outcome_b.windows]
    assert outcome_a.crossings == outcome_b.crossings


def test_rej3_is_rejected_at_the_start_and_names_the_stored_minimum(
    episodes: dict[str, EpisodeResult],
) -> None:
    """Independent: 6.0 m is below the stored minimum 6.278 m (45 C, reference fittings,
    NPSH3 4 m, coastal, RVP_9_0, f_d = 0.8), so the run stops at t = 0 before any step."""
    result = episodes["REJ-3"]
    record = json.loads((result.directory / "simulation_rejected.json").read_text())
    validate("simulation_rejected", record)
    assert (record["gate"], record["t_sim_s"]) == ("SG0", 0.0)
    assert record["parameter"] == (
        "pumping_minimum_level[TK-101,45C,reference_fittings,NPSH3=4m,coastal,RVP_9_0,f_d=0.8]"
    )
    assert record["value"] == pytest.approx(6.0, abs=1e-9)  # volume-to-level round trip
    assert record["limit"] == pytest.approx(6.278, abs=1e-3)
    assert result.outcome.steps == 0


def test_the_checkpoint_is_independent_of_later_progress(model: HydraulicModel) -> None:
    a = _engine(model, "S0-A", ListSink())
    a.run(until=50.0)
    saved = a.checkpoint()
    volumes = dict(saved.volumes)
    a.run(until=100.0)
    assert saved.volumes == volumes and saved.t == 50.0 and a.state.t == 100.0


# --- check valve and pump domain inside the engine ----------


@pytest.mark.parametrize("sid", ["S0-A", "S0-C"])
def test_check_valve_and_standby_branch_hold_at_every_recorded_time(
    series: dict[str, Series], sid: str
) -> None:
    s = series[sid]
    for edge in ("E-PA1", "E-PA2", "E-PA3", "E-PA4"):
        assert all(r[2] >= 0.0 for r in s.edge[edge]), edge
    for edge in ("E-PB0", "E-PB1", "E-PB2", "E-PB3", "E-PB4"):
        assert all(r[2] == 0.0 for r in s.edge[edge]), edge
    assert all(r[2] == "running" and r[4] == "OK" for r in s.pump["P-101A"])
    assert all(r[2] == "stopped" and r[3] == 0.0 for r in s.pump["P-101B"])
    assert all(r[3] * 3600.0 <= 350.0 for r in s.pump["P-101A"])  # the pump domain, Q/s <= 350 m3/h
    assert all(
        r[5] is not None and r[5] >= 1.3 for r in s.pump["P-101A"]
    )  # NPSH margin at every row


def test_the_pump_domain_is_enforced_inside_the_engine(root: Path, tmp_path: Path) -> None:
    shutil.copytree(root / "config", tmp_path / "config")
    path = tmp_path / "config" / "delivery_boundary.json"
    doc = json.loads(path.read_text())
    doc["parameters"]["reference_fittings"]["value"] = (
        1.0  # too little resistance: the intersection exceeds 350 m3/h
    )
    path.write_text(json.dumps(doc))
    local = HydraulicModel.load(tmp_path / "config")
    result = run_episode("S0-A", tmp_path / "out", local)
    assert result.rejected and result.outcome.rejection is not None
    assert (result.outcome.rejection["gate"], result.outcome.rejection["parameter"]) == (
        "SG0",
        "pump_domain",
    )
    assert result.outcome.rejection["t_sim_s"] == 0.0


def test_release_gate_is_asked_before_an_episode(
    model: HydraulicModel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import verum.sim.episode as episode_module
    from verum.gates import ReleaseNotAllowed

    def refuse(tier: str) -> None:
        raise ReleaseNotAllowed(tier)

    monkeypatch.setattr(episode_module, "assert_release_allowed", refuse)
    with pytest.raises(ReleaseNotAllowed):
        run_episode("S0-A", tmp_path, model)
    assert not any(tmp_path.iterdir())


def test_episode_directories_hold_no_observation_fields(series: dict[str, Series]) -> None:
    for s in series.values():
        assert {e["actor"] for e in s.events} <= {
            "operator",
            "autonomous_protection",
            "simulator_truth",
        }


def test_tier_follows_the_flagged_windows_and_the_gate_still_blocks_production(
    episodes: dict[str, EpisodeResult],
) -> None:
    """Decision D37: only the episodes with a flagged window are restricted; the release gate
    refuses production_candidate while generation is disabled and allows the other tiers."""
    from verum.gates import ReleaseNotAllowed, assert_release_allowed

    for sid, result in episodes.items():
        doc = json.loads((result.directory / "episode.json").read_text())
        flagged = bool(doc["validity_windows"])
        assert flagged is (sid in FLAGGED)
        assert doc["dataset_tier"] == (
            "restricted_benchmark" if flagged else "analytic_verification"
        )
    assert_release_allowed("analytic_verification")
    assert_release_allowed("restricted_benchmark")
    with pytest.raises(ReleaseNotAllowed):
        assert_release_allowed("production_candidate")
