"""Sampling of one episode: the cell of its slot, then the scenario record and the faults.

The cell of a slot (family, atmosphere, temperature, subtypes and classes) is drawn from the stream
of the first attempt and is the same for every attempt. An attempt then draws the lineup, the
set-point, the initial levels inside the band that the cell allows, the assets and the severities.
Every draw comes from a named stream of the attempt seed, so an attempt is a function of the
campaign seed, the slot and the attempt number alone.

See D83 to D86, D151, D152, D153 and D154.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from verum.campaign import switch
from verum.campaign.classes import (
    AUDIT_CELL,
    NO_SEVERITY,
    RANGES,
    AuditCells,
    ClassInterval,
    ClassTable,
    asset_class,
)
from verum.campaign.eligibility import (
    PARALLEL_BRANCH_MODE,
    SENSOR_TAGS,
    LineupInfo,
    lineup_info,
)
from verum.campaign.plan import EPISODE_STRIDE, CampaignConfig, Slot
from verum.faults import FaultSpec
from verum.faults.spec import RAMPS_S
from verum.faults.validate import ELIGIBLE_VALVES
from verum.hydraulics.pumping_minimum import pumping_minimum_level, stratum_filename
from verum.params import UnresolvedParameter
from verum.rng import RandomStreams
from verum.seeds import episode_seed
from verum.tanks import load_tank_geometry, load_tank_parameters

TANKS = ("TK-101", "TK-102", "TK-103")
SETPOINTS = (300.0, 400.0, 500.0, 600.0)
TEMPERATURES = (25.0, 35.0, 40.0)
TEMPERATURE_WEIGHTS = (0.435, 0.326, 0.239)
STRESS_TEMPERATURE = 45.0
FAMILIES = ("delivery", "receipt", "concurrent", "switch", "branched")
FAMILY_WEIGHTS = {"delivery": 0.35, "receipt": 0.30, "concurrent": 0.25}
CONCURRENT_MODES = ("RECEIVE_101_DELIVER_102_A", "RECEIVE_101_DELIVER_101_A")
DELIVERY_MARGIN_M = 0.5
LEVEL_RANGE_M = (1.8, 12.0)
ONSET_MIN_S = 600.0
SEPARATION_S = 300.0
SWITCH_ONSET_MIN_S = 1300.0
PHYSICAL = ("leak", "restriction_position_visible", "restriction_obstruction", "pump")
SENSORS = ("bias", "drift", "stuck")
PHYSICAL_ALL = (*PHYSICAL, "misroute_a")
ALL_FAMILIES = ("delivery", "receipt", "concurrent")
SUBTYPE_FAMILIES: dict[str, tuple[str, ...]] = {"pump": ("delivery", "concurrent")}
BRANCH_PREFIX = {"delivery": "XV-S", "receipt": "XV-R1"}  # valves that give a second branch


class NoCandidate(Exception):
    """An attempt that cannot be built: no feasible levels, or no asset in the cell."""


@dataclass
class FaultChoice:
    subtype: str
    asset: str
    asset_class: str
    cls: str
    severity: float | None
    spec: FaultSpec
    latent: bool


@dataclass(frozen=True)
class Cell:
    family: str
    atmosphere: str
    temperature_c: float
    subtypes: tuple[str, ...]
    classes: tuple[str, ...]

    @property
    def key(self) -> str:
        faults = "+".join(f"{s}:{c}" for s, c in zip(self.subtypes, self.classes, strict=True))
        return f"{self.family}|{self.atmosphere}|{self.temperature_c:g}|{faults or 'healthy'}"

    @property
    def unit(self) -> tuple[str, str, float]:
        return (self.family, self.atmosphere, self.temperature_c)


@dataclass
class EpisodeSpec:
    index: int
    seed: int
    slot: Slot
    attempt: int
    cell: Cell
    scenario: dict[str, Any]
    faults: list[FaultChoice]
    strata: dict[str, Any]
    gaps: list[dict[str, Any]] = field(default_factory=list)


def tank_of(valve: str) -> str:
    return f"TK-{valve[-3:]}"


def receiving_tanks(info: LineupInfo) -> list[str]:
    return [tank_of(v) for v in sorted(info.open_valves) if v.startswith("XV-R1")]


def delivering_tanks(info: LineupInfo) -> list[str]:
    return [tank_of(v) for v in sorted(info.open_valves) if v.startswith("XV-S")]


def receipt_rise_m(setpoint: float) -> float:
    """Level rise in an hour at 1.06 times the set-point, with the residual and allowance."""
    p = load_tank_parameters()
    volume = 1.06 * setpoint + p["headroom_residual_delivery_m3"].value
    return volume / load_tank_geometry().area_m2 + p["headroom_level_allowance_m"].value


def level_bands(
    modes: list[str], atmosphere: str, temperature: float, setpoint: float
) -> dict[str, tuple[float, float]] | None:
    """Feasible band of each tank, or None if one tank has no level that passes."""
    bands = {t: LEVEL_RANGE_M for t in TANKS}
    for mode in modes:
        info = lineup_info(mode)
        for tank in receiving_tanks(info):
            lo, hi = bands[tank]
            bands[tank] = (lo, min(hi, LEVEL_RANGE_M[1] - receipt_rise_m(setpoint)))
        for tank in delivering_tanks(info):
            try:
                minimum = pumping_minimum_level(
                    tank, temperature, "reference_fittings", 4.0, None,
                    stratum_filename(atmosphere, "RVP_9_0", "v2"),
                ).value  # fmt: skip
            except UnresolvedParameter:
                return None
            lo, hi = bands[tank]
            bands[tank] = (max(lo, minimum + DELIVERY_MARGIN_M), hi)
    return bands if all(lo < hi for lo, hi in bands.values()) else None


class Sampler:
    def __init__(
        self, config: CampaignConfig, classes: ClassTable, audit: AuditCells | None = None
    ) -> None:
        self.config, self.classes = config, classes
        self.audit = audit if audit is not None else AuditCells()

    def cell(self, slot: Slot) -> Cell:
        """The cell of a slot, drawn from the stream of its first attempt."""
        seed = episode_seed(self.config.seed, slot.index * EPISODE_STRIDE)
        rng = RandomStreams(seed).stream("campaign/cell")
        picks = self._subtypes(slot, rng)
        family = self._family(slot, picks, rng)
        atmosphere = str(rng.choice(["coastal", "inland"]))
        temperature = (
            STRESS_TEMPERATURE
            if slot.stress
            else float(rng.choice(TEMPERATURES, p=TEMPERATURE_WEIGHTS))
        )
        classes = tuple(self._class_of(slot, s, rng) for s in picks)
        return Cell(family, atmosphere, temperature, tuple(picks), classes)

    def sample(self, slot: Slot, attempt: int) -> EpisodeSpec:
        """Attempt ``attempt`` of a slot; raises ``NoCandidate`` if the cell gives no episode."""
        cell = self.cell(slot)
        index = slot.index * EPISODE_STRIDE + attempt
        seed = episode_seed(self.config.seed, index)
        rng = RandomStreams(seed).stream("campaign/sampler")
        modes = self._modes(slot, cell, rng)
        setpoint = self._setpoint(modes, cell, rng)
        levels = self._levels(modes, cell, setpoint, rng)
        raw = self._scenario(slot, seed, modes, cell, levels, setpoint)
        info = lineup_info(modes[-1])
        faults, gaps = self._faults(slot, cell, info, rng)
        strata = {
            "family": cell.family, "atmosphere": cell.atmosphere,
            "temperature_c": cell.temperature_c, "stress": cell.temperature_c == STRESS_TEMPERATURE,
            "mode": modes[0], "setpoint_m3h": setpoint,
        }  # fmt: skip
        return EpisodeSpec(index, seed, slot, attempt, cell, raw, faults, strata, gaps)

    # --- what the episode contains ----------
    def _subtypes(self, slot: Slot, rng: np.random.Generator) -> list[str]:
        if slot.kind == "healthy":
            return []
        if slot.kind == "single":
            assert slot.subtype is not None
            return [slot.subtype]
        if slot.kind == "branched":
            return [] if slot.branch == "healthy" else [str(slot.branch)]

        def pick(options: tuple[str, ...]) -> str:
            return options[int(rng.integers(len(options)))]

        pair = str(slot.pair_type)
        physical = tuple(t for t in PHYSICAL_ALL if not (slot.switch and t == "pump"))
        if pair == "physical_physical":
            return [pick(PHYSICAL), pick(PHYSICAL[:3])]
        if pair == "physical_sensor":
            return [pick(physical), pick(SENSORS)]
        if pair == "sensor_sensor":
            return [pick(SENSORS), pick(SENSORS)]
        return ["leak", pick(PHYSICAL[1:3])]

    def _family(self, slot: Slot, picks: list[str], rng: np.random.Generator) -> str:
        if slot.kind == "branched":
            return "branched"
        if slot.switch:
            return "switch"
        allowed = set(ALL_FAMILIES)
        if slot.pair_type == "physical_physical":
            allowed = {"concurrent"}
        for subtype in picks:
            if not (slot.latent and subtype == "pump"):
                allowed &= set(SUBTYPE_FAMILIES.get(subtype, ALL_FAMILIES))
        names = [f for f in FAMILY_WEIGHTS if f in allowed]
        weights = np.array([FAMILY_WEIGHTS[f] for f in names])
        return names[int(rng.choice(len(names), p=weights / weights.sum()))]

    def _class_of(self, slot: Slot, subtype: str, rng: np.random.Generator) -> str:
        """The class of the cell for a fault: latent, read from the audit, or drawn."""
        if slot.latent:
            return "latent"
        if subtype in NO_SEVERITY:
            return AUDIT_CELL
        names = self.classes.names(subtype)
        return names[int(rng.integers(len(names)))]

    def _modes(self, slot: Slot, cell: Cell, rng: np.random.Generator) -> list[str]:
        tank = TANKS[int(rng.integers(3))][-3:]
        family = cell.family
        if family == "delivery":
            return [f"DELIVER_{tank}_{'AB'[int(rng.integers(2))]}"]
        if family == "concurrent":
            return [CONCURRENT_MODES[int(rng.integers(2))]]
        if family == "receipt":
            return [f"RECEIVE_{tank}"]
        if family == "branched":
            if slot.branch != "misroute_a":
                return [PARALLEL_BRANCH_MODE]
            if rng.random() < 0.5:
                return [f"DELIVER_{tank}_{'AB'[int(rng.integers(2))]}"]
            return [f"RECEIVE_{tank}"]
        other = [t[-3:] for t in TANKS if t[-3:] != tank]
        return [f"RECEIVE_{tank}", f"RECEIVE_{other[int(rng.integers(2))]}"]

    def _setpoint(self, modes: list[str], cell: Cell, rng: np.random.Generator) -> float:
        options: tuple[float, ...] = SETPOINTS
        if cell.family == "switch":
            options = switch.setpoints_for(f"TK-{modes[0][-3:]}", SETPOINTS)
        return float(options[int(rng.integers(len(options)))])

    def _levels(
        self, modes: list[str], cell: Cell, setpoint: float, rng: np.random.Generator
    ) -> dict[str, float]:
        bands = level_bands(modes, cell.atmosphere, cell.temperature_c, setpoint)
        if bands is None:
            raise NoCandidate(f"no feasible levels for {modes} in {cell.key}")
        return {t: float(rng.uniform(lo, hi)) for t, (lo, hi) in bands.items()}

    def _scenario(
        self, slot: Slot, seed: int, modes: list[str], cell: Cell, levels: dict[str, float],
        setpoint: float,
    ) -> dict[str, Any]:  # fmt: skip
        receiving = bool(receiving_tanks(lineup_info(modes[0])))
        schedule: list[dict[str, Any]] = []
        if len(modes) == 2:
            schedule = switch.schedule(f"RECEIVE_{modes[0][-3:]}", modes[1], setpoint)
        elif receiving:
            schedule.append({"t_s": 0.0, "command": "receipt_setpoint", "value_m3h": setpoint})
        return {
            "scenario_id": f"C{slot.index:06d}", "description": "Campaign episode.", "seed": seed,
            "duration_s": self.config.duration_s, "temperature_c": cell.temperature_c,
            "fitting_profile": "reference_fittings", "healthy_envelope": True,
            "atmosphere_stratum": cell.atmosphere, "volatility_class": "RVP_9_0",
            "demand_process": True, "variability_profile": "v2",
            "initial": {
                "mode": modes[0], "tank_levels_m": levels, "receipt_flow_m3h": 0.0,
                "receipt_setpoint_m3h": 0.0,
            },
            "schedule": schedule,
        }  # fmt: skip

    # --- faults ----------
    def _faults(
        self, slot: Slot, cell: Cell, info: LineupInfo, rng: np.random.Generator
    ) -> tuple[list[FaultChoice], list[dict[str, Any]]]:
        picks = list(cell.subtypes)
        if not picks:
            return [], []
        lo = SWITCH_ONSET_MIN_S if slot.switch else ONSET_MIN_S
        hi = self.config.duration_s - 1800.0
        onsets = self._onsets(len(picks), lo, hi, rng)
        paths = self._paths(slot, picks, info, rng)
        taken: set[str] = set()
        faults, gaps = [], []
        for subtype, cls, onset, path in zip(picks, cell.classes, onsets, paths, strict=True):
            choice, gap = self._fault(slot, subtype, cls, onset, path, info, taken, rng)
            taken.add(choice.asset)
            faults.append(choice)
            gaps += gap
        return faults, gaps

    def _onsets(self, count: int, lo: float, hi: float, rng: np.random.Generator) -> list[float]:
        if count == 1:
            return [float(round(rng.uniform(lo, hi)))]
        first = float(round(rng.uniform(lo, hi - SEPARATION_S)))
        second = float(round(rng.uniform(first + SEPARATION_S, hi)))
        return [first, second] if rng.random() < 0.5 else [second, first]

    def _paths(
        self, slot: Slot, picks: list[str], info: LineupInfo, rng: np.random.Generator
    ) -> list[str | None]:
        if slot.pair_type == "physical_physical":
            return ["delivery", "receipt"]
        if slot.pair_type == "leak_restriction":
            options = [
                p
                for p, edges, valves in (
                    ("receipt", info.receipt_edges, info.receipt_valves),
                    ("delivery", info.delivery_edges, info.delivery_valves),
                )
                if edges and valves
            ]
            path = options[int(rng.integers(len(options)))]
            return [path, path]
        return [None] * len(picks)

    def _pool(self, subtype: str, path: str | None, info: LineupInfo, slot: Slot) -> list[str]:
        latent = slot.latent
        if subtype == "leak":
            edges = {"receipt": info.receipt_edges, "delivery": info.delivery_edges}
            return edges[path] if path else sorted(info.edges)
        if subtype.startswith("restriction"):
            if latent:
                return info.idle_valves
            valves = {"receipt": info.receipt_valves, "delivery": info.delivery_valves}
            return valves[path] if path else info.receipt_valves + info.delivery_valves
        if subtype == "misroute_a":
            if latent:
                return info.receipt_valves + info.delivery_valves
            if slot.kind == "branched":
                prefix = BRANCH_PREFIX["delivery" if info.mode.startswith("DELIVER") else "receipt"]
                return [v for v in info.idle_valves if v.startswith(prefix)]
            return info.idle_valves
        if subtype == "pump":
            return info.idle_pumps if latent else sorted(info.pumps)
        if subtype == "misroute_b":
            return ["XV-R101", "XV-R102"] if info.mode == PARALLEL_BRANCH_MODE else []
        return list(SENSOR_TAGS)

    def _fault(
        self, slot: Slot, subtype: str, cls: str, onset: float, path: str | None, info: LineupInfo,
        taken: set[str], rng: np.random.Generator,
    ) -> tuple[FaultChoice, list[dict[str, Any]]]:  # fmt: skip
        anyclass = cls in ("latent", AUDIT_CELL)
        pool = [
            a
            for a in self._pool(subtype, path, info, slot)
            if a not in taken and (anyclass or self.classes.has_class(subtype, a, cls))
        ]
        if not pool:
            raise NoCandidate(f"no asset for {subtype} of class {cls} in {info.mode}")
        asset = pool[int(rng.integers(len(pool)))]
        aclass = asset_class(subtype, asset)
        severity, name = self._severity(subtype, aclass, cls, asset, info, rng)
        gaps = self.classes.gaps(subtype, aclass)
        gap = [{"subtype": subtype, "asset_class": aclass, "missing": gaps}] if gaps else []
        spec = make_spec(subtype, asset, severity, onset, rng)
        return FaultChoice(subtype, asset, aclass, name, severity, spec, slot.latent), gap

    def _severity(
        self, subtype: str, aclass: str, cls: str, asset: str, info: LineupInfo,
        rng: np.random.Generator,
    ) -> tuple[float | None, str]:  # fmt: skip
        """Severity and class name: from the interval of the cell class, or from the audit."""
        if subtype in NO_SEVERITY:
            name = "latent" if cls == "latent" else self.audit.class_of(subtype, info.mode, asset)
            return None, name
        if cls == "latent":
            lo, hi = RANGES[subtype]
            interval = ClassInterval("latent", lo, hi)
        else:
            interval = next(iv for iv in self.classes.intervals(subtype, aclass) if iv.name == cls)
        return interval.draw(float(rng.random())), interval.name


def make_spec(
    subtype: str, asset: str, severity: float | None, onset: float, rng: np.random.Generator
) -> FaultSpec:
    """The fault specification of a subtype at a severity coordinate."""
    ramp = float(RAMPS_S[int(rng.integers(len(RAMPS_S)))])
    if subtype == "leak":
        assert severity is not None
        return FaultSpec("PIPE_LEAK", "orifice", asset, onset, ramp, severity,
                         float(rng.uniform(0.05, 0.95)), 0.62)  # fmt: skip
    if subtype.startswith("restriction"):
        assert severity is not None
        mode = subtype.removeprefix("restriction_")
        return FaultSpec("VALVE_RESTRICTION", "restriction", asset, onset, ramp, 1.0 - severity,
                         fault_mode=mode)  # fmt: skip
    if subtype == "pump":
        assert severity is not None
        return FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", asset, onset, ramp, 1.0 - severity)
    if subtype == "misroute_a":
        return FaultSpec("VALVE_MISROUTING", "closed_but_open", asset, onset, ramp, 1.0)
    if subtype == "misroute_b":
        assert severity is not None
        return FaultSpec("VALVE_MISROUTING", "open_but_stuck", asset, onset, ramp, severity)
    if subtype == "stuck":
        return FaultSpec("SENSOR_DRIFT", "stuck", asset, onset, None, 0.0)
    assert severity is not None
    sign = 1.0 if rng.random() < 0.5 else -1.0
    step = None if (subtype == "drift" or rng.random() < 0.5) else ramp
    return FaultSpec("SENSOR_DRIFT", subtype, asset, onset, step, sign * severity)


__all__ = ["ELIGIBLE_VALVES", "EpisodeSpec", "FaultChoice", "Sampler", "make_spec"]
