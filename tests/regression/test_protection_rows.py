"""Hidden protection rows: the true level is labelled and the detector input is its own field.

The true level in a protection row equals the tank level at the same instant and is not what the
alarm or the trip sees. The independent level is the true level plus the fixed offset of the
episode, which the trip event records.

See D33 and D40.
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
    """The true level of each protection row equals the tank level of the row at the same instant.
    Independent: yes, because the levels are read from separate rows.
    """
    rows, tank_level = protection_rows(episodes["S0u-E"].directory, "TK-101")
    assert len(rows) > 3000
    for t, payload in rows:
        assert "process_level_m" not in payload
        assert payload["true_level_m"] == pytest.approx(tank_level[t], abs=1e-12)


def test_independent_level_is_the_true_level_plus_the_detector_offset(
    episodes: dict[str, EpisodeResult],
) -> None:
    """The independent level of each protection row equals the true level plus the detector offset
    recorded in the trip event. Independent: yes, because the offset is read from the event record
    and the levels from separate rows.
    """
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
