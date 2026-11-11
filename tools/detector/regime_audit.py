"""Read-only check: which fields define the lineup regime and does a fault change them?

The regime key of the first experiment is the state of the 16 on/off tags of a window. This
module shows, per fault type, how often the key of a faulty window is one that no fault-free
train window has, which tags differ from the nearest fault-free key, and whether the key changes
inside one episode when the fault begins.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import guard
from conditions import read_conditions
from fitting import MIN_REGIME
from windows import BOOL_TAGS, FAULT_TYPES, Windows, load_split

Key = tuple[int, ...]


def nearest(key: Key, pool: list[Key]) -> tuple[Key, list[str]]:
    """The fault-free key with the fewest differing tags, and the names of those tags."""
    best = min(pool, key=lambda k: sum(a != b for a, b in zip(key, k, strict=True)))
    diff = [t for t, a, b in zip(BOOL_TAGS, key, best, strict=True) if a != b]
    return best, diff


def episode_change(w: Windows) -> dict[str, list[int]]:
    """Per fault type: windows whose key differs from the same episode's fault-free key, and total.

    The reference is the most common key of the episode's fault-free windows.
    """
    by_ep: dict[str, Counter[Key]] = {}
    for e, f, k in zip(w.episodes, w.faulty, w.lineup, strict=True):
        if f == 0:
            by_ep.setdefault(e, Counter())[k] += 1
    out = {t: [0, 0] for t in FAULT_TYPES}
    for e, f, k, t in zip(w.episodes, w.faulty, w.lineup, w.kind, strict=True):
        if f == 1 and e in by_ep:
            out[t][1] += 1
            out[t][0] += k != by_ep[e].most_common(1)[0][0]
    return out


def audit(rel: Path) -> dict[str, Any]:
    """Counts behind the statement about the regime key, for train and validation."""
    guard.install()
    result: dict[str, Any] = {"fields": list(BOOL_TAGS), "min_windows": MIN_REGIME}
    train = load_split(rel, "train")
    guard.ALLOWED_EPISODES.update(train.episodes)
    pool = sorted({k for k, f in zip(train.lineup, train.faulty, strict=True) if f == 0})
    known = set(pool)
    for name, w in (("train", train), ("validation", load_split(rel, "validation"))):
        rows: dict[str, Any] = {}
        for t in FAULT_TYPES:
            idx = [i for i in range(len(w.ids)) if w.kind[i] == t]
            unseen = [i for i in idx if w.lineup[i] not in known]
            flips: Counter[str] = Counter()
            for i in unseen:
                flips.update(nearest(w.lineup[i], pool)[1])
            rows[t] = {
                "windows": len(idx),
                "key_never_fault_free": len(unseen),
                "tags_differing": dict(flips.most_common(6)),
            }
        rows["same_episode_change"] = episode_change(w)
        result[name] = rows
    result["fault_free_keys_in_train"] = len(known)
    val = load_split(rel, "validation")
    guard.ALLOWED_EPISODES.update(val.episodes)
    result["conditions"] = condition_table(train, val, rel)
    return result


def condition_table(train: Windows, val: Windows, rel: Path) -> dict[str, Any]:
    """Windows and episodes per operator-set regime (atmosphere, temperature, flow set point)."""
    conds = read_conditions(rel, [*train.episodes, *val.episodes])
    rows: dict[tuple[str, float, float], list[int]] = {}
    for tag, w in (("train", train), ("validation", val)):
        seen: set[str] = set()
        for e, f in zip(w.episodes, w.faulty, strict=True):
            row = rows.setdefault(conds[e].regime, [0] * 6)
            base = 0 if tag == "train" else 2
            row[base + int(f)] += 1
            if e not in seen:
                seen.add(e)
                row[4 + (tag == "validation")] += 1
    stress = Counter((c.stress, c.temperature_c == 45.0) for c in conds.values())
    table = [
        {"regime": list(k), "train_fault_free": v[0], "train_faulty": v[1], "val_fault_free": v[2],
         "val_faulty": v[3], "episodes_train": v[4], "episodes_validation": v[5],
         "own_baseline": v[0] >= MIN_REGIME}
        for k, v in sorted(rows.items())
    ]  # fmt: skip
    return {"regimes": table, "stress_vs_45C": {str(k): n for k, n in stress.items()}}


def run(rel: Path, out: Path) -> None:
    """Write the audit as JSON."""
    out.write_text(json.dumps(audit(rel), indent=1))
