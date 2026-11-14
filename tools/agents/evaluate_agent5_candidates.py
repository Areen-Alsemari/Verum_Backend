"""Build the chained Agent 5 requests of the validation split and score them in variants.

Phase collect runs every validation episode through the runner in window order as one run (valid
windows only, a skipped position padded with an empty entry), with the installed agents for roles
1 to 4 and 7 and placeholders after the diagnosis, and stores each Agent 5 request with its label.
Phase score runs the Agent 5 found on the import path on the stored requests: mode prev gives the
previous and the absent-assessment outputs, mode new adds the shuffled-assessment controls. The
release folder is opened only under the audit hook of the detector experiments.
See reports/agent5_candidates_results.md for the commands.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import random
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Any

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_name] = "1"  # one thread per worker process
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

import guard  # noqa: E402
import run_runner_sample as sample_tools  # noqa: E402

SEED, SHUFFLES, WORKERS = 20261108, 5, 10
LATER_ROLES = ("diagnostic_reasoning", "inspection_planning", "evidence_verification_decision")
STATE: dict[str, Any] = {}


def read_json(path: Path) -> Any:
    """A gzipped JSON file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    """Write a gzipped JSON file."""
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(value, f)


def init_collect(release: str) -> None:
    """Install the audit hook and load the reference once per worker."""
    guard.install()
    from verum.agents.common import file_sha256

    path = Path(release) / "knowledge" / "public_reference.json"
    STATE["reference"] = json.loads(path.read_text(encoding="utf-8"))
    STATE["sha"] = file_sha256(path)


def collect_episode(job: tuple[int, list[dict[str, Any]], dict[str, Any], str]) -> int:
    """Run one episode as one chained run and store the Agent 5 request of each window."""
    from verum.agents.common import StubAgent
    from verum.agents.runner import AssessmentLog, run_analysis

    e, windows, summaries, out = job
    case_id = f"E{e:04d}"
    log, last = AssessmentLog(), None
    for w in windows:
        log = sample_tools.pad_gap(log, case_id, last, w["position"])
        snap = sample_tools.make_snapshot(
            case_id, w, summaries[w["window_id"]], STATE["reference"], STATE["sha"]
        )
        agents = {role: StubAgent(role) for role in LATER_ROLES}
        bundle = run_analysis(snap, "runtime", agents=agents, recent=log)
        log, last = bundle.assessments, w["position"]
        request = bundle.requests["diagnostic_reasoning"]
        write_json(Path(out) / f"{w['window_id']}.json.gz", {"window": w, "request": request})
    return len(windows)


def episodes_of(release: Path) -> list[tuple[str, list[dict[str, Any]], dict[str, Any]]]:
    """Valid validation windows grouped by episode in position order, with their summaries."""
    records, lineage = sample_tools.load_split(release, "validation")
    episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    summaries: dict[str, Any] = {}
    for r in records:
        if not r.target["supervised_loss_mask"]:
            continue
        row = sample_tools.window_row(r, lineage, "validation")
        row["components"] = [
            {"mechanism": c["mechanism"], "asset_id": c.get("asset_id")}
            for c in (r.target["injected_components"] or [])
        ]
        episodes[row["episode_id"]].append(row)
        summaries[r.example_id] = r.input["observations"]
    out = []
    for ep, ws in sorted(episodes.items()):
        ws.sort(key=lambda x: x["position"])
        out.append((ep, ws, {w["window_id"]: summaries[w["window_id"]] for w in ws}))
    return out


def collect(release: Path, cache: Path) -> None:
    """Phase collect."""
    cache.mkdir(parents=True, exist_ok=True)
    jobs = [(e, ws, sm, str(cache)) for e, (_, ws, sm) in enumerate(episodes_of(release))]
    print("episodes", len(jobs), "windows", sum(len(j[1]) for j in jobs), flush=True)
    with Pool(WORKERS, initializer=init_collect, initargs=(str(release),)) as pool:
        done = sum(pool.imap_unordered(collect_episode, jobs))
    print("collected", done, flush=True)


def rehash(request: dict[str, Any]) -> dict[str, Any]:
    """Refresh the registry hash of the anomaly report after it was changed."""
    from verum.agents.common import stable_hash

    report = request["input"]["anomaly_report"]
    if report is not None:
        for row in request["evidence"]:
            if row["evidence_id"] == report["report_id"]:
                row["content_sha256"] = stable_hash(report)
    return request


def stripped(request: dict[str, Any]) -> dict[str, Any]:
    """A copy of a request whose anomaly report has no window assessment."""
    changed = copy.deepcopy(request)
    report = changed["input"]["anomaly_report"]
    if report is not None and report.get("result") is not None:
        report["result"].pop("window_assessment", None)
    return rehash(changed)


def borrowed(request: dict[str, Any], donor: dict[str, Any]) -> dict[str, Any]:
    """A copy with the anomaly result and the persistence statement of another window.

    The donor's recent assessments are not taken: the contract refuses recent assessments that
    are later than the request cutoff, and Agent 5 does not read them.
    """
    changed = copy.deepcopy(request)
    mine, theirs = changed["input"]["anomaly_report"], donor["input"]["anomaly_report"]
    if mine is not None and mine.get("result") is not None:
        mine["result"] = copy.deepcopy((theirs or {}).get("result") or mine["result"])
        if theirs is None or theirs.get("result") is None:
            mine["result"].pop("window_assessment", None)
    if "persistence" in donor["input"]:
        changed["input"]["persistence"] = copy.deepcopy(donor["input"]["persistence"])
    return rehash(changed)


def digest(response: dict[str, Any]) -> str:
    """Hash of a whole response."""
    return hashlib.sha256(json.dumps(response, sort_keys=True).encode()).hexdigest()


def summary_of(response: dict[str, Any]) -> dict[str, Any]:
    """Status, hashes with and without the implementation version, and the hypotheses."""
    unversioned = copy.deepcopy(response)
    unversioned["implementation"].pop("version", None)
    result = response.get("result")
    hyps = []
    for h in [] if result is None else result["hypotheses"]:
        c = h["components"][0]
        hyps.append({
            "id": h["hypothesis_id"], "mechanism": c["mechanism"], "asset": c["asset_id"],
            "tag": c["tag_id"], "score": None if h["score"] is None else h["score"]["value"],
        })  # fmt: skip
    return {
        "status": response["status"], "digest": digest(response),
        "digest_unversioned": digest(unversioned), "version": response["implementation"]["version"],
        "hyps": hyps, "ranking": (result or {}).get("ranking_basis"),
    }  # fmt: skip


def init_score(cache: str, mode: str) -> None:
    """Install the audit hook and load Agent 5 once per worker."""
    guard.install()
    from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent

    STATE.update(cache=Path(cache), mode=mode, agent=DiagnosticReasoningAgent())


def run(request: dict[str, Any]) -> dict[str, Any]:
    """Agent 5 on one request."""
    return summary_of(STATE["agent"].run(request))


def score_one(job: tuple[str, dict[str, str]]) -> tuple[str, dict[str, Any]]:
    """Every variant of one window; the classifier runs once and is reused."""
    wid, donors = job
    stored = read_json(STATE["cache"] / f"{wid}.json.gz")
    request = stored["request"]
    model = STATE["agent"]._model
    first, memo = model.predict_candidates, {}
    model.predict_candidates = lambda obs: memo.setdefault("p", first(obs))
    out: dict[str, Any] = {}
    if STATE["mode"] == "prev":
        out["prev"], out["prev_absent"] = run(request), run(stripped(request))
    else:
        out["new"], out["absent"] = run(request), run(stripped(request))
        for name, donor in donors.items():
            other = read_json(STATE["cache"] / f"{donor}.json.gz")["request"]
            out[name] = run(borrowed(request, other))
    model.predict_candidates = first
    return wid, {"window": stored["window"], "variants": out}


def shuffle_plan(ids: list[str]) -> dict[str, dict[str, str]]:
    """For each window and each seeded shuffle, the window whose assessment it borrows."""
    plan: dict[str, dict[str, str]] = {i: {} for i in ids}
    for s in range(SHUFFLES):
        order = list(ids)
        random.Random(SEED + s).shuffle(order)
        for wid, donor in zip(ids, order, strict=True):
            plan[wid][f"shuffle{s}"] = donor
    return plan


def score(mode: str, cache: Path, out: Path) -> None:
    """Phase score."""
    import verum

    print("verum:", verum.__file__, flush=True)
    ids = sorted(p.name.removesuffix(".json.gz") for p in cache.glob("*.json.gz"))
    results: dict[str, Any] = {}
    with Pool(WORKERS, initializer=init_score, initargs=(str(cache), mode)) as pool:
        for wid, value in pool.imap_unordered(score_one, shuffle_plan(ids).items(), 4):
            results[wid] = value
    write_json(out, results)
    print("scored", len(results), flush=True)


def main() -> None:
    """Command line: collect the requests, or score them with the Agent 5 on the import path."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("phase", choices=("collect", "score"))
    parser.add_argument("--cache", type=Path, required=True, help="folder of stored requests")
    parser.add_argument("--mode", choices=("prev", "new"), help="score: which variants")
    parser.add_argument("--out", type=Path, help="score: result file")
    parser.add_argument("--release", type=Path, default=sample_tools.DEFAULT_RELEASE)
    args = parser.parse_args()
    guard.install()
    if args.phase == "collect":
        collect(args.release, args.cache)
    else:
        score(args.mode, args.cache, args.out)
    print("guard:", guard.summary(), flush=True)


if __name__ == "__main__":
    main()
