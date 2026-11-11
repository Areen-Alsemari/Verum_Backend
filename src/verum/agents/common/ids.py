"""Deterministic identifiers for analyses and reports.

An analysis identifier names one case at one revision. A report identifier starts with the role key,
so it can be told apart from source evidence, whose identifiers may not start with a role key.
Both are derived from message content only, so a repeated run of the same request gives the same
identifiers.
"""

from __future__ import annotations

from verum.agents.common.numbers import stable_hash
from verum.agents.common.roles import ROLES, require_role

HASH_CHARACTERS = 8


def analysis_id(case_id: str, revision: int) -> str:
    """Return the analysis identifier of a case at a revision."""
    if not case_id:
        raise ValueError("a case identifier is required")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("a revision is a nonnegative integer")
    return f"AN-{case_id}-r{revision}"


def report_id(role: str, analysis: str, request_id: str) -> str:
    """Return the report identifier for the answer of a role to a request."""
    require_role(role)
    if not analysis or not request_id:
        raise ValueError("an analysis and a request identifier are required")
    digest = stable_hash({"request_id": request_id, "agent": role})
    return f"{role}-{analysis}-{digest[:HASH_CHARACTERS]}"


def has_report_prefix(identifier: str) -> bool:
    """Whether an identifier begins like a report identifier."""
    return identifier.startswith(tuple(f"{role}-" for role in ROLES))


def require_source_id(identifier: str) -> str:
    """Return a source evidence identifier, or raise if it could be mistaken for a report."""
    if not identifier:
        raise ValueError("an evidence identifier is required")
    if has_report_prefix(identifier):
        raise ValueError("source evidence identifiers cannot start with a role key")
    return identifier
