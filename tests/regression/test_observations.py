"""Observations of whole episodes: schema, causality, leakage, contacts, D2 consequences.

Inputs: the completed episodes with their observation and audit files, and the gateway.
Outputs: pass/fail.
Key assumptions:
    * Expected values are hand-derived or taken from the specification; where a test reads
      hidden truth (the detector output, f_d) it is only to compute the expectation.
    * LK-01 to LK-12 (build-failing leakage checks) are covered by the tests marked LK:
      LK-01 no truth key in an observation or the gateway payload; LK-02 no normality label;
      LK-03 no scenario name; LK-04 no tier; LK-05 no validity-window id; LK-06 no
      truth dataset name; LK-07 the allowlist rejects an injected hidden key; LK-08 the
      audit is not served; LK-09 dropout rate equal across scenarios; LK-10 quality
      flags carry no scenario pattern; LK-11 the LSHH observation equals the detector output
      after the delay; LK-12 the episode id is opaque.
    * Random dropout is the same for every episode, and every null row is a dropout: decision
      D39 gives idle segments a pressure, so there are no structural nulls.

Source: ``docs/design_decisions.md`` D27 to D33; ``revised/05_simulation_validation_dataset.md``
sections 7.2 and 9.
"""

from __future__ import annotations

import gzip
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
    check_obs, check_audit = validator("observation"), validator("observation_audit")
    assert all(check_obs.is_valid(row) for row in obs[sid])
    assert all(check_audit.is_valid(row) for row in audit[sid])
    assert len(obs[sid]) == len(audit[sid]) > 20000


@pytest.mark.parametrize("sid", COMPLETED)
def test_only_the_thirty_emitted_tags_have_rows(
    obs: dict[str, list[dict[str, Any]]], sid: str
) -> None:
    tags = {r["tag_id"] for r in obs[sid]}
    assert tags == EMITTED and len(tags) == 30 and not tags & WITHHELD


@pytest.mark.parametrize("sid", COMPLETED)
def test_causality_source_not_after_sim_not_after_available(
    obs: dict[str, list[dict[str, Any]]], audit: dict[str, list[dict[str, Any]]], sid: str
) -> None:
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
    first = {r["tag_id"]: r for r in obs[sid] if r["t_sim_s"] == 0.0 and r["tag_id"] in EVENT_TAGS}
    assert set(first) == EVENT_TAGS and len(EVENT_TAGS) == 16
    assert all(r["value"] in (0.0, 1.0) and r["unit"] == "bool" for r in first.values())


def test_the_valve_contact_follows_the_stroke_with_the_lag_of_the_table(
    obs: dict[str, list[dict[str, Any]]],
) -> None:
    """XV-R000 closes from the isolation request: alpha = 1 - (t - t_req)/10 falls below 0.97 at
    t_req + 0.3 s, and the contact row follows after the 2.0 s lag (hand: t_req + 2.3 s) and the
    0.1 s comms delay."""
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
    """The head at the start of E002 reaches 13.5 barg at the closure, above the 10
    barg range: clipped with quality suspect. The isolated segment then relaxes to the tank head
    with 60 s (decision D39): it is below 10 barg after 60 ln(13.46/10) = 18 s, and at the end
    of the hour it reads the hydrostatic value of TK-101 (13.0 m: (13.0 - 1.0 m) x 0.0735 = 0.88
    barg, less the tank-side losses)."""
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
    """Decision D2 consequence. Hand: the duty flow falls 4.46 m3/h per metre of level
    (1.24e-3 m3/s per m) and TK-101 falls 0.442 m in the hour, so the mean flow drops by
    about 1.97 m3/h between the first and the last ten minutes (mean of the two windows,
    separated by 3000 s, so the drop is 0.37 m of the 0.44 m): 1.65 m3/h."""
    flow = [r for r in obs["S0-A"] if r["tag_id"] == "FT-201" and r["value"] is not None]
    first = np.mean([r["value"] for r in flow if 0 <= r["t_sim_s"] < 600])
    last = np.mean([r["value"] for r in flow if 3000 <= r["t_sim_s"] < 3600])
    assert first - last == pytest.approx(1.65, abs=0.25)  # noise: 0.2/sqrt(600) = 0.008


def test_pt203_varies_with_flow_through_the_boundary_law(
    episodes: dict[str, EpisodeResult], obs: dict[str, list[dict[str, Any]]]
) -> None:
    """Decision D2 version 3: PT-203 = 2 bar + rho g c f_d (Q/300)^2 (hand), against the flow
    read from FT-201 and f_d from the hidden boundary state (used only for the expectation)."""
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
    """S0-A and S0-A-inland share the hydraulics defined in gauge terms (2 barg reservoir). The
    truth pressure is absolute (gauge + the stratum atmosphere), and every emitted pressure
    transmitter reports gauge against the episode atmosphere (decision D27), so the readings
    agree; no emitted tag is referenced to a fixed atmosphere. The hidden truth differs by
    101325 - 94300 = 7025 Pa, and the conversion in the unit tests shows the 0.07025 bar a
    fixed-reference (absolute) sensor would carry."""

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
    """Decision D39 leaves no structural null: every null row is a random dropout. For each
    continuous tag and episode the count is within five binomial deviations of 0.05 percent,
    and the pooled rate over all tags and episodes is within five deviations too."""
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
    """A real overrange is the only systematic cause of ``suspect``: PT-001 where the receipt
    path closes under the 10 barg cap (S0u-E, and the closure of the S0u-D receipt switch).
    Elsewhere ``suspect`` is the noise tail beyond 3 sigma below zero flow (P = 0.00135 per
    sample), a binomial count that is the same kind in every episode."""
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
    copy = tmp_path / "EP-COPY"
    shutil.copytree(episodes["S0-A"].directory, copy)
    rows = _load(copy, "observations")
    rows[0]["true_value"] = 9.0
    with gzip.open(copy / "observations.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.writelines(json.dumps(r) + "\n" for r in rows)
    with pytest.raises(ContractError):
        Gateway(copy).query(3600.0)


def test_lk12_the_episode_id_is_opaque_and_the_catalog_is_empty_not_invented(
    episodes: dict[str, EpisodeResult],
) -> None:
    payload = Gateway(episodes["S0-A"].directory).query(10.0)
    assert re.fullmatch(r"EP-[0-9A-F]{12}", payload["episode_id"])
    assert payload["inspection_catalog"] == []  # no catalog exists in the audited package
    kinds = {a["kind"] for a in payload["assets"]}
    assert kinds == {"tank", "pump", "isolation_valve"}
    assert len(payload["assets"]) == 3 + 2 + 11
