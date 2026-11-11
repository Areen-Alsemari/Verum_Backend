"""Old key against new key: every metric of the first experiment next to its re-run.

Inputs are the results files of the two scoring runs on the same validation windows. The old
key is the on/off lineup state, the new key the operator-set conditions (Amendment 2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import metrics as m
import numpy as np
from diagnostics import placebo
from evaluate import MODELS
from regime_report import table
from windows import FAULT_TYPES

SHOWN = ["C1", "C2a", "C2b", "C3", "C4", "C1s", "C2as", "C2bs", "C4s"]
Pair = tuple[dict[str, Any], dict[str, Any]]


def fmt(v: list[float]) -> str:
    """Point value and interval."""
    return f"{v[0]:.3f} ({v[1]:.3f} to {v[2]:.3f})"


def delta(old: list[float], new: list[float]) -> str:
    """Signed change of the point value."""
    return f"{new[0] - old[0]:+.3f}"


def metric_rows(old: dict[str, Any], new: dict[str, Any]) -> list[list[str]]:
    """One row per model and metric: old, new, change."""
    rows = []
    for name in SHOWN:
        for key, label in (("ap", "AP"), ("auroc", "AUROC"), ("matched_auroc", "matched AUROC")):
            a, b = old[name]["discrimination"][key], new[name]["discrimination"][key]
            rows.append([name, label, fmt(a), fmt(b), delta(a, b)])
        a, b = old[name]["alarms_at_5pct_far"], new[name]["alarms_at_5pct_far"]
        for key, label in (("far", "FAR at 5% target"), ("recall_all", "recall, all faults")):
            rows.append([name, label, fmt(a[key]), fmt(b[key]), delta(a[key], b[key])])
    return rows


def type_rows(old: dict[str, Any], new: dict[str, Any], names: list[str]) -> list[list[str]]:
    """Recall by fault type for the given models, old key against new key."""
    rows = []
    for name in names:
        a = old[name]["alarms_at_5pct_far"]["recall_by_type"]
        b = new[name]["alarms_at_5pct_far"]["recall_by_type"]
        for t in FAULT_TYPES:
            rows.append([name, t, str(a[t]["n"]), fmt(a[t]["recall"]), fmt(b[t]["recall"]),
                         delta(a[t]["recall"], b[t]["recall"])])  # fmt: skip
    return rows


def shuffle_rows(old: dict[str, Any], new: dict[str, Any]) -> list[list[str]]:
    """Shuffle control (mean of AP and AUROC under permuted labels), old and new."""
    rows = []
    for name in ["C3", "C4", "C4s"]:
        for key in ("ap", "auroc", "matched"):
            a, b = old[name]["shuffle"][key], new[name]["shuffle"][key]
            rows.append([name, key, f"{a[0]:.3f} ({a[1]:.3f} to {a[2]:.3f})",
                         f"{b[0]:.3f} ({b[1]:.3f} to {b[2]:.3f})"])  # fmt: skip
    return rows


def placebo_rows(old_work: Path, new_work: Path) -> list[list[str]]:
    """Placebo matched AUROC (positions 1 to 5, label = fault later in the episode)."""
    rows = []
    cache: dict[Path, Any] = {}
    for w in (old_work, new_work):
        d = np.load(w / "scores.npz")
        meta = json.loads((w / "meta.json").read_text())
        eps = np.asarray(meta["episodes"])
        later = np.isin(eps, eps[d["faulty"] == 1]).astype(np.intp)
        groups = m.episode_groups(meta["episodes"])
        stage = d["stage"].astype(np.intp)
        cache[w] = {n: placebo(d[f"score_{n}"], later, stage, groups) for n in MODELS if n in SHOWN}
    for name in SHOWN:
        a, b = cache[old_work][name], cache[new_work][name]
        rows.append([name, fmt(a), fmt(b), delta(a, b)])
    return rows


def contributors(old: dict[str, Any], new: dict[str, Any], names: list[str]) -> list[list[str]]:
    """Top three contributors, old and new."""
    out = []
    for name in names:
        a = ", ".join(f"{k} {v:.2f}" for k, v in old[name]["top_contributors"][:3])
        b = ", ".join(f"{k} {v:.2f}" for k, v in new[name]["top_contributors"][:3])
        out.append([name, a, b])
    return out


def saturation(work: Path) -> dict[str, dict[str, float]]:
    """Share of fault-free and of faulty windows at the maximum score, per fused model."""
    d = np.load(work / "scores.npz")
    y = d["faulty"]
    out = {}
    for name in ("C4", "C4s"):
        s = d[f"score_{name}"]
        top = s.max()
        out[name] = {"fault_free": float((s[y == 0] == top).mean()),
                     "faulty": float((s[y == 1] == top).mean())}  # fmt: skip
    return out


def _intro(om: dict[str, Any], nm: dict[str, Any]) -> list[str]:
    old, new = om["rare_regime_share_validation"], nm["rare_regime_share_validation"]
    return [
        "## Amendment 2 re-run: the regime key", "",
        "Validation windows, same fitted constants, thresholds and cross-fitting as before; only "
        "the key changed. The old-key rows are the first experiment, reproduced exactly (all "
        "score arrays identical). Intervals are 95% bootstrap over episodes. C1 and C2 are shown "
        "because they feed C4; the requested comparison is C3 and C4.", "",
        f"Validation windows in a regime without an own baseline: {old:.1%} with the old key, "
        f"{new:.1%} with the new key.", "",
    ]  # fmt: skip


def _saturation_text(sat: dict[str, dict[str, float]]) -> list[str]:
    a, b = sat["C4"], sat["C4s"]
    return [
        "Under the new key the fused score C4 sits at its floor of the calibrated p-value (the "
        f"maximum score) for {a['fault_free']:.1%} of fault-free and {a['faulty']:.1%} of faulty "
        f"validation windows (C4s: {b['fault_free']:.1%} and {b['faulty']:.1%}). The 95th "
        "percentile of fault-free scores is then the maximum, no score exceeds it, and the alarm "
        "rule gives no alarm at all; false-alarm rate and recall of C4 are zero by construction, "
        "not a measurement of the detector. AP and AUROC remain defined (with ties).", "",
    ]  # fmt: skip


def render(old: dict[str, Any], new: dict[str, Any], old_work: Path, new_work: Path) -> list[str]:
    """Markdown for the re-run of C3 and C4 with the new key."""
    om = json.loads((old_work / "meta.json").read_text())
    nm = json.loads((new_work / "meta.json").read_text())
    th = ["model", "fault type", "faulty windows", "old key", "new key", "change"]
    return [
        *_intro(om, nm),
        *table(["model", "metric", "old key", "new key", "change"], metric_rows(old, new)),
        "**Recall at the 5% false-alarm threshold by fault type, C3 and C4:**", "",
        *table(th, type_rows(old, new, ["C3", "C4"])),
        "**Shuffle control (mean and 2.5% to 97.5% range under permuted labels):**", "",
        *table(["model", "metric", "old key", "new key"], shuffle_rows(old, new)),
        "**Placebo (positions 1 to 5, label = fault later in the episode), matched AUROC:**", "",
        *table(["model", "old key", "new key", "change"], placebo_rows(old_work, new_work)),
        "**Largest contributors to the score on faulty windows:**", "",
        *table(["model", "old key", "new key"], contributors(old, new, ["C1", "C2b", "C3", "C4"])),
        *_saturation_text(saturation(new_work)),
    ]  # fmt: skip
