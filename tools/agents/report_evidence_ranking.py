"""Tables for the evaluation of the Agent 2 odds update of Agent 5 scores.

Inputs: the result file of the scoring script (every window with its label and the hypotheses of
each variant) and, optionally, the sample file of the earlier reports to select its validation
windows. Output: markdown tables on stdout. Contents: top-1 and top-3 accuracy for the family
and for the mechanism and asset, with bootstrap intervals over whole episodes, paired for the
differences; per-family results; fault-free windows by score level; ranking changes; reliability
of the scores; the ablation and shuffle controls; and the stop-rule outcome.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent5_agent2_evidence import FAMILY, table  # noqa: E402
from compare_agent2_runs import truth_pairs  # noqa: E402

from verum.agents.diagnostic_reasoning.model import DiagnosticModel  # noqa: E402

BOOTSTRAPS = 1000
SEED = 20261108
SHUFFLES = 5
LEVELS = (0.5, 0.9)
METRICS = ("family top-1", "family top-3", "exact top-1", "exact top-3")
Row = dict[str, Any]
Results = dict[str, Row]


def load(path: Path, sample: Path | None) -> Results:
    """The scored windows, restricted to the validation windows of a sample file if given."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        results: Results = json.load(f)
    if sample is None:
        return results
    wanted = {w["window_id"] for w in json.loads(sample.read_text())["validation"]}
    return {k: v for k, v in results.items() if k in wanted}


def truth_of(window: Row) -> tuple[set[tuple[str, str]], set[str]]:
    """Injected mechanism and asset pairs, and the injected families."""
    return truth_pairs(window), {FAMILY[m] for m in window["mechanisms"]}


def hits(rows: list[Row], window: Row, k: int) -> tuple[bool, bool]:
    """Whether the first k hypotheses hold the injected family and the injected pair."""
    pairs, families = truth_of(window)
    top = rows[:k]
    family = any(FAMILY[r["mechanism"]] in families for r in top)
    return family, any((r["mechanism"], r["asset"]) in pairs for r in top)


def accuracy_matrix(results: Results, variant: str) -> tuple[np.ndarray[Any, Any], list[str]]:
    """One row per faulty window: four hit indicators, and the episode of each row."""
    rows, episodes = [], []
    for value in results.values():
        window = value["window"]
        if not window["fault"]:
            continue
        hyp = value["variants"][variant]
        f1, e1 = hits(hyp, window, 1)
        f3, e3 = hits(hyp, window, 3)
        rows.append([f1, f3, e1, e3])
        episodes.append(window["episode_id"])
    return np.asarray(rows, dtype=float), episodes


def episode_sums(
    matrix: np.ndarray[Any, Any], episodes: list[str]
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Per-episode sums of the indicators and counts of windows."""
    names = sorted(set(episodes))
    where = {n: i for i, n in enumerate(names)}
    index = np.asarray([where[e] for e in episodes])
    sums = np.zeros((len(names), matrix.shape[1]))
    counts = np.zeros(len(names))
    np.add.at(sums, index, matrix)
    np.add.at(counts, index, 1.0)
    return sums, counts


def bootstrap_draws(n: int) -> np.ndarray[Any, Any]:
    """Resamples of episode indices, the same for every comparison."""
    rng = np.random.default_rng(SEED)
    return rng.integers(0, n, size=(BOOTSTRAPS, n))


def interval(values: np.ndarray[Any, Any]) -> tuple[float, float]:
    """The 95% percentile interval of a bootstrap distribution."""
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def accuracy_rows(results: Results) -> tuple[list[list[Any]], dict[str, np.ndarray[Any, Any]]]:
    """Accuracy and paired differences with intervals; the differences are also returned."""
    prev, episodes = accuracy_matrix(results, "prev")
    new, _ = accuracy_matrix(results, "new")
    sums_p, counts = episode_sums(prev, episodes)
    sums_n, _ = episode_sums(new, episodes)
    draws = bootstrap_draws(len(counts))
    den = counts[draws].sum(axis=1)
    boot_p = sums_p[draws].sum(axis=1) / den[:, None]
    boot_n = sums_n[draws].sum(axis=1) / den[:, None]
    diff = boot_n - boot_p
    rows = []
    for j, name in enumerate(METRICS):
        lo, hi = interval(diff[:, j])
        mean_p, mean_n = prev[:, j].mean(), new[:, j].mean()
        rows.append([name, len(prev), f"{mean_p:.3f}", f"{mean_n:.3f}",
                     f"{mean_n - mean_p:+.3f} ({lo:+.3f} to {hi:+.3f})"])  # fmt: skip
    return rows, {"diff": diff}


def family_rows(results: Results) -> list[list[Any]]:
    """Top-1 accuracy by the family of the injected fault."""
    groups: dict[str, list[Row]] = {}
    for value in results.values():
        w = value["window"]
        if w["fault"]:
            key = "several components" if w["n_components"] > 1 else FAMILY[w["mechanisms"][0]]
            groups.setdefault(key, []).append(value)
    rows = []
    for key in sorted(groups):
        items = groups[key]
        cells = []
        for variant in ("prev", "new"):
            got = [hits(v["variants"][variant], v["window"], 1) for v in items]
            cells += [f"{np.mean([g[0] for g in got]):.3f}", f"{np.mean([g[1] for g in got]):.3f}"]
        rows.append([key, len(items), *cells])
    return rows


def thresholds() -> tuple[dict[str, float], dict[str, float]]:
    """The decision thresholds of the classifier by mechanism and by mechanism and asset."""
    artifact = DiagnosticModel().artifact
    assert artifact is not None
    return dict(artifact["mechanism_thresholds"]), dict(artifact["component_thresholds"])


def own_threshold(row: Row, mech: dict[str, float], comp: dict[str, float]) -> float:
    """The decision threshold of one hypothesis; 0.5 for the two rule candidates."""
    if "observation_residual_rule" in row["method"]:
        return 0.5
    key = f"{row['mechanism']}::{row['asset']}"
    return comp[key] if key in comp else mech[row["mechanism"]]


def fault_free_rows(results: Results, variants: list[str]) -> list[list[Any]]:
    """Hypotheses on fault-free windows: count, mean score, and counts at each level."""
    mech, comp = thresholds()
    free = [v for v in results.values() if not v["window"]["fault"]]
    out = []
    for name in variants:
        hyps = [h for v in free for h in v["variants"][name]]
        scores = [h["score"] for h in hyps]
        own = sum(h["score"] >= own_threshold(h, mech, comp) for h in hyps)
        levels = [sum(s >= level for s in scores) for level in LEVELS]
        mean = f"{np.mean(scores):.3f}" if scores else "-"
        out.append([name, len(free), len(hyps), mean, own, *levels])
    return out


def ranking_rows(results: Results) -> list[list[Any]]:
    """How often the first hypothesis or the order changes, and what that does to correctness."""
    top = order = both = gained = lost = faulty = 0
    for v in results.values():
        a, b = v["variants"]["prev"], v["variants"]["new"]
        if len(a) < 1:
            continue
        both += 1
        top += a[0]["id"] != b[0]["id"]
        order += [h["id"] for h in a] != [h["id"] for h in b]
        if v["window"]["fault"]:
            faulty += 1
            before, after = hits(a, v["window"], 1)[1], hits(b, v["window"], 1)[1]
            gained += after and not before
            lost += before and not after
    return [[both, top, order, faulty, gained, lost]]


def binned(results: Results, variant: str) -> list[list[float]]:
    """For each score bin of width 0.1, whether each hypothesis matches an injected pair."""
    bins: list[list[float]] = [[] for _ in range(10)]
    for v in results.values():
        pairs = truth_pairs(v["window"]) if v["window"]["fault"] else set()
        for h in v["variants"][variant]:
            bins[min(9, int(h["score"] * 10))].append(float((h["mechanism"], h["asset"]) in pairs))
    return bins


def reliability_rows(results: Results, variant: str) -> list[list[Any]]:
    """Share of hypotheses that match an injected pair, by score bin."""
    rows = []
    for i, hit in enumerate(binned(results, variant)):
        if hit:
            rows.append([f"{i / 10:.1f} to {(i + 1) / 10:.1f}", len(hit), f"{np.mean(hit):.3f}"])
    return rows


def calibration_error(results: Results, variant: str) -> float:
    """Weighted mean absolute gap between the centre of each score bin and its match rate."""
    bins = binned(results, variant)
    total = sum(len(b) for b in bins)
    gap = sum(len(b) * abs((i + 0.5) / 10 - np.mean(b)) for i, b in enumerate(bins) if b)
    return float(gap / total) if total else 0.0


def control_rows(results: Results) -> list[list[Any]]:
    """Ablation identity and the gain of each shuffle in the four accuracy measures."""
    same = sum(
        v["variants"]["ablation"] == v["variants"]["prev_ablation"] for v in results.values()
    )
    prev, _ = accuracy_matrix(results, "prev")
    rows = [["ablation: output identical to the previous Agent 5", f"{same} of {len(results)}"]]
    gains = []
    for s in range(SHUFFLES):
        got, _ = accuracy_matrix(results, f"shuffle{s}")
        gains.append(got.mean(axis=0) - prev.mean(axis=0))
        rows.append([f"shuffle {s}: change in " + ", ".join(METRICS),
                     ", ".join(f"{g:+.3f}" for g in gains[-1])])  # fmt: skip
    rows.append(["shuffle: mean change", ", ".join(f"{g:+.3f}" for g in np.mean(gains, axis=0))])
    return rows


def stop_rule(results: Results, diff: np.ndarray[Any, Any]) -> list[str]:
    """The pre-registered stop rule applied to these results."""
    lows = [interval(diff[:, j])[0] for j in (0, 2)]
    accuracy_ok = any(low > 0 for low in lows)
    before, after = fault_free_rows(results, ["prev", "new"])
    no_increase = all(after[i] <= before[i] for i in (4, 5, 6))
    keep = accuracy_ok and no_increase
    return [
        f"- lower bound of the paired difference, family top-1: {lows[0]:+.3f}; "
        f"mechanism and asset top-1: {lows[1]:+.3f}; above zero for either: {accuracy_ok}",
        f"- fault-free hypotheses at their own threshold, at 0.5, at 0.9: before "
        f"{before[4]}, {before[5]}, {before[6]}; after {after[4]}, {after[5]}, {after[6]}; "
        f"no increase: {no_increase}",
        f"- outcome: {'keep' if keep else 'do not keep; report the negative result'}",
    ]


def render(results: Results) -> str:
    """All tables as one markdown text."""
    rows, extra = accuracy_rows(results)
    faulty = sum(v["window"]["fault"] for v in results.values())
    parts = [f"windows {len(results)}, faulty {faulty}, fault-free {len(results) - faulty}"]
    parts += ["\n### Accuracy on faulty windows (previous, update, difference with 95% interval)"]
    parts += [table(["measure", "windows", "previous", "update", "paired difference"], rows)]
    parts += ["\n### Top-1 by the family of the injected fault"]
    head = ["injected family", "windows", "family before", "exact before", "family after",
            "exact after"]  # fmt: skip
    parts += [table(head, family_rows(results))]
    parts += ["\n### Fault-free windows"]
    head = [
        "variant",
        "windows",
        "hypotheses",
        "mean score",
        "at own threshold",
        "at 0.5",
        "at 0.9",
    ]
    parts += [table(head, fault_free_rows(results, ["prev", "new"]))]
    parts += ["\n### Ranking changes"]
    head = ["windows with a hypothesis", "first hypothesis changes", "order changes",
            "faulty windows", "top-1 gained", "top-1 lost"]  # fmt: skip
    parts += [table(head, ranking_rows(results))]
    for variant in ("prev", "new"):
        err = calibration_error(results, variant)
        parts += [f"\n### Reliability of the score, {variant} (weighted gap {err:.3f})"]
        parts += [
            table(["score bin", "hypotheses", "match rate"], reliability_rows(results, variant))
        ]
    parts += ["\n### Controls", table(["control", "result"], control_rows(results))]
    parts += ["\n### Stop rule", *stop_rule(results, extra["diff"])]
    return "\n".join(parts) + "\n"


def main() -> None:
    """Print the tables for a result file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scores", type=Path)
    parser.add_argument(
        "--sample", type=Path, help="restrict to the validation windows of a sample"
    )
    args = parser.parse_args()
    sys.stdout.write(render(load(args.scores, args.sample)))


if __name__ == "__main__":
    main()
