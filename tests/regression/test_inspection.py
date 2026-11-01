"""The inspection package: catalog, models, preconditions, workflow, validator, history, gateway.

The checks use evaluator directories written by hand with a small test helper, so every
expected outcome is arithmetic on the true quantities that the test sets. Statistical checks use
many draws and four-sigma bounds. The checks on real episodes with known faults are in the file
of the slow tests.
Historical extrapolation tests explicitly opt into the archived research workflow.

See D100 to D109.
"""

from __future__ import annotations

import ast
import gzip
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from _inspection_cases import (
    EPISODE,
    SEED,
    edit,
    fault_truth,
    grid,
    request,
    row,
    write,
)
from verum.api import Gateway, GatewayViolation, check_allowlist
from verum.api.gateway import FORBIDDEN_TEXT
from verum.contracts import validate
from verum.contracts.paths import repo_root
from verum.inspection import history, models, preconditions, workflow
from verum.inspection.assets import load_assets
from verum.inspection.catalog import ACTION_IDS, load_catalog
from verum.inspection.service import InspectionService
from verum.inspection.truth import Truth
from verum.inspection.validation import RequestError
from verum.params import UnresolvedParameter
from verum.rng import RandomStreams
from verum.sensors import load_sensor_config

CATALOG = load_catalog()
ASSETS = load_assets()
SIGMAS = 4.0


def truth_of(tmp: Path, rows: list[dict[str, Any]], **kw: Any) -> Truth:
    return Truth(write(tmp, rows, **kw))


def outcome(
    tmp: Path, rows: list[dict[str, Any]], action: str, target: str, t: float = 1800.0,
    stream: int = 1,
) -> models.Outcome:  # fmt: skip
    state = truth_of(tmp, rows).state(t)
    rng = RandomStreams(SEED).stream(f"inspection/REQ-INSP-{stream:05d}/measurement")
    return models.perform(CATALOG, ASSETS, state, action, target, rng, allow_legacy_simulation=True)


def within(count: float, trials: int, p: float) -> bool:
    return abs(count - trials * p) <= SIGMAS * math.sqrt(trials * p * (1 - p)) + 1.0


# --- catalog ----------
def test_the_catalog_has_the_costs_durations_and_uncertainties_of_the_document() -> None:
    """The seven actions have the costs, durations and expanded uncertainties of the table of the
    instrumentation document, every record is a parameter record of the tag DESIGN with the
    provenance of D100, and the uncertainties the document does not state are unresolved.

    Independent: yes, because the numbers are copied by hand from the document.
    """
    assert ACTION_IDS == tuple(f"ACT-INSP-0{i}" for i in range(1, 8))
    cost = [CATALOG.action(a).cost_usd for a in ACTION_IDS]
    minutes = [CATALOG.action(a).duration_min for a in ACTION_IDS]
    assert cost == [280.0, 90.0, 140.0, 350.0, 110.0, 160.0, 120.0]
    assert minutes == [90.0, 45.0, 60.0, 120.0, 45.0, 60.0, 45.0]
    u = {
        ("ACT-INSP-01", "maximum_rim_seal_gap"): 1.0,
        ("ACT-INSP-02", "measured_differential_pressure"): 0.01,
        ("ACT-INSP-02", "stem_travel"): 2.0,
        ("ACT-INSP-03", "overall_velocity_rms"): 0.1,
        ("ACT-INSP-04", "acoustic_level"): 1.0,
        ("ACT-INSP-04", "wall_thickness"): 0.05,
        ("ACT-INSP-05", "manual_innage_level"): 1.5,
        ("ACT-INSP-07", "calibration_error"): 0.025,
    }
    for (action, name), value in u.items():
        assert CATALOG.action(action).u(name) == value
    for action, name in (
        ("ACT-INSP-03", "spectral_peak_ratios"), ("ACT-INSP-05", "water_bottom_cut"),
        ("ACT-INSP-06", "cracking_pressure"), ("ACT-INSP-04", "leak_station_along_edge"),
    ):  # fmt: skip
        with pytest.raises(UnresolvedParameter):
            CATALOG.action(action).u(name)
    raw = json.loads((repo_root() / "config" / "inspection_catalog.json").read_text())
    for a in raw["actions"].values():
        assert a["cost_usd"]["evidence_tag"] == "DESIGN"
        assert a["cost_usd"]["provenance_id"] == "VERUM-DD-D100-v1.0"


def test_the_agent_view_of_the_catalog_holds_no_model_or_threshold() -> None:
    """The view returned to agents has only the listed keys, the unresolved uncertainties are
    null, and none of the model, threshold or workflow constants appears in it.

    Independent: yes, because the key list is written out and the constants are searched as text.
    """
    view = CATALOG.agent_view()
    keys = {"action_id", "name", "target_kind", "targets", "preconditions", "cost_usd",
            "duration_min", "outputs"}  # fmt: skip
    assert len(view) == 7 and all(set(v) == keys for v in view)
    text = json.dumps(view)
    for word in ("q50", "threshold", "baseline", "rejection", "sigma", "0.9", "7.1", "2.8"):
        assert word not in text, word
    peaks = next(o for o in view[2]["outputs"] if o["name"] == "spectral_peak_ratios")
    assert peaks["uncertainty_k2"] is None and peaks["modelled"] is False


# --- truth: interpolation, pre/post pair, horizon ----------
def event_rows() -> list[dict[str, Any]]:
    rows = [row(0.0), row(60.0), row(100.0, "pre_event"), row(100.0, "post_event"), row(120.0),
            row(3600.0)]  # fmt: skip
    for r, level in zip(rows, (0.0, 6.0, 10.0, 30.0, 40.0, 40.0), strict=True):
        r["tanks"]["TK-101"]["level_m"] = level
    for r in rows[3:]:
        r["valves"]["XV-R000"]["commanded_open"] = False
    return rows


def test_a_number_is_interpolated_and_a_pair_takes_the_side_of_the_time(tmp_path: Path) -> None:
    """Between rows a number is linear; before an event at 100 s it runs from the row at 60 s to
    the pre-event row (6 to 10, so 8 at 80 s), at 100 s it is the post-event value 30, after it
    runs from 30 to 40 (35 at 110 s), and a state is that of the last row at or before the time.

    Independent: yes, because every expected value is linear arithmetic on the rows written here.
    """
    truth = truth_of(tmp_path, event_rows())

    def level(t: float) -> float:
        return float(truth.state(t)["tanks"]["TK-101"]["level_m"])

    def commanded(t: float) -> bool:
        return bool(truth.state(t)["valves"]["XV-R000"]["commanded_open"])

    assert level(30.0) == pytest.approx(3.0) and level(80.0) == pytest.approx(8.0)
    assert level(99.999999) == pytest.approx(10.0, abs=1e-5)
    assert level(100.0) == 30.0 and level(110.0) == pytest.approx(35.0)
    assert commanded(99.0) is True and commanded(100.0) is False and commanded(110.0) is False


def test_after_the_horizon_the_process_is_held_and_the_faults_follow_their_trajectories(
    tmp_path: Path,
) -> None:
    """After 3600 s the level stays at the last row. A pump head fault whose ramp ends at 3900 s
    has severity 0.25 at the horizon, 0.75 at 3800 s and 1 from 3900 s on, with the head scale
    1 - 0.3 s, while the process state is still the last row.

    Independent: yes, because the trajectory is a straight line written out by hand.
    """
    rows = grid()
    for r in rows:
        r["faults"] = [
            {
                "fault_instance_id": f"FI-{EPISODE}-00", "fault_type": "PUMP_HEAD_DEGRADATION",
                "asset_id": "P-101A", "severity": 0.0, "parameter": "pump_head_scale",
                "unit": "1", "parameter_value": 1.0,
            }
        ]  # fmt: skip
    rows[-1]["faults"][0].update(severity=0.25, parameter_value=0.925)
    rows[-1]["pumps"]["P-101A"]["head_scale"] = 0.925
    rows[-1]["tanks"]["TK-102"]["level_m"] = 7.5
    faults = [fault_truth("P-101A", "PUMP_HEAD_DEGRADATION", 3500.0, 400.0, 1.0, 0.7)]
    truth = truth_of(tmp_path, rows, faults=faults)
    held = truth.state(5000.0)
    assert held["tanks"]["TK-102"]["level_m"] == 7.5
    for t, s in ((3600.0, 0.25), (3800.0, 0.75), (3900.0, 1.0), (5000.0, 1.0)):
        state = truth.state(t)
        assert state["faults"][0]["severity"] == pytest.approx(s)
        assert state["pumps"]["P-101A"]["head_scale"] == pytest.approx(1.0 - 0.3 * s)


# --- actions on known truths ----------
def test_valve_check_separates_the_commanded_actual_and_contact_states(tmp_path: Path) -> None:
    """A fully open valve passing 0.05 m3/s through an edge of 0.20274 m has a loss of 90 Pa
    (0.1 * 750 * (0.05 / 0.032284)^2 / 2), so about 0.0009 bar and the category normal. Open to 0.5,
    with the loss coefficient 5.0, it shows 0.045 bar and the category minor because the stem does
    not follow the command. A closed valve with 3.0 bar on one side shows 0.1 bar (minor) with 2.9
    bar and 1.45 bar (critical) with 1.55 bar on the other.

    Independent: yes, because the drops are hand arithmetic; the coefficient 5.0 at an opening of
    0.5 is the value of the valve law of the hydraulic model.
    """
    rows = grid()
    for edge in ("E-S101a", "E-S101b"):
        edit(rows, f"edges.{edge}.flow_m3s", 0.05)
        edit(rows, f"edges.{edge}.p_from_pa_gauge", 300000.0)
        edit(rows, f"edges.{edge}.p_to_pa_gauge", 300000.0)
    area = math.pi * 0.20274**2 / 4.0
    open_drop = 0.1 * 750.0 * (0.05 / area) ** 2 / 2.0 / 1.0e5
    o = outcome(tmp_path, rows, "ACT-INSP-02", "XV-S101")
    assert o.name == "measured_differential_pressure" and o.unit == "bar"
    assert o.true["true_value"] == pytest.approx(open_drop, rel=1e-6)
    assert o.value == pytest.approx(open_drop, abs=5 * 0.005) and o.uncertainty_k2 == 0.01
    assert o.category == models.NORMAL
    edit(rows, "valves.XV-S101.position_frac", 0.5)
    o = outcome(tmp_path, rows, "ACT-INSP-02", "XV-S101")
    half = 5.0 * 750.0 * (0.05 / area) ** 2 / 2.0 / 1.0e5
    assert o.true["true_value"] == pytest.approx(half, rel=1e-6)
    assert o.value == pytest.approx(half, abs=5 * 0.005) and o.category == models.MINOR
    text = " ".join(o.notes)
    assert "Commanded state: open" in text and "Open contact reads open" in text
    travel = float(re.search(r"stem travel: ([0-9.]+) percent", text).group(1))  # type: ignore[union-attr]
    assert travel == pytest.approx(50.0, abs=5.0)
    edit(rows, "valves.XV-S101.position_frac", 0.0)
    edit(rows, "valves.XV-S101.commanded_open", False)
    for edge in ("E-S101a", "E-S101b"):
        edit(rows, f"edges.{edge}.flow_m3s", 0.0)
    edit(rows, "edges.E-S101b.p_from_pa_gauge", 290000.0)
    o = outcome(tmp_path, rows, "ACT-INSP-02", "XV-S101")
    assert o.value == pytest.approx(0.1, abs=5 * 0.005) and o.category == models.MINOR
    edit(rows, "edges.E-S101b.p_from_pa_gauge", 155000.0)
    o = outcome(tmp_path, rows, "ACT-INSP-02", "XV-S101")
    assert o.value == pytest.approx(1.45, abs=5 * 0.005) and o.category == models.CRITICAL


def test_pump_vibration_rises_monotonically_with_the_head_loss(tmp_path: Path) -> None:
    """The overall velocity is 1.5 + 5.6 h / 0.3 mm/s for a head loss fraction h: 1.5 at 0, 4.3 at
    0.15 and 8.0333 at 0.35, it increases with h, and the categories are normal, minor and critical.

    Independent: yes, because the law is evaluated by hand at three head losses.
    """
    expected = {
        0.0: (1.5, models.NORMAL),
        0.15: (4.3, models.MINOR),
        0.35: (8.0333, models.CRITICAL),
    }
    values = []
    for loss, (true, category) in expected.items():
        rows = grid()
        edit(rows, "pumps.P-101A.head_scale", 1.0 - loss)
        o = outcome(tmp_path, rows, "ACT-INSP-03", "P-101A")
        assert o.true["true_value"] == pytest.approx(true, abs=1e-3)
        assert o.value == pytest.approx(true, abs=5 * 0.05) and o.category == category
        values.append(o.true["true_value"])
    assert values == sorted(values) and len(set(values)) == 3
    assert "spectral peak ratios are not modelled" in " ".join(o.notes)


@pytest.mark.parametrize(
    ("q", "p"), [(0.0, 0.0), (0.45, 0.2), (0.9, 0.5), (1.8, 0.8), (9.0, 1 / 1.01)]
)
def test_the_detection_probability_follows_the_formula(q: float, p: float, tmp_path: Path) -> None:
    """The detection frequency over 2000 surveys of a leak of q m3/h is P = 1 / (1 + (0.9 / q)^2)
    within four binomial standard deviations: 0 at no leak, 0.2 at 0.45, 0.5 at 0.9, 0.8 at 1.8.

    Independent: yes, because the probabilities are evaluated by hand from the formula.
    """
    assert models.detection_probability(q, 0.9) == pytest.approx(p)
    rows = grid()
    if q > 0.0:
        edit(rows, "leaks", [{"fault_instance_id": "FI-x", "edge_id": "E-D1", "fraction": 0.4,
                              "flow_m3s": q / 3600.0}])  # fmt: skip
    state = truth_of(tmp_path, rows).state(1800.0)
    hits = 0
    for k in range(2000):
        rng = np.random.default_rng(k)
        hits += models.leak_survey(CATALOG, ASSETS, state, "E-D1", rng).value == 1.0
    assert within(hits, 2000, p), (q, hits)


def test_a_survey_of_another_edge_finds_nothing_and_the_station_error_is_stated(
    tmp_path: Path,
) -> None:
    """A leak on E-D1 is not found by a survey of E-D2, and the stations reported for E-D1 have
    mean near the true position (0.4 of the edge length) and standard deviation near 5 m, clipped
    to the edge.

    Independent: yes, because the mean and spread are those of the declared distribution.
    """
    length = ASSETS.edges["E-D1"].length_m
    rows = grid()
    edit(rows, "leaks", [{"fault_instance_id": "FI-x", "edge_id": "E-D1", "fraction": 0.4,
                          "flow_m3s": 0.25}])  # fmt: skip
    state = truth_of(tmp_path, rows).state(1800.0)
    assert models.leak_survey(CATALOG, ASSETS, state, "E-D2", np.random.default_rng(1)).value == 0.0
    stations = []
    for k in range(3000):
        o = models.leak_survey(CATALOG, ASSETS, state, "E-D1", np.random.default_rng(k))
        assert o.category == models.CRITICAL
        stations.append(float(re.search(r"at ([0-9.]+) m", o.notes[0]).group(1)))  # type: ignore[union-attr]
    assert all(0.0 <= s <= length for s in stations)
    if length > 40.0:  # the clip does not bias the mean and spread
        assert np.mean(stations) == pytest.approx(0.4 * length, abs=0.5)
        assert np.std(stations) == pytest.approx(5.0, rel=0.05)


def test_the_dip_detects_a_level_sensor_fault_and_a_calibration_detects_a_pressure_fault(
    tmp_path: Path,
) -> None:
    """With a level offset of 0.5 m on LT-101 the sounding of 9000 mm differs from the reported
    9500 mm and is inconclusive, without it it is normal; a bias of 5 percent of the 10 bar span on
    PT-202A gives a calibration error of -5 percent of span, without it the error is near 0.

    Independent: yes, because the offsets are set by hand and the expected values are arithmetic.
    """
    rows = grid()
    o = outcome(tmp_path, rows, "ACT-INSP-05", "TK-101")
    assert o.value == pytest.approx(9000.0, abs=5.0) and o.category == models.NORMAL
    edit(rows, "tags.LT-101.fault_offset", 0.5)
    o = outcome(tmp_path, rows, "ACT-INSP-05", "TK-101")
    assert o.value == pytest.approx(9000.0, abs=5.0) and o.category == models.INCONCLUSIVE
    spec = load_sensor_config().tags["PT-202A"]
    span = spec.range_hi - spec.range_lo  # type: ignore[operator]
    rows = grid()
    o = outcome(tmp_path, rows, "ACT-INSP-07", "PT-202A")
    assert o.value == pytest.approx(0.0, abs=0.05) and o.category == models.NORMAL
    edit(rows, "tags.PT-202A.fault_offset", 0.05 * span * 1.0e5)
    o = outcome(tmp_path, rows, "ACT-INSP-07", "PT-202A")
    assert o.value == pytest.approx(-5.0, abs=0.05) and o.category == models.INCONCLUSIVE
    assert o.unit == "percent of span"


def test_a_stuck_level_sensor_is_found_by_the_dip(tmp_path: Path) -> None:
    """A stuck LT-102 reports 6 m while the level has risen to 8 m: the offset is -2 m, the
    sounding of 8000 mm differs from the reported 6000 mm and is inconclusive.

    Independent: yes, because the stuck value and the true level are set by hand.
    """
    rows = grid()
    edit(rows, "tanks.TK-102.level_m", 8.0)
    edit(rows, "tags.LT-102.value", 8.0)
    edit(rows, "tags.LT-102.fault_offset", -2.0)
    o = outcome(tmp_path, rows, "ACT-INSP-05", "TK-102")
    assert o.value == pytest.approx(8000.0, abs=5.0) and o.category == models.INCONCLUSIVE


def test_the_actions_that_wait_for_the_vapour_track_return_an_intact_result_and_say_so(
    tmp_path: Path,
) -> None:
    """The rim survey and the fitting check return the category intact, a gap of at least 0 mm
    near 0, low confidence, and a note that the state is not available.

    Independent: yes, because the placeholder is the rule of D109.
    """
    rows = grid()
    for action, name in (
        ("ACT-INSP-01", "maximum_rim_seal_gap"),
        ("ACT-INSP-06", "seating_integrity"),
    ):
        o = outcome(tmp_path, rows, action, "TK-103")
        assert o.name == name and o.category == models.NORMAL and o.evidence == "low_confidence"
        assert o.value >= 0.0 and o.value < 2.0
        assert any("not available in this release" in n for n in o.notes)


# --- measurement error ----------
def test_the_measurement_error_has_mean_zero_and_standard_deviation_u_over_two(
    tmp_path: Path,
) -> None:
    """Over 4000 draws the error of the pressure drop, of the sounding and of the calibration has
    mean zero and standard deviation U/2 (0.005 bar, 0.75 mm, 0.0125 percent of span) within
    sampling error.

    Independent: yes, because the targets are the stated U/2 and the bounds are statistical.
    """
    rows = grid()
    edit(rows, "edges.E-S101a.p_to_pa_gauge", 300000.0)
    edit(rows, "edges.E-S101b.p_from_pa_gauge", 290000.0)
    state = truth_of(tmp_path, rows).state(1800.0)
    cases = [
        (models.valve_check, "XV-S101", models.valve_drop_bar(ASSETS, state, "XV-S101"), 0.005),
        (models.dip_sounding, "TK-101", 9000.0, 0.75),
        (models.loop_calibration, "PT-001", 0.0, 0.0125),
    ]
    for model, target, true, sd in cases:
        draws = [
            model(CATALOG, ASSETS, state, target, np.random.default_rng(k)) for k in range(4000)
        ]
        errors = np.array([o.value - true for o in draws])
        assert abs(errors.mean()) <= SIGMAS * sd / math.sqrt(4000), model.__name__
        assert errors.std() == pytest.approx(sd, rel=SIGMAS / math.sqrt(2 * 4000)), model.__name__


# --- preconditions ----------
def test_the_preconditions_pass_and_fail_with_plain_reason_codes(tmp_path: Path) -> None:
    """Level 1.7 m fails and 1.9 m passes; a valve with no flow and no pressure fails and one with a
    flow passes; a drop to 2.9 bar fails and 3.1 bar passes; a tank receiving fails and a tank at
    rest passes; the actions with a permit only always pass.

    Independent: yes, because each case is a state set by hand against the stated limit.
    """

    def code(rows: list[dict[str, Any]], action: str, target: str, t: float = 1800.0) -> Any:
        return preconditions.check(CATALOG, ASSETS, truth_of(tmp_path, rows), action, target, t)

    rows = grid()
    edit(rows, "tanks.TK-101.level_m", 1.7)
    assert code(rows, "ACT-INSP-01", "TK-101") == "LEVEL_BELOW_1_8_M"
    edit(rows, "tanks.TK-101.level_m", 1.9)
    assert code(rows, "ACT-INSP-01", "TK-101") is None
    rows = grid()
    for edge in ("E-S101a", "E-S101b"):
        edit(rows, f"edges.{edge}.flow_m3s", 0.0)
        edit(rows, f"edges.{edge}.p_from_pa_gauge", 0.0)
        edit(rows, f"edges.{edge}.p_to_pa_gauge", 0.0)
    assert code(rows, "ACT-INSP-02", "XV-S101") == "VALVE_NOT_FLOWING_OR_PRESSURISED"
    assert code(rows, "ACT-INSP-02", "XV-S102") is None
    edit(rows, "edges.E-S101b.flow_m3s", 0.05)
    assert code(rows, "ACT-INSP-02", "XV-S101") is None
    rows = grid()
    edit(rows, "edges.E-D1.p_from_pa_gauge", 290000.0)
    edit(rows, "edges.E-D1.p_to_pa_gauge", 290000.0)
    assert code(rows, "ACT-INSP-04", "E-D1") == "EDGE_BELOW_3_BAR"
    edit(rows, "edges.E-D1.p_to_pa_gauge", 330000.0)
    assert code(rows, "ACT-INSP-04", "E-D1") is None  # the mean of the ends is 3.1 bar
    rows = grid()
    for edge in ("E-R101a", "E-R101b", "E-R102a", "E-R102b", "E-R103a", "E-R103b"):
        edit(rows, f"edges.{edge}.flow_m3s", 0.0)
    assert code(rows, "ACT-INSP-06", "TK-101") is None
    edit(rows, "edges.E-R101a.flow_m3s", 0.02)
    assert code(rows, "ACT-INSP-06", "TK-101") == "TANK_IN_RECEIPT_MODE"
    assert code(rows, "ACT-INSP-06", "TK-102") is None
    for action, target in (("ACT-INSP-05", "TK-101"), ("ACT-INSP-07", "PT-001")):
        assert code(grid(), action, target) is None


def test_a_pump_must_have_run_under_load_for_twenty_minutes(tmp_path: Path) -> None:
    """At 1100 s the pump has run for less than 1200 s and fails; at 1300 s it passes; with a stop
    between 700 and 800 s it fails at 1500 s (the window starts at 300 s) and passes at 2100 s;
    a pump with no flow in its discharge edge fails.

    Independent: yes, because the window of 20 min is stated in the decision and applied by hand.
    """

    def code(rows: list[dict[str, Any]], t: float) -> Any:
        truth = truth_of(tmp_path, rows)
        return preconditions.check(CATALOG, ASSETS, truth, "ACT-INSP-03", "P-101A", t)

    rows = grid()
    assert code(rows, 1100.0) == "PUMP_NOT_UNDER_LOAD_20_MIN" and code(rows, 1300.0) is None
    for r in rows:
        if 700.0 <= r["t_sim_s"] <= 800.0:
            r["pumps"]["P-101A"]["run_state"] = "stopped"
    assert code(rows, 1500.0) == "PUMP_NOT_UNDER_LOAD_20_MIN" and code(rows, 2100.0) is None
    rows = grid()
    edit(rows, "edges.E-PA2.flow_m3s", 0.0)
    assert code(rows, 2100.0) == "PUMP_NOT_UNDER_LOAD_20_MIN"


# --- workflow ----------
def test_the_timeline_has_the_stated_delays_and_order(tmp_path: Path) -> None:
    """Over 3000 requests the approval delay is uniform from 300 to 1800 s, the scheduling delay
    uniform from 0 to 900 s, the performed time is the start plus the duration of the action, the
    result is visible 120 s later, the order is strict, and 5 percent are rejected for a non-safety
    reason within binomial bounds.

    Independent: yes, because the ranges and the rejection probability are stated in D101.
    """
    truth = truth_of(tmp_path, grid())
    plans = [
        workflow.plan(CATALOG, ASSETS, truth, f"REQ-INSP-{i:05d}", "ACT-INSP-05", "TK-101",
                      100.0, allow_extrapolated_research=True)
        for i in range(3000)
    ]
    approval = np.array([p.t_decision_s - 100.0 for p in plans])
    scheduling = np.array([p.t_start_s - p.t_decision_s for p in plans])
    assert 300.0 <= approval.min() and approval.max() <= 1800.0
    assert 0.0 <= scheduling.min() and scheduling.max() <= 900.0
    assert abs(approval.mean() - 1050.0) < SIGMAS * 433.0 / math.sqrt(3000)
    assert abs(scheduling.mean() - 450.0) < SIGMAS * 260.0 / math.sqrt(3000)
    for p in plans:
        assert p.t_performed_s - p.t_start_s == pytest.approx(45.0 * 60.0)
        assert p.t_visible_s - p.t_performed_s == pytest.approx(120.0)
        assert p.t_requested_s < p.t_decision_s <= p.t_start_s < p.t_performed_s < p.t_visible_s
    assert within(sum(p.reason == "NON_SAFETY_REASON" for p in plans), 3000, 0.05)


def test_a_request_has_the_same_timeline_whatever_the_other_requests_are(tmp_path: Path) -> None:
    """The timeline and the outcome of a request are the same when other requests are submitted
    before it, after it, or not at all, and when the service is built again.

    Independent: yes, because the comparison is between runs of the same request.
    """
    folder = write(tmp_path, grid())
    alone = InspectionService(folder, allow_extrapolated_research=True)
    alone.submit(request(7, "ACT-INSP-05", "TK-101"), 100.0)
    busy = InspectionService(folder, allow_extrapolated_research=True)
    for n, (action, target) in enumerate(
        (("ACT-INSP-05", "TK-102"), ("ACT-INSP-02", "XV-S101")), 1
    ):
        busy.submit(request(n, action, target), 100.0)
    busy.submit(request(7, "ACT-INSP-05", "TK-101"), 100.0)
    busy.submit(request(9, "ACT-INSP-07", "PT-001"), 100.0)
    a, b = alone.record("REQ-INSP-00007"), busy.record("REQ-INSP-00007")
    assert a.timeline == b.timeline
    assert a.outcome is not None and b.outcome is not None
    assert (a.outcome.value, a.outcome.category) == (b.outcome.value, b.outcome.category)


def test_no_result_is_visible_before_the_performed_time_plus_the_delivery(tmp_path: Path) -> None:
    """A result is requested at the request time, approved after the decision, and has findings only
    from the performed time plus 120 s; one instant earlier it has none; a rejected request is
    cancelled from the decision and never has findings; an asset without a request has no row.

    Independent: yes, because the instants are those of the timeline that the test reads.
    """
    service = InspectionService(write(tmp_path, grid()), allow_extrapolated_research=True)
    approved = rejected = None
    for n in range(1, 60):
        service.submit(request(n, "ACT-INSP-05", "TK-101"), 100.0)
        tl = service.record(f"REQ-INSP-{n:05d}").timeline
        approved = approved or (tl if tl.approved else None)
        rejected = rejected or (tl if not tl.approved else None)
    assert approved is not None and rejected is not None
    rows = {r["request_id"]: r for r in service.results(100.0)}
    assert {r["workflow_status"] for r in rows.values()} == {"requested"}
    assert len(rows) == 59 and set(rows[approved.request_id]) == {
        "schema_version",
        "dataset",
        "result_id",
        "request_id",
        "action_id",
        "workflow_status",
    }

    def status(tl: workflow.Timeline, t: float) -> dict[str, Any]:
        return {r["request_id"]: r for r in service.results(t)}[tl.request_id]

    assert status(approved, approved.t_decision_s)["workflow_status"] == "approved"
    before = status(approved, approved.t_visible_s - 1e-6)
    assert before["workflow_status"] == "approved" and "findings" not in before
    after = status(approved, approved.t_visible_s)
    assert after["workflow_status"] == "performed" and after["findings"]["primary_metric"]
    assert after["performed_at_t_sim_s"] == approved.t_performed_s
    assert status(rejected, rejected.t_decision_s)["workflow_status"] == "cancelled"
    assert "findings" not in status(rejected, rejected.t_visible_s + 1e5)
    views = {r["request_id"]: r for r in service.requests(rejected.t_decision_s)}
    assert views[rejected.request_id]["human_approval"]["status"] == "REJECTED"
    assert views[rejected.request_id]["human_approval"]["rejection_reason"] == rejected.reason
    empty = InspectionService(write(tmp_path / "other", grid()), allow_extrapolated_research=True)
    assert not empty.results(1e6)


def test_a_failed_precondition_rejects_the_request_with_its_code(tmp_path: Path) -> None:
    """A survey of a tank at 1.5 m is rejected at the decision with the code
    LEVEL_BELOW_1_8_M (unless the random non-safety rejection came first), and the request view
    shows the status REJECTED and that reason.

    Independent: yes, because the level is set by hand against the stated limit.
    """
    rows = grid()
    edit(rows, "tanks.TK-103.level_m", 1.5)
    service = InspectionService(write(tmp_path, rows), allow_extrapolated_research=True)
    reasons = set()
    for n in range(1, 40):
        service.submit(request(n, "ACT-INSP-01", "TK-103"), 100.0)
        tl = service.record(f"REQ-INSP-{n:05d}").timeline
        assert not tl.approved
        reasons.add(tl.reason)
        view = service.requests(tl.t_decision_s)[-1]
        assert view["human_approval"]["status"] == "REJECTED"
    assert reasons <= {"LEVEL_BELOW_1_8_M", "NON_SAFETY_REASON"} and "LEVEL_BELOW_1_8_M" in reasons


# --- request validator ----------
def test_the_request_validator_refuses_what_the_rules_forbid(tmp_path: Path) -> None:
    """The service refuses an unknown asset, an action not allowed for the kind of the asset, a
    reported information gain above log2 of the number of distinct hypotheses (1.585 bits for 3,
    1 bit for 2), fewer than two distinct hypotheses, a request dated in the future, a duplicate
    identifier, a request that sets its own approval and a request outside the closed schema; and
    it accepts a request at the bound.

    Independent: yes, because the bounds are evaluated by hand.
    """
    service = InspectionService(write(tmp_path, grid()), allow_extrapolated_research=True)

    def code(req: dict[str, Any], t: float = 100.0) -> str:
        with pytest.raises(RequestError) as info:
            service.submit(req, t)
        return info.value.code

    assert code(request(1, "ACT-INSP-05", "TK-999")) == "UNKNOWN_ASSET"
    assert code(request(1, "ACT-INSP-03", "TK-101")) == "ACTION_NOT_ALLOWED_FOR_ASSET"
    assert code(request(1, "ACT-INSP-04", "XV-S101")) == "ACTION_NOT_ALLOWED_FOR_ASSET"
    assert code(request(1, "ACT-INSP-05", "TK-101", hypotheses=3, gain=1.6)) == (
        "INFORMATION_GAIN_EXCEEDS_BOUND"
    )
    assert code(request(1, "ACT-INSP-05", "TK-101", hypotheses=2, gain=1.01)) == (
        "INFORMATION_GAIN_EXCEEDS_BOUND"
    )
    same = request(1, "ACT-INSP-05", "TK-101")
    same["justification"]["competing_hypotheses"] = ["a", "a"]
    assert code(same) == "TOO_FEW_DISTINCT_HYPOTHESES"
    assert code(request(1, "ACT-INSP-05", "TK-101", t=500.0), 100.0) == "REQUEST_IN_THE_FUTURE"
    approved = request(1, "ACT-INSP-05", "TK-101")
    approved["human_approval"] = {"status": "APPROVED", "approver_id": "A"}
    assert code(approved) == "APPROVAL_SET_BY_AGENT"
    broken = request(1, "ACT-INSP-05", "TK-101")
    del broken["justification"]
    assert code(broken) == "SCHEMA"
    extra = {**request(1, "ACT-INSP-05", "TK-101"), "true_value": 1.0}
    assert code(extra) == "SCHEMA"
    service.submit(request(1, "ACT-INSP-05", "TK-101", hypotheses=3, gain=math.log2(3)), 100.0)
    service.submit(request(2, "ACT-INSP-05", "TK-101", hypotheses=2, gain=1.0), 100.0)
    assert code(request(1, "ACT-INSP-05", "TK-101")) == "DUPLICATE_REQUEST_ID"


# --- history ----------
def test_the_history_does_not_depend_on_the_faults_of_the_episode(tmp_path: Path) -> None:
    """A faulted and a healthy episode with the same seed have the same history, another seed has a
    different one, every record passes the closed schema, every prior record lies before the start,
    and a record holds no measured value.

    Independent: yes, because the two episodes differ only in their truth and the comparison is
    equality of the records.
    """
    healthy = InspectionService(write(tmp_path / "h", grid()), allow_extrapolated_research=True)
    rows = grid()
    edit(rows, "leaks", [{"fault_instance_id": "FI-x", "edge_id": "E-D1", "fraction": 0.4,
                          "flow_m3s": 0.01}], since=1000.0)  # fmt: skip
    faulted = InspectionService(
        write(
            tmp_path / "f",
            rows,
            faults=[fault_truth("E-D1", "PIPE_LEAK", 1000.0, 300.0, 0.0, 1e-4)],
        ), allow_extrapolated_research=True,
    )
    other = InspectionService(write(tmp_path / "o", grid(), seed=SEED + 1),
                              allow_extrapolated_research=True)
    assert healthy.history(0.0) == faulted.history(0.0) != other.history(0.0)
    records = healthy.history(0.0)
    assert len(records) > 50 and all(r["t_recorded_s"] < 0 for r in records)
    allowed = {
        "schema_version", "dataset", "record_id", "asset_id", "kind", "t_recorded_s", "description",
        "action_id", "outcome_category", "within_tolerance", "work_type",
    }  # fmt: skip
    assert all(set(r) <= allowed for r in records)
    assert {r["kind"] for r in records} == {"inspection", "calibration", "work_order"}
    assert len({r["record_id"] for r in records}) == len(records)
    assert all(r["asset_id"] in {a["asset_id"] for a in ASSETS.listing()} for r in records)
    assert history.prior_history(SEED, CATALOG, ASSETS) == history.prior_history(
        SEED, CATALOG, ASSETS
    )


def test_the_history_is_time_gated_and_a_performed_inspection_adds_a_record(
    tmp_path: Path,
) -> None:
    """An in-episode inspection adds a history record only from the time its result is visible, and
    a prior record is visible from the start.

    Independent: yes, because the instants are read from the timeline.
    """
    service = InspectionService(write(tmp_path, grid()), allow_extrapolated_research=True)
    for n in range(1, 30):
        service.submit(request(n, "ACT-INSP-05", "TK-101"), 100.0)
    tl = next(r.timeline for r in map(service.record, [f"REQ-INSP-{n:05d}" for n in range(1, 30)])
              if r.timeline.approved)  # fmt: skip
    base = len(service.history(0.0))
    assert len(service.history(tl.t_visible_s - 1e-6)) < len(service.history(tl.t_visible_s))
    assert len(service.history(0.0)) == base
    appended = [r for r in service.history(tl.t_visible_s) if r["t_recorded_s"] >= 0]
    assert appended and all(r["kind"] == "inspection" for r in appended)


# --- gateway and leakage ----------
def agent_gateway(tmp: Path, service: InspectionService | None) -> Gateway:
    folder = tmp / "agent" / EPISODE
    folder.mkdir(parents=True)
    with gzip.open(folder / "observations.jsonl.gz", "wt", encoding="utf-8"):
        pass
    return Gateway(folder, service)


def strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in [str(k), *strings(v)]]
    if isinstance(node, list):
        return [s for v in node for s in strings(v)]
    return [node] if isinstance(node, str) else []


def test_lk_gateway_functions_return_schema_rows_and_no_hidden_text(tmp_path: Path) -> None:
    """Over all seven actions, the payloads of catalog, requests, results and history pass the
    allowlist and the closed schemas, hold no key outside the interface, and no string that names a
    truth dataset, a fault, a severity, a fault instance, a window or a scenario (LK-01 to LK-08,
    LK-12).

    Independent: yes, because the hidden words are listed by hand and the payloads are scanned.
    """
    rows = grid()
    edit(rows, "leaks", [{"fault_instance_id": "FI-hidden", "edge_id": "E-D1", "fraction": 0.4,
                          "flow_m3s": 0.01}])  # fmt: skip
    edit(rows, "faults", [{"fault_instance_id": "FI-hidden", "fault_type": "PIPE_LEAK",
                           "asset_id": "E-D1", "severity": 1.0, "parameter": "leak_area",
                           "unit": "m2", "parameter_value": 1e-4}])  # fmt: skip
    faults = [fault_truth("E-D1", "PIPE_LEAK", 0.0, 1.0, 0.0, 1e-4)]
    service = InspectionService(write(tmp_path, rows, faults=faults),
                                allow_extrapolated_research=True)
    gateway = agent_gateway(tmp_path, service)
    targets = [("ACT-INSP-01", "TK-101"), ("ACT-INSP-02", "XV-S101"), ("ACT-INSP-03", "P-101A"),
               ("ACT-INSP-04", "E-D1"), ("ACT-INSP-05", "TK-101"), ("ACT-INSP-06", "TK-102"),
               ("ACT-INSP-07", "PT-001")]  # fmt: skip
    for n, (action, target) in enumerate(targets, 1):
        gateway.submit_request(request(n, action, target), 100.0)
    late = 1.0e6
    payloads = [gateway.catalog(), gateway.requests(late), gateway.results(late),
                gateway.history(late), gateway.query(late)]  # fmt: skip
    hidden = re.compile(
        r"(?i)fault|severity|FI-|VW-|truth|hidden|ground_truth|scenario|tier|window"
    )
    for payload in payloads:
        check_allowlist(payload)
        assert set(payload) <= {"episode_id", "as_of_s", "observations", "assets",
                                "inspection_catalog", "inspection_requests", "inspection_results",
                                "history"}  # fmt: skip
        for text in strings(payload):
            assert not FORBIDDEN_TEXT.search(text) and not hidden.search(text), text
    performed = [
        r for r in payloads[2]["inspection_results"] if r["workflow_status"] == "performed"
    ]
    assert performed
    for r in performed:
        validate("inspection_result", r)
        assert set(r["findings"]) == {
            "outcome_category",
            "primary_metric",
            "secondary_observations",
        }


def test_the_gateway_without_a_service_refuses_and_the_api_package_stays_clean(
    tmp_path: Path,
) -> None:
    """A gateway with no inspection service refuses to submit or to return results, and the api
    package imports neither the truth readers nor the models, workflow or history of the
    inspection package, only its catalog, its asset list and its schema check.

    Independent: yes, because the import lists are read from the source files.
    """
    gateway = agent_gateway(tmp_path, None)
    with pytest.raises(GatewayViolation):
        gateway.results(10.0)
    with pytest.raises(GatewayViolation):
        gateway.submit_request(request(1, "ACT-INSP-05", "TK-101"), 100.0)
    assert gateway.catalog()["inspection_catalog"]
    imported = set()
    for path in (repo_root() / "src" / "verum" / "api").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported |= {node.module, *(f"{node.module}.{a.name}" for a in node.names)}
    inspection = {m for m in imported if m.startswith("verum.inspection")}
    allowed = {"assets", "catalog", "checks"}
    assert {m.split(".")[2] for m in inspection} <= allowed
    assert not any(m.startswith(("verum.truth", "verum.sim", "verum.hydraulics")) for m in imported)


def test_the_outcome_keeps_the_true_quantity_out_of_the_serialised_result(tmp_path: Path) -> None:
    """The evaluator-side record holds the true quantity of an outcome, and no serialised result or
    request view carries a key for it.

    Independent: yes, because the keys of the views are compared with the closed schema.
    """
    service = InspectionService(write(tmp_path, grid()), allow_extrapolated_research=True)
    for n in range(1, 25):
        service.submit(request(n, "ACT-INSP-05", "TK-101"), 100.0)
    done = [service.record(f"REQ-INSP-{n:05d}") for n in range(1, 25)]
    done = [r for r in done if r.outcome is not None]
    assert done and all("true_value" in r.outcome.true for r in done if r.outcome)
    text = json.dumps(service.results(1e6)) + json.dumps(service.requests(1e6))
    assert "true_value" not in text and "reported_mm" not in text


def test_the_service_is_deterministic(tmp_path: Path) -> None:
    """Two services over the same directory return identical requests, results and history for the
    same submissions, and a different request identifier gives a different draw.

    Independent: no, because it compares the function with itself; it guards against hidden state.
    """
    folder = write(tmp_path, grid())
    outputs = []
    for _ in range(2):
        s = InspectionService(folder, allow_extrapolated_research=True)
        for n in (3, 4):
            s.submit(request(n, "ACT-INSP-02", "XV-S101"), 100.0)
        outputs.append((s.requests(1e6), s.results(1e6), s.history(1e6)))
    assert outputs[0] == outputs[1]
    s = InspectionService(folder, allow_extrapolated_research=True)
    for n in range(1, 40):
        s.submit(request(n, "ACT-INSP-05", "TK-101"), 100.0)
    values = {s.record(f"REQ-INSP-{n:05d}").outcome.value for n in range(1, 40)  # type: ignore[union-attr]
              if s.record(f"REQ-INSP-{n:05d}").outcome}  # fmt: skip
    assert len(values) > 10
