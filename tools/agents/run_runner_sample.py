"""Run the full runner over a fixed, seeded sample of 181 windows and store every bundle.

Inputs: the reference release folder (train and validation role files only) and the code of the
checkout the script is started from. Outputs, in the output folder: the sample, one row per
window, a run summary and one gzipped bundle per window, which are the inputs of the comparison
script for two Agent 2 versions.
Assumptions: the sample is stratified by fault mechanism plus whole-episode tracks, drawn with
one fixed seed. Labels are kept for grouping only and are never given to an agent. The test
split is refused at load time and every opened data file is recorded to prove it stayed closed.
Source: the Agent 2 before and after report.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

GUARD_PATH = Path(__file__).resolve().parents[1] / "detector"
SEED = 20261108
REPO = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE = REPO / "data" / "reference_release_v2" / "verum_reference_v2"
QUOTA = {
    "restriction_position_visible": 10,
    "pump": 8,
    "bias": 8,
    "leak": 8,
    "drift": 8,
    "stuck": 8,
    "misroute_a": 6,
    "restriction_obstruction": 1,
}
TRACK_MECHANISMS = ("restriction_position_visible", "leak", "pump", "bias", "drift", "stuck")
MULTI_FAULT_QUOTA = 8
FAULT_FREE_PER_POSITION = 3
FAULT_FREE_TRACKS = 2
MIN_FAULT_FREE_TRACK_WINDOWS = 12
TRAIN_SANITY_EACH = 6
WINDOW_STEP_S = 300

Window = dict[str, Any]
ACCESSED: set[str] = set()


def install_audit() -> None:
    """Record every file opened under the data folder so a touch of the test split is visible."""

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args and isinstance(args[0], (str, bytes)):
            path = args[0].decode() if isinstance(args[0], bytes) else args[0]
            if "reference_release_v2" in path:
                ACCESSED.add(path)

    sys.addaudithook(hook)


def install_guard() -> None:
    """Raise on any open under the release folder that is not train, validation or reference."""
    sys.path.insert(0, str(GUARD_PATH))
    import guard

    guard.install()


def guard_summary() -> dict[str, Any]:
    """The opens that the guard allowed, by folder, and the rejected ones."""
    import guard

    summary: dict[str, Any] = guard.summary()
    return summary


def touched_test_split() -> list[str]:
    """Opened data paths that belong to the test split."""
    pattern = re.compile(r"/(test)(\.jsonl\.gz|/|$)")
    return sorted(p for p in ACCESSED if pattern.search(p))


def load_split(release: Path, split: str) -> tuple[list[Any], dict[str, Any]]:
    """Diagnostic reasoning records of one split and the episode lineage."""
    if split not in ("train", "validation"):
        raise ValueError("only the train and validation splits may be loaded here")
    from verum.agents.common import episode_lookup, iter_role_records

    records = list(iter_role_records(release, "diagnostic_reasoning", split))
    return records, episode_lookup(release, split)


def labels_of(record: Any) -> dict[str, Any]:
    """Truth label of a window, used for grouping only."""
    comps = record.target["injected_components"] or []
    return {
        "fault": bool(comps),
        "assets": sorted({c["asset_id"] for c in comps}),
        "fault_types": sorted({c["fault_type"] for c in comps}),
        "mechanisms": sorted({c["mechanism"] for c in comps}),
        "n_components": len(comps),
    }


def round_robin(pool: list[Any], key: Any, k: int, rnd: random.Random) -> list[Any]:
    """Up to k items, taken in turn from each group so that no group dominates."""
    groups: dict[Any, list[Any]] = defaultdict(list)
    for item in pool:
        groups[key(item)].append(item)
    order = sorted(groups, key=str)
    rnd.shuffle(order)
    for g in groups.values():
        rnd.shuffle(g)
    picked: list[Any] = []
    while len(picked) < k and any(groups.values()):
        for g in order:
            if groups[g] and len(picked) < k:
                picked.append(groups[g].pop())
    return picked


def position_of(record: Any, lineage: dict[str, Any]) -> int:
    """Index of the window inside its episode."""
    return int(round(lineage[record.example_id].source_cutoff_s / WINDOW_STEP_S))


def split_pool(
    eligible: list[Any],
) -> tuple[dict[str, list[Any]], list[Any], list[Any]]:
    """Single-mechanism fault windows by mechanism, multi-fault windows, fault-free windows."""
    single: dict[str, list[Any]] = defaultdict(list)
    multi: list[Any] = []
    free: list[Any] = []
    for r in eligible:
        lab = labels_of(r)
        if not lab["fault"]:
            free.append(r)
        elif len(lab["mechanisms"]) == 1 and lab["n_components"] == 1:
            single[lab["mechanisms"][0]].append(r)
        else:
            multi.append(r)
    return single, multi, free


def pick_windows(eligible: list[Any], lineage: dict[str, Any], rnd: random.Random) -> set[str]:
    """Stratified picks: fault windows by mechanism, multi-fault windows, fault-free by position."""
    single, multi, free = split_pool(eligible)
    chosen: set[str] = set()
    for mech, k in QUOTA.items():
        for r in round_robin(single[mech], lambda r: labels_of(r)["assets"][0], k, rnd):
            chosen.add(r.example_id)
    for r in round_robin(
        multi, lambda r: tuple(labels_of(r)["mechanisms"]), MULTI_FAULT_QUOTA, rnd
    ):
        chosen.add(r.example_id)
    by_pos: dict[int, list[Any]] = defaultdict(list)
    for r in free:
        by_pos[position_of(r, lineage)].append(r)
    for p in sorted(by_pos):
        for r in rnd.sample(by_pos[p], FAULT_FREE_PER_POSITION):
            chosen.add(r.example_id)
    return chosen


def pick_tracks(eligible: list[Any], lineage: dict[str, Any], rnd: random.Random) -> list[str]:
    """Episodes whose every eligible window is kept: six fault episodes and two fault-free."""
    by_ep: dict[str, list[Any]] = defaultdict(list)
    for r in eligible:
        by_ep[lineage[r.example_id].episode_id].append(r)
    fault_eps: dict[str, list[str]] = defaultdict(list)
    free_eps: list[str] = []
    for ep, rs in by_ep.items():
        mechs = {m for r in rs for m in labels_of(r)["mechanisms"]}
        if len(mechs) == 1 and all(labels_of(r)["n_components"] <= 1 for r in rs):
            fault_eps[next(iter(mechs))].append(ep)
        elif not mechs and len(rs) >= MIN_FAULT_FREE_TRACK_WINDOWS:
            free_eps.append(ep)
    track_eps = [sorted(fault_eps[m])[rnd.randrange(len(fault_eps[m]))] for m in TRACK_MECHANISMS]
    track_eps += rnd.sample(sorted(free_eps), FAULT_FREE_TRACKS)
    return [r.example_id for ep in track_eps for r in by_ep[ep]]


def window_row(record: Any, lineage: dict[str, Any], tag: str) -> Window:
    """One sample row: identifiers, position and label."""
    ref = lineage[record.example_id]
    return {
        "window_id": record.example_id,
        "set": tag,
        "episode_id": ref.episode_id,
        "position": position_of(record, lineage),
        "cutoff_s": ref.source_cutoff_s,
        **labels_of(record),
    }


def build_sample(records: list[Any], lineage: dict[str, Any]) -> list[Window]:
    """Stratified sample plus whole-episode tracks."""
    rnd = random.Random(SEED)
    eligible = [r for r in records if r.target["supervised_loss_mask"]]
    tags = {wid: "sample" for wid in pick_windows(eligible, lineage, rnd)}
    for wid in pick_tracks(eligible, lineage, rnd):
        tags.setdefault(wid, "track")
    rows = [window_row(r, lineage, tags[r.example_id]) for r in eligible if r.example_id in tags]
    rows.sort(key=lambda x: (x["episode_id"], x["position"]))
    return rows


def build_train_sanity(records: list[Any], lineage: dict[str, Any]) -> list[Window]:
    """Twelve train windows, six with one injected fault and six without, as a sanity check."""
    rnd = random.Random(SEED + 1)
    elig = [r for r in records if r.target["supervised_loss_mask"]]
    faulty = [r for r in elig if labels_of(r)["fault"] and labels_of(r)["n_components"] == 1]
    free = [r for r in elig if not labels_of(r)["fault"]]
    picks = round_robin(faulty, lambda r: labels_of(r)["mechanisms"][0], TRAIN_SANITY_EACH, rnd)
    picks += rnd.sample(free, TRAIN_SANITY_EACH)
    return [window_row(r, lineage, "train") for r in picks]


def summary_of(records: list[Any], ids: set[str]) -> dict[str, dict[str, Any]]:
    """Observation summaries of the chosen windows, which is all the agents are given."""
    return {r.example_id: r.input["observations"] for r in records if r.example_id in ids}


def dump(path: Path, obj: Any) -> None:
    """Write JSON, gzipped when the name ends in .gz."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(obj, f, default=str)
    else:
        path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def make_snapshot(case_id: str, w: Window, summary: Any, reference: Any, sha: str) -> Any:
    """The snapshot of one window as a case of the given run."""
    from verum.agents.runner import Snapshot

    return Snapshot(
        case_id=case_id,
        revision=0,
        as_of_s=float(w["cutoff_s"]),
        summary=summary,
        reference=reference,
        reference_snapshot_sha256=sha,
    )


def save_bundle(bundle: Any, window: Window, out: Path) -> None:
    """Store the requests, reports and evidence of one run with the window that produced them."""
    contents = {
        "window": window,
        "context": bundle.context,
        "requests": bundle.requests,
        "reports": bundle.reports,
        "issues": bundle.issues,
        "notes": bundle.notes,
        "evidence": bundle.registry.rows(),
    }
    dump(out / "bundles" / f"{window['window_id']}.json.gz", contents)


def run_window(
    n: int,
    w: Window,
    summaries: dict[str, Any],
    reference: Any,
    sha: str,
    out: Path,
    case_id: str | None = None,
    recent: Any = None,
) -> tuple[dict[str, Any], Any]:
    """Run, verify and report one window; failures are recorded in the row, never raised.

    Returns the row and the assessment log to pass to the next window of the same run, which is
    None unless a log was given.
    """
    from verum.agents.inspection_quality_documentation import report as rep
    from verum.agents.runner import run_analysis, verify_bundle

    wid = w["window_id"]
    row: dict[str, Any] = {"n": n, "window_id": wid, "set": w["set"], "crash": None}
    t0, next_log = time.time(), None
    try:
        snap = make_snapshot(case_id or f"V{n:04d}", w, summaries[wid], reference, sha)
        extra = {} if recent is None else {"recent": recent}
        b = run_analysis(snap, "runtime", allow_placeholders=False, **extra)
        next_log = b.assessments if recent is not None else None
        t1 = time.time()
        row.update(run_s=round(t1 - t0, 2), bundle_issues=b.issues)
        row["notes"] = [(x["role"], x["code"]) for x in b.notes]
        save_bundle(b, w, out)
        row.update(verify_and_report(b, verify_bundle, rep.build_report, out, wid))
        row["verify_report_s"] = round(time.time() - t1, 2)
    except Exception as ex:
        row["crash"] = f"{type(ex).__name__}: {str(ex)[:300]}"
        row["crash_tb"] = traceback.format_exc()[-2000:]
    return row, next_log


def verify_and_report(
    bundle: Any, verify: Any, build_report: Any, out: Path, wid: str
) -> dict[str, Any]:
    """Verification and final report outcome of one bundle."""
    result: dict[str, Any] = {}
    try:
        v = verify(bundle, allow_placeholders=False)
        result["verify"] = "ok"
        result["verified_roles"] = sorted(v.responses)
        try:
            dump(out / "final_reports" / f"{wid}.json", build_report(v))
            result["report"] = "ok"
        except Exception as ex:
            result["report"] = f"FAIL {type(ex).__name__}: {str(ex)[:200]}"
            result["report_tb"] = traceback.format_exc()[-1500:]
    except Exception as ex:
        result["verify"] = f"FAIL {type(ex).__name__}: {str(ex)[:300]}"
        result["verify_tb"] = traceback.format_exc()[-1500:]
    return result


def pad_gap(log: Any, case_id: str, last: int | None, position: int) -> Any:
    """Add a window without an assessment for every skipped position of the run."""
    first_skipped = position if last is None else last + 1
    for skipped in range(first_skipped, position):
        log = log.extended(case_id, skipped * WINDOW_STEP_S, None)
    return log


def run_chained(
    sample: list[Window], summaries: dict[str, Any], reference: Any, sha: str, out: Path
) -> list[dict[str, Any]]:
    """Run the windows of each episode in time order as one run with a shared assessment log."""
    from verum.agents.runner import AssessmentLog

    episodes: dict[str, list[Window]] = defaultdict(list)
    for w in sample:
        episodes[w["episode_id"]].append(w)
    rows: list[dict[str, Any]] = []
    for e, (_, windows) in enumerate(sorted(episodes.items())):
        log, last = AssessmentLog(), None
        for w in sorted(windows, key=lambda x: x["position"]):
            case_id = f"E{e:04d}"
            log = pad_gap(log, case_id, last, w["position"])
            row, log = run_window(len(rows), w, summaries, reference, sha, out, case_id, log)
            rows.append(row)
            last = w["position"]
    return rows


def parse_args() -> argparse.Namespace:
    """Command line: the output folder and the release folder."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="folder for the run outputs")
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument(
        "--chain", action="store_true", help="run the windows of one episode as one run"
    )
    return parser.parse_args()


def run_each(
    windows: list[Window], summaries: dict[str, Any], reference: Any, sha: str, out: Path
) -> list[dict[str, Any]]:
    """Run every window as a case of its own."""
    rows: list[dict[str, Any]] = []
    started = time.time()
    for n, w in enumerate(windows):
        rows.append(run_window(n, w, summaries, reference, sha, out)[0])
        if n % 10 == 0:
            print(n, w["window_id"], f"elapsed {time.time() - started:.0f}s", flush=True)
    return rows


def main() -> int:
    """Draw the sample, run every window and write the summary."""
    args = parse_args()
    install_audit()
    install_guard()
    import verum
    from verum.agents.common import file_sha256

    print("verum:", verum.__file__, flush=True)
    ref_path = args.release / "knowledge" / "public_reference.json"
    reference = json.loads(ref_path.read_text())
    sha = file_sha256(ref_path)
    val, val_ep = load_split(args.release, "validation")
    sample = build_sample(val, val_ep)
    trn, trn_ep = load_split(args.release, "train")
    train = build_train_sanity(trn, trn_ep)
    ids = {s["window_id"] for s in sample} | {s["window_id"] for s in train}
    summaries = summary_of(val, ids) | summary_of(trn, ids)
    dump(args.out / "sample.json", {"seed": SEED, "validation": sample, "train_sanity": train})
    print("sample:", len(sample), "validation,", len(train), "train", flush=True)
    started = time.time()
    if args.chain:
        rows = run_chained(sample + train, summaries, reference, sha, args.out)
    else:
        rows = run_each(sample + train, summaries, reference, sha, args.out)
    total = time.time() - started
    dump(args.out / "run_rows.json", rows)
    meta = {
        "total_s": round(total, 1),
        "windows": len(rows),
        "per_snapshot_s": round(total / len(rows), 2),
        "test_split_files_touched": touched_test_split(),
        "data_files_opened": sorted(ACCESSED),
        "guard": guard_summary(),
    }
    dump(args.out / "run_meta.json", meta)
    print("done", len(rows), "| test-split files touched:", touched_test_split(), flush=True)
    print("guard:", guard_summary(), flush=True)
    return 1 if touched_test_split() else 0


if __name__ == "__main__":
    raise SystemExit(main())
