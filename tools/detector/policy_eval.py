"""Episode-level metrics of an alarm policy, with shuffle and placebo controls.

Episode rates are bootstrapped by resampling whole episodes; an episode counts once however many
of its windows are drawn, so each window carries the weight one over the episode size.
"""

from __future__ import annotations

from typing import Any

import metrics as m
import numpy as np
from policies import WINDOWS_PER_DAY, Bools, Episodes, Floats
from windows import FAULT_TYPES

SEED = 20261108
RESAMPLES = 1000
PERMUTATIONS = 200


class Context:
    """Shared resamples and episode weights of one set."""

    def __init__(self, e: Episodes) -> None:
        groups = list(e.order)
        self.res = m.make_resamples(groups, RESAMPLES, SEED)
        self.idx = np.concatenate(groups)
        size = np.asarray([len(o) for o in e.order], dtype=np.float64)
        self.w = 1.0 / size[e.eid]


def ratio(num: Floats, den: Floats, c: Context) -> list[float]:
    """Point value and 95% interval of a ratio of sums over resampled episodes."""

    def f(i: m.Ints) -> float:
        total = den[i].sum()
        return float(num[i].sum() / total) if total > 0 else float("nan")

    return [round(v, 4) for v in m.interval(f, c.idx, c.res)]


def _per_episode(e: Episodes, flag: Bools, window_mask: Bools) -> Bools:
    """True where an episode has a flagged window among the masked ones."""
    return np.asarray([bool((flag[o] & window_mask[o]).any()) for o in e.order], dtype=bool)


def false_alarms(e: Episodes, a: Bools, c: Context) -> dict[str, Any]:
    """Fault-free episodes with any alarm, and the window-level alarm rate on fault-free windows."""
    free_ep = ~e.ep_faulty
    any_alarm = _per_episode(e, a, np.ones(len(a), dtype=bool))
    num = (any_alarm & free_ep)[e.eid].astype(np.float64) * c.w
    den = free_ep[e.eid].astype(np.float64) * c.w
    ff = (e.y == 0).astype(np.float64)
    rate = ratio(a * ff, ff, c)
    return {
        "fault_free_episodes": int(free_ep.sum()), "alarmed": int((any_alarm & free_ep).sum()),
        "share": ratio(num, den, c), "window_rate": rate,
        "per_day": [round(v * WINDOWS_PER_DAY, 2) for v in rate],
    }  # fmt: skip


def detection(e: Episodes, a: Bools, c: Context) -> dict[str, Any]:
    """Episode detection rate (alarming at a faulty window), overall and by episode type."""
    hit = _per_episode(e, a, e.y == 1)
    types = np.asarray(e.ep_type)
    out: dict[str, Any] = {}
    for name in ("all", *FAULT_TYPES):
        sel = e.ep_faulty if name == "all" else types == name
        den = sel[e.eid].astype(np.float64) * c.w
        out[name] = {"n": int(sel.sum()), "detected": int((hit & sel).sum()),
                     "rate": ratio((hit & sel)[e.eid] * c.w, den, c)}  # fmt: skip
    return out


def delays(e: Episodes, a: Bools) -> dict[str, Any]:
    """Quartiles of first alarming faulty cutoff minus the earliest onset, and the misses."""
    values, missed = [], 0
    for i, o in enumerate(e.order):
        if not e.ep_faulty[i]:
            continue
        hit = o[a[o] & (e.y[o] == 1)]
        if len(hit) == 0:
            missed += 1
        else:
            values.append(float(e.cutoff[hit].min() - e.onset[i]))
    q = np.percentile(values, [25, 50, 75]).tolist() if values else [float("nan")] * 3
    return {"detected": len(values), "never": missed, "quartiles_s": [round(v, 1) for v in q]}


def window_recall(e: Episodes, a: Bools, c: Context) -> dict[str, Any]:
    """Share of faulty windows at which the policy is alarming, by window fault type."""
    out = {}
    for t in FAULT_TYPES:
        sel = (e.kind == t).astype(np.float64)
        out[t] = {"n": int(sel.sum()), "recall": ratio(a * sel, sel, c)}
    return out


def shuffle_detection(e: Episodes, a: Bools) -> list[float]:
    """Detection rate when the onsets of faulty episodes are given to random episodes."""
    rng = np.random.default_rng(SEED)
    onsets = e.onset[e.ep_faulty]
    count = len(onsets)
    rates = []
    for _ in range(PERMUTATIONS):
        chosen = rng.choice(len(e.order), size=count, replace=False)
        given = rng.permutation(onsets)
        hits = [bool((a[e.order[i]] & (e.cutoff[e.order[i]] >= t)).any())
                for i, t in zip(chosen, given, strict=True)]  # fmt: skip
        rates.append(float(np.mean(hits)))
    lo, hi = np.percentile(rates, [2.5, 97.5])
    return [round(float(np.mean(rates)), 4), round(float(lo), 4), round(float(hi), 4)]


def placebo_rate(e: Episodes, a: Bools, c: Context) -> list[float]:
    """Alarming rate at fault-free positions 1 to 5: episodes with a later fault minus others."""
    early = ((e.stage <= 5) & (e.y == 0)).astype(np.float64)
    later = e.ep_faulty[e.eid].astype(np.float64)

    def diff(i: m.Ints) -> float:
        out = []
        for mask in (later, 1.0 - later):
            den = (early * mask)[i].sum()
            out.append((a * early * mask)[i].sum() / den if den > 0 else float("nan"))
        return float(out[0] - out[1])

    return [round(v, 4) for v in m.interval(diff, c.idx, c.res)]
