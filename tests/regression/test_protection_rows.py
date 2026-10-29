"""Hidden protection rows: the true level is labelled, the detector input is its own field.

Inputs: the written S0u-E episode. Outputs: pass/fail.
Key assumptions:
    * The hidden field ``true_level_m`` of a ``protection_state`` row is the true tank level,
      the same number as the ``tank_state`` row at the same instant; it is not what the alarm
      sees (the level-transmitter chain, decision D40) or what the trip sees (the detector).
    * ``independent_level_m`` is the level the independent detector sees: the true level plus
      the fixed offset of the episode (decision D33), which the trip event records.
Independence: the offset is read from the event record and the levels from separate rows.

Source: ``docs/design_decisions.md`` D33, D40.
"""

from __future__ import annotations

import gzip
import json

import pytest

from sim_helpers import protection_rows
from verum.sim.episode import EpisodeResult


def test_true_level_is_labelled_and_matches_the_tank_row(
    episodes: dict[str, EpisodeResult],
) -> None:
    rows, tank_level = protection_rows(episodes["S0u-E"].directory, "TK-101")
    assert len(rows) > 3000
    for t, payload in rows:
        assert "process_level_m" not in payload
        assert payload["true_level_m"] == pytest.approx(tank_level[t], abs=1e-12)


def test_independent_level_is_the_true_level_plus_the_detector_offset(
    episodes: dict[str, EpisodeResult],
) -> None:
    directory = episodes["S0u-E"].directory
    with gzip.open(directory / "events.jsonl.gz", "rt") as handle:
        trip = next(
            e for e in map(json.loads, handle) if e["payload"].get("kind") == "HIGH_HIGH_TRIP"
        )
    offset = trip["payload"]["detector_offset_m"]
    rows, _ = protection_rows(directory, "TK-101")
    for _t, payload in rows[::50]:
        assert payload["independent_level_m"] - payload["true_level_m"] == pytest.approx(
            offset, abs=1e-12
        )
