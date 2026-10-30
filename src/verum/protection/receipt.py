"""Receipt interlock: protection must permit receipt into every connected tank.

A mode receives into the tank of every open receipt inlet valve. Receipt is permitted only while the
protection of each such tank is normal or in high alarm; an unavailable protection or a latched trip
blocks it. A mode that does not receive is never blocked.
"""

from __future__ import annotations

from collections.abc import Mapping

from verum.lineups import Mode
from verum.protection.machine import TankProtection


class ReceiptBlocked(Exception):
    """Raised when protection does not permit normal receipt."""


def receiving_tanks(mode: Mode) -> tuple[str, ...]:
    """Tanks that a mode receives into."""
    return tuple(f"TK-{v[-3:]}" for v in sorted(mode.open_valves) if v.startswith("XV-R1"))


def assert_receipt_allowed(mode: Mode, protections: Mapping[str, TankProtection]) -> None:
    """Raise ``ReceiptBlocked`` if any receiving tank lacks permitting protection."""
    for tank in receiving_tanks(mode):
        protection = protections.get(tank)
        if protection is None:
            raise ReceiptBlocked(f"{mode.name}: no protection configured for {tank}")
        if not protection.normal_receipt_permitted:
            raise ReceiptBlocked(f"{mode.name}: {tank} protection is {protection.state.value}")
