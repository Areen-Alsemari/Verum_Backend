"""The eight role keys, in the order of the interface manifest.

Role keys name the agent subpackages, the message schemas and the example messages. The tuple is
defined once here and checked against the manifest by a test.
"""

from __future__ import annotations

from typing import Final

ROLES: Final[tuple[str, ...]] = (
    "predictive_health",
    "anomaly_detection",
    "topology_dependency",
    "historical_asset_intelligence",
    "diagnostic_reasoning",
    "inspection_planning",
    "inspection_quality_documentation",
    "evidence_verification_decision",
)


def require_role(role: str) -> str:
    """Return the role key, or raise if it is not one of the eight roles."""
    if role not in ROLES:
        raise ValueError(f"unknown agent role {role!r}")
    return role
