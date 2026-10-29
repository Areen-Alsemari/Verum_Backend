"""Episode seeds of a campaign.

Inputs: a campaign seed and an episode index. Outputs: the seed of the episode, a 64-bit
integer.
Key assumptions:
    * Decision D41: the seed is the first 64-bit word of the state of
      ``SeedSequence(entropy=campaign_seed, spawn_key=(episode_index,))``. It is a pure
      function of the two numbers, so any episode of a campaign can be regenerated alone.
    * Two indices of one campaign never give the same seed; ``campaign_seeds`` raises if they
      do, and ``assert_distinct`` is the same check for any list of seeds.
    * There is no global seed: the result is only handed to ``verum.rng.RandomStreams``.

Source: ``docs/design_decisions.md`` D41.
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
