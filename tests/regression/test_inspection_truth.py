"""The inspection truth of an episode: rows, discontinuities, fault fields and unchanged outputs.

The rows are compared with the full hydraulic-state truth of short episodes, one for a healthy run
and one for each fault subtype. The comparison of the other outputs uses digests of two episodes
stored before the file existed.

See D156.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from verum.campaign import runner
from verum.campaign.eligibility import model_and_table
from verum.campaign.plan import Block, CampaignConfig
from verum.faults import FaultSet, FaultSpec, instance_ids
from verum.faults.truth import parameter_name, parameter_value
from verum.sensors import load_sensor_config
from verum.sensors.adapter import observe_rows
from verum.sim import inspection
from verum.sim.episode import EpisodeResult, run_episode
from verum.sim.scenario import parse_scenario
from verum.truth import read_rows

LIMIT_BYTES = 250_000
Key = tuple[str, str, float, str | None]


def scenario(
    mode: str, schedule: list[dict[str, Any]], name: str, duration: float = 2500.0
) -> dict[str, Any]:
    return {
        "scenario_id": name, "description": "inspection truth", "seed": 17,
        "duration_s": duration, "temperature_c": 25.0, "fitting_profile": "reference_fittings",
        "healthy_envelope": True, "atmosphere_stratum": "coastal", "volatility_class": "RVP_9_0",
        "demand_process": True, "variability_profile": "v2",
        "initial": {
            "mode": mode, "receipt_flow_m3h": 0.0, "receipt_setpoint_m3h": 0.0,
            "tank_levels_m": {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0},
        },
        "schedule": schedule,
    }  # fmt: skip


def spec(
    kind: str, variant: str, asset: str, ramp: float | None, magnitude: float, **kw: Any
) -> FaultSpec:
    return FaultSpec(kind, variant, asset, 630.0, ramp, magnitude, **kw)


RECEIVE = [{"t_s": 0.0, "command": "receipt_setpoint", "value_m3h": 400.0}]
CASES: dict[str, tuple[str, list[dict[str, Any]], FaultSpec | None]] = {
    "healthy": ("DELIVER_101_A", [], None),
    "leak": ("DELIVER_101_A", [], spec("PIPE_LEAK", "orifice", "E-D1", 300.0, 1e-4,
                                       position=0.5, discharge_coefficient=0.62)),
    "restriction": ("DELIVER_101_A", [], spec("VALVE_RESTRICTION", "restriction", "XV-S101", 300.0,
                                              0.5, fault_mode="position_visible")),
    "obstruction": ("DELIVER_101_A", [], spec("VALVE_RESTRICTION", "restriction", "XV-S101",
                                              300.0, 0.5, fault_mode="obstruction")),
    "pump": ("DELIVER_101_A", [], spec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 300.0,
                                       0.8)),
    "bias": ("DELIVER_101_A", [], spec("SENSOR_DRIFT", "bias", "FT-201", None, 0.05)),
    "drift": ("DELIVER_101_A", [], spec("SENSOR_DRIFT", "drift", "PT-203", None, 0.02)),
    "stuck": ("DELIVER_101_A", [], spec("SENSOR_DRIFT", "stuck", "LT-101", None, 0.0)),
    "misroute_a": ("DELIVER_101_A", [], spec("VALVE_MISROUTING", "closed_but_open", "XV-S102",
                                             300.0, 1.0)),
    "misroute_b": ("RECEIVE_101_102", RECEIVE, spec("VALVE_MISROUTING", "open_but_stuck", "XV-R101",
                                                    300.0, 0.02)),
}  # fmt: skip
Run = tuple[Path, FaultSet | None, EpisodeResult]


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Run]:
    model, _ = model_and_table()
    out: dict[str, Run] = {}
    for name, (mode, schedule, fault) in CASES.items():
        root = tmp_path_factory.mktemp(name)
        faults = FaultSet((fault,)) if fault is not None else None
        raw = scenario(mode, schedule, f"INSP-{name}")
        result = run_episode(raw["scenario_id"], root, model, parse_scenario(raw), faults)
        assert not result.rejected, (name, result.outcome.rejection)
        out[name] = (root, faults, result)
    return out


def payloads(directory: Path) -> dict[Key, dict[str, Any]]:
    rows = read_rows(directory, "hydraulic_state")
    return {
        (r["record_type"], r["element_id"], r["t_sim_s"], r["side"]): r["payload"] for r in rows
    }


def by_time(directory: Path) -> dict[tuple[float, str | None], dict[str, Any]]:
    return {(r["t_sim_s"], r["side"]): r for r in read_rows(directory, "inspection_truth")}


# --- rows against the full truth ----------
@pytest.mark.slow
@pytest.mark.parametrize("name", list(CASES))
def test_rows_equal_the_full_truth_at_three_times(name: str, runs: dict[str, Run]) -> None:
    """At 60, 1200 and 2400 s the tank, edge, valve and pump fields equal the hydraulic-state rows
    of the full truth exactly (a gauge pressure is the written absolute pressure less the
    atmosphere), and the leak flow equals the leak flow of the edge row.

    Independent: yes, because the expected values are read from the full truth file, which the
    writer does not produce.
    """
    directory, faults, result = runs[name]
    truth = payloads(result.directory)
    rows = by_time(result.directory)
    meta = json.loads((result.directory / "episode.json").read_text(encoding="utf-8"))
    patm = meta["atmosphere_pa_abs"]
    for t in (60.0, 1200.0, 2400.0):
        row = rows[(t, None)]
        for tank, got in row["tanks"].items():
            p = truth["tank_state", tank, t, None]
            assert got == {k: p[k] for k in ("level_m", "temperature_K", "volume_m3")}
        assert len(row["edges"]) == 28
        for edge, got in row["edges"].items():
            p = truth["edge_state", edge, t, None]
            assert got["flow_m3s"] == p["flow_m3s"]
            assert got["p_from_pa_gauge"] == p["p_from_pa_abs"] - patm
            assert got["p_to_pa_gauge"] == p["p_to_pa_abs"] - patm
        assert len(row["valves"]) == 11
        for valve, got in row["valves"].items():
            p = truth["valve_state", valve, t, None]
            assert got["commanded_open"] == p["commanded_open"]
            assert got["position_frac"] == p["position_frac"]
        for pump, got in row["pumps"].items():
            p = truth["pump_state", pump, t, None]
            assert (got["run_state"], got["speed_ratio"]) == (p["run_state"], p["speed_ratio"])
        for leak in row["leaks"]:
            p = truth["edge_state", leak["edge_id"], t, None]
            assert leak["flow_m3s"] == p.get("leak_flow_m3s", 0.0)
    assert (name == "leak") == bool(rows[(1200.0, None)]["leaks"])
    if name == "leak":
        assert rows[(1200.0, None)]["leaks"][0]["flow_m3s"] > 0.0
        assert rows[(60.0, None)]["leaks"][0]["flow_m3s"] == 0.0
        assert rows[(1200.0, None)]["leaks"][0]["fraction"] == 0.5


@pytest.mark.slow
def test_the_times_are_the_grid_the_events_and_the_fault_knots(runs: dict[str, Run]) -> None:
    """The rows of the leak episode are the 60 s grid, the pre-event and post-event pairs of the
    events of the full truth, and the extra rows at the onset (630 s) and the end of the ramp
    (930 s), the last time, in time order.

    Independent: yes, because the event times are read from the full truth file.
    """
    _directory, _faults, result = runs["leak"]
    events = {
        r["t_sim_s"]
        for r in read_rows(result.directory, "hydraulic_state")
        if r["side"] == "pre_event"
    }
    grid = {k * 60.0 for k in range(42)} | {2500.0}
    rows = read_rows(result.directory, "inspection_truth")
    keys = [(r["t_sim_s"], r["side"]) for r in rows]
    assert keys == sorted(
        keys, key=lambda k: (k[0], {"pre_event": 0, None: 1, "post_event": 2}[k[1]])
    )
    expect: set[tuple[float, str | None]] = {
        (t, None) for t in grid | {630.0, 930.0} if t not in events
    }
    expect |= {(t, s) for t in events for s in ("pre_event", "post_event")}
    assert set(keys) == expect and len(keys) == len(set(keys))
    assert (630.0, None) in set(keys) and (930.0, None) in set(keys)


# --- discontinuities ----------
@pytest.mark.slow
def test_pre_and_post_rows_at_the_start_of_a_valve_stroke(tmp_path: Path) -> None:
    """When the common receipt valve is commanded closed at 300 s the file has a pre-event row
    with the valve commanded open and a post-event row commanded closed, the opening is 1 in both
    (the stroke has just started), both rows equal the pre-event and post-event rows of the full
    truth, and at 360 s the valve is closed and its contact is released.

    Independent: yes, because the expected values are read from the full truth file.
    """
    model, _ = model_and_table()
    schedule = [
        {"t_s": 0.0, "command": "receipt_setpoint", "value_m3h": 300.0},
        {"t_s": 300.0, "command": "close_valves", "valves": ["XV-R000"]},
    ]
    raw = scenario("RECEIVE_101", schedule, "INSP-stroke", 700.0)
    result = run_episode(raw["scenario_id"], tmp_path, model, parse_scenario(raw), None)
    assert not result.rejected
    truth = payloads(result.directory)
    rows = by_time(result.directory)
    pre, post = rows[(300.0, "pre_event")], rows[(300.0, "post_event")]
    closing = (pre["valves"]["XV-R000"], post["valves"]["XV-R000"])
    assert (closing[0]["commanded_open"], closing[1]["commanded_open"]) == (True, False)
    assert (
        pre["valves"]["XV-R000"]["position_frac"]
        == post["valves"]["XV-R000"]["position_frac"]
        == 1.0
    )
    assert (
        pre["valves"]["XV-R000"]["contact_open"] == post["valves"]["XV-R000"]["contact_open"] == 1
    )
    patm = json.loads((result.directory / "episode.json").read_text())["atmosphere_pa_abs"]
    for side, row in (("pre_event", pre), ("post_event", post)):
        for edge, got in row["edges"].items():
            p = truth["edge_state", edge, 300.0, side]
            assert got["flow_m3s"] == p["flow_m3s"]
            assert got["p_from_pa_gauge"] == p["p_from_pa_abs"] - patm
    assert (300.0, None) not in rows
    later = rows[(360.0, None)]["valves"]["XV-R000"]
    assert later["commanded_open"] is False and later["position_frac"] == 0.0
    assert later["contact_open"] == 0


@pytest.mark.slow
def test_a_ramp_knot_gives_one_row_and_a_step_gives_a_pre_and_a_post_row(
    runs: dict[str, Run],
) -> None:
    """A ramped fault has one row at its onset and one at the end of its ramp, with severity 0 and
    1 and the leak area 0 and 1e-4 m2. A step fault has a pre row with severity 0 and no offset
    and a post row with severity 1, and its bias offset is 0.05 of the span of the transmitter.

    Independent: yes, because the severity and the offset are worked out by hand from the
    specification.
    """
    leak = by_time(runs["leak"][2].directory)
    assert leak[(630.0, None)]["faults"][0]["severity"] == 0.0
    assert leak[(630.0, None)]["faults"][0]["parameter_value"] == 0.0
    assert leak[(930.0, None)]["faults"][0]["severity"] == 1.0
    assert leak[(930.0, None)]["faults"][0]["parameter_value"] == 1e-4
    assert leak[(780.0, None)]["faults"][0]["severity"] == pytest.approx(0.5)
    bias = by_time(runs["bias"][2].directory)
    pre, post = bias[(630.0, "pre_event")], bias[(630.0, "post_event")]
    assert pre["faults"][0]["severity"] == 0.0 and post["faults"][0]["severity"] == 1.0
    assert pre["tags"]["FT-201"]["fault_offset"] == 0.0
    flow = load_sensor_config().tags["FT-201"]
    span = flow.range_hi - flow.range_lo  # type: ignore[operator]
    assert post["tags"]["FT-201"]["fault_offset"] == pytest.approx(0.05 * span / 3600.0, rel=1e-12)
    assert pre["tags"]["FT-201"]["value"] == pytest.approx(
        post["tags"]["FT-201"]["value"], rel=1e-9
    )


@pytest.mark.slow
def test_tag_values_and_offsets_follow_the_sensor_fault(runs: dict[str, Run]) -> None:
    """A drift of 0.02 of the span of PT-203 per hour adds 0.02 span (t - 630 s) / 3600 s, in
    pascal after the conversion from bar; a stuck sensor holds the value of its first sample after
    the onset, which the clean chain output of the observation step gives; a tag without a fault
    has no offset.

    Independent: yes, because the drift is hand arithmetic and the frozen value comes from the
    noise-free observation of the first scheduled sample.
    """
    cfg = load_sensor_config()
    span = cfg.tags["PT-203"].range_hi - cfg.tags["PT-203"].range_lo  # type: ignore[operator]
    drift = by_time(runs["drift"][2].directory)
    assert drift[(1200.0, None)]["tags"]["PT-203"]["fault_offset"] == pytest.approx(
        0.02 * span * 570.0 / 3600.0 * 1.0e5, rel=1e-12
    )
    assert drift[(1200.0, None)]["tags"]["FT-201"]["fault_offset"] == 0.0
    result = runs["stuck"][2]
    clean = observe_rows(result.directory, None, None, clean=True)
    first = next(o for o in clean.observations if o["tag_id"] == "LT-101" and o["t_sim_s"] >= 630.0)
    stuck = by_time(result.directory)
    for t in (660.0, 1200.0, 2400.0):
        row = stuck[(t, None)]["tags"]["LT-101"]
        assert row["value"] + row["fault_offset"] == pytest.approx(first["value"], rel=1e-12)
    assert stuck[(600.0, None)]["tags"]["LT-101"]["fault_offset"] == 0.0


# --- fault fields ----------
def test_the_parameter_of_each_fault_type_follows_its_mapping() -> None:
    """At severity 0, 0.5 and 1 the parameter is the leak area, the opening ceiling, the head
    scale, the signed bias, the drift rate or the opening floor of the mapping of its type.

    Independent: yes, because every value is worked out by hand from the mapping text.
    """
    cases = [
        (spec("PIPE_LEAK", "orifice", "E-D1", 300.0, 1e-3, position=0.5, discharge_coefficient=0.6),
         "leak_area", [0.0, 5e-4, 1e-3]),
        (spec("VALVE_RESTRICTION", "restriction", "XV-S101", 300.0, 0.2, fault_mode="obstruction"),
         "valve_opening_ceiling", [1.0, 0.6, 0.2]),
        (spec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 300.0, 0.7),
         "pump_head_scale", [1.0, 0.85, 0.7]),
        (spec("SENSOR_DRIFT", "bias", "FT-001", 300.0, -0.04),
         "reading_offset_fraction_of_span", [0.0, -0.02, -0.04]),
        (spec("VALVE_MISROUTING", "closed_but_open", "XV-S102", 300.0, 1.0),
         "valve_opening_floor", [0.0, 0.5, 1.0]),
        (spec("VALVE_MISROUTING", "open_but_stuck", "XV-R101", 300.0, 0.02),
         "valve_opening_ceiling", [1.0, 0.51, 0.02]),
    ]  # fmt: skip
    for fault, name, want in cases:
        assert parameter_name(fault)[0] == name
        got = [parameter_value(fault, 630.0 + f * 300.0) for f in (0.0, 0.5, 1.0)]
        assert got == pytest.approx(want, rel=1e-12, abs=1e-15), name


def test_the_row_times_cover_a_step_with_a_pre_and_a_post_row() -> None:
    """For events at 100 s, a ramp from 330 s to 630 s and a step at 400 s on a 700 s episode the
    keys are the grid and the last time, the event pair, the two ramp knots as single rows and
    the step pair.

    Independent: yes, because the expected keys are listed by hand.
    """
    rows = [{"t_sim_s": 100.0, "side": "pre_event"}, {"t_sim_s": 100.0, "side": "post_event"}]
    ramp = FaultSpec("PIPE_LEAK", "orifice", "E-D1", 330.0, 300.0, 1e-4, 0.5, 0.6)
    step = FaultSpec("SENSOR_DRIFT", "bias", "FT-001", 400.0, None, 0.05)
    keys = inspection._times(rows, 700.0, (ramp, step))
    plain = [0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 330.0, 360.0, 420.0, 480.0, 540.0, 600.0]
    want: list[tuple[float, str | None]] = [(t, None) for t in [*plain, 630.0, 660.0, 700.0]]
    want += [(100.0, "pre_event"), (100.0, "post_event")]
    want += [(400.0, "pre_event"), (400.0, "post_event")]
    order = {"pre_event": 0, None: 1, "post_event": 2}
    assert keys == sorted(want, key=lambda k: (k[0], order[k[1]]))


# --- other outputs unchanged, size, absence from the agent folder ----------
PILOT = CampaignConfig(
    20261102, 60,
    Block(
        size=60, healthy=20, single=20, pair=10, branched=10, latent=1, switch=5, stress=5, audit=6
    ),
)  # fmt: skip
STORED = {  # digests of two episodes of the second pilot, taken before the file existed
    35: {
        "observations.jsonl.gz": "b807494e9bdd07ad9caf51976e9a667c986af5f798cfaf24724ab825618eeb5f",
        "fault_truth.jsonl.gz": "53303ec50ef8fe4d736d381403e08746eff77ab59c4b572d56f73ac341f9c651",
        "labels.json": "53fb97491268892b61cf5d6f43ed549d89de41f5e5d9fd587c187af1d1682647",
        "observation_audit.jsonl.gz":
            "9d0ac7f27d976e6a4950ed1b31a333374775e14c08a6a26cf01c6a2904e33078",
        "scenario.json": "ea585d03083ff1e177791a8c48aca43e95bbe34bc25e457cd5474ff5f396f9c0",
    },
    54: {
        "observations.jsonl.gz": "46327435e1cd32c06036459a0a816d7444cb3c3c66f544c8a122f41e288274aa",
        "fault_truth.jsonl.gz": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "labels.json": "1bb5ebf5fdc3c9fed31c67ef55a8e6d7bf2bebb7c23cb3db4b3f56146fd338d2",
        "observation_audit.jsonl.gz":
            "24164a42e08be10f2fc5094bc759a8fff8adb36351ea67e6c3d2cb49ad13fbc6",
        "scenario.json": "25b41f2aef9637fc6df82892e1d8c2bc6f06c04769f913029c7886602a1baab9",
    },
}  # fmt: skip


MANIFEST_TEXT = {  # truth manifest of the same episodes, without the line of the provenance file
    35: """\
dc69f686bb3b9add761ae7dd3d07b0a32845d576c2f67ee3b5e010aa8b1d4d92  boundary_state.jsonl.gz
0c04df65455d46b3aa1661f89404418472c452531cf7529fdb09af9dca3a82e2  episode.json
8dc9e6f6afed04d733d24a731759bd0cd7e48590dde36b672f32219925bf0a70  events.jsonl.gz
4ecc4519c97df517f5b886295f0b322673f11a62c7c028c6abf16239bfe4a75a  fault_truth.jsonl.gz
ed9f8b47d943b55887b2ab0e6f50cf47d97183b7e6de0643987b4d64836750f1  hydraulic_state.jsonl.gz
efcca300ac69a48b8fd36c698685c3baafe2df3ce3b312162b3ccacbedbfba85  mass_ledger.jsonl.gz
d7502e032f612e697528d543110446e5a751a38588ee2bfde87749f93e7cc57e  observation_audit.jsonl.gz
26ce03b5fee3ae9c0d920c255a5f7a5c74e74a7018d20e2e66496a76f8688eed  observations.jsonl.gz
860dcbe4003f955735234581186339fb30b14b61da6a00742d831498b06d7857  solver_diagnostics.jsonl.gz
ac73670af3abed54ac6fb4695131f4099be9fbe39d6076c5d0264a6bbdae9d83  validity_windows.jsonl.gz
""",
    54: """\
3851a05671c473e367ab5e44d0084a85a1fad8fb185fad5a68c183eb6ccc72e0  boundary_state.jsonl.gz
96ef4e26064e46ecd9bc36388d3d40b3a8dc6b020c50d0934a46ac3b70babae6  episode.json
7b523653c6a1dd316153d83249057a81340e9a786cf3f287fe714ed87265386a  events.jsonl.gz
ac73670af3abed54ac6fb4695131f4099be9fbe39d6076c5d0264a6bbdae9d83  fault_truth.jsonl.gz
529a5d6dd3329df45dc664d9ab79684b25f5122fb5c29cdba85bbcdcf2bb316a  hydraulic_state.jsonl.gz
2801d242c00efba40e238ea943a705c58584d72ac8ad57284d6e43464fe5d23a  mass_ledger.jsonl.gz
e539b4d4b611f6c975f898eb690969a7999e63a93a129f0b58291b77aee19642  observation_audit.jsonl.gz
1ce6b3197f9c1e85507b72c5a8dfcf979048ede374862507b99f833220f6489d  observations.jsonl.gz
3d5d57c895996a3f1d9a84cf7b6afb77671d27d74eb8a7dcd93118d14f39d02f  solver_diagnostics.jsonl.gz
ac73670af3abed54ac6fb4695131f4099be9fbe39d6076c5d0264a6bbdae9d83  validity_windows.jsonl.gz
""",
}


@pytest.fixture(scope="module")
def stored_slots(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, dict[int, dict[str, Any]]]:
    root = tmp_path_factory.mktemp("digest")
    records = {i: runner.execute_slot(PILOT, i, root) for i in STORED}
    for i, record in records.items():
        runner.write_record(runner.Layout(root), record)
        assert record["status"] == "completed", i
    return root, records


@pytest.mark.slow
@pytest.mark.parametrize("slot", list(STORED))
def test_the_other_outputs_are_byte_identical_to_the_stored_digests(
    slot: int, stored_slots: tuple[Path, dict[int, dict[str, Any]]]
) -> None:
    """The observations, the observation audit, the fault truth, the labels, the scenario and the
    truth manifest of two episodes of the second pilot equal the digests taken before the
    inspection truth existed (a gzip file is hashed after decompression). The manifest is compared
    line by line without the line of the provenance file, which holds the code commit and so
    changes with every commit.

    Independent: yes, because the digests were stored before the change.
    """
    root, records = stored_slots
    record = records[slot]
    episode = record["episode_id"]
    found = {
        name.split(episode + "/", 1)[1]: digest
        for name, digest in record["files"].items()
        if episode in name
    }
    for name, digest in STORED[slot].items():
        assert found[name] == digest, name
    manifest = root / "evaluator" / "episodes" / episode / "truth" / "MANIFEST.sha256"
    lines = [x.split("  ") for x in manifest.read_text(encoding="utf-8").splitlines()]
    stored = [x.split("  ") for x in MANIFEST_TEXT[slot].splitlines()]
    assert {n: h for h, n in lines if n != "provenance.json"} == {n: h for h, n in stored}
    assert inspection.FILE not in {n for _h, n in lines}


@pytest.mark.slow
@pytest.mark.parametrize("slot", list(STORED))
def test_the_inspection_file_is_small_listed_and_evaluator_only(
    slot: int, stored_slots: tuple[Path, dict[int, dict[str, Any]]]
) -> None:
    """For a 3600 s episode the file is below 250 KB compressed, its hash is listed in the record,
    it is in the evaluator store only, and no agent-visible file names it.

    Independent: yes, because the limit is stated in the decision and the lists are read from disk.
    """
    root, records = stored_slots
    record = records[slot]
    episode = record["episode_id"]
    evaluator = root / "evaluator" / "episodes" / episode / inspection.FILE
    assert 0 < evaluator.stat().st_size < LIMIT_BYTES
    assert f"evaluator/episodes/{episode}/{inspection.FILE}" in record["files"]
    assert not list((root / "agent_visible").rglob("*inspection*"))
    assert not (root / "evaluator" / "episodes" / episode / "truth" / inspection.FILE).exists()
    rows = [json.loads(x) for x in gzip.open(evaluator, "rt")]
    assert rows[0]["t_sim_s"] == 0.0 and rows[-1]["t_sim_s"] == 3600.0
    assert rows == sorted(rows, key=lambda r: r["t_sim_s"])


def test_the_fault_entries_carry_the_instance_ids_of_the_fault_truth() -> None:
    """The instance identifiers of a fault set are the episode identifier and the index of the
    fault, as in the fault-truth rows, and the parameter holds its last value after the ramp.

    Independent: yes, because the identifiers are written out by hand.
    """
    fault = spec(
        "PIPE_LEAK", "orifice", "E-D1", 300.0, 1e-4, position=0.5, discharge_coefficient=0.6
    )
    assert instance_ids("EP-1", (fault, fault)) == ["FI-EP-1-00", "FI-EP-1-01"]
    assert parameter_value(fault, 10_000.0) == 1e-4
