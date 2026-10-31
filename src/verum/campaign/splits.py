"""Train, validation and test splits of a campaign.

The unit of a split is the scenario family times the atmosphere times the temperature. Some whole
units are held out for test, and in addition one asset of each fault subtype is held out. An episode
is test if its unit is held out or if any of its faults is on a held-out asset; the other units are
split between train and validation.

See D86.
"""

from __future__ import annotations

from dataclasses import dataclass

from verum.campaign.eligibility import SENSOR_TAGS, leak_pool
from verum.campaign.plan import CampaignConfig
from verum.campaign.sampler import FAMILIES, FAMILY_WEIGHTS, TEMPERATURE_WEIGHTS, TEMPERATURES
from verum.faults.validate import ELIGIBLE_VALVES, PUMPS
from verum.rng import RandomStreams

Unit = tuple[str, str, float]
TEST_UNIT_WEIGHT = 0.10
VALIDATION_SHARE = 0.30
ATMOSPHERES = ("coastal", "inland")
TEMPERATURE_CHOICES = (*TEMPERATURES, 45.0)


@dataclass(frozen=True)
class SplitPlan:
    test_units: frozenset[Unit]
    validation_units: frozenset[Unit]
    held_assets: dict[str, str]


def unit_weights() -> dict[Unit, float]:
    """Expected share of the episodes in each unit."""
    family = {**FAMILY_WEIGHTS, "switch": 0.09}
    temperature = dict(zip(TEMPERATURES, TEMPERATURE_WEIGHTS, strict=True)) | {45.0: 0.0}
    raw = {
        (f, a, t): family[f] * 0.5 * (temperature[t] * 0.92 + (0.08 if t == 45.0 else 0.0))
        for f in FAMILIES
        for a in ATMOSPHERES
        for t in TEMPERATURE_CHOICES
    }
    total = sum(raw.values())
    return {u: w / total for u, w in raw.items()}


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


def build_split_plan(config: CampaignConfig) -> SplitPlan:
    """Held-out units and assets, drawn from the campaign seed."""
    rng = RandomStreams(config.seed).stream("campaign/splits")
    weights = unit_weights()
    order = [u for u in sorted(weights)]
    order = [order[i] for i in rng.permutation(len(order))]
    test: set[Unit] = set()
    for unit in order:
        if test and sum(weights[u] for u in test) >= TEST_UNIT_WEIGHT:
            break
        test.add(unit)
    rest = [u for u in order if u not in test]
    validation: set[Unit] = set()
    target = VALIDATION_SHARE * sum(weights[u] for u in rest)
    for unit in rest:
        if sum(weights[u] for u in validation) >= target:
            break
        validation.add(unit)
    held = {}
    for subtype in config.subtypes:
        pool = asset_pool(subtype)
        held[subtype] = pool[int(rng.integers(len(pool)))]
    return SplitPlan(frozenset(test), frozenset(validation), held)


def split_of(plan: SplitPlan, unit: Unit, faults: list[tuple[str, str]]) -> str:
    """Split of an episode from its unit and its (subtype, asset) pairs."""
    if unit in plan.test_units or any(plan.held_assets[s] == a for s, a in faults):
        return "test"
    return "validation" if unit in plan.validation_units else "train"
