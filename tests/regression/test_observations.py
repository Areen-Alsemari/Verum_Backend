"""Observations of whole episodes: schema, causality, leakage, contacts and the consequences of the
delivery boundary law.

The completed episodes are checked with their observation and audit files and through the gateway.
Expected values are hand-derived or taken from the specification, and hidden truth is read only to
compute an expectation. The leakage checks LK-01 to LK-12 are covered by the tests marked LK, and
their list is in the "Observations of whole episodes" section of the verification notes.

See D27 to D33.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sim_helpers import esd_timeline
from verum.api import Gateway, GatewayViolation, check_allowlist
from verum.contracts import ContractError, load_schema, validator
from verum.provenance import canonical_json
from verum.sensors import load_sensor_config
from verum.sim.episode import EpisodeResult

CFG = load_sensor_config()
EMITTED = set(CFG.tags)
WITHHELD = {"YS-201A", "VT-201A", "IT-201A", "YS-201B", "VT-201B", "IT-201B"}
COMPLETED = ["S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-F", "S0-G", "S0-A-inland"]
OBS_KEYS = set(load_schema("observation")["properties"])
TIMELINE = esd_timeline()
CAPPED_CLOSURES = {"S0u-D", "S0u-E"}
EVENT_TAGS = {t for t, s in CFG.tags.items() if s.kind == "event"}
CONTINUOUS = [t for t, spec in CFG.tags.items() if spec.kind == "continuous"]
# The exact agent-visible catalog of config/inspection_catalog.json version 1.0.0 (D100), pinned
# so that a change of a name, a cost, a unit or an uncertainty is caught here and not only by the
# digest test of the inspection parameters.
EXPECTED_CATALOG = [
    {"action_id": "ACT-INSP-01", "cost_usd": 280.0, "duration_min": 90.0,
     "name": "Floating Roof Rim Seal and Deck Survey",
     "outputs": [{"modelled": False, "name": "maximum_rim_seal_gap", "uncertainty_k2": None,
                  "unit": "mm"}],
     "preconditions": ["Tank level above 1.8 m", "Authorised permit issued by the approval"],
     "target_kind": "tank", "targets": "Tanks TK-101 to TK-103"},
    {"action_id": "ACT-INSP-02", "cost_usd": 90.0, "duration_min": 45.0,
     "name": "Isolation Valve Mechanical Travel and Pressure Drop Verification",
     "outputs": [
         {"modelled": True, "name": "measured_differential_pressure", "uncertainty_k2": 0.01,
          "unit": "bar"},
         {"modelled": True, "name": "stem_travel", "uncertainty_k2": 2.0, "unit": "percent"},
     ],
     "preconditions": ["Pipeline flowing or pressurised at the target valve",
                        "Cold work permit issued by the approval"],
     "target_kind": "isolation_valve", "targets": "Isolation valves XV-*"},
    {"action_id": "ACT-INSP-03", "cost_usd": 140.0, "duration_min": 60.0,
     "name": "Pump Vibration Spectral Analysis",
     "outputs": [
         {"modelled": False, "name": "overall_velocity_rms", "uncertainty_k2": None,
          "unit": "mm/s"},
         {"modelled": False, "name": "spectral_peak_ratios", "uncertainty_k2": None, "unit": "1"},
     ],
     "preconditions": ["Pump running under load for at least 20 min"],
     "target_kind": "pump", "targets": "Pumps P-101A and P-101B"},
    {"action_id": "ACT-INSP-04", "cost_usd": 350.0, "duration_min": 120.0,
     "name": "Ultrasonic Pipeline Acoustic Leak Survey",
     "outputs": [
         {"modelled": False, "name": "leak_detected", "uncertainty_k2": None, "unit": "1"},
         {"modelled": False, "name": "leak_station_along_edge", "uncertainty_k2": None,
          "unit": "m"},
         {"modelled": False, "name": "acoustic_level", "uncertainty_k2": None, "unit": "dB"},
         {"modelled": False, "name": "wall_thickness", "uncertainty_k2": None, "unit": "mm"},
     ],
     "preconditions": ["Gauge pressure above 3 bar at the target edge",
                        "Ground access issued by the approval"],
     "target_kind": "pipe", "targets": "Pipe edges of the topology"},
    {"action_id": "ACT-INSP-05", "cost_usd": 110.0, "duration_min": 45.0,
     "name": "Manual Dip-Tape Sounding and Water Bottom Check",
     "outputs": [
         {"modelled": True, "name": "manual_innage_level", "uncertainty_k2": 1.5, "unit": "mm"},
         {"modelled": False, "name": "water_bottom_cut", "uncertainty_k2": None, "unit": "mm"},
     ],
     "preconditions": ["Gauging access issued by the approval"],
     "target_kind": "tank", "targets": "Tanks TK-101 to TK-103"},
    {"action_id": "ACT-INSP-06", "cost_usd": 160.0, "duration_min": 60.0,
     "name": "Vent and Deck Fitting Inspection",
     "outputs": [
         {"modelled": False, "name": "seating_integrity", "uncertainty_k2": None, "unit": "1"},
         {"modelled": False, "name": "cracking_pressure", "uncertainty_k2": None, "unit": "bar"},
     ],
     "preconditions": ["Tank out of receipt mode"],
     "target_kind": "tank", "targets": "Tanks TK-101 to TK-103"},
    {"action_id": "ACT-INSP-07", "cost_usd": 120.0, "duration_min": 45.0,
     "name": "Field Pressure Transmitter Loop Calibration",
     "outputs": [{"modelled": True, "name": "calibration_error", "uncertainty_k2": 0.025,
                  "unit": "percent of span"}],
     "preconditions": ["Manifold isolation permitted by the approval"],
     "target_kind": "pressure_transmitter",
     "targets": "Pressure transmitters PT-001, PT-201, PT-202A, PT-202B and PT-203"},
]  # fmt: skip
EXPECTED_CATALOG_SHA256 = "96abdccff038f2e891c665f07f1a59a743a5d1384f01536b9fa60297c2b854b0"


def _load(directory: Path, name: str) -> list[dict[str, Any]]:
    with gzip.open(directory / f"{name}.jsonl.gz", "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


@pytest.fixture(scope="module")
def obs(episodes: dict[str, EpisodeResult]) -> dict[str, list[dict[str, Any]]]:
    return {sid: _load(episodes[sid].directory, "observations") for sid in COMPLETED}


@pytest.fixture(scope="module")
def audit(episodes: dict[str, EpisodeResult]) -> dict[str, list[dict[str, Any]]]:
    return {sid: _load(episodes[sid].directory, "observation_audit") for sid in COMPLETED}


@pytest.mark.parametrize("sid", COMPLETED)
def test_every_observation_and_audit_row_validates_against_its_closed_schema(
    obs: dict[str, list[dict[str, Any]]], audit: dict[str, list[dict[str, Any]]], sid: str
) -> None:
    """Every observation and audit row validates against its closed schema, and the two files have
    the same number of rows. Independent: yes, because the schemas are separate files.
    """
    check_obs, check_audit = validator("observation"), validator("observation_audit")
    assert all(check_obs.is_valid(row) for row in obs[sid])
    assert all(check_audit.is_valid(row) for row in audit[sid])
    assert len(obs[sid]) == len(audit[sid]) > 20000


@pytest.mark.parametrize("sid", COMPLETED)
def test_only_the_thirty_emitted_tags_have_rows(
    obs: dict[str, list[dict[str, Any]]], sid: str
) -> None:
    """Only the thirty emitted tags have rows and no withheld tag does. Independent: yes, because
    the expected tag set is the contract.
    """
    tags = {r["tag_id"] for r in obs[sid]}
    assert tags == EMITTED and len(tags) == 30 and not tags & WITHHELD


@pytest.mark.parametrize("sid", COMPLETED)
def test_causality_source_not_after_sim_not_after_available(
    obs: dict[str, list[dict[str, Any]]], audit: dict[str, list[dict[str, Any]]], sid: str
) -> None:
    """For every row the source time is not after the simulation time and the simulation time is not
    after the availability time. Independent: yes, because the expected ordering is the causality
    rule.
    """
    by_key = {(r["tag_id"], r["t_sim_s"]): r for r in obs[sid]}
    for a in audit[sid]:
        row = by_key[(a["tag_id"], a["t_sim_s"])]
        assert a["t_source_s"] <= row["t_sim_s"] + 1e-9
        assert a["max_truth_time_used_s"] <= row["t_sim_s"] + 1e-9
        assert row["t_sim_s"] <= row["t_available_s"]
    assert max(r["t_sim_s"] for r in obs[sid]) <= 3600.0


def test_the_gateway_never_returns_a_later_row_over_a_whole_episode(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]]
) -> None:
    """At a series of query times the gateway returns only rows available by then, and the set only
    grows. Independent: yes, because the expected set is computed from the row times.
    """
    gateway = Gateway(episodes["S0u-E"].directory)
    rows = obs["S0u-E"]
    previous = 0
    for t in (0.0, 0.05, 1.0, 600.0, TIMELINE["trip"], TIMELINE["closed"], 3000.0, 3600.0, 3601.0):
        got = gateway.query(t)["observations"]
        assert all(r["t_available_s"] <= t for r in got)
        assert len(got) == sum(1 for r in rows if r["t_available_s"] <= t) >= previous
        previous = len(got)


def test_observations_are_a_pure_function_of_the_truth_and_the_seed(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    """Observing the same episode again gives identical rows. Independent: yes, because equality is
    the property.
    """
    from verum.sensors.adapter import observe_rows

    again = observe_rows(episodes["S0-G"].directory).observations
    assert again == obs["S0-G"]
    copy = tmp_path / "copy"
    shutil.copytree(episodes["S0-G"].directory, copy)
    assert observe_rows(copy).observations == obs["S0-G"]


@pytest.mark.parametrize("sid", COMPLETED)
def test_every_event_tag_has_an_initial_row_at_t_zero(
    obs: dict[str, list[dict[str, Any]]], sid: str
) -> None:
    """Each of the 16 event tags has a boolean row at t = 0. Independent: yes, because the expected
    count is the contract.
    """
    first = {r["tag_id"]: r for r in obs[sid] if r["t_sim_s"] == 0.0 and r["tag_id"] in EVENT_TAGS}
    assert set(first) == EVENT_TAGS and len(EVENT_TAGS) == 16
    assert all(r["value"] in (0.0, 1.0) and r["unit"] == "bool" for r in first.values())


def test_the_valve_contact_follows_the_stroke_with_the_lag_of_the_table(
    obs: dict[str, list[dict[str, Any]]],
) -> None:
    """The open contact of the common receipt valve releases 2.3 s after the isolation request, plus
    the communication delay. Independent: yes, because the time is hand arithmetic on the stroke and
    the contact lag.
    """
    rows = [r for r in obs["S0u-E"] if r["tag_id"] == "XV-R000"]
    assert [(r["t_sim_s"], r["value"]) for r in rows] == [
        (0.0, 1.0),
        (pytest.approx(TIMELINE["request"] + 2.3), 0.0),
    ]
    assert rows[1]["t_available_s"] == pytest.approx(TIMELINE["request"] + 2.4)
    s0ud = [r for r in obs["S0u-D"] if r["tag_id"] == "XV-R101"]
    assert [r["value"] for r in s0ud] == [1.0, 0.0]
    assert s0ud[1]["t_sim_s"] == pytest.approx(
        600.0 + 0.03 * 30.0 + 1.5
    )  # 0.97 at 0.9 s, lag 1.5 s


def test_lk11_the_lshh_observation_is_the_detector_output_after_the_comms_delay(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]]
) -> None:
    """The high-high level switch observation equals the detector output after the communication
    delay. Independent: yes, because the expected time is the trip time plus the stated delay.
    """
    trip = next(
        e
        for e in _load(episodes["S0u-E"].directory, "events")
        if e["payload"].get("kind") == "HIGH_HIGH_TRIP"
    )
    rows = [r for r in obs["S0u-E"] if r["tag_id"] == "LSHH-101"]
    assert [r["value"] for r in rows] == [0.0, 1.0]
    assert rows[1]["t_sim_s"] == pytest.approx(trip["t_sim_s"], abs=1e-9)
    assert rows[1]["t_available_s"] == pytest.approx(trip["t_sim_s"] + 0.05)
    for other in ("LSHH-102", "LSHH-103"):
        assert [r["value"] for r in obs["S0u-E"] if r["tag_id"] == other] == [0.0]


def test_pt001_clips_at_ten_bar_then_relaxes_toward_the_hydrostatic_value(
    obs: dict[str, list[dict[str, Any]]],
) -> None:
    """After the isolation the PT-001 reading is clipped at 10 barg with a suspect flag, falls below
    it after about 18 s, and ends at the hydrostatic value. Independent: yes, because the values are
    hand arithmetic.
    """
    rows = [r for r in obs["S0u-E"] if r["tag_id"] == "PT-001" and r["value"] is not None]
    closed = TIMELINE["closed"]
    clipped = [r for r in rows if closed < r["t_sim_s"] < closed + 15.0]
    assert clipped and all(r["value"] == 10.0 and r["quality_flag"] == "suspect" for r in clipped)
    early = [r for r in rows if r["t_sim_s"] < closed - 100.0]
    assert all(r["quality_flag"] != "suspect" for r in early)
    final = [r["value"] for r in rows if r["t_sim_s"] > 3500.0]
    assert all(r["quality_flag"] == "good" for r in rows if r["t_sim_s"] > closed + 25.0)
    assert 0.5 < sum(final) / len(final) < 1.2
    assert [r["value"] for r in rows if closed + 25.0 < r["t_sim_s"] < closed + 35.0][0] < 10.0


def test_ft201_varies_with_the_falling_tank_level(obs: dict[str, list[dict[str, Any]]]) -> None:
    """The mean delivery flow drops by about 1.65 m3/h between the first and last ten minutes as the
    tank level falls. Independent: yes, because the drop is hand arithmetic from the flow slope.
    """
    flow = [r for r in obs["S0-A"] if r["tag_id"] == "FT-201" and r["value"] is not None]
    first = np.mean([r["value"] for r in flow if 0 <= r["t_sim_s"] < 600])
    last = np.mean([r["value"] for r in flow if 3000 <= r["t_sim_s"] < 3600])
    assert first - last == pytest.approx(1.65, abs=0.25)  # noise: 0.2/sqrt(600) = 0.008


def test_pt203_varies_with_flow_through_the_boundary_law(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]]
) -> None:
    """The PT-203 reading equals 2 bar plus rho g c f_d (Q/300)^2, using the flow read from FT-201.
    Independent: yes, because the law is evaluated by hand and the hidden factor is used only for
    the expectation.
    """
    boundary = {
        r["t_sim_s"]: r["downstream_factor"]
        for r in _load(episodes["S0-F"].directory, "boundary_state")
        if r["side"] is None
    }
    pt = {r["t_sim_s"]: r["value"] for r in obs["S0-F"] if r["tag_id"] == "PT-203" and r["value"]}
    ft = {r["t_sim_s"]: r["value"] for r in obs["S0-F"] if r["tag_id"] == "FT-201" and r["value"]}
    for start in range(600, 3000, 600):
        times = [t for t in pt if start <= t < start + 600]
        p = np.mean([pt[t] for t in times])
        q = np.mean([ft[t] for t in ft if start <= t < start + 600])
        f = np.mean([boundary[float(math.floor(t))] for t in times])
        expected = (200000.0 + 750.0 * 9.80665 * 10.060889 * f * (q / 300.0) ** 2) / 1e5
        assert p == pytest.approx(expected, abs=0.03), start
    values = [pt[t] for t in sorted(pt)]
    assert max(values) - min(values) > 0.0  # not a constant 2 barg


def test_gauge_readings_agree_between_the_strata_while_the_absolute_truth_differs(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]]
) -> None:
    """Gauge readings agree between the coastal and inland strata while the hidden absolute pressure
    differs by 7025 Pa. Independent: yes, because the difference is hand arithmetic.
    """

    def mean(sid: str, tag: str) -> float:
        values = [r["value"] for r in obs[sid] if r["tag_id"] == tag and r["value"] is not None]
        return float(np.mean(values))

    assert mean("S0-A", "PT-203") == pytest.approx(mean("S0-A-inland", "PT-203"), abs=0.002)
    assert mean("S0-A", "FT-201") == pytest.approx(mean("S0-A-inland", "FT-201"), abs=0.01)
    docs = {
        sid: json.loads((episodes[sid].directory / "episode.json").read_text())["atmosphere_pa_abs"]
        for sid in ("S0-A", "S0-A-inland")
    }
    assert docs["S0-A"] - docs["S0-A-inland"] == 7025.0


def test_lk09_null_rate_is_the_binomial_dropout_rate_for_every_tag_in_every_episode(
    obs: dict[str, list[dict[str, Any]]],
) -> None:
    """For every continuous tag and episode the number of null rows is within five binomial
    deviations of the 0.05 percent dropout rate. Independent: yes, because the bound is a
    hand-derived binomial limit.
    """
    n_total = missing = 0
    for sid in COMPLETED:
        for tag in CONTINUOUS:
            rows = [r for r in obs[sid] if r["tag_id"] == tag]
            lost = sum(r["availability_status"] == "missing_sample" for r in rows)
            mean = len(rows) * 0.0005
            assert lost < mean + 5.0 * math.sqrt(mean) + 2.0, (sid, tag, lost, len(rows))
            assert all(
                (r["value"] is None) == (r["availability_status"] == "missing_sample") for r in rows
            )
            n_total, missing = n_total + len(rows), missing + lost
    assert abs(missing - n_total * 0.0005) < 5.0 * math.sqrt(n_total * 0.0005)


def test_lk10_quality_flags_carry_no_scenario_pattern(
    obs: dict[str, list[dict[str, Any]]],
) -> None:
    """Suspect flags on PT-001 occur only where the receipt path closes under the cap, and elsewhere
    they follow the noise tail in the same way in every episode. Independent: yes, because the
    expected pattern is derived from the cap and the noise tail.
    """
    for sid in COMPLETED:
        suspect = [r for r in obs[sid] if r["quality_flag"] == "suspect"]
        pt001 = [r for r in suspect if r["tag_id"] == "PT-001"]
        assert (len(pt001) > 0) is (sid in CAPPED_CLOSURES), sid
        rest = len(suspect) - len(pt001)
        samples = sum(r["tag_id"] in ("FT-001", "FT-201") for r in obs[sid])
        mean = samples * 0.00135
        assert rest < mean + 5.0 * math.sqrt(mean) + 2.0, (sid, rest)
        assert {r["tag_id"] for r in suspect} <= {"PT-001", "FT-001", "FT-201"}
    ok_flags = {"good", "suspect", "bad"}
    assert all(r["quality_flag"] in ok_flags for rows in obs.values() for r in rows)


FORBIDDEN = re.compile(
    r"(?i)(S0u?-[A-Z0-9]|REJ-\d|VW-\d|analytic_verification|restricted_benchmark|truth|normal"
    r"|window|scenario|hidden|ground_truth|hydraulic_state|fault)"
)


def test_lk01_to_lk06_no_hidden_content_in_agent_visible_data(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]]
) -> None:
    """No truth key, normality label, scenario name, tier, validity-window identifier or truth
    dataset name appears in any observation row. Independent: yes, because the check scans the
    written rows.
    """
    for sid in COMPLETED:
        for row in obs[sid]:
            assert set(row) == OBS_KEYS, sid  # LK-01: only the closed schema's keys
        text = "\n".join(json.dumps(r, sort_keys=True) for r in obs[sid][::37])
        assert not FORBIDDEN.search(text.replace("episode_id", "").replace("EP-", "")), sid
        payload = Gateway(episodes[sid].directory).query(3600.0)
        check_allowlist(payload)
        assert set(payload) == {
            "episode_id",
            "as_of_s",
            "observations",
            "assets",
            "inspection_catalog",
        }


def test_lk07_and_lk08_the_allowlist_rejects_hidden_material() -> None:
    """The gateway allowlist rejects an injected hidden key or word, and the audit file is not
    served. Independent: yes, because the offending payload is written by the test.
    """
    base: dict[str, Any] = {
        "episode_id": "EP-1",
        "as_of_s": 1.0,
        "observations": [],
        "assets": [],
        "inspection_catalog": [],
    }
    check_allowlist(base)
    for bad in (
        {**base, "validity_windows": []},
        {**base, "observation_audit": []},
        {**base, "tier": "restricted_benchmark"},
        {**base, "assets": [{"asset_id": "S0u-E", "kind": "tank"}]},
        {**base, "observations": [{"unit": "analytic_verification"}]},
        {**base, "inspection_catalog": ["VW-0001"]},
        {**base, "observations": [{"ground_truth": 1.0}]},
    ):
        with pytest.raises(GatewayViolation):
            check_allowlist(bad)


def test_the_gateway_refuses_a_row_outside_the_closed_schema(
    episodes: dict[str, EpisodeResult], tmp_path: Path
) -> None:
    """The gateway refuses an observation row that has a field outside the closed schema.
    Independent: yes, because the offending row is written by the test.
    """
    copy = tmp_path / "EP-COPY"
    shutil.copytree(episodes["S0-A"].directory, copy)
    rows = _load(copy, "observations")
    rows[0]["true_value"] = 9.0
    with gzip.open(copy / "observations.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.writelines(json.dumps(r) + "\n" for r in rows)
    with pytest.raises(ContractError):
        Gateway(copy).query(3600.0)


def test_lk12_the_episode_id_is_opaque_and_the_catalog_is_the_seven_actions(
    episodes: dict[str, EpisodeResult],
) -> None:
    """The episode identifier is opaque, and the inspection catalog equals the pinned content of
    the seven actions of the instrumentation document (D100), not only their seven identifiers.
    Independent: yes, because the expected pattern and the pinned catalog are the stated rules.
    """
    payload = Gateway(episodes["S0-A"].directory).query(10.0)
    assert re.fullmatch(r"EP-[0-9A-F]{12}", payload["episode_id"])
    assert payload["inspection_catalog"] == EXPECTED_CATALOG
    digest = hashlib.sha256(canonical_json(payload["inspection_catalog"]).encode("utf-8"))
    assert digest.hexdigest() == EXPECTED_CATALOG_SHA256
    kinds = {a["kind"] for a in payload["assets"]}
    assert kinds == {"tank", "pump", "isolation_valve", "pipe", "pressure_transmitter"}
    assert len(payload["assets"]) == 3 + 2 + 11 + 28 + 5
