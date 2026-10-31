"""Running a campaign: slots, attempts, storage, resume and the manifest.

A slot is run by one worker. Its attempts are simulated in turn in a scratch folder until one is
completed or five in a row have failed, and the observations, the hidden labels and, for an audit
subset, the full truth of the completed attempt are stored. A record of the slot, with the outcome
of every attempt, is written last, so an interrupted run resumes at the slot level. The manifest
is built from the records in slot order, so it does not depend on the number of workers or on the
order in which slots finish.

See D83, D87, D88, D151 and D152.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import shutil
import signal
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any

from verum.campaign import switch
from verum.campaign.classes import ClassTable
from verum.campaign.eligibility import model_and_table
from verum.campaign.plan import EPISODE_STRIDE, Block, CampaignConfig, Slot, build_plan
from verum.campaign.sampler import EpisodeSpec, NoCandidate, Sampler
from verum.campaign.splits import REFERENCE_SLOTS, SplitPlan, build_split_plan, split_of
from verum.contracts.errors import ContractError
from verum.contracts.paths import repo_root
from verum.faults import FaultSet
from verum.provenance import config_hash, git_state
from verum.sim.episode import EpisodeResult, run_episode
from verum.sim.scenario import parse_scenario

MIN_FREE_GB = 20.0
MAX_WORKERS = 6
OBSERVATIONS = "observations.jsonl.gz"
INSPECTION = "inspection_truth.jsonl.gz"
PAIR_SEPARATION_S = 300.0
CONFIG_FILE = "campaign_config.json"
PROGRESS_FILE = "progress.json"
PROGRESS_EVERY = 20
MAX_ATTEMPTS = EPISODE_STRIDE
Executor = Callable[[CampaignConfig, int, Path], dict[str, Any]]


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def agent(self) -> Path:
        return self.root / "agent_visible"

    @property
    def evaluator(self) -> Path:
        return self.root / "evaluator"

    @property
    def records(self) -> Path:
        return self.evaluator / "records"

    @property
    def work(self) -> Path:
        return self.root / "work"


def worker_count(requested: int | None = None) -> int:
    """At most the cores minus two, and never more than six."""
    limit = max(1, min(MAX_WORKERS, (os.cpu_count() or 1) - 2))
    return limit if requested is None else max(1, min(requested, limit))


def check_disk(root: Path, minimum_gb: float = MIN_FREE_GB) -> float:
    """Free space in GB at ``root``; raises if it is below the minimum."""
    probe = root if root.exists() else root.parent
    free = shutil.disk_usage(probe).free / 1e9
    if free < minimum_gb:
        raise RuntimeError(f"{free:.1f} GB free at {probe}, less than the {minimum_gb:g} GB needed")
    return free


def sha256(path: Path) -> str:
    """Hash of the content of a file; a gzip file is hashed after decompression, because the
    compressed bytes carry the time at which they were written."""
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return hashlib.sha256(data).hexdigest()


@dataclass
class Context:
    plan: list[Slot]
    sampler: Sampler
    splits: SplitPlan


@lru_cache(maxsize=4)
def context(config: CampaignConfig) -> Context:
    sampler = Sampler(config, ClassTable())
    reference = [sampler.cell(s) for s in build_plan(replace(config, n=REFERENCE_SLOTS))]
    return Context(build_plan(config), sampler, build_split_plan(config, reference))


def unit_of(strata: dict[str, Any]) -> tuple[str, str, float]:
    return (strata["family"], strata["atmosphere"], strata["temperature_c"])


def fault_labels(spec: EpisodeSpec, episode: str, notes: dict[str, Any]) -> list[dict[str, Any]]:
    """The label of each fault: type, asset, severity, class, onset, mode and activity."""
    labels = []
    for i, f in enumerate(spec.faults):
        mode = notes.get("fault_modes", [None] * len(spec.faults))[i]
        activity = notes.get("fault_activity", ["active"] * len(spec.faults))[i]
        labels.append({
            "instance_id": f"FI-{episode}-{i:02d}", "fault_type": f.spec.fault_type,
            "subtype": f.subtype, "asset_id": f.asset, "severity": f.severity, "class": f.cls,
            "onset_s": f.spec.onset_s, "ramp_s": f.spec.ramp_s, "magnitude": f.spec.magnitude,
            "mode": mode, "activity": activity,
        })  # fmt: skip
    return labels


def simulate(
    config: CampaignConfig, slot_index: int, attempt: int, work: Path
) -> tuple[EpisodeSpec, EpisodeResult]:
    """Sample attempt ``attempt`` of a slot and run it in ``work``."""
    ctx = context(config)
    spec = ctx.sampler.sample(ctx.plan[slot_index], attempt)
    scenario = parse_scenario(spec.scenario)
    faults = FaultSet(tuple(f.spec for f in spec.faults)) if spec.faults else None
    model, _ = model_and_table()
    result = run_episode(
        scenario.scenario_id, work, model, scenario, faults,
        max_faults=2, min_separation_s=PAIR_SEPARATION_S,
    )  # fmt: skip
    return spec, result


def slot_record(config: CampaignConfig, slot: Slot) -> dict[str, Any]:
    """The fields of a record that follow from the plan and the cell alone."""
    cell = context(config).sampler.cell(slot)
    return {
        "index": slot.index, "kind": slot.kind, "pair_type": slot.pair_type,
        "branch": slot.branch, "latent": slot.latent, "switch": slot.switch,
        "stress": slot.stress, "audit": slot.audit, "cell": cell.key,
        "unit": list(cell.unit), "subtypes": list(cell.subtypes), "classes": list(cell.classes),
    }  # fmt: skip


def write_record(layout: Layout, record: dict[str, Any]) -> None:
    layout.records.mkdir(parents=True, exist_ok=True)
    path = layout.records / f"{record['index']:06d}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def store_files(
    layout: Layout, spec: EpisodeSpec, result: EpisodeResult, labels: dict[str, Any]
) -> dict[str, str]:
    """Move the files of a completed episode to the agent and evaluator stores; return hashes."""
    episode = result.episode_id
    agent = layout.agent / "episodes" / episode
    evaluator = layout.evaluator / "episodes" / episode
    for folder in (agent, evaluator):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    shutil.copy2(result.directory / OBSERVATIONS, agent / OBSERVATIONS)
    (evaluator / "labels.json").write_text(json.dumps(labels, sort_keys=True), encoding="utf-8")
    (evaluator / "scenario.json").write_text(
        json.dumps(spec.scenario, sort_keys=True), encoding="utf-8"
    )
    keep = [
        "observation_audit.jsonl.gz",
        "fault_truth.jsonl.gz",
        "validity_windows.jsonl.gz",
        INSPECTION,
    ]
    for name in keep:
        if (result.directory / name).exists():
            shutil.copy2(result.directory / name, evaluator / name)
    if spec.slot.audit:
        truth = evaluator / "truth"
        truth.mkdir()
        for path in sorted(result.directory.iterdir()):
            if path.name not in {OBSERVATIONS, "provenance.json", *keep} and path.is_file():
                shutil.copy2(path, truth / path.name)
    root = layout.root
    return {
        str(p.relative_to(root)): sha256(p)
        for f in (agent, evaluator)
        for p in sorted(f.rglob("*"))
        if p.is_file()
    }


def restricting_kinds(result: EpisodeResult) -> list[str]:
    """Kinds of the windows that take an episode out of the main tier (D150)."""
    return sorted({w.kind for w in result.outcome.windows if w.restricts})


def run_attempt(
    config: CampaignConfig, slot: Slot, attempt: int, layout: Layout
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """One attempt of a slot: its summary, and the completed episode's fields if it completed."""
    summary: dict[str, Any] = {
        "attempt": attempt,
        "episode_index": slot.index * MAX_ATTEMPTS + attempt,
    }
    work = layout.work / f"{slot.index:06d}_{attempt}"
    shutil.rmtree(work, ignore_errors=True)
    try:
        spec, result = simulate(config, slot.index, attempt, work)
        summary["seed"] = spec.seed
        if result.rejected:
            gate = (result.outcome.rejection or {}).get("gate")
            return summary | {"status": "rejected", "gate": gate}, None
        kinds = restricting_kinds(result)
        if kinds and slot.kind != "branched":
            return summary | {
                "status": "excluded",
                "reason": "validity_window",
                "windows": kinds,
            }, None
        return summary | {"status": "completed"}, completed_fields(config, spec, result, layout)
    except NoCandidate as exc:
        return summary | {"status": "rejected", "gate": "SAMPLING", "detail": str(exc)}, None
    except ContractError as exc:
        return summary | {"status": "rejected", "gate": "SPEC", "detail": str(exc)}, None
    except Exception as exc:  # noqa: BLE001  (a solver failure outside the gates is recorded, not fatal)
        return summary | {"status": "error", "error": f"{type(exc).__name__}: {exc}"}, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def completed_fields(
    config: CampaignConfig, spec: EpisodeSpec, result: EpisodeResult, layout: Layout
) -> dict[str, Any]:
    """Store the files of a completed attempt and return the fields of its slot record."""
    ctx = context(config)
    doc = json.loads((result.directory / "episode.json").read_text(encoding="utf-8"))
    faults = fault_labels(spec, result.episode_id, doc)
    pairs = [(f.subtype, f.asset) for f in spec.faults]
    split = split_of(ctx.splits, unit_of(spec.strata), pairs)
    labels = {
        "episode_id": result.episode_id, "faults": faults, "index": spec.slot.index,
        "kind": spec.slot.kind, "pair_type": spec.slot.pair_type, "branch": spec.slot.branch,
        "split": split, "strata": spec.strata, "latent": spec.slot.latent,
        "cell": spec.cell.key, "tier": doc["dataset_tier"],
    }  # fmt: skip
    files = store_files(layout, spec, result, labels)
    return {
        "episode_id": result.episode_id, "seed": spec.seed, "attempt": spec.attempt,
        "strata": spec.strata, "split": split, "tier": doc["dataset_tier"], "faults": faults,
        "files": files, "gaps": spec.gaps, "subtypes": [f.subtype for f in spec.faults],
    }  # fmt: skip


def execute_slot(config: CampaignConfig, index: int, root: Path) -> dict[str, Any]:
    """Run the attempts of one slot and return its record (written by the caller)."""
    layout = Layout(root)
    start = time.perf_counter()
    slot = context(config).plan[index]
    record = slot_record(config, slot)
    attempts: list[dict[str, Any]] = []
    done: dict[str, Any] | None = None
    for attempt in range(MAX_ATTEMPTS):
        summary, done = run_attempt(config, slot, attempt, layout)
        attempts.append(summary)
        if done is not None:
            break
    record["attempts"] = attempts
    record["status"] = "completed" if done is not None else "gap"
    if done is not None:
        record |= done
    record["wall_s"] = time.perf_counter() - start
    return record


def load_config(root: Path) -> CampaignConfig:
    """The configuration a campaign was run with, as stored at its root."""
    raw = json.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
    return CampaignConfig(**{**raw, "block": Block(**raw["block"])})


def record_valid(layout: Layout, index: int) -> bool:
    """A record exists and every file it lists is present with the stored hash."""
    path = layout.records / f"{index:06d}.json"
    if not path.exists():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return all(
        (layout.root / rel).is_file() and sha256(layout.root / rel) == digest
        for rel, digest in record.get("files", {}).items()
    )


def _call(args: tuple[Executor, CampaignConfig, int, Path]) -> dict[str, Any]:
    executor, config, index, root = args
    record = executor(config, index, root)
    write_record(Layout(root), record)
    return record


def _ignore_interrupt() -> None:
    """Workers leave the interrupt to the parent, which stops submitting and lets slots finish."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _stream(
    pool: Any, jobs: Iterable[Any], depth: int, stop: Callable[[], bool]
) -> Iterator[dict[str, Any]]:
    """Results in the order they finish, with at most ``depth`` slots submitted at a time; no new
    slot is submitted once ``stop`` is true, and the slots in flight are finished."""
    source = iter(jobs)
    inflight: list[AsyncResult[dict[str, Any]]] = []
    exhausted = False
    while inflight or not exhausted:
        while not exhausted and len(inflight) < depth:
            job = None if stop() else next(source, None)
            if job is None:
                exhausted = True
                break
            inflight.append(pool.apply_async(_call, (job,)))
        ready = [r for r in inflight if r.ready()]
        for r in ready:
            inflight.remove(r)
            yield r.get()
        if not ready:
            time.sleep(0.2)


def run_campaign(
    config: CampaignConfig,
    root: Path,
    workers: int | None = None,
    executor: Executor = execute_slot,
    indices: list[int] | None = None,
    stop: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Run the pending slots, then write the manifest, labels and accounting."""
    check_disk(root)
    layout = Layout(root)
    layout.records.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_FILE).write_text(json.dumps(asdict(config), sort_keys=True), encoding="utf-8")
    wanted = list(range(config.n)) if indices is None else indices
    pending = [i for i in wanted if not record_valid(layout, i)]
    n = worker_count(workers)
    start = time.perf_counter()
    jobs = [(executor, config, i, root) for i in pending]
    if n == 1 or len(jobs) <= 1:
        results: Iterator[dict[str, Any]] = iter(_serial(jobs, stop))
        done = _log(layout, results, config, wanted, start)
    else:
        with Pool(n, initializer=_ignore_interrupt) as pool:
            done = _log(layout, _stream(pool, jobs, 2 * n, stop), config, wanted, start)
    elapsed = time.perf_counter() - start
    manifest = finalize(config, root, indices=wanted)
    (layout.evaluator / "accounting.json").write_text(
        json.dumps(
            {"workers": n, "slots_run": done, "elapsed_s": elapsed, **accounting(layout, wanted)}
        ),
        encoding="utf-8",
    )
    return manifest


def _serial(jobs: list[Any], stop: Callable[[], bool]) -> Iterator[dict[str, Any]]:
    for job in jobs:
        if stop():
            return
        yield _call(job)


def progress(
    layout: Layout, config: CampaignConfig, wanted: list[int], start: float
) -> dict[str, Any]:
    """Counts of the finished slots and an estimate of the time left, from this run's rate."""
    records = load_records(layout, wanted)
    status = Counter(r["status"] for r in records)
    attempts = sum(len(r["attempts"]) for r in records)
    elapsed = time.perf_counter() - start
    return {
        "target_slots": len(wanted), "slots_finished": len(records),
        "completed": status["completed"], "gaps": status["gap"], "attempts": attempts,
        "elapsed_s": elapsed, "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }  # fmt: skip


def _log(
    layout: Layout,
    results: Iterator[dict[str, Any]],
    config: CampaignConfig,
    wanted: list[int],
    start: float,
) -> int:
    """Count the finished slots and write the progress file every ``PROGRESS_EVERY`` slots."""
    done = 0
    already = len(load_records(layout, wanted))
    for _ in results:
        done += 1
        if done % PROGRESS_EVERY == 0:
            write_progress(layout, config, wanted, start, done, already)
    write_progress(layout, config, wanted, start, done, already)
    return done


def write_progress(
    layout: Layout, config: CampaignConfig, wanted: list[int], start: float, done: int, already: int
) -> None:
    """Write the progress file: finished, attempts, rate of this run and the time left."""
    info = progress(layout, config, wanted, start)
    elapsed = info["elapsed_s"]
    rate = done / elapsed * 3600.0 if elapsed > 0 and done else 0.0
    left = len(wanted) - info["slots_finished"]
    info |= {
        "slots_this_run": done, "slots_before_run": already, "rate_slots_per_hour": rate,
        "estimated_remaining_s": left / rate * 3600.0 if rate else None,
    }  # fmt: skip
    path = layout.root / PROGRESS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    with (layout.root / "progress.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{info['updated']} {info['slots_finished']}/{len(wanted)} slots\n")


def load_records(layout: Layout, indices: list[int]) -> list[dict[str, Any]]:
    out = []
    for i in sorted(indices):
        path = layout.records / f"{i:06d}.json"
        if path.exists():
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue  # a torn record is run again
    return out


def accounting(layout: Layout, indices: list[int]) -> dict[str, Any]:
    records = load_records(layout, indices)
    sizes = {"agent_visible": 0, "evaluator": 0}
    for r in records:
        for rel in r.get("files", {}):
            size = (layout.root / rel).stat().st_size if (layout.root / rel).exists() else 0
            sizes["agent_visible" if rel.startswith("agent_visible") else "evaluator"] += size
    walls = [r["wall_s"] for r in records if "wall_s" in r]
    return {
        "bytes": sizes, "mean_wall_s": sum(walls) / len(walls) if walls else 0.0,
        "records": len(records),
    }  # fmt: skip


def cell_table(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """For each cell: slots, completed, gaps, attempts, exclusions and rejections by reason."""
    table: dict[str, dict[str, Any]] = {}
    for r in records:
        row = table.setdefault(
            r["cell"],
            {"slots": 0, "completed": 0, "gaps": 0, "attempts": 0, "excluded": {}, "rejected": {},
             "errors": 0},
        )  # fmt: skip
        row["slots"] += 1
        row["completed" if r["status"] == "completed" else "gaps"] += 1
        for a in r["attempts"]:
            row["attempts"] += 1
            if a["status"] == "excluded":
                key = "+".join(a["windows"])
                row["excluded"][key] = row["excluded"].get(key, 0) + 1
            elif a["status"] == "rejected":
                row["rejected"][a["gate"]] = row["rejected"].get(a["gate"], 0) + 1
            elif a["status"] == "error":
                row["errors"] += 1
    return dict(sorted(table.items()))


def finalize(
    config: CampaignConfig, root: Path, indices: list[int] | None = None
) -> dict[str, Any]:
    """Write the manifest, the label files and the description from the records."""
    layout = Layout(root)
    wanted = list(range(config.n)) if indices is None else indices
    records = [{k: v for k, v in r.items() if k != "wall_s"} for r in load_records(layout, wanted)]
    ctx = context(config)
    model, _ = model_and_table()
    commit, _dirty = git_state()
    manifest = {
        "campaign_seed": config.seed, "target_n": config.n, "config": asdict(config),
        "config_hash": config_hash(model.directory), "code_commit": commit,
        "held_out_units": sorted(map(list, ctx.splits.test_units)),
        "validation_units": sorted(map(list, ctx.splits.validation_units)),
        "held_out_assets": ctx.splits.held_assets, "held_out_share": ctx.splits.held_share,
        "gaps": class_gaps() + switch_gaps(), "cells": cell_table(records), "episodes": records,
    }  # fmt: skip
    layout.evaluator.mkdir(parents=True, exist_ok=True)
    (layout.evaluator / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    write_label_files(layout, records)
    write_readme(layout)
    return manifest


def switch_gaps() -> list[dict[str, Any]]:
    """Switch combinations left out because their closing stroke keeps a collapse window (D153)."""
    return [{
        "subtype": "switch", "first_tank": switch.LIMITED_TANK,
        "setpoint_m3h": switch.STAGE_ONE_M3H,
        "reason": "the fall of the flow is shorter than the wave criterion of the receipt path "
        "and the set-point has no intermediate value",
    }]  # fmt: skip


def class_gaps() -> list[dict[str, Any]]:
    """Classes that the unresolved boundaries remove, by subtype and asset class."""
    from verum.campaign.plan import SUBTYPES

    table = ClassTable()
    out = []
    for subtype in SUBTYPES:
        for key in table.params:
            fault, aclass, _ = key.split("/")
            if fault == subtype and (g := table.gaps(subtype, aclass)):
                entry = {"subtype": subtype, "asset_class": aclass, "missing": g}
                if entry not in out:
                    out.append(entry)
    return out


def _label_row(r: dict[str, Any], evaluator: bool = False) -> dict[str, Any]:
    faults = [{k: v for k, v in f.items()} for f in r["faults"]]
    row = {
        "episode_id": r["episode_id"],
        "split": r["split"],
        "healthy": not faults,
        "faults": faults,
    }
    if evaluator:
        row |= {"family": r["strata"]["family"], "tier": r["tier"], "cell": r["cell"]}
    return row


def write_label_files(layout: Layout, records: list[dict[str, Any]]) -> None:
    """Labels of train and validation for the agents; labels of test for the evaluator only."""
    done = [r for r in records if r["status"] == "completed"]
    visible = [r for r in done if r["split"] in ("train", "validation")]
    layout.agent.mkdir(parents=True, exist_ok=True)
    with (layout.agent / "labels_train_validation.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(_label_row(r), sort_keys=True) + "\n" for r in visible)
    test = [r for r in done if r["split"] == "test"]
    with (layout.evaluator / "labels_test.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(_label_row(r, True), sort_keys=True) + "\n" for r in test)
    with (layout.evaluator / "labels_all.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(_label_row(r, True), sort_keys=True) + "\n" for r in done)


def write_readme(layout: Layout) -> None:
    """Copy the description of the agent-visible folder next to the episodes."""
    source = repo_root() / "docs" / "campaign_agent_readme.md"
    (layout.agent / "README.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def regenerate(config: CampaignConfig, record: dict[str, Any], scratch: Path) -> dict[str, str]:
    """Rebuild a stored episode from its seed; return the hash of its observations and of its
    inspection truth."""
    work = scratch / f"{record['index']:06d}"
    shutil.rmtree(work, ignore_errors=True)
    try:
        _spec, result = simulate(config, record["index"], record["attempt"], work)
        return {
            "agent_visible": sha256(result.directory / OBSERVATIONS),
            "evaluator": sha256(result.directory / INSPECTION),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def read_observations(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _regenerate_one(args: tuple[CampaignConfig, dict[str, Any], Path]) -> tuple[str, bool]:
    config, record, scratch = args
    episode = record["episode_id"]
    stored = {
        "agent_visible": record["files"][f"agent_visible/episodes/{episode}/{OBSERVATIONS}"],
        "evaluator": record["files"][f"evaluator/episodes/{episode}/{INSPECTION}"],
    }
    return episode, stored == regenerate(config, record, scratch)


def verify_sample(
    config: CampaignConfig, root: Path, count: int, workers: int | None = None
) -> list[tuple[str, bool]]:
    """Rebuild ``count`` completed episodes, chosen by the campaign seed, and compare the hashes."""
    layout = Layout(root)
    done = [r for r in load_records(layout, list(range(config.n))) if r["status"] == "completed"]
    chosen = random.Random(config.seed).sample(done, min(count, len(done)))
    jobs = [(config, r, layout.work) for r in chosen]
    n = worker_count(workers)
    if n == 1 or len(jobs) <= 1:
        return [_regenerate_one(j) for j in jobs]
    with Pool(n) as pool:
        return pool.map(_regenerate_one, jobs, chunksize=1)
