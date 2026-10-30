"""Episode seeds of a campaign.

The seed of an episode is the first 64-bit word of the state of a seed sequence built from the
campaign seed and the episode index. It is a pure function of the two numbers, so any episode can be
regenerated alone, and two indices of one campaign never share a seed.

See D41.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def episode_seed(campaign_seed: int, episode_index: int) -> int:
    """Seed of episode ``episode_index`` of the campaign."""
    if campaign_seed < 0 or episode_index < 0:
        raise ValueError("the campaign seed and the episode index must not be negative")
    sequence = np.random.SeedSequence(entropy=campaign_seed, spawn_key=(episode_index,))
    return int(sequence.generate_state(1, dtype=np.uint64)[0])


def assert_distinct(seeds: Sequence[int]) -> None:
    """Raise ``ValueError`` if two seeds are equal."""
    seen: dict[int, int] = {}
    for index, seed in enumerate(seeds):
        if seed in seen:
            raise ValueError(f"episodes {seen[seed]} and {index} share the seed {seed}")
        seen[seed] = index


def campaign_seeds(campaign_seed: int, episodes: int) -> list[int]:
    """The seeds of the first ``episodes`` episodes, checked to be distinct."""
    seeds = [episode_seed(campaign_seed, i) for i in range(episodes)]
    assert_distinct(seeds)
    return seeds
