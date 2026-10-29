"""Lineup transitions, allowed only through the hold states.

Inputs: a ``LineupTable`` and requested mode changes. Outputs: a boolean for a
single step, or a ``LineupController`` that tracks the current mode and rejects
invalid steps with ``TransitionRejected``.
Key assumptions:
    * The audited table documents two chains: receipt switching
      ``RECEIVE_i -> SWITCH_RECEIPT_HOLD -> RECEIVE_j`` and pump changeover
      ``DELIVER_i_A -> CHANGEOVER_HOLD -> DELIVER_i_B``. The remaining rules are
      this module's reading of "transitions only through the hold states":
        - a step between two all-closed states (IDLE, MAINTENANCE_ISOLATED, a
          hold) needs no valve motion and is allowed;
        - an active mode (valves open or a pump running) is entered from, and
          left to, a hold state only, never directly from or to another mode;
        - SWITCH_RECEIPT_HOLD serves modes that open XV-R000, and
          CHANGEOVER_HOLD serves modes that run a pump;
        - leaving CHANGEOVER_HOLD for a delivery mode keeps the source tank of
          the last delivery mode before the hold.
    * These extra rules are proposals pending team confirmation. They do not
      model timing; valve and pump motion is a hydraulic-phase matter.
    * The controller changes a recorded mode only. It is not a handle that
      moves any valve.

Source: ``revised/01_facility_tanks_topology.md`` section 6.2 (receipt
switching and pump changeover paragraph).
"""

from __future__ import annotations

import re

from verum.lineups.table import LineupRejected, LineupTable, Mode

_DELIVER = re.compile(r"^DELIVER_(\d{3})_[AB]$")
_COMBINED = re.compile(r"^RECEIVE_\d{3}_DELIVER_(\d{3})_[AB]$")


class TransitionRejected(Exception):
    """Raised for a mode change that does not go through a hold state."""


def source_tank(mode_name: str) -> str | None:
    """Tank number the mode delivers from, or None if it does not deliver."""
    for pattern in (_DELIVER, _COMBINED):
        match = pattern.match(mode_name)
        if match:
            return match.group(1)
    return None


def step_allowed(table: LineupTable, source: str, target: str) -> bool:
    """Whether one step is allowed, ignoring the tank-continuity rule."""
    a, b = table.mode(source), table.mode(target)
    if a.name == b.name:
        return False
    if a.all_closed and b.all_closed:
        return True
    if a.all_closed and not b.all_closed:
        return _hold_serves(table, a, b)
    if b.all_closed and not a.all_closed:
        return _hold_serves(table, b, a)
    return False


def _hold_serves(table: LineupTable, hold: Mode, active: Mode) -> bool:
    if hold.name == "SWITCH_RECEIPT_HOLD":
        return active.receiving
    if hold.name == "CHANGEOVER_HOLD":
        return active.delivering
    return False


class LineupController:
    """Current mode plus the memory the continuity rule needs."""

    def __init__(self, table: LineupTable, initial: str = "IDLE") -> None:
        table.mode(initial)
        self._table = table
        self._current = initial
        self._last_source: str | None = source_tank(initial)

    @property
    def current(self) -> str:
        return self._current

    def request(self, target: str) -> str:
        """Move to ``target`` if the step is allowed; return the new mode."""
        try:
            allowed = step_allowed(self._table, self._current, target)
        except LineupRejected as exc:
            raise TransitionRejected(str(exc)) from exc
        if not allowed:
            raise TransitionRejected(
                f"{self._current} -> {target} does not go through a hold state"
            )
        self._check_continuity(target)
        self._current = target
        if source_tank(target) is not None:
            self._last_source = source_tank(target)
        return target

    def _check_continuity(self, target: str) -> None:
        wanted = source_tank(target)
        if self._current == "CHANGEOVER_HOLD" and wanted is not None:
            if self._last_source is not None and wanted != self._last_source:
                raise TransitionRejected(
                    f"changeover must keep source tank {self._last_source}, not {wanted}"
                )
