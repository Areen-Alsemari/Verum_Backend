"""The inspection actions on real episodes with known faults.

Short episodes are run with one fault each (a leak, a restriction in both modes, a pump head loss,
a sensor bias, drift and stuck-at, and a misrouting that forces an idle valve open) and each action
is performed on the true state after the ramp. The expected outcomes are worked out by hand from the
known parameters of the fault, so the models are checked against the engine and not against their
own inputs.

See D102 and D103.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import pytest

from verum.campaign.eligibility import model_and_table
from verum.faults import FaultSet, FaultSpec
from verum.inspection import models
from verum.inspection.assets import load_assets
from verum.inspection.catalog import load_catalog
from verum.inspection.service import InspectionService
from verum.rng import RandomStreams
from verum.sim.episode import EpisodeResult, run_episode
from verum.sim.scenario import parse_scenario

CATALOG = load_catalog()
ASSETS = load_assets()
ONSET, RAMP, T = 630.0, 300.0, 2400.0
pytestmark = pytest.mark.slow


def scenario(name: str) -> dict[str, Any]:
    return {
        "scenario_id": f"INSPE-{name}", "description": "inspection", "seed": 23,
        "duration_s": 2500.0, "temperature_c": 25.0, "fitting_profile": "reference_fittings",
        "healthy_envelope": True, "atmosphere_stratum": "coastal", "volatility_class": "RVP_9_0",
        "demand_process": True, "variability_profile": "v2",
        "initial": {
            "mode": "DELIVER_101_A", "receipt_flow_m3h": 0.0, "receipt_setpoint_m3h": 0.0,
            "tank_levels_m": {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0},
        },
        "schedule": [],
    }  # fmt: skip


def fault(
    kind: str, variant: str, asset: str, ramp: float | None, magnitude: float, **kw: Any
) -> FaultSpec:
    return FaultSpec(kind, variant, asset, ONSET, ramp, magnitude, **kw)


FAULTS: dict[str, FaultSpec | None] = {
    "healthy": None,
    "leak": fault("PIPE_LEAK", "orifice", "E-D1", RAMP, 1e-4, position=0.5,
                  discharge_coefficient=0.62),
    "restriction": fault("VALVE_RESTRICTION", "restriction", "XV-S101", RAMP, 0.5,
                         fault_mode="position_visible"),
    "obstruction": fault("VALVE_RESTRICTION", "restriction", "XV-S101", RAMP, 0.5,
                         fault_mode="obstruction"),
    "pump": fault("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", RAMP, 0.8),
    "bias": fault("SENSOR_DRIFT", "bias", "PT-202A", None, 0.05),
    "drift": fault("SENSOR_DRIFT", "drift", "PT-203", None, 0.02),
    "stuck": fault("SENSOR_DRIFT", "stuck", "LT-101", None, 0.0),
    "misroute_a": fault("VALVE_MISROUTING", "closed_but_open", "XV-S102", RAMP, 1.0),
}  # fmt: skip


@pytest.fixture(scope="module")
def episodes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, InspectionService]:
    model, _ = model_and_table()
    out: dict[str, InspectionService] = {}
    for name, spec in FAULTS.items():
        root = tmp_path_factory.mktemp(name)
        raw = scenario(name)
        faults = FaultSet((spec,)) if spec is not None else None
        result: EpisodeResult = run_episode(
            raw["scenario_id"], root, model, parse_scenario(raw), faults
        )
        assert not result.rejected, (name, result.outcome.rejection)
        (result.directory / "scenario.json").write_text(json.dumps(raw), encoding="utf-8")
        out[name] = InspectionService(result.directory, allow_extrapolated_research=True)
    return out


def perform(service: InspectionService, action: str, target: str, k: int = 1) -> models.Outcome:
    state = service.truth.state(T)
    rng = RandomStreams(service.truth.seed).stream(f"inspection/REQ-INSP-{k:05d}/measurement")
    return models.perform(CATALOG, ASSETS, state, action, target, rng)


def test_a_leak_is_detected_with_the_probability_of_its_orifice_flow(
    episodes: dict[str, InspectionService],
) -> None:
    """The leak flow in the truth is the orifice flow of a leak of 1e-4 m2 with a coefficient of
    0.62 at the pressure of its edge, to within 15 percent, and a survey of the edge detects it with
    the frequency 1 / (1 + (0.9 / q)^2) within four standard deviations, while a survey of an edge
    without the leak and every survey of a healthy episode find nothing.

    Independent: yes, because the flow is the orifice law evaluated by hand from the known area
    and the pressure in the truth, and the probability is the formula.
    """
    service = episodes["leak"]
    state = service.truth.state(T)
    leak = state["leaks"][0]
    edge = state["edges"]["E-D1"]
    pressure = 0.5 * (edge["p_from_pa_gauge"] + edge["p_to_pa_gauge"])
    expected = 0.62 * 1e-4 * math.sqrt(2.0 * pressure / 750.0)
    assert leak["flow_m3s"] == pytest.approx(expected, rel=0.15)
    q = leak["flow_m3s"] * 3600.0
    p = models.detection_probability(q, 0.9)
    hits = sum(
        models.leak_survey(CATALOG, ASSETS, state, "E-D1", np.random.default_rng(k)).value
        for k in range(1500)
    )
    assert abs(hits - 1500 * p) <= 4.0 * math.sqrt(1500 * p * (1 - p)) + 1.0
    other = models.leak_survey(CATALOG, ASSETS, state, "E-D2", np.random.default_rng(1))
    assert other.value == 0.0
    healthy = episodes["healthy"].truth.state(T)
    assert not healthy["leaks"]
    assert (
        models.leak_survey(CATALOG, ASSETS, healthy, "E-D1", np.random.default_rng(1)).value == 0.0
    )


def test_the_restriction_modes_differ_in_the_contact_and_agree_in_the_opening(
    episodes: dict[str, InspectionService],
) -> None:
    """A restriction with an opening ceiling of 0.5 on the open suction valve shows an actual
    opening near 50 percent and a higher drop (about 0.12 bar against 0.003 bar, from the loss
    coefficient 5.0 at that opening and a flow near 300 m3/h) in both modes, and the category
    minor. In the position-visible mode the contact reads closed, and in the obstruction mode it
    still reads open. The healthy valve is open with a drop below the limit and the category normal.

    Independent: yes, because the ceiling is the known fault parameter, the contact threshold of
    0.98 is the stated rule of the contact, and the drops are hand arithmetic.
    """

    def notes(name: str) -> tuple[models.Outcome, float, str]:
        o = perform(episodes[name], "ACT-INSP-02", "XV-S101")
        text = " ".join(o.notes)
        travel = float(re.search(r"stem travel: ([0-9.]+) percent", text).group(1))  # type: ignore[union-attr]
        return o, travel, text

    healthy, h_travel, h_text = notes("healthy")
    assert h_travel == pytest.approx(100.0, abs=6.0) and healthy.category == models.NORMAL
    assert "Open contact reads open" in h_text
    for name, contact in (("restriction", "closed"), ("obstruction", "open")):
        o, travel, text = notes(name)
        assert travel == pytest.approx(50.0, abs=6.0), name
        assert f"Open contact reads {contact}" in text, name
        assert "Commanded state: open" in text
        assert o.value > healthy.value + 0.05 and o.category == models.MINOR, name


def test_a_pump_head_loss_raises_the_vibration_by_the_declared_law(
    episodes: dict[str, InspectionService],
) -> None:
    """A head scale of 0.8 is a head loss of 0.2, so the overall velocity is 1.5 + 5.6 * 0.2 / 0.3
    = 5.2333 mm/s within noise and the category is minor; the healthy pump reads 1.5 mm/s and is
    normal.

    Independent: yes, because the velocity is the law evaluated by hand at the known head scale.
    """
    degraded = perform(episodes["pump"], "ACT-INSP-03", "P-101A")
    healthy = perform(episodes["healthy"], "ACT-INSP-03", "P-101A")
    assert (
        degraded.value == pytest.approx(5.2333, abs=5 * 0.05) and degraded.category == models.MINOR
    )
    assert healthy.value == pytest.approx(1.5, abs=5 * 0.05) and healthy.category == models.NORMAL


def test_sensor_faults_are_found_by_the_dip_and_by_the_calibration(
    episodes: dict[str, InspectionService],
) -> None:
    """A bias of 0.05 of the span on PT-202A gives a calibration error of -5 percent of span, a
    drift of 0.02 of the span per hour on PT-203 gives -0.02 * 100 * (2400 - 630) / 3600 = -0.983
    percent, and a healthy transmitter gives about 0; a stuck LT-101 gives a sounding that differs
    from the frozen reading by the level that moved since the onset; a healthy tank agrees.

    Independent: yes, because the errors are arithmetic on the known bias, rate and onset.
    """
    bias = perform(episodes["bias"], "ACT-INSP-07", "PT-202A")
    assert (
        bias.value == pytest.approx(-5.0, abs=5 * 0.0125) and bias.category == models.INCONCLUSIVE
    )
    drift = perform(episodes["drift"], "ACT-INSP-07", "PT-203")
    assert drift.value == pytest.approx(-0.02 * 100 * (T - ONSET) / 3600.0, abs=5 * 0.0125)
    assert perform(episodes["healthy"], "ACT-INSP-07", "PT-203").category == models.NORMAL
    assert perform(episodes["bias"], "ACT-INSP-07", "PT-001").category == models.NORMAL
    state = episodes["stuck"].truth.state(T)
    moved = (state["tags"]["LT-101"]["value"] + state["tags"]["LT-101"]["fault_offset"]) * 1000.0
    dip = perform(episodes["stuck"], "ACT-INSP-05", "TK-101")
    assert dip.value == pytest.approx(state["tanks"]["TK-101"]["level_m"] * 1000.0, abs=5.0)
    assert abs(dip.value - moved) > 100.0 and dip.category == models.INCONCLUSIVE
    ok = perform(episodes["healthy"], "ACT-INSP-05", "TK-101")
    assert ok.category == models.NORMAL


def test_a_misrouted_valve_shows_a_closed_command_and_an_open_actual_opening(
    episodes: dict[str, InspectionService],
) -> None:
    """A suction valve that is commanded closed but forced open (opening floor 1.0) reports the
    commanded state closed and an actual opening near 100 percent, where the healthy valve reports
    an opening near 0.

    Independent: yes, because the floor of the opening is the known fault parameter.
    """

    def read(name: str) -> tuple[str, float]:
        text = " ".join(perform(episodes[name], "ACT-INSP-02", "XV-S102").notes)
        travel = float(re.search(r"stem travel: ([0-9.]+) percent", text).group(1))  # type: ignore[union-attr]
        return text, travel

    text, travel = read("misroute_a")
    assert "Commanded state: closed" in text and travel == pytest.approx(100.0, abs=6.0)
    text, travel = read("healthy")
    assert "Commanded state: closed" in text and travel == pytest.approx(0.0, abs=6.0)


def test_the_workflow_on_a_real_episode_gives_a_result_only_after_its_time(
    episodes: dict[str, InspectionService],
) -> None:
    """On the pump episode a request for a vibration survey is decided, scheduled and performed
    after the horizon, so its result is visible only at the performed time plus 120 s and
    reports the state held at the horizon.

    Independent: yes, because the instants are read from the timeline and the state at the
    horizon is the last row.
    """
    service = episodes["pump"]
    for n in range(90, 120):
        request: dict[str, Any] = {
            "schema_version": "0.5.0", "dataset": "inspection_requests",
            "request_id": f"REQ-INSP-{n:05d}", "t_requested_sim_s": 2400.0,
            "action_id": "ACT-INSP-03", "target_asset": "P-101A",
            "justification": {"competing_hypotheses": ["pump", "valve", "normal"],
                              "agent_reported_information_gain_bits": 1.0,
                              "estimated_cost_usd": 140.0},
            "human_approval": {"status": "PENDING"},
        }  # fmt: skip
        service.submit(request, 2400.0)
        tl = service.record(request["request_id"]).timeline
        if tl.approved:
            break
    assert tl.approved and tl.t_performed_s > service.truth.horizon_s
    rid = tl.request_id
    early = {r["request_id"]: r for r in service.results(tl.t_visible_s - 1e-6)}
    assert "findings" not in early[rid] and early[rid]["workflow_status"] == "approved"
    rows = {r["request_id"]: r for r in service.results(tl.t_visible_s)}
    found = rows[rid]["findings"]["primary_metric"]
    assert found["value"] == pytest.approx(5.2333, abs=0.25)
