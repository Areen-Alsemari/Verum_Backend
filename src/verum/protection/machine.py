"""Independent high-level protection state machine for one tank.

Inputs: injected signals only (process level, independent level and its
validity, power availability, observed closure evidence, observed receipt
flow) and explicit authorised reset events. Outputs: the state, a latched-trip
flag and timestamped events, including the *request* to close valves.
Key assumptions:
    * Pure logic. There is no hydraulics, no clock and no valve handle: the
      machine records that closure is requested, and only injected closure
      evidence can move it to confirmed. A request is not a closure.
    * The trip is decided on the independent level signal alone. The process
      (LT) signal can raise the high alarm but never trips and cannot block a
      trip, so a drifting LT does not defeat the independent layer.
    * One transition per update. A trip enters HIGH_HIGH and the next update
      enters ISOLATION_REQUESTED; the timeout runs from the trip time.
    * Confirmation needs both closure evidence for every requested valve and an
      observed receipt flow at or below the residual threshold. After the
      timeout, anything short of that fails the isolation.
    * PROTECTION_UNAVAILABLE is entered only from NORMAL or HIGH_ALARM; once a
      trip is latched, the latch and its isolation sequence are not lost when a
      signal is later declared invalid.
    * The latch clears only on an authorised reset from operations or
      protection, with the independent signal valid and below the trip level.
      No agent can reset, bypass or command a valve through this module.

Source: ``revised/01_facility_tanks_topology.md`` section 6.3 (state machine and
required protection tests); ``docs/design_decisions.md`` D12 and D13.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from verum.protection.config import ProtectionConfig


class ProtectionState(StrEnum):
    NORMAL = "NORMAL"
    HIGH_ALARM = "HIGH_ALARM"
    HIGH_HIGH = "HIGH_HIGH"
    ISOLATION_REQUESTED = "ISOLATION_REQUESTED"
    CONFIRMED_ISOLATED = "CONFIRMED_ISOLATED"
    FAILED_ISOLATION = "FAILED_ISOLATION"
    PROTECTION_UNAVAILABLE = "PROTECTION_UNAVAILABLE"


LATCHED = frozenset(
    {
        ProtectionState.HIGH_HIGH,
        ProtectionState.ISOLATION_REQUESTED,
        ProtectionState.CONFIRMED_ISOLATED,
        ProtectionState.FAILED_ISOLATION,
    }
)
RECEIPT_PERMITTED = frozenset({ProtectionState.NORMAL, ProtectionState.HIGH_ALARM})
RESET_SOURCES = frozenset({"operations", "protection"})


class ResetRefused(Exception):
    """Raised when a reset is not authorised or its safe predicates do not hold."""


@dataclass(frozen=True)
class Signals:
    """Injected inputs for one update."""

    t_s: float
    process_level_m: float | None
    independent_level_m: float | None
    independent_valid: bool = True
    power_ok: bool = True
    closed_confirmed: Mapping[str, bool] | None = None
    receipt_flow_m3h: float | None = None


@dataclass(frozen=True)
class AuthorisedReset:
    """A reset event from operations or protection; anything else is refused."""

    source: str
    authoriser: str
    t_s: float


@dataclass(frozen=True)
class ProtectionEvent:
    """A timestamped output; ``requested_valves`` is filled for a closure request."""

    t_s: float
    kind: str
    detail: str = ""
    requested_valves: tuple[str, ...] = ()


class TankProtection:
    """State machine for the protection of one tank."""

    def __init__(self, config: ProtectionConfig) -> None:
        self._config = config
        # Resolve the timing now so that an unresolved parameter stops start-up.
        self._timeout_s = config.timeout_s()
        self._threshold = config.residual_flow_threshold_m3h
        self._state = ProtectionState.NORMAL
        self._trip_t_s: float | None = None
        self._last_t_s = 0.0
        self._ever_confirmed: set[str] = set()
        self.events: list[ProtectionEvent] = []

    # --- read-only views ---------------------------------------------------------
    @property
    def state(self) -> ProtectionState:
        return self._state

    @property
    def trip_latched(self) -> bool:
        return self._state in LATCHED

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    @property
    def normal_receipt_permitted(self) -> bool:
        """False while unavailable or after a trip; true in NORMAL and HIGH_ALARM."""
        return self._state in RECEIPT_PERMITTED

    # --- update --------------------------------------------------------------------
    def update(self, signals: Signals) -> ProtectionState:
        """Apply one set of injected signals and return the new state."""
        if signals.t_s < self._last_t_s:
            raise ValueError("time must not go backwards")
        self._last_t_s = signals.t_s
        available = signals.independent_valid and signals.power_ok
        if self._state in LATCHED:
            self._advance_trip(signals)
        else:
            self._advance_untripped(signals, available)
        return self._state

    def _emit(self, t_s: float, kind: str, detail: str = "", valves: tuple[str, ...] = ()) -> None:
        self.events.append(ProtectionEvent(t_s, kind, detail, valves))

    def _advance_untripped(self, s: Signals, available: bool) -> None:
        if not available:
            if self._state is not ProtectionState.PROTECTION_UNAVAILABLE:
                self._state = ProtectionState.PROTECTION_UNAVAILABLE
                self._emit(
                    s.t_s, "PROTECTION_UNAVAILABLE", "independent signal invalid or power lost"
                )
            return
        if self._state is ProtectionState.PROTECTION_UNAVAILABLE:
            self._state = ProtectionState.NORMAL
            self._emit(s.t_s, "PROTECTION_AVAILABLE")
        if s.independent_level_m is not None and s.independent_level_m >= self._config.high_high_m:
            self._trip(s.t_s)
        elif s.process_level_m is not None and s.process_level_m >= self._config.high_alarm_m:
            if self._state is ProtectionState.NORMAL:
                self._state = ProtectionState.HIGH_ALARM
                self._emit(s.t_s, "HIGH_ALARM")
        elif self._state is ProtectionState.HIGH_ALARM:
            self._state = ProtectionState.NORMAL
            self._emit(s.t_s, "ALARM_CLEARED")

    def _trip(self, t_s: float) -> None:
        self._state = ProtectionState.HIGH_HIGH
        self._trip_t_s = t_s
        self._ever_confirmed = set()
        self._emit(t_s, "HIGH_HIGH_TRIP", "independent level at or above the trip level")

    def _advance_trip(self, s: Signals) -> None:
        if self._state is ProtectionState.HIGH_HIGH:
            self._state = ProtectionState.ISOLATION_REQUESTED
            valves = self._config.isolation_valves
            self._emit(s.t_s, "ISOLATION_REQUESTED", "closure requested, not confirmed", valves)
        elif self._state is ProtectionState.ISOLATION_REQUESTED:
            self._check_isolation(s)
        elif self._state is ProtectionState.CONFIRMED_ISOLATED:
            self._check_contradiction(s)

    def _closed(self, s: Signals) -> dict[str, bool]:
        evidence = s.closed_confirmed or {}
        return {v: bool(evidence.get(v, False)) for v in self._config.isolation_valves}

    def _check_contradiction(self, s: Signals) -> None:
        closed = self._closed(s)
        withdrawn = [v for v in self._ever_confirmed if not closed[v]]
        if withdrawn:
            self._fail(s.t_s, f"contradiction: closure evidence withdrawn for {sorted(withdrawn)}")

    def _check_isolation(self, s: Signals) -> None:
        closed = self._closed(s)
        self._check_contradiction(s)
        if self._state is ProtectionState.FAILED_ISOLATION:
            return
        self._ever_confirmed |= {v for v, c in closed.items() if c}
        flow = s.receipt_flow_m3h
        stopped = flow is not None and flow <= self._threshold
        if all(closed.values()) and stopped:
            self._state = ProtectionState.CONFIRMED_ISOLATED
            self._emit(s.t_s, "ISOLATION_CONFIRMED", "closure evidence and flow stop observed")
            return
        assert self._trip_t_s is not None
        if s.t_s - self._trip_t_s >= self._timeout_s:
            self._fail(s.t_s, self._failure_reason(closed, flow))

    def _failure_reason(self, closed: Mapping[str, bool], flow: float | None) -> str:
        if flow is not None and flow > self._threshold:
            return f"residual flow {flow:g} m3/h above {self._threshold:g} m3/h after the timeout"
        if not all(closed.values()):
            missing = sorted(v for v, c in closed.items() if not c)
            return f"timeout without closure evidence for {missing}"
        return "timeout without flow evidence"

    def _fail(self, t_s: float, reason: str) -> None:
        self._state = ProtectionState.FAILED_ISOLATION
        self._emit(t_s, "ISOLATION_FAILED", reason)

    # --- reset ---------------------------------------------------------------------
    def reset(self, event: AuthorisedReset, signals: Signals) -> ProtectionState:
        """Clear a latched trip, only for an authorised event and safe predicates."""
        if event.source not in RESET_SOURCES or not event.authoriser:
            raise ResetRefused(f"reset source {event.source!r} is not authorised")
        if not self.trip_latched:
            raise ResetRefused("no latched trip to reset")
        level = signals.independent_level_m
        if not signals.independent_valid or level is None or level >= self._config.high_high_m:
            raise ResetRefused(
                "safe predicates not met: independent level valid and below trip level"
            )
        self._state = ProtectionState.NORMAL
        self._trip_t_s = None
        self._ever_confirmed = set()
        self._emit(event.t_s, "RESET", f"authorised by {event.authoriser} ({event.source})")
        return self._state
