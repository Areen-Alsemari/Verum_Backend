"""The plan of a campaign: what kind of episode each slot is.

The plan is built in blocks of fixed composition, so that a block, and every block before it, is the
same whatever the target size. A block holds exact numbers of healthy, single-fault, pair and
branched slots and of latent, switch, stress and audit marks. Subtypes, pair types and branched
kinds are spread equally over the whole campaign in rounds, each round with its own random stream.

See D83, D84, D85, D151 and D152.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from verum.rng import RandomStreams

SUBTYPES = (
    "leak", "restriction_position_visible", "restriction_obstruction", "pump",
    "bias", "drift", "stuck", "misroute_a", "misroute_b",
)  # fmt: skip
MAIN_SUBTYPES = tuple(s for s in SUBTYPES if s != "misroute_b")
PAIR_TYPES = ("physical_physical", "physical_sensor", "sensor_sensor", "leak_restriction")
BRANCH_KINDS = ("healthy", "misroute_b", "misroute_a")
LATENT_SUBTYPES = ("pump", "restriction_position_visible", "restriction_obstruction", "misroute_a")
NO_SWITCH_SUBTYPES = ("pump",)
SWITCH_PAIR_TYPES = ("physical_sensor", "sensor_sensor", "leak_restriction")
EPISODE_STRIDE = 5  # attempts per slot; the seed of an attempt follows slot * 5 + attempt


@dataclass(frozen=True)
class Block:
    size: int = 100
    healthy: int = 18
    single: int = 56
    pair: int = 20
    branched: int = 6
    latent: int = 3
    switch: int = 9
    stress: int = 8
    audit: int = 10

    def __post_init__(self) -> None:
        if self.healthy + self.single + self.pair + self.branched != self.size:
            raise ValueError("the kinds of a block must add up to its size")


@dataclass(frozen=True)
class CampaignConfig:
    seed: int
    n: int
    block: Block = field(default_factory=Block)
    duration_s: float = 3600.0

    @property
    def subtypes(self) -> tuple[str, ...]:
        return MAIN_SUBTYPES


@dataclass(frozen=True)
class Slot:
    index: int
    kind: str  # healthy, single, pair or branched
    subtype: str | None = None
    pair_type: str | None = None
    branch: str | None = None
    latent: bool = False
    switch: bool = False
    stress: bool = False
    audit: bool = False


def _spread(
    values: tuple[str, ...], ordinals: range, config: CampaignConfig, name: str
) -> list[str]:
    """The value of each ordinal: equal counts in every round of ``len(values)`` ordinals."""
    out = []
    for k in ordinals:
        rng = RandomStreams(config.seed).stream(f"campaign/plan/{name}/round{k // len(values)}")
        out.append(values[int(rng.permutation(len(values))[k % len(values)])])
    return out


def _pick(candidates: list[int], count: int, rng: np.random.Generator) -> set[int]:
    count = min(count, len(candidates))
    return {candidates[i] for i in rng.permutation(len(candidates))[:count]}


def _block(config: CampaignConfig, b: int) -> list[Slot]:
    """The slots of block ``b``."""
    blk = config.block
    rng = RandomStreams(config.seed).stream(f"campaign/plan/block{b}")
    kinds = (
        ["healthy"] * blk.healthy + ["single"] * blk.single + ["pair"] * blk.pair
        + ["branched"] * blk.branched
    )  # fmt: skip
    kinds = [kinds[i] for i in rng.permutation(blk.size)]
    singles = iter(_spread(MAIN_SUBTYPES, range(b * blk.single, (b + 1) * blk.single), config, "s"))
    pairs = iter(_spread(PAIR_TYPES, range(b * blk.pair, (b + 1) * blk.pair), config, "p"))
    branches = iter(
        _spread(BRANCH_KINDS, range(b * blk.branched, (b + 1) * blk.branched), config, "b")
    )
    base: list[tuple[str, str | None, str | None, str | None]] = []
    for kind in kinds:
        base.append((
            kind,
            next(singles) if kind == "single" else None,
            next(pairs) if kind == "pair" else None,
            next(branches) if kind == "branched" else None,
        ))  # fmt: skip
    latent = _pick([i for i, x in enumerate(base) if x[1] in LATENT_SUBTYPES], blk.latent, rng)
    can_switch = [
        i
        for i, (kind, sub, pair, _branch) in enumerate(base)
        if kind == "healthy"
        or (kind == "single" and (sub not in NO_SWITCH_SUBTYPES or i in latent))
        or (kind == "pair" and pair in SWITCH_PAIR_TYPES)
    ]
    switch = _pick(can_switch, blk.switch, rng)
    stress = _pick([i for i, x in enumerate(base) if x[0] != "branched"], blk.stress, rng)
    audit = _pick(list(range(blk.size)), blk.audit, rng)
    return [
        Slot(b * blk.size + i, kind, sub, pair, branch, i in latent, i in switch, i in stress,
             i in audit)
        for i, (kind, sub, pair, branch) in enumerate(base)
    ]  # fmt: skip


def build_plan(config: CampaignConfig) -> list[Slot]:
    """The slot of every index of the campaign: whole blocks, cut at the target size."""
    blocks = -(-config.n // config.block.size)
    return [s for b in range(blocks) for s in _block(config, b)][: config.n]
