"""Attach validity-window identifiers to observation rows by time.

Inputs: observation rows (agent-visible schema) and the validity-window records of the same
episode (hidden). Outputs: copies of the observation rows with the key
``validity_window_ids``, the identifiers of the windows that contain the sample time.
Key assumptions:
    * Evaluation side only. The audited ``observation_audit`` schema is closed and has no field
      for this, so the join is made by time here instead of being stored in the audit row.
    * A window contains a sample if ``t_start_s <= t_sim_s <= t_end_s`` (the sample time, not
      the availability time). A window without an end is open to the end of the episode.
    * The input rows are not modified; the joined rows are evaluator data and must never be
      served.

Source: ``docs/design_decisions.md`` D25.
"""

from __future__ import annotations

import bisect
import gzip
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

WINDOW_FILE = "validity_windows.jsonl.gz"


def load_windows(episode_directory: Path) -> list[dict[str, Any]]:
    """The hidden window records of an episode, in file order."""
    with gzip.open(episode_directory / WINDOW_FILE, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def attach_window_ids(
    observations: Iterable[dict[str, Any]], windows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Copies of the observation rows with ``validity_window_ids`` (sorted ids, maybe empty)."""
    ordered = sorted(windows, key=lambda w: (w["t_start_s"], w["window_id"]))
    starts = [w["t_start_s"] for w in ordered]
    joined = []
    for row in observations:
        t = row["t_sim_s"]
        upto = bisect.bisect_right(starts, t)
        ids = sorted(
            w["window_id"] for w in ordered[:upto] if w["t_end_s"] is None or t <= w["t_end_s"]
        )
        joined.append({**row, "validity_window_ids": ids})
    return joined
