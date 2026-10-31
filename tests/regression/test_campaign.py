"""The campaign generator: plan, sampler, splits, runner, storage and leakage.

The plan, sampler and split checks run without a simulation and use large samples, so their
frequencies can be compared with binomial bounds. The runner checks use a stub episode to test
resume and worker independence, and a small campaign of real episodes tests regeneration, storage
and the leakage rules.

See D83 to D88.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from verum.api import Gateway, check_allowlist
from verum.campaign import runner
from verum.campaign.classes import ClassTable
from verum.campaign.plan import CampaignConfig, build_plan
from verum.campaign.sampler import Sampler
from verum.campaign.splits import build_split_plan, split_of
from verum.contracts import load_schema
from verum.faults import FaultSet, lineup_states, violations
from verum.gates import assert_release_allowed
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.seeds import campaign_seeds
from verum.sim.episode import run_episode
from verum.sim.scenario import parse_scenario

CONFIG = CampaignConfig(20261101, 3000)
SIGMAS = 4.0
EDGES = [e.edge_id for e in HydraulicModel.load().topology.edges]
TAGS = [
    "FT-001",
    "PT-001",
    "LT-101",
    "LT-102",
    "LT-103",
    "PT-201",
    "PT-202A",
    "PT-202B",
    "FT-201",
    "PT-203",
    "TT-001",
]


def within(count: int, trials: int, p: float) -> bool:
    """Whether a count is within four binomial standard deviations of its expectation."""
    return abs(count - trials * p) <= SIGMAS * math.sqrt(trials * p * (1 - p)) + 1.0


@pytest.fixture(scope="module")
def sampled() -> list[Any]:
    sampler = Sampler(CONFIG, ClassTable())
    return [sampler.sample(slot) for slot in build_plan(CONFIG)]


def on_receipt_path(asset: str) -> bool:
    return asset.startswith(("E00", "E-R", "XV-R"))


def without_time(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "wall_s"} for r in records]


# --- plan ----------
def test_the_plan_has_the_exact_composition_and_marks() -> None:
    """The plan of 1000 episodes has 200 healthy, 600 single and 200 pair episodes, equal subtypes
    and pair types, at most 5 percent latent faults and 10 percent switch, stress and audit marks.

    Independent: yes, because the counts follow from the shares by arithmetic.
    """
    plan = build_plan(CampaignConfig(7, 1000))
    assert Counter(s.kind for s in plan) == {"healthy": 200, "single": 600, "pair": 200}
    subtypes = Counter(s.subtype for s in plan if s.kind == "single")
    assert (
        set(subtypes) == set(CampaignConfig(7, 1000).subtypes)
        and max(subtypes.values()) - min(subtypes.values()) <= 1
    )
    pairs = Counter(s.pair_type for s in plan if s.kind == "pair")
    assert len(pairs) == 4 and max(pairs.values()) == min(pairs.values()) == 50
    assert sum(s.latent for s in plan) <= 0.05 * 800
    assert sum(s.switch for s in plan) <= 100 and sum(s.stress for s in plan) <= 100
    assert sum(s.audit for s in plan) == 100


def test_the_plan_is_a_function_of_the_seed_and_the_size() -> None:
    """The same seed and size give the same plan; another seed gives another.

    Independent: no, because it compares the function with itself; it guards against hidden state.
    """
    assert build_plan(CampaignConfig(7, 300)) == build_plan(CampaignConfig(7, 300))
    assert build_plan(CampaignConfig(7, 300)) != build_plan(CampaignConfig(8, 300))


def test_no_two_episodes_of_a_campaign_share_a_seed(sampled: list[Any]) -> None:
    """The seeds of 6000 episodes and the seeds in the sampled scenario records are distinct.

    Independent: yes, because the check counts distinct values.
    """
    assert len(set(campaign_seeds(CONFIG.seed, 6000))) == 6000
    assert len({e.scenario["seed"] for e in sampled}) == len(sampled)


# --- sampler ----------
def test_stratum_family_subtype_and_class_frequencies_follow_the_plan(sampled: list[Any]) -> None:
    """Atmosphere, temperature, family, subtype and class counts are within four binomial standard
    deviations of the plan.

    Independent: yes, because the expectations come from the shares and from equal allocation.
    """
    n = len(sampled)
    assert within(sum(e.strata["atmosphere"] == "inland" for e in sampled), n, 0.5)
    assert sum(e.strata["temperature_c"] == 45.0 for e in sampled) <= 0.10 * n
    assert sum(e.strata["family"] == "switch" for e in sampled) <= 0.10 * n
    healthy = [e for e in sampled if e.slot.kind == "healthy"]
    assert within(sum(e.strata["family"] == "delivery" for e in healthy), len(healthy), 0.35 / 0.91)
    singles = Counter(f.subtype for e in sampled if e.slot.kind == "single" for f in e.faults)
    assert all(within(c, 1800, 1 / 8) for c in singles.values())
    cells: dict[tuple[str, str], Counter[str]] = {}
    for e in sampled:
        for f in e.faults:
            if e.slot.kind == "single" and not f.latent:
                cells.setdefault((f.subtype, f.asset_class), Counter())[f.cls] += 1
    for counts in cells.values():
        total = sum(counts.values())
        if total >= 40:
            assert all(within(c, total, 1 / len(counts)) for c in counts.values())


def test_a_pair_never_shares_an_asset_and_its_onsets_obey_the_rules(sampled: list[Any]) -> None:
    """In every pair the two assets differ, the onsets lie in 600 to 1800 s and are 300 s apart,
    and every fault set passes the eligibility rules for the lineup in force at its onset.

    Independent: yes, because the rules are written here as arithmetic on the sampled values.
    """
    table = load_lineup_table(HydraulicModel.load().topology)
    for e in sampled:
        specs = [f.spec for f in e.faults]
        if not specs:
            continue
        assert len({s.asset_id for s in specs}) == len(specs)
        onsets = sorted(s.onset_s for s in specs)
        assert all(600.0 <= o <= 1800.0 for o in onsets)
        assert len(onsets) == 1 or onsets[1] - onsets[0] >= 300.0
        raw = parse_scenario(e.scenario)
        states = lineup_states(raw.initial_mode, 0.0, raw.schedule, table.modes, onsets[0])
        problems = violations(specs, EDGES, TAGS, 3600.0, states, 2, 300.0)
        assert problems == [], (e.index, problems)


def test_pair_types_follow_their_definition(sampled: list[Any]) -> None:
    """Sensor pairs hold two sensor faults, a leak-restriction pair a leak and a restriction on one
    path, and a physical-physical pair one fault on each path.

    Independent: yes, because the definitions of D85 are applied to the sampled faults.
    """
    sensors = {"bias", "drift", "stuck"}
    for e in sampled:
        kinds = [f.subtype for f in e.faults]
        if e.slot.pair_type == "sensor_sensor":
            assert set(kinds) <= sensors
        elif e.slot.pair_type == "physical_sensor":
            assert len(set(kinds) & sensors) == 1
        elif e.slot.pair_type == "leak_restriction":
            assert kinds[0] == "leak" and kinds[1].startswith("restriction")
            a, b = (f.asset for f in e.faults)
            assert on_receipt_path(a) == on_receipt_path(b)
        elif e.slot.pair_type == "physical_physical":
            a, b = (f.asset for f in e.faults)
            assert on_receipt_path(a) != on_receipt_path(b)


def test_the_initial_levels_are_inside_the_band_of_the_stratum(sampled: list[Any]) -> None:
    """A delivering tank starts at least 0.5 m above the stored pumping minimum, every tank starts
    within 1.8 to 12 m, and the set-point is one of the allowed values.

    Independent: yes, because the minimum is read from the stored table, not computed.
    """
    from verum.hydraulics.pumping_minimum import pumping_minimum_level, stratum_filename

    table = load_lineup_table(HydraulicModel.load().topology)
    for e in sampled[:400]:
        sc = parse_scenario(e.scenario)
        assert all(1.8 <= v <= 12.0 for v in sc.tank_levels_m.values())
        for valve in table.mode(sc.initial_mode).open_valves:
            if valve.startswith("XV-S"):
                tank = f"TK-{valve[-3:]}"
                minimum = pumping_minimum_level(
                    tank, sc.temperature_c, "reference_fittings", 4.0, None,
                    stratum_filename(sc.atmosphere_stratum, "RVP_9_0", "v2"),
                ).value  # fmt: skip
                assert sc.tank_levels_m[tank] >= minimum + 0.5 - 1e-9
        assert sc.variability_profile == "v2" and sc.duration_s == 3600.0


def test_the_class_intervals_follow_the_class_file() -> None:
    """A leak on a discharge edge has three classes bounded at 1.36e-5 and 5.43e-5 m2, the visible
    restriction has only the clear class, an obstruction on the pump branch has only the invisible
    class, and the gaps name the classes that the unresolved boundaries remove.

    Independent: yes, because the boundaries are read by hand from the class file.
    """
    table = ClassTable()
    leak = table.intervals("leak", "discharge")
    assert [c.name for c in leak] == ["invisible", "marginal", "clear"]
    assert leak[1].start == pytest.approx(1.36e-5, rel=0.01)
    assert leak[2].start == pytest.approx(5.43e-5, rel=0.01)
    assert [c.name for c in table.intervals("restriction_position_visible", "tank_inlet")] == [
        "clear"
    ]
    assert [c.name for c in table.intervals("restriction_obstruction", "pump_branch")] == [
        "invisible"
    ]
    assert table.gaps("restriction_obstruction", "pump_branch") == ["marginal", "clear"]
    assert table.gaps("drift", "pressure") == ["clear"] and table.gaps("leak", "discharge") == []
    assert [c.name for c in table.intervals("bias", "flow")] == ["marginal", "clear"]  # a floor
    assert [c.name for c in table.intervals("stuck", "flow")] == ["none"]


# --- splits ----------
def test_held_out_strata_and_assets_never_reach_train_or_validation(sampled: list[Any]) -> None:
    """A train or validation episode is in no held-out unit and has no fault on a held-out asset,
    a whole unit and one asset of each subtype are held out, and the test share is 10 to 35 percent.

    Independent: yes, because the rule is applied to the sampled episodes by direct comparison.
    """
    plan = build_split_plan(CONFIG)
    assert plan.test_units and set(plan.held_assets) == set(CONFIG.subtypes)
    counts: Counter[str] = Counter()
    for e in sampled:
        unit = (e.strata["family"], e.strata["atmosphere"], e.strata["temperature_c"])
        faults = [(f.subtype, f.asset) for f in e.faults]
        which = split_of(plan, unit, faults)
        counts[which] += 1
        if which != "test":
            assert unit not in plan.test_units
            assert all(plan.held_assets[s] != a for s, a in faults)
        else:
            assert unit in plan.test_units or any(plan.held_assets[s] == a for s, a in faults)
    assert 0.10 <= counts["test"] / len(sampled) <= 0.35
    assert counts["train"] > counts["validation"] > 0


# --- runner with a stub episode ----------
def stub_executor(config: CampaignConfig, index: int, root: Path) -> dict[str, Any]:
    """An episode that writes two small files, for the tests of resume and worker order."""
    ctx = runner.context(config)
    spec = ctx.sampler.sample(ctx.plan[index])
    record = runner.base_record(config, spec)
    episode = f"EP-{index:012X}"
    layout = runner.Layout(root)
    agent = layout.agent / "episodes" / episode
    evaluator = layout.evaluator / "episodes" / episode
    for folder in (agent, evaluator):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    (agent / runner.OBSERVATIONS).write_bytes(gzip.compress(f"{index}".encode(), mtime=0))
    (evaluator / "labels.json").write_text(json.dumps({"index": index}), encoding="utf-8")
    files = {
        str(p.relative_to(root)): runner.sha256(p)
        for f in (agent, evaluator)
        for p in sorted(f.rglob("*"))
        if p.is_file()
    }
    faults = [
        {"subtype": f.subtype, "asset_id": f.asset, "class": f.cls, "severity": f.severity}
        for f in spec.faults
    ]
    return {**record, "episode_id": episode, "status": "completed", "tier": "analytic_verification",
            "faults": faults, "files": files, "wall_s": 0.1 * index}  # fmt: skip


SMALL = CampaignConfig(11, 60)


def manifest_text(root: Path) -> str:
    return (runner.Layout(root).evaluator / "manifest.json").read_text(encoding="utf-8")


def test_one_and_three_workers_give_the_same_manifest_and_files(tmp_path: Path) -> None:
    """A run on one worker and a run on three give the same manifest and the same file hashes,
    although the episodes finish in another order and take another time.

    Independent: yes, because the comparison is of two runs, and the manifest holds no timing.
    """
    a, b = tmp_path / "one", tmp_path / "three"
    runner.run_campaign(SMALL, a, workers=1, executor=stub_executor)
    runner.run_campaign(SMALL, b, workers=3, executor=stub_executor)
    assert manifest_text(a) == manifest_text(b)
    names = sorted(p.relative_to(a) for p in (a / "agent_visible").rglob("*") if p.is_file())
    assert names == sorted(
        p.relative_to(b) for p in (b / "agent_visible").rglob("*") if p.is_file()
    )
    assert all(runner.sha256(a / n) == runner.sha256(b / n) for n in names)


def test_an_interrupted_run_resumes_to_the_same_manifest(tmp_path: Path) -> None:
    """A run that stops after 25 episodes, with one record damaged and one episode file removed,
    continues without redoing the finished episodes and ends with the manifest of an uninterrupted
    run.

    Independent: yes, because the reference is a separate uninterrupted run.
    """
    whole, cut = tmp_path / "whole", tmp_path / "cut"
    runner.run_campaign(SMALL, whole, workers=1, executor=stub_executor)
    runner.run_campaign(SMALL, cut, workers=1, executor=stub_executor, indices=list(range(25)))
    layout = runner.Layout(cut)
    (layout.records / "000003.json").write_text("{", encoding="utf-8")  # a torn record
    victim = json.loads((layout.records / "000004.json").read_text())["files"]
    (cut / next(iter(victim))).unlink()  # a lost episode file
    stamp = (layout.records / "000010.json").stat().st_mtime_ns
    runner.run_campaign(SMALL, cut, workers=1, executor=stub_executor)
    assert (layout.records / "000010.json").stat().st_mtime_ns == stamp  # finished, not redone
    assert manifest_text(cut) == manifest_text(whole)


def test_labels_of_test_episodes_stay_in_the_evaluator_store(tmp_path: Path) -> None:
    """No row of the agent-visible labels file belongs to a test episode, the test labels are in the
    evaluator store, and no agent-visible text file names a test episode's faults.

    Independent: yes, because the check compares the files with the split of each record.
    """
    runner.run_campaign(SMALL, tmp_path, workers=1, executor=stub_executor)
    layout = runner.Layout(tmp_path)
    records = runner.load_records(layout, list(range(SMALL.n)))
    test_ids = {r["episode_id"] for r in records if r["split"] == "test"}
    rows = [
        json.loads(x)
        for x in (layout.agent / "labels_train_validation.jsonl").read_text().splitlines()
    ]
    assert rows and not {r["episode_id"] for r in rows} & test_ids and test_ids
    assert {r["split"] for r in rows} <= {"train", "validation"}
    held = [
        json.loads(x) for x in (layout.evaluator / "labels_test.jsonl").read_text().splitlines()
    ]
    assert {r["episode_id"] for r in held} == test_ids
    for path in layout.agent.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".jsonl", ".json"}:
            text = path.read_text(encoding="utf-8")
            assert not any(i in text for i in test_ids), path


def test_the_runner_respects_the_machine_limits(tmp_path: Path) -> None:
    """At most six workers and never more than the cores minus two, and a run stops when the free
    space is below the minimum.

    Independent: yes, because the limits are stated in the rule.
    """
    assert runner.worker_count() <= 6 and runner.worker_count() <= max(1, (os.cpu_count() or 1) - 2)
    assert runner.worker_count(64) == runner.worker_count()
    assert runner.check_disk(tmp_path, 0.001) > 0.001
    with pytest.raises(RuntimeError, match="free"):
        runner.check_disk(tmp_path, 1e9)


def test_the_release_gate_still_refuses_the_production_candidate() -> None:
    """The gate refuses the production-candidate tier while production generation is disabled.

    Independent: yes, because the gate is the code under test and the policy file is its input.
    """
    with pytest.raises(Exception, match="production"):
        assert_release_allowed("production_candidate")


# --- real episodes ----------
def selected_indices(config: CampaignConfig, count: int) -> list[int]:
    """One episode of each kind, subtype and pair type first, then the lowest indices."""
    seen: set[tuple[str, str | None]] = set()
    chosen: list[int] = []
    for slot in runner.context(config).plan:
        key = (slot.kind, slot.subtype or slot.pair_type)
        if key not in seen and not slot.switch:
            seen.add(key)
            chosen.append(slot.index)
    for slot in runner.context(config).plan:
        if len(chosen) >= count:
            break
        if slot.index not in chosen:
            chosen.append(slot.index)
    return sorted(chosen[:count])


REAL = CampaignConfig(20261101, 60)


@pytest.fixture(scope="module")
def real_campaign(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("campaign")
    runner.run_campaign(REAL, root, workers=3, indices=selected_indices(REAL, 20))
    return root


@pytest.mark.slow
def test_regeneration_from_the_seed_matches_the_stored_hashes(real_campaign: Path) -> None:
    """Twenty episodes rebuilt from the seed and the configuration give the stored observation hash.

    Independent: yes, because the stored hash comes from the first run and the second run shares
    only the seed and the configuration.
    """
    layout = runner.Layout(real_campaign)
    records = runner.load_records(layout, list(range(REAL.n)))
    assert sum(r["status"] == "completed" for r in records) >= 10
    results = runner.verify_sample(REAL, real_campaign, 20, workers=3)
    assert results and all(ok for _, ok in results)


@pytest.mark.slow
def test_every_candidate_passes_the_gates_or_is_recorded_as_rejected(real_campaign: Path) -> None:
    """Each episode of the small campaign is completed, excluded for a validity window, or rejected
    with a gate and a parameter, and only completed episodes have files.

    Independent: yes, because the statuses are read from the records the runner wrote.
    """
    for r in runner.load_records(runner.Layout(real_campaign), list(range(REAL.n))):
        assert r["status"] in {"completed", "excluded", "rejected", "error"}
        if r["status"] == "rejected":
            assert r["rejection"]["gate"] and not r.get("files")
        if r["status"] == "completed":
            assert r["files"] and r["tier"] == "analytic_verification"
        if r["status"] == "error":
            pytest.fail(r["error"])


FORBIDDEN = (
    "analytic_verification|restricted_benchmark|production_candidate|ground_truth|fault_truth|"
    "validity|scenario|stratum|coastal|inland|train|validation|leak|misrout|degrad|stuck|drift|bias"
)


@pytest.mark.slow
def test_campaign_episodes_pass_the_leakage_rules(real_campaign: Path) -> None:
    """Over the completed episodes: only the closed schema's keys, the gateway allowlist, no hidden
    word, an opaque identifier, and the agent folder holds observations only.

    Independent: yes, because the checks scan the written files.
    """
    import re

    layout = runner.Layout(real_campaign)
    keys = set(load_schema("observation")["properties"])
    pattern = re.compile(FORBIDDEN, re.IGNORECASE)
    done = [
        r for r in runner.load_records(layout, list(range(REAL.n))) if r["status"] == "completed"
    ]
    assert done
    for r in done:
        folder = layout.agent / "episodes" / r["episode_id"]
        assert [p.name for p in folder.iterdir()] == [runner.OBSERVATIONS]  # LK-02
        rows = runner.read_observations(folder / runner.OBSERVATIONS)
        assert all(set(row) == keys for row in rows)  # LK-01
        text = "\n".join(json.dumps(row, sort_keys=True) for row in rows[::41])
        assert not pattern.search(text.replace("episode_id", "").replace("EP-", ""))
        payload = Gateway(folder).query(3600.0)
        check_allowlist(payload)  # LK-07
        assert re.fullmatch(r"EP-[0-9A-F]{12}", r["episode_id"])  # LK-12


@pytest.mark.slow
def test_dropout_and_quality_rates_equal_those_of_the_healthy_episode_of_the_same_seed(
    real_campaign: Path, tmp_path: Path
) -> None:
    """For four faulted episodes the same scenario without the faults has the same dropout pattern
    and the same counts of quality flags and availability states on the continuous tags.

    Independent: yes, because the comparison is between two separate runs of the engine.
    """
    layout = runner.Layout(real_campaign)
    done = [
        r
        for r in runner.load_records(layout, list(range(REAL.n)))
        if r["status"] == "completed" and r["faults"]
    ][:4]
    assert done
    model = HydraulicModel.load()
    for r in done:
        raw = json.loads(
            (layout.evaluator / "episodes" / r["episode_id"] / "scenario.json").read_text()
        )
        twin = run_episode(raw["scenario_id"], tmp_path, model, parse_scenario(raw), FaultSet(()))
        both = [
            runner.read_observations(
                layout.agent / "episodes" / r["episode_id"] / runner.OBSERVATIONS
            ),
            runner.read_observations(twin.directory / runner.OBSERVATIONS),
        ]
        # A valve fault adds contact rows (events), which are a consequence of the fault, not of
        # the dropout; the continuous tags are compared.
        a, b = ([x for x in rows if x["unit"] != "bool"] for rows in both)
        assert [(x["tag_id"], x["t_sim_s"], x["value"] is None) for x in a] == [
            (x["tag_id"], x["t_sim_s"], x["value"] is None) for x in b
        ]
        assert Counter(x["quality_flag"] for x in a) == Counter(x["quality_flag"] for x in b)
        assert Counter(x["availability_status"] for x in a) == Counter(
            x["availability_status"] for x in b
        )


@pytest.mark.slow
def test_one_and_three_workers_give_the_same_real_episodes(
    real_campaign: Path, tmp_path: Path
) -> None:
    """Four real episodes run on one worker have the manifest records and file hashes of the same
    episodes run on three.

    Independent: yes, because the reference is a separate run with another worker count.
    """
    indices = selected_indices(REAL, 20)[:4]
    runner.run_campaign(REAL, tmp_path, workers=1, indices=indices)
    mine = runner.load_records(runner.Layout(tmp_path), indices)
    theirs = runner.load_records(runner.Layout(real_campaign), indices)
    assert without_time(mine) == without_time(theirs)
