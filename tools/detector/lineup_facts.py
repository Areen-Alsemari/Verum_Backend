"""Descriptive counts of the commanded operating mode against the injected faults.

Read-only, no model: it tabulates, for the episodes that have eligible windows, how many carry
a fault and which valves the faults are on, per commanded mode, and how strongly mode and fault
placement are associated. The mode is a campaign stratum held with the episode labels.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import conditions
import guard
import numpy as np
from numpy.typing import NDArray
from windows import load_split


def cramers_v(table: NDArray[np.float64]) -> float:
    """Cramer's V of a contingency table of counts."""
    n = table.sum()
    expected = table.sum(axis=1, keepdims=True) * table.sum(axis=0, keepdims=True) / n
    chi2 = float(((table - expected) ** 2 / np.where(expected > 0, expected, 1.0)).sum())
    dof = min(table.shape) - 1
    return float(np.sqrt(chi2 / (n * dof))) if dof > 0 else float("nan")


def per_mode(conds: dict[str, conditions.Condition]) -> dict[str, Any]:
    """Episodes, episodes with a fault and valve-fault assets, per commanded mode."""
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"episodes": 0, "with_fault": 0, "valve_faults": Counter(), "families": set()}
    )
    for c in conds.values():
        r = rows[c.mode]
        r["episodes"] += 1
        r["with_fault"] += int(bool(c.faults))
        r["families"].add(c.family)
        r["valve_faults"].update(f[1] for f in c.faults if f[1].startswith("XV-"))
    return {
        m: {**r, "valve_faults": dict(r["valve_faults"]), "families": sorted(r["families"])}
        for m, r in sorted(rows.items())
    }


def association(rows: dict[str, Any]) -> dict[str, float]:
    """Cramer's V of mode against having a fault, and of mode against the valve of a fault."""
    modes = list(rows)
    fault = np.asarray([[r["episodes"] - r["with_fault"], r["with_fault"]] for r in rows.values()])
    assets = sorted({a for r in rows.values() for a in r["valve_faults"]})
    valve = np.asarray([[rows[m]["valve_faults"].get(a, 0) for a in assets] for m in modes])
    return {
        "mode_vs_any_fault": round(cramers_v(fault.astype(np.float64)), 3),
        "mode_vs_faulty_valve": round(cramers_v(valve.astype(np.float64)), 3),
    }


def run(rel: Path, out: Path) -> dict[str, Any]:
    """Tabulate over the episodes of train and validation windows."""
    guard.install()
    val, train = load_split(rel, "validation"), load_split(rel, "train")
    guard.ALLOWED_EPISODES.update(val.episodes)
    guard.ALLOWED_EPISODES.update(train.episodes)
    conds = conditions.read_conditions(rel, [*train.episodes, *val.episodes])
    rows = per_mode(conds)
    res = {"modes": rows, "association": association(rows), "episodes": len(conds)}
    out.write_text(json.dumps(res, indent=1))
    return res
