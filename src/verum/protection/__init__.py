"""Independent protection logic: pure state machine and receipt interlock.

Source: ``revised/01_facility_tanks_topology.md`` section 6.3.
"""

from verum.protection.config import ProtectionConfig, load_protection_config
from verum.protection.machine import (
    AuthorisedReset,
    ProtectionEvent,
    ProtectionState,
    ResetRefused,
    Signals,
    TankProtection,
)
from verum.protection.receipt import ReceiptBlocked, assert_receipt_allowed, receiving_tanks

__all__ = [
    "AuthorisedReset",
    "ProtectionConfig",
    "ProtectionEvent",
    "ProtectionState",
    "ReceiptBlocked",
    "ResetRefused",
    "Signals",
    "TankProtection",
    "assert_receipt_allowed",
    "load_protection_config",
    "receiving_tanks",
]
