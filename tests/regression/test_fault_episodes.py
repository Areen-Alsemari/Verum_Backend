"""Episodes with one injected fault: equivalence at severity 0, determinism, restart, schemas,
rejection, eligibility, sensor faults and leakage.

A shortened delivery scenario is run with a fault set and compared with the healthy twin of the same
seed. A fault of severity 0 changes no byte, sensor faults change the noise-free series by closed
forms, and nothing about a fault may reach the agent-visible rows or the gateway. The closed forms
are in the "Fault episodes" section of the verification notes.

See D63 to D67.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import _fault_cases as fc
from _series import load_series
from verum.api import Gateway, check_allowlist
from verum.contracts import ContractError, load_schema, validate
from verum.faults import FaultSet, FaultSpec, check, from_record, violations
from verum.hydraulics import HydraulicModel
from verum.sensors import load_sensor_config
from verum.sensors.adapter import observe_rows
from verum.sim.episode import EpisodeResult, run_episode
from verum.sim.scenario import load_scenario
from verum.truth import ListSink, read_rows

pytestmark = pytest.mark.slow

DURATION = 2400.0
SENSORS = load_sensor_config()
SPAN = {t: s.range_hi - s.range_lo for t, s in SENSORS.tags.items() if s.kind == "continuous"}  # type: ignore[operator]
LEAK = FaultSpec("PIPE_LEAK", "orifice", "E-PA3", 600.0, 300.0, 5e-4, 0.5, 0.62)
BIAS = FaultSpec("SENSOR_DRIFT", "bias", "PT-203", 600.0, None, 0.03)
DRIFT = FaultSpec("SENSOR_DRIFT", "drift", "FT-201", 600.0, None, -0.02)
STUCK = FaultSpec("SENSOR_DRIFT", "stuck", "PT-202A", 600.0, None, 0.0)
DATA_FILES = (
    "hydraulic_state", "solver_diagnostics", "mass_ledger", "events", "boundary_state",
    "validity_windows", "observations", "observation_audit",
)  # fmt: skip


def zero(spec: FaultSpec) -> FaultSpec:
    return dataclasses.replace(spec, peak_severity=0.0)


ZERO_FAULTS = [
    zero(LEAK),
    FaultSpec(
        "VALVE_RESTRICTION",
        "restriction",
        "XV-S101",
        600.0,
        300.0,
        0.5,
        None,
        None,
        0.0,
        "position_visible",
    ),
    FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 600.0, 300.0, 0.8, None, None, 0.0),
    zero(BIAS),
    zero(STUCK),
    FaultSpec("VALVE_MISROUTING", "closed_but_open", "XV-S102", 600.0, 300.0, 1.0, None, None, 0.0),
]


def run(model: HydraulicModel, out: Path, faults: FaultSet | None = None) -> EpisodeResult:
    scenario = dataclasses.replace(load_scenario("S0-A"), duration_s=DURATION)
    return run_episode("S0-A", out, model, scenario, faults)


@pytest.fixture(scope="module")
def healthy(model: HydraulicModel, tmp_path_factory: pytest.TempPathFactory) -> EpisodeResult:
    return run(model, tmp_path_factory.mktemp("healthy"))


@pytest.fixture(scope="module")
def faulted(
    model: HydraulicModel, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, EpisodeResult]:
    specs = {"leak": LEAK, "bias": BIAS, "drift": DRIFT, "stuck": STUCK}
    out = tmp_path_factory.mktemp("faulted")
    return {k: run(model, out / k, FaultSet((s,))) for k, s in specs.items()}


def same_bytes(a: EpisodeResult, b: EpisodeResult, names: tuple[str, ...]) -> bool:
    return all(
        (a.directory / f"{n}.jsonl.gz").read_bytes() == (b.directory / f"{n}.jsonl.gz").read_bytes()
        for n in names
    )


@pytest.mark.parametrize("spec", ZERO_FAULTS, ids=lambda s: f"{s.fault_type}-{s.variant}")
def test_a_fault_of_severity_zero_reproduces_the_healthy_episode_bit_for_bit(
    model: HydraulicModel, healthy: EpisodeResult, tmp_path: Path, spec: FaultSpec
) -> None:
    """A fault of severity 0 gives truth and observation files that equal the healthy episode byte
    for byte. Independent: yes, because the healthy twin is the reference.
    """
    twin = run(model, tmp_path, FaultSet((spec,)))
    assert not twin.rejected and same_bytes(healthy, twin, DATA_FILES)


def test_the_same_inputs_give_the_same_files(
    model: HydraulicModel, faulted: dict[str, EpisodeResult], tmp_path: Path
) -> None:
    """Running the same faulted episode twice gives the same identifier and file hashes.
    Independent: yes, because equality is the property.
    """
    again = run(model, tmp_path, FaultSet((LEAK,)))
    assert again.episode_id == faulted["leak"].episode_id
    assert again.file_hashes == faulted["leak"].file_hashes


def test_a_restart_inside_a_leak_ramp_continues_bit_for_bit(model: HydraulicModel) -> None:
    """A run restarted from a checkpoint inside a leak ramp gives exactly the rows of the continuous
    run. Independent: yes, because equality is the property.
    """
    faults = fc.leak("E-PA3", 5e-4, 300.0, 300.0)
    sink_a = ListSink()
    a = fc.engine(model, "S0-A", 800.0, faults, sink=sink_a)
    a.run(until=450.0)  # the ramp runs from 300 s to 600 s
    mark = {d: len(rows) for d, rows in sink_a.rows.items()}
    saved = a.checkpoint()
    a_outcome = a.run()
    sink_b = ListSink()
    b = fc.engine(model, "S0-A", 800.0, faults, state=saved, sink=sink_b)
    b_outcome = b.run()
    for dataset in sink_a.rows:
        assert sink_a.rows[dataset][mark[dataset] :] == sink_b.rows[dataset], dataset
    assert (
        a_outcome.ledger == b_outcome.ledger and a_outcome.final_volumes == b_outcome.final_volumes
    )
    assert saved.leak_flows and b.state.cum_spilled_m3 > 0.0


def test_every_written_row_and_record_of_a_leak_episode_is_valid(
    faulted: dict[str, EpisodeResult],
) -> None:
    """Every row and record of a leak episode validates against its schema. Independent: yes,
    because the schemas are separate files.
    """
    result = faulted["leak"]
    series = load_series(
        result.directory
    )  # validates every row of every dataset against its schema
    assert all(count == 0 for count in series.invalid.values())
    rows = read_rows(result.directory, "fault_truth")
    assert len(rows) == 1
    for row in rows:
        validate("fault_truth", row)
    record = json.loads((result.directory / "episode.json").read_text())
    validate("episode", record)
    assert record["fault_instance_ids"] == [rows[0]["fault_instance_id"]]
    assert rows[0]["fault_type"] == "PIPE_LEAK" and rows[0]["asset_id"] == "E-PA3"
    assert rows[0]["severity_trajectory"]["knots"] == [[0.0, 0.0], [300.0, 1.0]]
    assert rows[0]["location"] == {"edge_id": "E-PA3", "fraction": 0.5}
    validate("fault_spec", LEAK.as_record())
    assert from_record(LEAK.as_record()) == LEAK


def test_a_leak_edge_row_carries_the_separate_sink(faulted: dict[str, EpisodeResult]) -> None:
    """The edge rows of a leak carry the leak as a separate sink with its flow. Independent: yes,
    because the expected fields are written out in the test.
    """
    rows = read_rows(faulted["leak"].directory, "hydraulic_state")
    edge = {
        r["t_sim_s"]: r["payload"]
        for r in rows
        if r["record_type"] == "edge_state" and r["element_id"] == "E-PA3" and r["side"] is None
    }
    assert "leak_flow_m3s" not in edge[500.0] and edge[1000.0]["leak_flow_m3s"] > 0.0
    ledger = [
        r for r in read_rows(faulted["leak"].directory, "mass_ledger") if r["scope"] == "network"
    ]
    assert ledger[-1]["cumulative_spill_kg"] > 0.0 and ledger[-1]["closed"] is True


def test_a_rejected_candidate_is_never_labelled_as_a_fault(
    model: HydraulicModel, tmp_path: Path
) -> None:
    """A fault whose run is rejected leaves a rejection record and is never labelled as a fault.
    Independent: yes, because the expected outcome is the rejection rule.
    """
    dead = FaultSet((dataclasses.replace(LEAK, asset_id="E-R102a"),))
    result = run(model, tmp_path, dead)
    assert result.rejected
    record = json.loads((result.directory / "simulation_rejected.json").read_text())
    validate("simulation_rejected", record)
    assert record["gate"] == "SGF"
    episode = json.loads((result.directory / "episode.json").read_text())
    assert episode["fault_instance_ids"] == [] and episode["status"] == "rejected"
    assert not (result.directory / "fault_truth.jsonl.gz").exists()


# --- eligibility (no run) ----------

VIS = "position_visible"
EDGES = {"E-PA3", "E-S101a", "E003"}
TAGS = {"PT-203", "FT-201", "LT-101"}


def good() -> list[FaultSpec]:
    return [LEAK]


def test_an_eligible_specification_has_no_violation() -> None:
    """A well-formed specification has no violation. Independent: yes, because the expected outcome
    is the eligibility rule.
    """
    assert violations(good(), EDGES, TAGS, 3600.0) == []
    check(good(), EDGES, TAGS, 3600.0)


@pytest.mark.parametrize(
    ("spec", "text"),
    [
        (dataclasses.replace(LEAK, onset_s=599.0), "onset"),
        (dataclasses.replace(LEAK, onset_s=1801.0), "onset"),
        (dataclasses.replace(LEAK, ramp_s=None), "ramps"),
        (dataclasses.replace(LEAK, ramp_s=100.0), "ramps"),
        (dataclasses.replace(LEAK, asset_id="E-NOWHERE"), "eligible asset"),
        (dataclasses.replace(LEAK, magnitude=1.5e-3), "leak area"),
        (dataclasses.replace(LEAK, magnitude=1e-6), "leak area"),
        (dataclasses.replace(LEAK, position=0.99), "position"),
        (dataclasses.replace(LEAK, discharge_coefficient=None), "coefficient"),
        (
            FaultSpec(
                "VALVE_RESTRICTION", "restriction", "XV-R000", 600.0, 300.0, 0.5, fault_mode=VIS
            ),
            "asset",
        ),
        (
            FaultSpec(
                "VALVE_RESTRICTION", "restriction", "XV-S101", 600.0, 300.0, 0.95, fault_mode=VIS
            ),
            "ceiling",
        ),
        (FaultSpec("VALVE_RESTRICTION", "restriction", "XV-S101", 600.0, 300.0, 0.5), "fault_mode"),
        (
            FaultSpec(
                "VALVE_RESTRICTION", "restriction", "XV-S101", 600.0, 300.0, 0.5, fault_mode="half"
            ),
            "fault_mode",
        ),
        (dataclasses.replace(LEAK, fault_mode="obstruction"), "no fault_mode"),
        (FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 600.0, 300.0, 0.6), "scale"),
        (FaultSpec("SENSOR_DRIFT", "bias", "XV-S101", 600.0, None, 0.03), "asset"),
        (FaultSpec("SENSOR_DRIFT", "bias", "PT-203", 600.0, None, 0.06), "of span"),
        (FaultSpec("SENSOR_DRIFT", "stuck", "PT-203", 600.0, None, 0.01), "no magnitude"),
        (FaultSpec("VALVE_MISROUTING", "open_but_stuck", "XV-S101", 600.0, 300.0, 0.5), "stuck"),
        (FaultSpec("PIPE_LEAK", "bias", "E-PA3", 600.0, 300.0, 5e-4, 0.5, 0.62), "variant"),
    ],
)
def test_an_ineligible_specification_is_refused(spec: FaultSpec, text: str) -> None:
    """Each ineligible specification is refused with its own reason. Independent: yes, because the
    expected reasons are written out per case.
    """
    problems = violations([spec], EDGES, TAGS, 3600.0)
    assert problems and any(text in p for p in problems), problems
    with pytest.raises(ContractError):
        check([spec], EDGES, TAGS, 3600.0)


def test_one_fault_per_episode_and_per_asset() -> None:
    """Two faults in one episode, or two on one asset, are refused. Independent: yes, because the
    expected outcome is the one-fault rule.
    """
    two = [LEAK, dataclasses.replace(LEAK, position=0.7)]
    assert any("one fault per episode" in p for p in violations(two, EDGES, TAGS, 3600.0))
    assert any("two faults" in p for p in violations(two, EDGES, TAGS, 3600.0))


def test_the_specification_schema_refuses_an_open_record() -> None:
    """The specification schema refuses a record with an added field. Independent: yes, because the
    expected outcome is the closed schema.
    """
    record = LEAK.as_record()
    with pytest.raises(ContractError):
        validate("fault_spec", {**record, "severity_label": "high"})
    with pytest.raises(ContractError):
        validate("fault_spec", {k: v for k, v in record.items() if k != "onset_s"})


# --- sensor faults ----------


def clean(result: EpisodeResult, spec: FaultSpec | None) -> dict[str, list[dict[str, Any]]]:
    hook = FaultSet((spec,)).sensor_hook(SPAN) if spec else None
    rows = observe_rows(result.directory, hook=hook, clean=True).observations
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["tag_id"], []).append(r)
    return by


def test_bias_drift_and_stuck_match_their_closed_forms_and_touch_nothing_else(
    healthy: EpisodeResult, faulted: dict[str, EpisodeResult]
) -> None:
    """Bias, drift and stuck-at faults change the noise-free series by their closed forms and leave
    the truth files and the other tags unchanged. Independent: yes, because the reference is a
    closed form and the healthy twin.
    """
    base = clean(healthy, None)
    for key, spec in (("bias", BIAS), ("drift", DRIFT), ("stuck", STUCK)):
        changed = clean(faulted[key], spec)
        assert same_bytes(healthy, faulted[key], DATA_FILES[:6])  # the truth files are the twin's
        assert {t: v for t, v in changed.items() if t != spec.asset_id} == {
            t: v for t, v in base.items() if t != spec.asset_id
        }
        span, tag = SPAN[spec.asset_id], spec.asset_id
        first_after = next(r["value"] for r in base[tag] if r["t_sim_s"] >= spec.onset_s)
        for a, b in zip(base[tag], changed[tag], strict=True):
            t = a["t_sim_s"]
            if t < spec.onset_s:
                expected = a["value"]
            elif key == "bias":
                expected = a["value"] + 0.03 * span
            elif key == "drift":
                expected = a["value"] - 0.02 * span * (t - 600.0) / 3600.0
            else:
                expected = first_after
            assert b["value"] == pytest.approx(expected, abs=1e-9), (key, t)


def test_a_noisy_faulted_series_differs_from_the_twin_by_the_offset_and_one_step(
    healthy: EpisodeResult, faulted: dict[str, EpisodeResult]
) -> None:
    """A noisy faulted series differs from the healthy one by the fault offset up to one
    quantisation step, because the noise draws are the same. Independent: yes, because the reference
    is the healthy twin and a closed form.
    """
    def tag_rows(result: EpisodeResult, tag: str) -> list[dict[str, Any]]:
        path = result.directory / "observations.jsonl.gz"
        with gzip.open(path, "rt") as handle:
            return [r for r in map(json.loads, handle) if r["tag_id"] == tag]

    step = SPAN["PT-203"] / 65535.0
    for a, b in zip(tag_rows(healthy, "PT-203"), tag_rows(faulted["bias"], "PT-203"), strict=True):
        assert (a["value"] is None) == (b["value"] is None)  # the dropout pattern is the same
        if a["value"] is not None:
            offset = 0.03 * SPAN["PT-203"] if a["t_sim_s"] >= 600.0 else 0.0
            assert b["value"] - a["value"] == pytest.approx(offset, abs=1.01 * step)


# --- leakage ----------

FORBIDDEN = re.compile(
    r"(?i)(S0u?-[A-Z0-9]|REJ-\d|VW-\d|FI-|analytic_verification|restricted_benchmark|truth|normal"
    r"|window|scenario|hidden|ground_truth|hydraulic_state|fault|severity|leak|spill|restrict"
    r"|misrout|degrad|stuck|drift|bias)"
)


def observations(result: EpisodeResult) -> list[dict[str, Any]]:
    with gzip.open(result.directory / "observations.jsonl.gz", "rt") as handle:
        return [json.loads(line) for line in handle]


@pytest.mark.parametrize("key", ["leak", "bias", "drift", "stuck"])
def test_no_fault_information_reaches_the_agent_visible_data(
    healthy: EpisodeResult, faulted: dict[str, EpisodeResult], key: str
) -> None:
    """No fault, severity, window, scenario or tier word appears in the agent-visible rows, and the
    dropout pattern equals that of the healthy twin. Independent: yes, because the check scans the
    written rows.
    """
    result = faulted[key]
    keys = set(load_schema("observation")["properties"])
    rows = observations(result)
    assert all(set(r) == keys for r in rows)  # LK-01: only the closed schema's keys
    text = "\n".join(json.dumps(r, sort_keys=True) for r in rows[::37])
    assert not FORBIDDEN.search(text.replace("episode_id", "").replace("EP-", ""))
    payload = Gateway(result.directory).query(DURATION)
    check_allowlist(payload)  # LK-07: the allowlist
    assert not FORBIDDEN.search(json.dumps(payload).replace("episode_id", "").replace("EP-", ""))
    # LK-09 and LK-10: the dropout pattern and the quality counts equal those of the healthy twin.
    twin = observations(healthy)
    assert [(r["tag_id"], r["t_sim_s"], r["value"] is None) for r in rows] == [
        (r["tag_id"], r["t_sim_s"], r["value"] is None) for r in twin
    ]
    assert Counter(r["quality_flag"] for r in rows) == Counter(r["quality_flag"] for r in twin)
    assert Counter(r["availability_status"] for r in rows) == Counter(
        r["availability_status"] for r in twin
    )
    assert re.fullmatch(r"EP-[0-9A-F]{12}", result.episode_id)  # LK-12: opaque identifier


def test_the_fault_files_are_not_served_and_the_packages_do_not_import_the_faults(
    faulted: dict[str, EpisodeResult], root: Path
) -> None:
    """The gateway serves no fault file, and the sensors and api packages do not import the fault
    package. Independent: yes, because the check inspects the payload keys and the imports.
    """
    assert set(Gateway(faulted["leak"].directory).query(100.0)) == {
        "episode_id", "as_of_s", "observations", "assets", "inspection_catalog",
    }  # fmt: skip
    for package in ("sensors", "api"):
        for path in (root / "src" / "verum" / package).glob("*.py"):
            assert "verum.faults" not in path.read_text(encoding="utf-8"), path


# --- misrouting: the states it creates are judged by the gates, not suppressed ----------


def test_a_valve_commanded_closed_but_open_keeps_three_separate_records(
    model: HydraulicModel,
) -> None:
    """A valve forced open against its closed command keeps the command, the actual opening and the
    physical state apart, flags a branched lineup, and its open contact reads 1 above an opening of
    0.98. Independent: yes, because the expected records follow from the actuator rule.
    """
    spec = FaultSpec("VALVE_MISROUTING", "closed_but_open", "XV-S102", 300.0, 30.0, 1.0)
    e, outcome = fc.run(model, "S0-A", 700.0, FaultSet((spec,)))
    assert outcome.rejection is None
    assert "branched_lineup" in {w.kind for w in outcome.windows}
    rows: Any = e.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
    valve = [r for r in rows if r["record_type"] == "valve_state" and r["element_id"] == "XV-S102"]
    last = [r for r in valve if r["t_sim_s"] == 600.0 and r["side"] is None][0]["payload"]
    assert last["commanded_open"] is False and last["position_frac"] == 1.0
    assert last["physically_closed"] is False
    series = [(r["t_sim_s"], r["side"], r["payload"]) for r in valve]
    from verum.sensors.adapter import _contact_changes

    changes = _contact_changes(series, 0.98, 0.97)
    assert changes[0] == (0.0, 0) and changes[-1][1] == 1
    assert changes[-1][0] == pytest.approx(300.0 + 0.98 * 30.0, abs=0.1)  # the opening is linear


def test_a_valve_stuck_almost_closed_is_stopped_by_a_gate_and_not_suppressed(
    model: HydraulicModel,
) -> None:
    """A pump valve stuck almost closed is stopped by an engine gate and the run is not suppressed.
    Independent: yes, because the expected outcome is the rule that a gate rejection is recorded.
    """
    spec = FaultSpec("VALVE_MISROUTING", "open_but_stuck", "XV-PAO", 300.0, 30.0, 0.01)
    _, outcome = fc.run(model, "S0-A", 700.0, FaultSet((spec,)))
    assert outcome.rejection is not None
    assert outcome.rejection["gate"] in {"SG0", "SG2"}  # the pump domain or the solver, D66
    assert outcome.rejection["t_sim_s"] > 300.0
