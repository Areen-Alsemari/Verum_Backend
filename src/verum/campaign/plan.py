"""The plan of a campaign: what kind of episode each index is.

The plan is a function of the campaign seed, the target size and the shares alone. It fixes the
number of healthy, single-fault and pair episodes exactly, spreads the subtypes and the pair types
equally, and marks the latent, switch, stress and audit episodes, so that every worker computes the
same plan and the counts do not depend on the order in which episodes finish.

See D83, D84, D85 and D87.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from verum.rng import RandomStreams

SUBTYPES = (
    "leak", "restriction_position_visible", "restriction_obstruction", "pump",
    "bias", "drift", "stuck", "misroute_a", "misroute_b",
)  # fmt: skip
PAIR_TYPES = ("physical_physical", "physical_sensor", "sensor_sensor", "leak_restriction")
LATENT_SUBTYPES = ("pump", "restriction_position_visible", "restriction_obstruction", "misroute_a")
NO_SWITCH_SUBTYPES = ("pump", "misroute_b")
SWITCH_PAIR_TYPES = ("physical_sensor", "sensor_sensor", "leak_restriction")


@dataclass(frozen=True)
class Shares:
    healthy: float = 0.20
    single: float = 0.60
    pair: float = 0.20


@dataclass(frozen=True)
class CampaignConfig:
    seed: int
    n: int
    shares: Shares = field(default_factory=Shares)
    duration_s: float = 3600.0
    latent_share: float = 0.04
    stress_share: float = 0.08
    switch_share: float = 0.09
    audit_share: float = 0.10
    parallel_branch: bool = False  # misrouting (b) needs a branched lineup, which carries a window

    @property
    def subtypes(self) -> tuple[str, ...]:
        return SUBTYPES if self.parallel_branch else tuple(s for s in SUBTYPES if s != "misroute_b")


@dataclass(frozen=True)
class Slot:
    index: int
    kind: str  # healthy, single or pair
    subtype: str | None = None
    pair_type: str | None = None
    latent: bool = False
    switch: bool = False
    stress: bool = False
    audit: bool = False


def _cycle(values: tuple[str, ...], count: int, rng: np.random.Generator) -> list[str]:
    """``count`` values spread equally over ``values`` and shuffled."""
    chosen = [values[i % len(values)] for i in range(count)]
    return [chosen[i] for i in rng.permutation(count)]


def _pick(candidates: list[int], count: int, rng: np.random.Generator) -> set[int]:
    count = min(count, len(candidates))
    return {candidates[i] for i in rng.permutation(len(candidates))[:count]}


def build_plan(config: CampaignConfig) -> list[Slot]:
    """The slot of every index of the campaign."""
    rng = RandomStreams(config.seed).stream("campaign/plan")
    n, shares = config.n, config.shares
    n_healthy, n_pair = round(shares.healthy * n), round(shares.pair * n)
    kinds = ["healthy"] * n_healthy + ["pair"] * n_pair + ["single"] * (n - n_healthy - n_pair)
    kinds = [kinds[i] for i in rng.permutation(n)]
    subtypes = iter(_cycle(config.subtypes, kinds.count("single"), rng))
    pair_types = iter(_cycle(PAIR_TYPES, kinds.count("pair"), rng))
    base: list[tuple[str, str | None, str | None]] = []
    for kind in kinds:
        if kind == "single":
            base.append((kind, next(subtypes), None))
        else:
            base.append((kind, None, next(pair_types) if kind == "pair" else None))
    faulted = [i for i, b in enumerate(base) if b[0] != "healthy"]
    latent = _pick(
        [i for i in faulted if base[i][1] in LATENT_SUBTYPES],
        int(config.latent_share * len(faulted)),
        rng,
    )
    can_switch = [
        i
        for i, (kind, sub, pair) in enumerate(base)
        if (kind == "healthy")
        or (kind == "single" and (sub not in NO_SWITCH_SUBTYPES or i in latent))
        or (kind == "pair" and pair in SWITCH_PAIR_TYPES)
    ]
    switch = _pick(can_switch, int(config.switch_share * n), rng)
    stress = _pick(list(range(n)), int(config.stress_share * n), rng)
    audit = _pick(list(range(n)), int(config.audit_share * n), rng)
    return [
        Slot(i, kind, sub, pair, i in latent, i in switch, i in stress, i in audit)
        for i, (kind, sub, pair) in enumerate(base)
    ]
