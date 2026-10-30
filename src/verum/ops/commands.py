"""Commands and valve orders issued by the operations controller.

Only the operations package creates these objects: the constructors require a token that no other
module imports, and a static test checks that. A command is data and changes nothing by itself,
since the engine executes the valve orders and receipt set-points it resolves to. Commanded state,
actual position and physical closure are different things, and a command sets only the commanded
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

_TOKEN: Final = object()
KINDS: Final = ("receipt_setpoint", "lineup", "valves")


@dataclass(frozen=True)
class ValveOrder:
    """Order to drive one valve to open (True) or closed (False)."""

    valve: str
    open: bool
    _issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _TOKEN:
            raise PermissionError("valve orders are issued only by the operations controller")


@dataclass(frozen=True)
class Command:
    """A timed command: a receipt set-point, a lineup mode or a list of valve orders."""

    t_s: float
    kind: str
    mode: str | None = None
    setpoint_m3h: float | None = None
    valves: tuple[tuple[str, bool], ...] = ()
    source: str = "schedule"
    _issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _TOKEN:
            raise PermissionError("commands are issued only by the operations controller")
        if self.kind not in KINDS:
            raise ValueError(f"unknown command kind {self.kind!r}")
        if self.t_s < 0:
            raise ValueError("a command time must not be negative")


def _make_command(**kwargs: object) -> Command:
    return Command(_issuer=_TOKEN, **kwargs)  # type: ignore[arg-type]


def _make_order(valve: str, is_open: bool) -> ValveOrder:
    return ValveOrder(valve, is_open, _issuer=_TOKEN)
