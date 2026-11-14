"""Markdown for the regime evidence of Amendment 2, built from the audit result."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from windows import FAULT_TYPES


def table(head: list[str], rows: Sequence[Sequence[object]]) -> list[str]:
    """Markdown table lines."""
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    return [*out, *["| " + " | ".join(str(c) for c in r) + " |" for r in rows], ""]


def fault_rows(res: dict[str, Any], split: str) -> list[list[object]]:
    """One row per fault type: how often the lineup key is a fault-free key."""
    rows = []
    for t in FAULT_TYPES:
        r = res[split][t]
        d, n = res[split]["same_episode_change"][t]
        flips = ", ".join(f"{k} {v}" for k, v in r["tags_differing"].items()) or "-"
        rows.append([split, t, r["windows"], r["key_never_fault_free"], f"{d}/{n}", flips])
    return rows


def key_section(res: dict[str, Any]) -> list[str]:
    """The old key and what a fault does to it."""
    head = ["split", "fault type", "windows", "key never fault-free", "own-episode change",
            "tags that differ from the nearest fault-free key"]  # fmt: skip
    return [
        "# Regime key: evidence for Amendment 2", "",
        "## The key of the first experiment", "",
        "The regime key behind the 200-window guard and the per-regime baselines of C1, C2 and "
        "C3 (R4) was the state of the 16 on/off tags of the window, taken from `latest_value`: "
        f"{', '.join(res['fields'])}. These are level switches, pump run states and valve "
        "contact states. A fault can change them: the restriction mode `position_visible` and "
        "misrouting act on valve positions.", "",
        "Windows whose key no fault-free train window has, and windows whose key differs from "
        "the most common key of the same episode's fault-free windows (own-episode change):", "",
        *table(head, fault_rows(res, "train") + fault_rows(res, "validation")),
        "Restriction and misrouting windows carry a key that no fault-free window has, and the "
        "differing tags are valve states (`XV-*`). Pump, bias, drift, stuck and leak windows "
        "have keys that fault-free windows also have. So the key contains fault effects for "
        "two fault types, and a baseline or guard built on it separates those windows by "
        "construction.", "",
    ]  # fmt: skip


def condition_section(res: dict[str, Any]) -> list[str]:
    """The new key and its regimes."""
    cond = res["conditions"]
    regs = cond["regimes"]
    own = [r for r in regs if r["own_baseline"]]
    total = sum(r["train_fault_free"] for r in regs)
    val_all = sum(r["val_fault_free"] + r["val_faulty"] for r in regs)
    pooled = sum(r["val_fault_free"] + r["val_faulty"] for r in regs if not r["own_baseline"])
    rows = [
        [" / ".join(str(x) for x in r["regime"]), r["episodes_train"], r["episodes_validation"],
         r["train_fault_free"], r["train_faulty"], r["val_fault_free"], r["val_faulty"],
         "yes" if r["own_baseline"] else "no"]
        for r in regs
    ]  # fmt: skip
    head = ["atmosphere / temperature C / set point m3/h", "episodes train", "episodes validation",
            "train fault-free", "train faulty", "validation fault-free", "validation faulty",
            "own baseline (200 or more train fault-free)"]  # fmt: skip
    return [
        "## The new key: operator-set conditions", "",
        "Atmosphere, temperature and flow set point of the episode. The stress flag is a set "
        f"condition and equals temperature 45 C in every episode ({cond['stress_vs_45C']}), so "
        "it adds nothing to the key. A fault changes none of these fields.", "",
        *table(head, rows),
        f"{len(regs)} regimes occur; {len(own)} have 200 or more fault-free train windows and "
        f"hold {sum(r['train_fault_free'] for r in own)} of {total} fault-free train windows. "
        f"{pooled} of {val_all} validation windows are in regimes without an own baseline and "
        "use the pooled baseline.", "",
    ]  # fmt: skip


def render(res: dict[str, Any]) -> str:
    """The whole evidence document."""
    return "\n".join(key_section(res) + condition_section(res))
