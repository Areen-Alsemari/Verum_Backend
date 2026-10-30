"""Campaign seeds and the fixed seeds of the named scenarios.

The seed of an episode is the first 64-bit word of the state of a seed sequence built from the
campaign seed and the episode index. No two episodes of a campaign share a seed, and each shipped
scenario has its own fixed seed. The expected seed is recomputed with numpy directly, and the
distinctness checks are structural.

See D41.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from verum.seeds import assert_distinct, campaign_seeds, episode_seed
from verum.sim.scenario import load_scenario


def test_the_seed_is_the_first_word_of_the_spawned_sequence() -> None:
    """The episode seed equals the first word of the spawned seed sequence for several campaigns and
    indices. Independent: yes, because the expected seed is recomputed with numpy directly.
    """
    for campaign, index in ((7, 0), (7, 1), (20261101, 41), (2**40, 9999)):
        sequence = np.random.SeedSequence(entropy=campaign, spawn_key=(index,))
        assert episode_seed(campaign, index) == int(sequence.generate_state(1, dtype=np.uint64)[0])
    assert episode_seed(7, 3) == episode_seed(7, 3)  # a pure function
    assert episode_seed(7, 3) != episode_seed(8, 3) and episode_seed(7, 3) != episode_seed(7, 4)


def test_no_two_episodes_of_a_campaign_share_a_seed() -> None:
    """No two of 20000 episodes of a campaign share a seed. Independent: yes, because the check
    counts distinct values.
    """
    for campaign in (1, 20261101):
        seeds = campaign_seeds(campaign, 20000)
        assert len(set(seeds)) == len(seeds) == 20000
    assert not set(campaign_seeds(1, 2000)) & set(campaign_seeds(2, 2000))


def test_the_check_fails_when_two_episodes_share_a_seed() -> None:
    """The distinctness check accepts distinct seeds and refuses a list with a repeated seed.
    Independent: yes, because the lists are written out in the test.
    """
    assert_distinct([1, 2, 3])
    with pytest.raises(ValueError, match="share the seed"):
        assert_distinct([5, 9, 5])
    seeds = campaign_seeds(3, 10)
    seeds[7] = seeds[2]  # an injected collision
    with pytest.raises(ValueError, match="episodes 2 and 7"):
        assert_distinct(seeds)


def test_negative_numbers_are_refused() -> None:
    """A negative campaign seed or episode index is refused. Independent: yes, because the expected
    outcome is the validation rule.
    """
    with pytest.raises(ValueError):
        episode_seed(-1, 0)
    with pytest.raises(ValueError):
        episode_seed(1, -1)


def test_every_shipped_scenario_has_its_own_fixed_seed(root: Path) -> None:
    """The 14 shipped scenarios each have their own fixed seed. Independent: yes, because the check
    counts distinct values in the scenario files.
    """
    files = sorted((root / "config" / "scenarios").glob("*.json"))
    seeds = {f.stem: json.loads(f.read_text())["seed"] for f in files}
    assert len(seeds) == 14  # the eleven shipped scenarios and the three v2 copies
    assert_distinct(list(seeds.values()))
    assert all(load_scenario(name).seed == seed for name, seed in seeds.items())
    assert all(isinstance(seed, int) and seed >= 0 for seed in seeds.values())
