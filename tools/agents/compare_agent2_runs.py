"""Compare two runner outputs on the same windows: pipeline health, Agent 2 events, Agent 5 use.

Inputs: two output folders written by a run of the full runner over one window sample, one made
with the old Agent 2 and one with the new. Each holds the sample, the per-window run rows, the
run summary and one gzipped bundle per window. Output: a markdown report on stdout or in a file.
Labels are read from the sample for grouping only; no agent saw them.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

GROUPS = (
    ("validation", False),
    ("validation", True),
    ("train_sanity", False),
    ("train_sanity", True),
)
MODEL_CATEGORY = "reported_signal_departure"
QUALITY_CATEGORIES = ("missing_reading", "non_good_quality")
EXCEEDED = re.compile(
    r"Window score [\d.]+ .*against the window threshold [\d.]+: (exceeded|not exceeded)"
)
Row = dict[str, Any]


def load_run(folder: Path) -> list[Row]:
    """One row per window: its label, the run row and the agent reports."""
    sample = json.loads((folder / "sample.json").read_text())
    runs = {r["window_id"]: r for r in json.loads((folder / "run_rows.json").read_text())}
    rows = []
    for group in ("validation", "train_sanity"):
        for w in sample[group]:
            path = folder / "bundles" / f"{w['window_id']}.json.gz"
            bundle = json.loads(gzip.open(path, "rt").read()) if path.exists() else None
            rows.append(
                {"group": group, "window": w, "run": runs[w["window_id"]], "bundle": bundle}
            )
    return rows


def wilson(k: int, n: int) -> str:
    """A proportion with its 95% Wilson interval, as text."""
    if n == 0:
        return "0/0"
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{k}/{n} = {p:.3f} ({max(0.0, centre - half):.3f} to {min(1.0, centre + half):.3f})"


def report_of(row: Row, role: str) -> dict[str, Any] | None:
    """The report of one role for a window, or None."""
    if row["bundle"] is None:
        return None
    found: dict[str, Any] | None = row["bundle"]["reports"].get(role)
    return found


def events_of(row: Row) -> list[dict[str, Any]]:
    """Agent 2 events of a window (empty when it has no result)."""
    rep = report_of(row, "anomaly_detection")
    return list(rep["result"]["events"]) if rep and rep["result"] else []


def health(rows: list[Row], folder: Path) -> list[list[Any]]:
    """Pipeline health counts for one run."""
    meta = json.loads((folder / "run_meta.json").read_text())
    runs = [r["run"] for r in rows]
    issues = sum(len(r.get("bundle_issues") or []) for r in runs)
    return [
        ["windows run", len(rows)],
        ["crashes", sum(bool(r["crash"]) for r in runs)],
        ["verify_bundle ok", sum(r.get("verify") == "ok" for r in runs)],
        ["final report built", sum(r.get("report") == "ok" for r in runs)],
        ["runner issues", issues],
        ["seconds per window", meta["per_snapshot_s"]],
        ["test-split files touched", len(meta["test_split_files_touched"])],
    ]


def status_counts(rows: list[Row], role: str) -> str:
    """Status counts of one role over all windows."""
    c = Counter((report_of(r, role) or {}).get("status", "none") for r in rows)
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


def group_rows(rows: list[Row], group: str, fault: bool) -> list[Row]:
    """Windows of one sample group with the given label."""
    return [r for r in rows if r["group"] == group and bool(r["window"]["fault"]) == fault]


def a2_rates(rows: list[Row]) -> list[list[Any]]:
    """Agent 2 event rates on faulty and fault-free windows."""
    out = []
    for group, fault in GROUPS:
        sel = group_rows(rows, group, fault)
        ev = [events_of(r) for r in sel]
        model = sum(any(e["category"] == MODEL_CATEGORY for e in x) for x in ev)
        quality = sum(any(e["category"] in QUALITY_CATEGORIES for e in x) for x in ev)
        tagless = sum(
            any(e["category"] == MODEL_CATEGORY and not e["tag_ids"] for e in x) for x in ev
        )
        out.append(
            [
                f"{group}, {'faulty' if fault else 'fault-free'}",
                wilson(model, len(sel)),
                wilson(tagless, len(sel)),
                wilson(quality, len(sel)),
                status_counts(sel, "anomaly_detection"),
            ]
        )
    return out


def exceeded(row: Row) -> bool | None:
    """Whether the new Agent 2 reported the window score as exceeded (None for the old one)."""
    rep = report_of(row, "anomaly_detection")
    for line in (rep or {}).get("limitations", []):
        m = EXCEEDED.search(line)
        if m:
            return m.group(1) == "exceeded"
    return None


def residual_rates(rows: list[Row]) -> list[list[Any]]:
    """For the new Agent 2: window-score exceedance and events per residual."""
    out = []
    for group, fault in GROUPS:
        sel = group_rows(rows, group, fault)
        flags = [exceeded(r) for r in sel]
        keys = Counter(
            e["event_id"].rsplit("-", 1)[1]
            for r in sel
            for e in events_of(r)
            if "-residual-" in e["event_id"]
        )
        out.append(
            [
                f"{group}, {'faulty' if fault else 'fault-free'}",
                len(sel),
                wilson(sum(f is True for f in flags), len(sel)),
                ", ".join(f"{k} {keys.get(k, 0)}" for k in ("R1", "R2", "R3", "R4")),
            ]
        )
    return out


def hypotheses(row: Row) -> list[dict[str, Any]]:
    """Agent 5 hypotheses of a window."""
    rep = report_of(row, "diagnostic_reasoning")
    return list(rep["result"]["hypotheses"]) if rep and rep["result"] else []


def pairs(row: Row) -> list[tuple[str, str]]:
    """Mechanism and asset of the first component of each hypothesis, in ranked order."""
    return [
        (h["components"][0]["mechanism"], h["components"][0]["asset_id"]) for h in hypotheses(row)
    ]


def compare_hypotheses(old: list[Row], new: list[Row]) -> list[list[Any]]:
    """Whether Agent 5 produced the same hypotheses with the old and the new Agent 2."""
    same_ids = same_pairs = same_order = both = 0
    for a, b in zip(old, new, strict=True):
        if (
            report_of(a, "diagnostic_reasoning") is None
            or report_of(b, "diagnostic_reasoning") is None
        ):
            continue
        both += 1
        ids = (
            [h["hypothesis_id"] for h in hypotheses(a)],
            [h["hypothesis_id"] for h in hypotheses(b)],
        )
        same_ids += ids[0] == ids[1]
        same_pairs += sorted(pairs(a)) == sorted(pairs(b))
        same_order += pairs(a) == pairs(b)
    return [
        ["windows with an Agent 5 report in both runs", both],
        ["identical hypothesis identifiers, same order", same_ids],
        ["same hypotheses (mechanism and asset), any order", same_pairs],
        ["same hypotheses in the same ranked order", same_order],
    ]


def a2_relation(row: Row, h: dict[str, Any]) -> str:
    """Whether Agent 5 cites the Agent 2 report as support, conflict or neither for a hypothesis."""
    rep = report_of(row, "anomaly_detection")
    if rep is None:
        return "neither"
    if rep["report_id"] in h.get("support_evidence_ids", []):
        return "support"
    return "conflict" if rep["report_id"] in h.get("conflict_evidence_ids", []) else "neither"


def event_mix(row: Row) -> str:
    """The kinds of Agent 2 events in a window, as one label."""
    ev = events_of(row)
    parts = []
    if any(e["category"] == MODEL_CATEGORY and not e["tag_ids"] for e in ev):
        parts.append("tagless model event")
    if any(e["category"] == MODEL_CATEGORY and e["tag_ids"] for e in ev):
        parts.append("tagged residual events")
    if any(e["category"] in QUALITY_CATEGORIES for e in ev):
        parts.append("quality events")
    return " + ".join(parts) or "no events"


def a2_use(rows: list[Row]) -> list[list[Any]]:
    """Hypotheses that cite Agent 2 as support or conflict, by label of the window."""
    out = []
    for group, fault in GROUPS:
        tally: Counter[str] = Counter()
        for r in group_rows(rows, group, fault):
            for h in hypotheses(r):
                tally[a2_relation(r, h)] += 1
        total = sum(tally.values())
        out.append(
            [
                f"{group}, {'faulty' if fault else 'fault-free'}",
                total,
                tally["support"],
                tally["conflict"],
                tally["neither"],
            ]
        )
    return out


def truth_pairs(window: dict[str, Any]) -> set[tuple[str, str]]:
    """Mechanism and asset pairs of the injected fault(s) of a window."""
    mechanisms, assets = window["mechanisms"], window["assets"]
    if window["n_components"] == 1:
        return set(zip(mechanisms, assets, strict=True))
    return {(m, a) for m in mechanisms for a in assets}


def a2_use_by_truth(rows: list[Row]) -> list[list[Any]]:
    """Support and conflict for hypotheses that match an injected fault and those that do not."""
    tally: Counter[tuple[bool, str]] = Counter()
    for r in rows:
        if not r["window"]["fault"]:
            continue
        truth = truth_pairs(r["window"])
        for h in hypotheses(r):
            pair = (h["components"][0]["mechanism"], h["components"][0]["asset_id"])
            tally[(pair in truth, a2_relation(r, h))] += 1
    out = []
    for hit in (True, False):
        n = sum(v for (k, _), v in tally.items() if k == hit)
        label = "matches an injected fault" if hit else "does not match"
        counts = [tally[(hit, k)] for k in ("support", "conflict", "neither")]
        out.append([label, n, *counts])
    return out


def conflict_causes(rows: list[Row]) -> list[list[Any]]:
    """For each mix of Agent 2 events and coverage: hypotheses seen and how many cite conflict."""
    seen: Counter[tuple[str, str]] = Counter()
    hit: Counter[tuple[str, str, str]] = Counter()
    for r in rows:
        rep = report_of(r, "anomaly_detection")
        coverage = rep["result"]["coverage"] if rep and rep["result"] else "none"
        key = (event_mix(r), coverage)
        for h in hypotheses(r):
            seen[key] += 1
            hit[(*key, a2_relation(r, h))] += 1
    return [
        [
            mix,
            cov,
            n,
            hit[(mix, cov, "support")],
            hit[(mix, cov, "conflict")],
            hit[(mix, cov, "neither")],
        ]
        for (mix, cov), n in sorted(seen.items())
    ]


def final_states(folder: Path, rows: list[Row]) -> str:
    """Counts of the final assessment state over the windows."""
    c: Counter[str] = Counter()
    for r in rows:
        path = folder / "final_reports" / f"{r['window']['window_id']}.json"
        c[json.loads(path.read_text())["assessment_state"] if path.exists() else "none"] += 1
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


def table(head: list[str], rows: list[list[Any]]) -> list[str]:
    """Markdown table lines."""
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    return [*lines, *("| " + " | ".join(str(c) for c in r) + " |" for r in rows), ""]


def health_section(old: list[Row], new: list[Row], old_dir: Path, new_dir: Path) -> list[str]:
    """Part (a): pipeline health of both runs."""
    ho, hn = health(old, old_dir), health(new, new_dir)
    roles = ["anomaly_detection", "diagnostic_reasoning", "inspection_planning",
             "evidence_verification_decision"]  # fmt: skip
    return [
        "## (a) Pipeline health", "",
        *table(["measure", "old Agent 2", "new Agent 2"],
               [[a[0], a[1], b[1]] for a, b in zip(ho, hn, strict=True)]),  # fmt: skip
        *table(["role", "old status counts", "new status counts"],
               [[r, status_counts(old, r), status_counts(new, r)] for r in roles]),  # fmt: skip
        f"Final assessment state, old: {final_states(old_dir, old)}. "
        f"New: {final_states(new_dir, new)}.", "",
    ]  # fmt: skip


def events_section(old: list[Row], new: list[Row]) -> list[str]:
    """Part (b): Agent 2 event rates of both runs."""
    head = ["windows", "any model event", "tagless model event", "quality event", "status"]
    return [
        "## (b) Agent 2 events",
        "",
        "Old Agent 2:",
        "",
        *table(head, a2_rates(old)),
        "New Agent 2:",
        "",
        *table(head, a2_rates(new)),
        "New Agent 2: window score above the pinned threshold, and residual events by key.",
        "",
        *table(["windows", "n", "window score exceeded", "residual events"], residual_rates(new)),
    ]


def agent5_section(old: list[Row], new: list[Row]) -> list[str]:
    """Part (c): what Agent 5 does with the events."""
    use = ["windows", "hypotheses", "support", "conflict", "neither"]
    mix = ["events", "coverage", "hypotheses", "support", "conflict", "neither"]
    truth_head = ["hypothesis", "hypotheses", "support", "conflict", "neither"]
    return [
        "## (c) What Agent 5 does with the events",
        "",
        *table(["comparison", "windows"], compare_hypotheses(old, new)),
        "Hypotheses that cite the Agent 2 report, old Agent 2:",
        "",
        *table(use, a2_use(old)),
        "New Agent 2:",
        "",
        *table(use, a2_use(new)),
        "Faulty windows only, by whether the hypothesis matches an injected fault, old:",
        "",
        *table(truth_head, a2_use_by_truth(old)),
        "New:",
        "",
        *table(truth_head, a2_use_by_truth(new)),
        "By the events Agent 2 sent and its coverage, old:",
        "",
        *table(mix, conflict_causes(old)),
        "New:",
        "",
        *table(mix, conflict_causes(new)),
    ]


def render(old_dir: Path, new_dir: Path) -> str:
    """The whole comparison as markdown."""
    old, new = load_run(old_dir), load_run(new_dir)
    parts = [*health_section(old, new, old_dir, new_dir), *events_section(old, new),
             *agent5_section(old, new)]  # fmt: skip
    return "\n".join(parts)


def main() -> None:
    """Write the comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    text = render(args.old, args.new)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
