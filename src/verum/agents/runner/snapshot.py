"""The inputs of one analysis: an observation summary, the reference and what has been supplied.

A snapshot is immutable, so a later analysis never edits an earlier one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    """One case at one revision and cutoff, with everything the request builders may use."""

    case_id: str
    revision: int
    as_of_s: float
    summary: dict[str, Any]
    reference: dict[str, Any]
    reference_snapshot_sha256: str
    source_sha256: str | None = None
    query_asset_ids: tuple[str, ...] | None = None
    direction: str = "both"
    history: tuple[dict[str, Any], ...] = ()
    inspection_results: tuple[dict[str, Any], ...] = ()
    inspection_requests: tuple[dict[str, Any], ...] = ()
    process_coverage: tuple[dict[str, Any], ...] = ()
    constraint_checks: tuple[dict[str, Any], ...] = ()
    budget: dict[str, Any] | None = None
    evidence_proposals: tuple[dict[str, Any], ...] = ()

