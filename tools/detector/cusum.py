"""Two-sided CUSUM on the raw 300-second series of the numeric tags, computed in parallel.

The raw rows are selected by simulation time only. Arrival time, quality flag and availability
status are not read as inputs. Each worker opens only the episodes it is given.
"""

from __future__ import annotations

import gzip
import json
import math
from multiprocessing import Pool
from pathlib import Path

import guard
import numpy as np
from numpy.typing import NDArray
from windows import NUMERIC_TAGS

REFERENCE_K = 0.5
WINDOW_S = 300.0
WindowJob = tuple[int, float, list[float], list[float]]
Task = tuple[str, str, list[WindowJob]]
WORKER_GUARD: dict[str, int] = {"allowed_opens": 0, "rejected": 0}


def cusum_max(
    values: NDArray[np.float64], mu: float, sigma: float, k: float = REFERENCE_K
) -> float:
    """Largest value of the two-sided CUSUM statistic of a standardised series."""
    if len(values) == 0:
        return float("nan")
    z = (values - mu) / sigma
    best = 0.0
    for sign in (1.0, -1.0):
        walk = np.r_[0.0, np.cumsum(sign * z - k)]
        best = max(best, float(np.max(walk - np.minimum.accumulate(walk))))
    return best


def _series(path: Path) -> dict[str, tuple[NDArray[np.float64], NDArray[np.float64]]]:
    rows: dict[str, list[tuple[float, float]]] = {t: [] for t in NUMERIC_TAGS}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            tag = row["tag_id"]
            value = row["value"]
            if tag in rows and isinstance(value, (int, float)) and math.isfinite(value):
                rows[tag].append((float(row["t_sim_s"]), float(value)))
    out = {}
    for tag, items in rows.items():
        arr = np.asarray(sorted(items), dtype=np.float64).reshape(-1, 2)
        out[tag] = (arr[:, 0], arr[:, 1])
    return out


def episode_task(args: Task) -> tuple[list[tuple[int, list[float], list[float]]], int]:
    """Statistics of every requested window of one episode."""
    root, episode, windows = args
    data = _series(Path(root) / "observations" / episode / "observations.jsonl.gz")
    out = []
    for index, cutoff, mu, sigma in windows:
        stats, means = [], []
        for j, tag in enumerate(NUMERIC_TAGS):
            t, v = data[tag]
            sel = v[(t >= cutoff - WINDOW_S) & (t < cutoff)]
            stats.append(cusum_max(sel, mu[j], sigma[j]))
            means.append(float(sel.mean()) if len(sel) else float("nan"))
        out.append((index, stats, means))
    return out, len(guard.REJECTED)


def _init(episodes: list[str]) -> None:
    guard.ALLOWED_EPISODES.update(episodes)
    guard.install()


def compute(
    root: Path,
    episodes: list[str],
    cutoffs: NDArray[np.float64],
    mu: NDArray[np.float64],
    sigma: NDArray[np.float64],
    procs: int = 8,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """CUSUM maximum and raw window mean per window and tag, given centre and scale vectors."""
    jobs: dict[str, list[WindowJob]] = {}
    for i, name in enumerate(episodes):
        jobs.setdefault(name, []).append((i, float(cutoffs[i]), list(mu[i]), list(sigma[i])))
    tasks = [(str(root), name, items) for name, items in sorted(jobs.items())]
    out = np.full((len(episodes), len(NUMERIC_TAGS)), np.nan)
    raw = out.copy()
    with Pool(procs, initializer=_init, initargs=(sorted(jobs),)) as pool:
        for result, rejected in pool.imap_unordered(episode_task, tasks, chunksize=8):
            WORKER_GUARD["allowed_opens"] += 1
            WORKER_GUARD["rejected"] = max(WORKER_GUARD["rejected"], rejected)
            for index, stats, means in result:
                out[index], raw[index] = stats, means
    return out, raw
