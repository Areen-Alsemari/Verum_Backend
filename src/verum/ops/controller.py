"""Operations controller: a scripted schedule of timed and reactive commands.

The controller is the only issuer of valve and receipt commands. Protection logic only requests
isolation, and a reactive schedule entry turns the request into closure commands after a configured
delay. Lineup changes pass through the hold states and may not change which pump is running. A
reactive valve command acts on valves directly and leaves the recorded lineup mode unchanged. The
schedule is data and has no randomness.

See D6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verum.lineups import LineupController, LineupTable
from verum.ops.commands import Command, ValveOrder, _make_command, _make_order


@dataclass(frozen=True)
class ReactiveEntry:
    """Respond to a protection event on a tank after a delay."""

    on_event: str
    tank: str
    delay_s: float
    valves: tuple[str, ...]


def _command_from(entry: dict[str, Any], source: str) -> Command:
    kind = entry["command"]
    t = float(entry.get("t_s", 0.0))
    if kind == "receipt_setpoint":
        return _make_command(
            t_s=t, kind="receipt_setpoint", setpoint_m3h=float(entry["value_m3h"]), source=source
        )
    if kind == "lineup":
        return _make_command(t_s=t, kind="lineup", mode=str(entry["mode"]), source=source)
    if kind in ("open_valves", "close_valves"):
        valves = tuple((v, kind == "open_valves") for v in entry["valves"])
        return _make_command(t_s=t, kind="valves", valves=valves, source=source)
    raise ValueError(f"unknown schedule command {kind!r}")


class OperationsController:
    """Holds the schedule and the lineup state machine."""

    def __init__(
        self, table: LineupTable, initial_mode: str, schedule: list[dict[str, Any]]
    ) -> None:
        self._table = table
        self.lineup = LineupController(table, initial_mode)
        self._timed = sorted(
            (_command_from(e, "schedule") for e in schedule if "t_s" in e), key=lambda c: c.t_s
        )
        self._reactive = [
            ReactiveEntry(e["on"], e["tank"], float(e.get("delay_s", 0.0)), tuple(e["valves"]))
            for e in schedule
            if "on" in e
        ]

    @property
    def timed_commands(self) -> tuple[Command, ...]:
        return tuple(self._timed)

    def react(self, event_kind: str, tank: str, t_s: float) -> list[Command]:
        """Commands that a protection event triggers, with their execution times."""
        commands = []
        for entry in self._reactive:
            if entry.on_event == event_kind and entry.tank == tank:
                valves = tuple((v, False) for v in entry.valves)
                commands.append(
                    _make_command(
                        t_s=t_s + entry.delay_s,
                        kind="valves",
                        valves=valves,
                        source=f"reactive:{event_kind}:{tank}",
                    )
                )
        return commands

    def resolve(
        self, command: Command, valve_open: dict[str, bool], running: frozenset[str]
    ) -> list[ValveOrder]:
        """Valve orders for a command; a lineup command also advances the lineup state."""
        if command.kind == "valves":
            return [_make_order(v, o) for v, o in command.valves]
        if command.kind != "lineup":
            return []
        assert command.mode is not None
        target = self._table.mode(command.mode)
        if target.running_pumps != running and not (target.all_closed and not running):
            raise ValueError("a lineup change must not start or stop a pump (decision D6)")
        self.lineup.request(command.mode)
        wanted = target.open_valves
        return [
            _make_order(v, v in wanted)
            for v in sorted(valve_open)
            if valve_open[v] != (v in wanted)
        ]
