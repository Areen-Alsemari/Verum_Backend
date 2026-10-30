"""The sixteen static operating lineups and their classification.

The topology contract does not carry lineups, so the table has its own configuration, and every
element it names is checked against the topology. Classification maps a valve and pump state to the
modes it matches or raises with a reason. Four modes have identical valve and pump states, so a
state matches all four and which applies is a property of the sequence. Rejection reasons are
checked in a fixed order so that the most specific one is reported. Routes not in the table are
disabled until added by change control.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.contracts.topology import Topology
from verum.graph import Lineup

FILENAME: Final = "lineups.json"
RECEIPT_INLETS: Final = ("XV-R101", "XV-R102", "XV-R103")
TANK_OUTLETS: Final = ("XV-S101", "XV-S102", "XV-S103")

BOTH_PUMPS = "both_pumps_running"
THREE_INLETS = "three_receipt_inlets_open"
MULTIPLE_OUTLETS = "more_than_one_outlet_open"
NOT_IN_TABLE = "lineup_not_in_table"
UNKNOWN_ELEMENT = "unknown_element"


class LineupRejected(Exception):
    """Raised for a valve and pump state that is not an allowed lineup."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class Mode:
    """One named lineup."""

    name: str
    open_valves: frozenset[str]
    running_pumps: frozenset[str]

    @property
    def lineup(self) -> Lineup:
        return Lineup(self.open_valves, self.running_pumps)

    @property
    def receiving(self) -> bool:
        return "XV-R000" in self.open_valves

    @property
    def delivering(self) -> bool:
        return bool(self.running_pumps)

    @property
    def all_closed(self) -> bool:
        return not self.open_valves and not self.running_pumps


@dataclass(frozen=True)
class LineupTable:
    """All modes, with the names of the hold states."""

    modes: dict[str, Mode]
    hold_states: tuple[str, ...]

    def mode(self, name: str) -> Mode:
        try:
            return self.modes[name]
        except KeyError:
            raise LineupRejected(NOT_IN_TABLE, f"unknown mode {name!r}") from None

    def matching(
        self, open_valves: Collection[str], running_pumps: Collection[str]
    ) -> tuple[str, ...]:
        """Names of every mode with exactly this valve and pump state."""
        valves, pumps = frozenset(open_valves), frozenset(running_pumps)
        return tuple(
            m.name
            for m in self.modes.values()
            if m.open_valves == valves and m.running_pumps == pumps
        )

    def classify(
        self,
        open_valves: Collection[str],
        running_pumps: Collection[str],
        topology: Topology,
    ) -> tuple[str, ...]:
        """Modes matching a state, or ``LineupRejected`` with the reason."""
        valves, pumps = frozenset(open_valves), frozenset(running_pumps)
        _reject_unknown(valves, pumps, topology)
        if len(pumps) > 1:
            raise LineupRejected(BOTH_PUMPS, f"running pumps {sorted(pumps)}")
        if all(v in valves for v in RECEIPT_INLETS):
            raise LineupRejected(THREE_INLETS, "XV-R101, XV-R102 and XV-R103 are all open")
        outlets = sorted(valves & set(TANK_OUTLETS))
        if len(outlets) > 1:
            raise LineupRejected(MULTIPLE_OUTLETS, f"open outlets {outlets}")
        found = self.matching(valves, pumps)
        if not found:
            raise LineupRejected(NOT_IN_TABLE, f"open {sorted(valves)}, running {sorted(pumps)}")
        return found


def _reject_unknown(valves: frozenset[str], pumps: frozenset[str], topology: Topology) -> None:
    known_valves = {n for n in topology.nodes if n.startswith("XV-")}
    unknown = (valves - known_valves) | (pumps - set(topology.pumps))
    if unknown:
        raise LineupRejected(UNKNOWN_ELEMENT, f"{sorted(unknown)}")


def parse_lineup_table(raw: Mapping[str, Any], topology: Topology) -> LineupTable:
    """Validate a decoded lineup file against the topology."""
    modes_raw = raw.get("modes")
    holds = raw.get("hold_states")
    if not isinstance(modes_raw, dict) or not isinstance(holds, list):
        raise ContractError("lineups: 'modes' and 'hold_states' are required")
    modes: dict[str, Mode] = {}
    for name, body in modes_raw.items():
        mode = Mode(name, frozenset(body["open_valves"]), frozenset(body["running_pumps"]))
        try:
            _reject_unknown(mode.open_valves, mode.running_pumps, topology)
        except LineupRejected as exc:
            raise ContractError(f"lineups: mode {name} names {exc}") from exc
        modes[name] = mode
    if not set(holds) <= set(modes):
        raise ContractError("lineups: a hold state is not a mode")
    return LineupTable(modes=modes, hold_states=tuple(holds))


def load_lineup_table(topology: Topology, directory: Path | None = None) -> LineupTable:
    """Load and validate the lineup table."""
    path = (directory or config_dir()) / FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return parse_lineup_table(raw, topology)
