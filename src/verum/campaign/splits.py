"""Train, validation and test splits of a campaign.

The unit of a split is the scenario family times the atmosphere times the temperature. Units that
hold at least 2.5 percent of the plan are held out, up to 8 percent together, and one asset of each
subtype is held out (an asset and family pair if the subtype has fewer than four assets). The shares
come from the cells of a reference prefix of the plan, so they do not depend on the target size.

See D86 and D155.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from verum.campaign.eligibility import SENSOR_TAGS, leak_pool
from verum.campaign.plan import SUBTYPES, CampaignConfig
from verum.campaign.sampler import Cell
from verum.faults.validate import ELIGIBLE_VALVES, PUMPS
from verum.rng import RandomStreams

Unit = tuple[str, str, float]
REFERENCE_SLOTS = 2000
MIN_UNIT_SHARE = 0.025
HELD_OUT_SHARE = 0.08
VALIDATION_SHARE = 0.30
MIN_ASSETS = 4
PAIR_FAMILIES: dict[str, tuple[str, ...]] = {
    "pump": ("delivery", "concurrent"),
    "misroute_b": ("branched",),
}


@dataclass(frozen=True)
class SplitPlan:
    test_units: frozenset[Unit]
    validation_units: frozenset[Unit]
    held_assets: dict[str, tuple[str, str | None]]
    held_share: float
    unit_shares: dict[Unit, float]


def unit_shares(cells: Sequence[Cell]) -> dict[Unit, float]:
    """Share of the slots in each unit, from their cells."""
    counts = Counter(c.unit for c in cells)
    return {u: n / len(cells) for u, n in sorted(counts.items())}


def asset_pool(subtype: str) -> list[str]:
    if subtype == "leak":
        return leak_pool()
    if subtype == "pump":
        return sorted(PUMPS)
    if subtype in ("bias", "drift", "stuck"):
        return list(SENSOR_TAGS)
    if subtype == "misroute_b":
        return ["XV-R101", "XV-R102"]
    return sorted(ELIGIBLE_VALVES)


def _held_assets(rng: np.random.Generator) -> dict[str, tuple[str, str | None]]:
    held: dict[str, tuple[str, str | None]] = {}
    for subtype in SUBTYPES:
        pool = asset_pool(subtype)
        asset = pool[int(rng.integers(len(pool)))]
        if len(pool) >= MIN_ASSETS:
            held[subtype] = (asset, None)
        else:
            families = PAIR_FAMILIES[subtype]
            held[subtype] = (asset, families[int(rng.integers(len(families)))])
    return held


def build_split_plan(config: CampaignConfig, cells: Sequence[Cell]) -> SplitPlan:
    """Held-out units and assets, drawn from the campaign seed, from the reference cells."""
    rng = RandomStreams(config.seed).stream("campaign/splits")
    shares = unit_shares(cells)
    order = sorted(shares)
    order = [order[i] for i in rng.permutation(len(order))]
    eligible = [u for u in order if shares[u] >= MIN_UNIT_SHARE]
    test: set[Unit] = set()
    for unit in eligible:
        if sum(shares[u] for u in test) >= HELD_OUT_SHARE:
            break
        test.add(unit)
    if sum(shares[u] for u in test) < HELD_OUT_SHARE:
        raise ValueError("the units of at least 2.5 percent of the plan hold less than 8 percent")
    rest = [u for u in order if u not in test]
    target = VALIDATION_SHARE * sum(shares[u] for u in rest)
    validation: set[Unit] = set()
    for unit in rest:
        if sum(shares[u] for u in validation) >= target:
            break
        validation.add(unit)
    held_share = sum(shares[u] for u in test)
    return SplitPlan(frozenset(test), frozenset(validation), _held_assets(rng), held_share, shares)


def split_of(plan: SplitPlan, unit: Unit, faults: list[tuple[str, str]]) -> str:
    """Split of an episode from its unit and its (subtype, asset) pairs."""
    if unit in plan.test_units or any(_is_held(plan, unit[0], s, a) for s, a in faults):
        return "test"
    return "validation" if unit in plan.validation_units else "train"


def _is_held(plan: SplitPlan, family: str, subtype: str, asset: str) -> bool:
    held_asset, held_family = plan.held_assets[subtype]
    return asset == held_asset and held_family in (None, family)
