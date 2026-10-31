"""Running a campaign: episodes, storage, resume and the manifest.

Each episode is a function of the campaign seed and its index. It is simulated in a scratch folder,
and its agent-visible observations, its hidden labels and, for an audit subset, its full truth are
stored; a record of the episode is written last, so an interrupted run resumes at the episode level.
The manifest is built from the records in index order, so it does not depend on the number of
workers or on the order in which episodes finish.

See D83, D87 and D88.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from verum.campaign.classes import ClassTable
from verum.campaign.eligibility import model_and_table
from verum.campaign.plan import CampaignConfig, Shares, Slot, build_plan
from verum.campaign.sampler import EpisodeSpec, Sampler
from verum.campaign.splits import SplitPlan, build_split_plan, split_of
from verum.contracts.errors import ContractError
from verum.contracts.paths import repo_root
from verum.faults import FaultSet
from verum.provenance import config_hash, git_state
from verum.sim.episode import EpisodeResult, run_episode
from verum.sim.scenario import parse_scenario

MIN_FREE_GB = 20.0
MAX_WORKERS = 6
OBSERVATIONS = "observations.jsonl.gz"
PAIR_SEPARATION_S = 300.0
CONFIG_FILE = "campaign_config.json"
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
    return Context(build_plan(config), Sampler(config, ClassTable()), build_split_plan(config))


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


def simulate(config: CampaignConfig, index: int, work: Path) -> tuple[EpisodeSpec, EpisodeResult]:
    """Sample episode ``index`` and run it in ``work``."""
    ctx = context(config)
    spec = ctx.sampler.sample(ctx.plan[index])
    scenario = parse_scenario(spec.scenario)
    faults = FaultSet(tuple(f.spec for f in spec.faults)) if spec.faults else None
    model, _ = model_and_table()
    result = run_episode(
        scenario.scenario_id, work, model, scenario, faults,
        max_faults=2, min_separation_s=PAIR_SEPARATION_S,
    )  # fmt: skip
    return spec, result


def base_record(config: CampaignConfig, spec: EpisodeSpec) -> dict[str, Any]:
    ctx = context(config)
    pairs = [(f.subtype, f.asset) for f in spec.faults]
    return {
        "index": spec.index, "seed": spec.seed, "scenario_id": spec.scenario["scenario_id"],
        "kind": spec.slot.kind, "pair_type": spec.slot.pair_type, "latent": spec.slot.latent,
        "strata": spec.strata, "audit": spec.slot.audit, "gaps": spec.gaps,
        "split": split_of(ctx.splits, unit_of(spec.strata), pairs),
        "subtypes": [f.subtype for f in spec.faults],
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
    keep = ["observation_audit.jsonl.gz", "fault_truth.jsonl.gz"]
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


def execute_episode(config: CampaignConfig, index: int, root: Path) -> dict[str, Any]:
    """Simulate and store one episode; return its record (written by the caller)."""
    layout = Layout(root)
    work = layout.work / f"{index:06d}"
    shutil.rmtree(work, ignore_errors=True)
    start = time.perf_counter()
    ctx = context(config)
    spec = ctx.sampler.sample(ctx.plan[index])
    record = base_record(config, spec)
    try:
        spec, result = simulate(config, index, work)
        record["episode_id"] = result.episode_id
        if result.rejected:
            record |= {
                "status": "rejected",
                "rejection": result.outcome.rejection,
                "faults": [
                    {k: v for k, v in lab.items() if k != "instance_id"}
                    for lab in fault_labels(spec, result.episode_id, {})
                ],
            }
        elif result.outcome.windows:
            kinds = sorted({w.kind for w in result.outcome.windows})
            record |= {"status": "excluded", "reason": "validity_window", "windows": kinds}
        else:
            episode_doc = json.loads(
                (result.directory / "episode.json").read_text(encoding="utf-8")
            )
            labels = fault_labels(spec, result.episode_id, episode_doc)
            meta = {
                k: record[k] for k in ("index", "kind", "pair_type", "split", "strata", "latent")
            }
            files = store_files(
                layout,
                spec,
                result,
                {
                    "episode_id": result.episode_id,
                    "faults": labels,
                    **meta,
                    "tier": episode_doc["dataset_tier"],
                },
            )
            record |= {
                "status": "completed",
                "tier": episode_doc["dataset_tier"],
                "faults": labels,
                "files": files,
            }
    except ContractError as exc:
        record |= {"status": "rejected", "rejection": {"gate": "SPEC", "parameter": str(exc)}}
    except Exception as exc:  # noqa: BLE001  (a solver failure outside the gates is recorded, not fatal)
        record |= {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    record["wall_s"] = time.perf_counter() - start
    return record


def load_config(root: Path) -> CampaignConfig:
    """The configuration a campaign was run with, as stored at its root."""
    raw = json.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
    return CampaignConfig(**{**raw, "shares": Shares(**raw["shares"])})


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


def run_campaign(
    config: CampaignConfig,
    root: Path,
    workers: int | None = None,
    executor: Executor = execute_episode,
    indices: list[int] | None = None,
) -> dict[str, Any]:
    """Run the pending episodes, then write the manifest, labels and accounting."""
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
        results = (_call(j) for j in jobs)
        done = _log(layout, results, len(jobs), start)
    else:
        with Pool(n) as pool:
            done = _log(layout, pool.imap_unordered(_call, jobs, chunksize=1), len(jobs), start)
    elapsed = time.perf_counter() - start
    manifest = finalize(config, root, indices=wanted)
    (layout.evaluator / "accounting.json").write_text(
        json.dumps(
            {"workers": n, "episodes_run": done, "elapsed_s": elapsed, **accounting(layout, wanted)}
        ),
        encoding="utf-8",
    )
    return manifest


def _log(layout: Layout, results: Any, total: int, start: float) -> int:
    done = 0
    for _ in results:
        done += 1
        if done % 10 == 0 or done == total:
            line = f"{done}/{total} episodes, {time.perf_counter() - start:.0f} s\n"
            with (layout.root / "progress.log").open("a", encoding="utf-8") as fh:
                fh.write(line)
    return done


def load_records(layout: Layout, indices: list[int]) -> list[dict[str, Any]]:
    out = []
    for i in sorted(indices):
        path = layout.records / f"{i:06d}.json"
        if path.exists():
            out.append(json.loads(path.read_text(encoding="utf-8")))
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
        "held_out_assets": ctx.splits.held_assets,
        "gaps": class_gaps() + branch_gap(config), "episodes": records,
    }  # fmt: skip
    layout.evaluator.mkdir(parents=True, exist_ok=True)
    (layout.evaluator / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    write_label_files(layout, records)
    write_readme(layout)
    return manifest


def branch_gap(config: CampaignConfig) -> list[dict[str, Any]]:
    """Misrouting (b) is left out unless the campaign accepts a branched lineup (D83, D75)."""
    if config.parallel_branch:
        return []
    return [{
        "subtype": "misroute_b",
        "reason": "the only eligible lineup, a receipt into two tanks, carries a validity window",
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


def _label_row(r: dict[str, Any]) -> dict[str, Any]:
    faults = [{k: v for k, v in f.items()} for f in r["faults"]]
    return {
        "episode_id": r["episode_id"],
        "split": r["split"],
        "healthy": not faults,
        "faults": faults,
    }


def write_label_files(layout: Layout, records: list[dict[str, Any]]) -> None:
    """Labels of train and validation for the agents; labels of test for the evaluator only."""
    done = [r for r in records if r["status"] == "completed"]
    visible = [r for r in done if r["split"] in ("train", "validation")]
    layout.agent.mkdir(parents=True, exist_ok=True)
    with (layout.agent / "labels_train_validation.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(_label_row(r), sort_keys=True) + "\n" for r in visible)
    test = [r for r in done if r["split"] == "test"]
    with (layout.evaluator / "labels_test.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(_label_row(r), sort_keys=True) + "\n" for r in test)


def write_readme(layout: Layout) -> None:
    """Copy the description of the agent-visible folder next to the episodes."""
    source = repo_root() / "docs" / "campaign_agent_readme.md"
    (layout.agent / "README.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def regenerate(config: CampaignConfig, record: dict[str, Any], scratch: Path) -> str:
    """Rebuild the observations of a stored episode from its seed; return their hash."""
    work = scratch / f"{record['index']:06d}"
    shutil.rmtree(work, ignore_errors=True)
    try:
        _spec, result = simulate(config, record["index"], work)
        return sha256(result.directory / OBSERVATIONS)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def read_observations(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _regenerate_one(args: tuple[CampaignConfig, dict[str, Any], Path]) -> tuple[str, bool]:
    config, record, scratch = args
    key = f"agent_visible/episodes/{record['episode_id']}/{OBSERVATIONS}"
    return record["episode_id"], record["files"][key] == regenerate(config, record, scratch)


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
