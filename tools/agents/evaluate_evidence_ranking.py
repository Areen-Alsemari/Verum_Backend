"""Build the Agent 5 requests of the validation split and score them with each Agent 5 variant.

Phase one (collect) runs the runner on every validation window with a valid label, with the
installed agents for roles 1 to 4 and 7 and placeholders for the roles after the diagnosis, and
stores the Agent 5 request of each window with its label. Phase two (score) runs Agent 5 on the
stored requests in variants: the previous scores, the odds update, the update with the window
assessment removed, and the update with the assessments of other windows (seeded shuffles).
The classifier is run once per window and reused by the variants. Train and validation files
only; the audit hook raises on any other open of the release folder.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import random
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"  # one thread per worker process
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

import guard  # noqa: E402
import run_runner_sample as sample_tools  # noqa: E402

from verum.agents.common import StubAgent, file_sha256, stable_hash  # noqa: E402

SEED = 20261108
SHUFFLES = 5
LATER_ROLES = ("diagnostic_reasoning", "inspection_planning", "evidence_verification_decision")
WORKERS = 8
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
    """Install the audit hook and load the reference once per worker process."""
    guard.install()
    path = Path(release) / "knowledge" / "public_reference.json"
    STATE["reference"] = json.loads(path.read_text())
    STATE["sha"] = file_sha256(path)


def collect_one(job: tuple[int, dict[str, Any], dict[str, Any], str]) -> str:
    """Run the runner on one window and store its Agent 5 request."""
    from verum.agents.runner import Snapshot, run_analysis

    n, window, summary, out = job
    snap = Snapshot(
        case_id=f"W{n:05d}",
        revision=0,
        as_of_s=float(window["cutoff_s"]),
        summary=summary,
        reference=STATE["reference"],
        reference_snapshot_sha256=STATE["sha"],
    )
    agents = {role: StubAgent(role) for role in LATER_ROLES}
    bundle = run_analysis(snap, "runtime", agents=agents)
    request = bundle.requests["diagnostic_reasoning"]
    write_json(Path(out) / f"{window['window_id']}.json.gz", {"window": window, "request": request})
    return str(window["window_id"])


def validation_windows(release: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every validation window with a valid label: its row and its observation summary."""
    records, lineage = sample_tools.load_split(release, "validation")
    rows, summaries = [], {}
    for record in records:
        if record.target["supervised_loss_mask"]:
            rows.append(sample_tools.window_row(record, lineage, "validation"))
            summaries[record.example_id] = record.input["observations"]
    return rows, summaries


def collect(release: Path, cache: Path, limit: int | None) -> None:
    """Phase one: run the runner on the validation windows and store the Agent 5 requests."""
    cache.mkdir(parents=True, exist_ok=True)
    rows, summaries = validation_windows(release)
    rows = rows[:limit] if limit else rows
    jobs = [(n, w, summaries[w["window_id"]], str(cache)) for n, w in enumerate(rows)]
    with Pool(WORKERS, initializer=init_collect, initargs=(str(release),)) as pool:
        for done, _ in enumerate(pool.imap_unordered(collect_one, jobs, chunksize=8), 1):
            if done % 500 == 0:
                print("collected", done, "of", len(jobs), flush=True)
    print("collected", len(jobs), flush=True)


def hypothesis_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Identifier, first component, score and method of each hypothesis, in returned order."""
    result = response.get("result")
    rows = []
    for h in [] if result is None else result["hypotheses"]:
        comp = h["components"][0]
        rows.append(
            {
                "id": h["hypothesis_id"],
                "mechanism": comp["mechanism"],
                "asset": comp["asset_id"],
                "score": h["score"]["value"],
                "method": h["score"]["method_id"],
                "support": len(h["support_evidence_ids"]),
                "conflict": len(h["conflict_evidence_ids"]),
            }
        )
    return rows


def with_assessment(request: dict[str, Any], assessment: dict[str, Any] | None) -> dict[str, Any]:
    """A copy of a request whose anomaly report has the given window assessment, or none."""
    changed = copy.deepcopy(request)
    report = changed["input"]["anomaly_report"]
    if report is None or report.get("result") is None:
        return changed
    report["result"].pop("window_assessment", None)
    if assessment is not None:
        report["result"]["window_assessment"] = copy.deepcopy(assessment)
    for row in changed["evidence"]:
        if row["evidence_id"] == report["report_id"]:
            row["content_sha256"] = stable_hash(report)
    return changed


def assessment_of(request: dict[str, Any]) -> dict[str, Any] | None:
    """The window assessment inside the anomaly report of a request."""
    report = request["input"]["anomaly_report"]
    found = (report or {}).get("result", {}) or {}
    value: dict[str, Any] | None = found.get("window_assessment")
    return value


def init_score(cache: str) -> None:
    """Install the audit hook and load the Agent 5 agent once per worker process."""
    guard.install()
    from verum.agents.diagnostic_reasoning import agent as module

    STATE["module"], STATE["agent"], STATE["cache"] = (
        module,
        module.DiagnosticReasoningAgent(),
        cache,
    )
    STATE["update"] = vars(module)["update_scores"]


def run_variant(request: dict[str, Any], update: bool) -> list[dict[str, Any]]:
    """Agent 5 on a request with the odds update on or off."""
    module = STATE["module"]
    module.update_scores = STATE["update"] if update else (lambda h, r, ratios=None: h)
    return hypothesis_rows(STATE["agent"].run(request))


def score_one(job: tuple[str, dict[str, str | None]]) -> tuple[str, dict[str, Any]]:
    """All variants for one window; donors give the shuffled assessments."""
    window_id, donors = job
    stored = read_json(Path(STATE["cache"]) / f"{window_id}.json.gz")
    request = stored["request"]
    model = STATE["agent"]._model
    first = model.predict_candidates
    memo: dict[str, Any] = {}
    model.predict_candidates = lambda obs: memo.setdefault("p", first(obs))
    out = {"prev": run_variant(request, False), "new": run_variant(request, True)}
    stripped = with_assessment(request, None)
    out["ablation"] = run_variant(stripped, True)
    out["prev_ablation"] = run_variant(stripped, False)
    for name, donor in donors.items():
        borrowed = (
            None
            if donor is None
            else assessment_of(read_json(Path(STATE["cache"]) / f"{donor}.json.gz")["request"])
        )
        out[name] = run_variant(with_assessment(request, borrowed), True)
    model.predict_candidates = first
    return window_id, {"window": stored["window"], "variants": out}


def shuffle_plan(ids: list[str]) -> dict[str, dict[str, str | None]]:
    """For each window and each seeded shuffle, the window whose assessment it borrows."""
    plan: dict[str, dict[str, str | None]] = {i: {} for i in ids}
    for s in range(SHUFFLES):
        order = list(ids)
        random.Random(SEED + s).shuffle(order)
        for window_id, donor in zip(ids, order, strict=True):
            plan[window_id][f"shuffle{s}"] = donor
    return plan


def score(cache: Path, out: Path) -> None:
    """Phase two: score the stored requests with every variant and write one result file."""
    ids = sorted(p.name.removesuffix(".json.gz") for p in cache.glob("*.json.gz"))
    plan = shuffle_plan(ids)
    results: dict[str, Any] = {}
    with Pool(WORKERS, initializer=init_score, initargs=(str(cache),)) as pool:
        for done, (wid, value) in enumerate(pool.imap_unordered(score_one, plan.items(), 4), 1):
            results[wid] = value
            if done % 500 == 0:
                print("scored", done, "of", len(ids), flush=True)
    write_json(out, results)
    print("scored", len(results), flush=True)


def main() -> None:
    """Command line: collect the requests or score them."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=("collect", "score"))
    parser.add_argument("--cache", type=Path, required=True, help="folder of stored requests")
    parser.add_argument("--out", type=Path, help="result file of the score phase")
    parser.add_argument("--release", type=Path, default=sample_tools.DEFAULT_RELEASE)
    parser.add_argument("--limit", type=int, help="only the first windows (for a trial)")
    args = parser.parse_args()
    guard.install()
    if args.phase == "collect":
        collect(args.release, args.cache, args.limit)
    else:
        score(args.cache, args.out)
    print("opened:", guard.summary())


if __name__ == "__main__":
    main()
