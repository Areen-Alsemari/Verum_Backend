"""Markdown tables for the grouped cross-validation results (Phase B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv_eval
import evaluate as ev
import numpy as np
from windows import FAULT_TYPES

# label, folder, label of the system it is compared with, candidate it adds
CHAIN = [
    ("B0", "B0", None, "baseline"),
    ("E1", "E1", "B0", "E1 set-point-conditioned baselines"),
    ("E1+E2", "E1_E2", "E1", "E2 mass balance with flow terms"),
    ("E1+E3", "E1_E3", "E1", "E3 related sensor pair residuals"),
    ("E1+E4", "E1_E4", "E1", "E4 out-of-sample calibration"),
]
TAGS = {"oof": "grouped CV (out of fold, train)", "val": "validation (held-out combinations)"}


def f3(v: list[float]) -> str:
    """Point value and interval, three decimals."""
    return f"{v[0]:.3f} ({v[1]:.3f} to {v[2]:.3f})"


def load(root: Path) -> dict[str, dict[str, Any]]:
    """Results of every system of the chain."""
    return {lab: json.loads((root / d / "results.json").read_text()) for lab, d, _, _ in CHAIN}


def decisions(root: Path) -> dict[str, dict[str, Any]]:
    """Paired differences against the previous system and the keep decision."""
    out = {}
    for lab, d, prev, _ in CHAIN:
        if prev is None:
            continue
        pd = next(x[1] for x in CHAIN if x[0] == prev)
        diff = {t: cv_eval.compare_systems(root / pd, root / d, t) for t in ("oof", "val")}
        out[lab] = {"against": prev, "diff": diff, "keep": cv_eval.keep_rule(diff["oof"])}
    return out


def kept_chain(dec: dict[str, dict[str, Any]]) -> list[str]:
    """Labels of the systems that stay, in order."""
    return ["B0"] + [lab for lab, v in dec.items() if v["keep"]]


def discrimination_rows(res: dict[str, Any], tag: str, labels: list[str]) -> list[list[str]]:
    """AP, AUROC and matched AUROC of the fused score of each system."""
    rows = []
    for lab in labels:
        d = res[lab][tag]["C4"]["discrimination"]
        rows.append([lab, f3(d["ap"]), f3(d["auroc"]), f3(d["matched_auroc"])])
    return rows


def component_rows(res: dict[str, Any], tag: str, lab: str) -> list[list[str]]:
    """Components of one system and the condition-only reference."""
    rows = []
    for name in ("C1n", "C2a", "C2b", "C3", "C4", "prior"):
        d = res[lab][tag][name]["discrimination"]
        rows.append([name, f3(d["ap"]), f3(d["auroc"]), f3(d["matched_auroc"])])
    return rows


def paired_rows(dec: dict[str, dict[str, Any]]) -> list[list[str]]:
    """Paired differences of the fused score and the decision."""
    rows = []
    for lab, v in dec.items():
        o, a = v["diff"]["oof"], v["diff"]["val"]
        verdict = "kept" if v["keep"] else "dropped"
        rows.append([lab, v["against"], f3(o["ap"]), f3(o["matched_auroc"]), verdict,
                     f3(a["ap"]), f3(a["matched_auroc"])])  # fmt: skip
    return rows


def operating_rows(res: dict[str, Any], tag: str, labels: list[str]) -> list[list[str]]:
    """False alarms, recall, delay and localisation of the fused score at the 5% threshold."""
    rows = []
    for lab in labels:
        r = res[lab][tag]
        c4, loc = r["C4"], r["localisation"]
        al = c4["alarms_at_5pct_far"]
        q = c4["delay"]["quartiles_s"]
        rows.append([lab, f3(al["far"]), c4["false_alarms_per_day"], f3(al["recall_all"]),
                     " / ".join(f"{v:.0f}" for v in q),
                     f"{c4['delay']['never_alarmed']}/{c4['delay']['episodes']}",
                     f3(loc["top1"]), f3(loc["top3"])])  # fmt: skip
    return rows


def type_rows(res: dict[str, Any], tag: str, picks: list[tuple[str, str]]) -> list[list[str]]:
    """Recall by fault type for chosen (system, score) pairs."""
    rows = []
    for t in FAULT_TYPES:
        cells = [
            res[lab][tag][name]["alarms_at_5pct_far"]["recall_by_type"][t] for lab, name in picks
        ]
        rows.append([t, cells[0]["n"], *[f3(c["recall"]) for c in cells]])
    return rows


def control_rows(res: dict[str, Any], tag: str, labels: list[str]) -> list[list[str]]:
    """Shuffle mean, placebo and the constant-column flags of the fused score."""
    rows = []
    for lab in labels:
        r = res[lab][tag]
        sh = r["C4"]["shuffle"]
        flags = ", ".join(r["constant_columns"]) or "none"
        rows.append([lab, f"{sh['ap'][0]:.3f}", f"{sh['auroc'][0]:.3f}",
                     f"{sh['matched'][0]:.3f}", f3(r["C4"]["placebo"]), flags])  # fmt: skip
    return rows


def contributor_rows(res: dict[str, Any], tag: str, labels: list[str]) -> list[list[str]]:
    """Top contributors of C3 and C4 per system."""
    rows = []
    for lab in labels:
        for name in ("C3", "C4"):
            top = ", ".join(f"{k} {v:.2f}" for k, v in res[lab][tag][name]["top_contributors"][:4])
            rows.append([lab, name, top])
    return rows


def versus_c3(root: Path, final: str, base: str) -> dict[str, Any]:
    """Paired difference: the final fused score minus C3 alone of the baseline system."""
    out = {}
    for tag in ("oof", "val"):
        d0 = np.load(root / base / f"{tag}.npz")
        d1 = np.load(root / final / f"{tag}.npz")
        meta = json.loads((root / base / f"{tag}_meta.json").read_text())
        c = ev.Context(d0, meta)
        out[tag] = cv_eval.paired(d1["score_C4"].astype(float), d0["score_C3"].astype(float), c)
    return out
