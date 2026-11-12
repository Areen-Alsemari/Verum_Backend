"""Evaluate the Agent 8 review precedence on windows run in order within each episode.

Phase one (collect) runs the full runner on every validation window with a valid label. The
windows of an episode are run one after the other in time order as one run, with the assessment
log, so that persistence is known from the third window; a position with no valid label counts
as a window without an assessment. For each window it stores the label, the decision the agent
returned and the values the rules read. Phase two (report) turns stored records, or the bundles
of a sample run, into tables: decision counts for rules A, B and E4, review shares for faulty and
fault-free windows and per fault type, and episode-level results. Only train and validation
files are opened; the audit hook raises on anything else under the release folder.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Any

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"  # one thread per worker process
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detector"))

import guard  # noqa: E402
import run_runner_sample as sample_tools  # noqa: E402
import simulate_agent8_precedence as design  # noqa: E402
from agent5_agent2_evidence import FAMILY, table  # noqa: E402
from compare_agent2_runs import wilson  # noqa: E402

from verum.agents.common import file_sha256  # noqa: E402

WORKERS = 8
STEP_S = 300.0
STATES = design.STATES
RULES = {"A": design.rule_a, "B": design.rule_b, "E4": design.rule_e4}
STATE: dict[str, Any] = {}
Row = dict[str, Any]


def record_of(window: Row, requests: Row, reports: Row) -> Row:
    """What the evaluation keeps of one window: its label, the actual decision and rule inputs."""
    row = {"w": window, "b": {"requests": requests, "reports": reports}}
    f = design.features(row)
    f["conflicts"] = [c["check_id"] for c in f["conflicts"]]
    return {
        "window_id": window["window_id"], "episode_id": window["episode_id"],
        "position": window["position"], "cutoff_s": window["cutoff_s"],
        "fault": window["fault"], "mechanisms": window["mechanisms"],
        "n_components": window["n_components"], "f": f,
    }  # fmt: skip


def init_collect(release: str) -> None:
    """Install the audit hook and load the reference once per worker process."""
    guard.install()
    path = Path(release) / "knowledge" / "public_reference.json"
    STATE["reference"], STATE["sha"] = json.loads(path.read_text()), file_sha256(path)


def episode_job(job: tuple[int, list[Row], dict[str, Any]]) -> list[Row]:
    """Run the windows of one episode in time order as one run and return their records."""
    from verum.agents.runner import AssessmentLog, Snapshot, run_analysis

    index, windows, summaries = job
    case_id, log, last, records = f"E{index:04d}", AssessmentLog(), None, []
    for w in sorted(windows, key=lambda x: x["position"]):
        log = sample_tools.pad_gap(log, case_id, last, w["position"])
        snap = Snapshot(
            case_id=case_id, revision=0, as_of_s=float(w["cutoff_s"]),
            summary=summaries[w["window_id"]], reference=STATE["reference"],
            reference_snapshot_sha256=STATE["sha"],
        )  # fmt: skip
        bundle = run_analysis(snap, "runtime", recent=log)
        log, last = bundle.assessments, w["position"]
        records.append(record_of(w, bundle.requests, bundle.reports))
    return records


def collect(release: Path, out: Path, limit: int | None) -> None:
    """Phase one: run every validation episode in order and store the records."""
    records, lineage = sample_tools.load_split(release, "validation")
    rows = [sample_tools.window_row(r, lineage, "validation") for r in records
            if r.target["supervised_loss_mask"]]  # fmt: skip
    summaries = {r.example_id: r.input["observations"] for r in records}
    episodes: dict[str, list[Row]] = defaultdict(list)
    for w in rows:
        episodes[w["episode_id"]].append(w)
    names = sorted(episodes)[:limit] if limit else sorted(episodes)
    jobs = [(i, episodes[n], {w["window_id"]: summaries[w["window_id"]] for w in episodes[n]})
            for i, n in enumerate(names)]  # fmt: skip
    done: list[Row] = []
    with Pool(WORKERS, initializer=init_collect, initargs=(str(release),)) as pool:
        for n, part in enumerate(pool.imap_unordered(episode_job, jobs), 1):
            done += part
            if n % 50 == 0:
                print("episodes", n, "of", len(jobs), flush=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(done, f)
    print("windows", len(done), flush=True)


def load_records(path: Path) -> list[Row]:
    """Records from a collect file, or from the bundles of a sample run folder."""
    if path.is_dir():
        sample = json.loads((path / "sample.json").read_text())
        out = []
        for w in sample["validation"] + sample["train_sanity"]:
            with gzip.open(path / "bundles" / f"{w['window_id']}.json.gz", "rt") as f:
                b = json.load(f)
            out.append(record_of(w, b["requests"], b["reports"]))
        return out
    with gzip.open(path, "rt", encoding="utf-8") as f:
        loaded: list[Row] = json.load(f)
    return loaded


def decisions(records: list[Row], rule: str) -> list[str]:
    """The decision of a rule for each record; E4 is also the decision the agent returned."""
    return [RULES[rule](r["f"]) for r in records]


def count_rows(records: list[Row]) -> str:
    """Decision counts per rule, for all, faulty and fault-free windows."""
    rows = []
    for rule in RULES:
        got = decisions(records, rule)
        for label, keep in (("all", None), ("faulty", True), ("fault-free", False)):
            sel = [
                d for d, r in zip(got, records, strict=True) if keep is None or r["fault"] == keep
            ]
            c = Counter(sel)
            flagged = c["review_required"]
            rows.append([rule, label, len(sel), *[c[s] for s in STATES], wilson(flagged, len(sel))])
    head = ["rule", "windows", "n", *STATES, "review share (95%)"]
    return table(head, rows)


def family_of(record: Row) -> str:
    """The fault type of a faulty window for the per-type table."""
    if record["n_components"] > 1:
        return "several components"
    return FAMILY[record["mechanisms"][0]]


def type_rows(records: list[Row]) -> str:
    """Review share of rules B and E4 per fault type."""
    rows = []
    kinds = sorted({family_of(r) for r in records if r["fault"]})
    for kind in kinds:
        sel = [r for r in records if r["fault"] and family_of(r) == kind]
        cells = [wilson(sum(RULES[k](r["f"]) == "review_required" for r in sel), len(sel))
                 for k in ("B", "E4")]  # fmt: skip
        rows.append([kind, len(sel), *cells])
    return table(["fault type", "windows", "rule B review", "rule E4 review"], rows)


def episode_stats(records: list[Row], rule: str) -> Row:
    """Episode-level results of a rule: flagged episodes and time to the first review."""
    episodes: dict[str, list[Row]] = defaultdict(list)
    for r in records:
        episodes[r["episode_id"]].append(r)
    stats: Row = {"faulty": 0, "faulty_flagged": 0, "free": 0, "free_flagged": 0,
                  "pre_onset": 0, "times": []}  # fmt: skip
    for rows in episodes.values():
        rows.sort(key=lambda r: r["position"])
        flagged = [RULES[rule](r["f"]) == "review_required" for r in rows]
        faulty = [r["fault"] for r in rows]
        if not any(faulty):
            stats["free"] += 1
            stats["free_flagged"] += any(flagged)
            continue
        onset = faulty.index(True)
        stats["faulty"] += 1
        stats["pre_onset"] += any(flagged[:onset])
        after = [i for i in range(onset, len(rows)) if flagged[i]]
        stats["faulty_flagged"] += bool(after)
        if after:
            stats["times"].append(rows[after[0]]["cutoff_s"] - rows[onset]["cutoff_s"])
    return stats


def episode_rows(records: list[Row]) -> str:
    """Episode-level table for the three rules."""
    rows = []
    for rule in RULES:
        s = episode_stats(records, rule)
        t = sorted(s["times"])
        q = [f"{t[int(p * (len(t) - 1))]:.0f}" for p in (0.25, 0.5, 0.75)] if t else ["-"] * 3
        never = s["faulty"] - s["faulty_flagged"]
        rows.append([
            rule, wilson(s["faulty_flagged"], s["faulty"]), s["pre_onset"],
            wilson(s["free_flagged"], s["free"]), *q, never,
        ])  # fmt: skip
    head = ["rule", "faulty episodes with a review", "faulty episodes reviewed before onset",
            "fault-free episodes with a review", "time to first review, quartile 1 (s)",
            "median (s)", "quartile 3 (s)", "faulty episodes never reviewed"]  # fmt: skip
    return table(head, rows)


def adoption(records: list[Row]) -> list[str]:
    """The pre-registered adoption rule applied to rule E4."""
    free = [r for r in records if not r["fault"]]
    share = sum(RULES["E4"](r["f"]) == "review_required" for r in free) / max(1, len(free))
    s = episode_stats(records, "E4")
    episodes = s["free_flagged"] / max(1, s["free"])
    ok = share <= 0.05 and episodes <= 0.10
    return [
        f"- review windows among fault-free windows: {share:.4f} (limit 0.05)",
        f"- fault-free episodes with any review window: {episodes:.4f} (limit 0.10)",
        f"- E4 adopted: {ok}" + ("" if ok else "; fall back to rule B"),
    ]


def first_alert(f: Row) -> str:
    """The first alert of rule E4 that holds, in the order of the agent, or none."""
    if f["reliable_conflict"]:
        return "reliable-family conflict"
    if f["hard_conflict"]:
        return "failed record check"
    if f["alarming"] is True:
        return "persistent alarm"
    if f["supported"] and f["alarming"] is not False:
        return "supported hypothesis"
    return "none"


def alert_rows(records: list[Row]) -> str:
    """Windows of rule E4 by the first alert that holds, for faulty and fault-free windows."""
    names = ["reliable-family conflict", "failed record check", "persistent alarm",
             "supported hypothesis", "none"]  # fmt: skip
    rows = []
    for label, keep in (("faulty", True), ("fault-free", False)):
        got = Counter(first_alert(r["f"]) for r in records if r["fault"] == keep)
        rows.append([label, *[got[n] for n in names]])
    return table(["windows", *names], rows)


def agreement(records: list[Row]) -> str:
    """How often the simulated E4 and rule A agree with the decision the agent returned."""
    e4 = sum(RULES["E4"](r["f"]) == r["f"]["actual"] for r in records)
    persist = Counter(str(r["f"]["alarming"]) for r in records)
    return (f"simulated E4 equals the returned decision in {e4} of {len(records)} windows; "
            f"windows with no proposal {sum(r['f']['checks'] == 0 for r in records)}; "
            f"persistence in the requests {dict(persist)}")  # fmt: skip


def render(records: list[Row]) -> str:
    """All tables as one markdown text."""
    faulty = sum(r["fault"] for r in records)
    episodes = len({r["episode_id"] for r in records})
    parts = [f"windows {len(records)}, faulty {faulty}, fault-free {len(records) - faulty}, "
             f"episodes {episodes}", agreement(records)]  # fmt: skip
    parts += ["\n### Decisions", count_rows(records), "\n### Review share per fault type",
              type_rows(records), "\n### Episode level", episode_rows(records),
              "\n### Rule E4 by the first alert that holds", alert_rows(records),
              "\n### Adoption rule", *adoption(records)]  # fmt: skip
    return "\n".join(parts) + "\n"


def main() -> None:
    """Command line: collect the records or report on them."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=("collect", "report"))
    parser.add_argument("path", type=Path, help="record file (collect output) or sample run folder")
    parser.add_argument("--release", type=Path, default=sample_tools.DEFAULT_RELEASE)
    parser.add_argument("--limit", type=int, help="only the first episodes (for a trial)")
    args = parser.parse_args()
    guard.install()
    if args.phase == "collect":
        collect(args.release, args.path, args.limit)
        print("opened:", guard.summary())
    else:
        sys.stdout.write(render(load_records(args.path)))


if __name__ == "__main__":
    main()
