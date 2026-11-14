"""The inputs of one analysis: an observation summary, the reference and what has been supplied.

A snapshot is immutable. A new inspection result produces a new snapshot with the next revision,
so a later analysis never edits the earlier one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    as_of_utc: str | None = None


def next_revision(
    previous: Snapshot,
    *,
    as_of_s: float,
    summary: dict[str, Any],
    inspection_results: tuple[dict[str, Any], ...],
    inspection_requests: tuple[dict[str, Any], ...] = (),
    process_coverage: tuple[dict[str, Any], ...] = (),
    as_of_utc: str | None = None,
) -> Snapshot:
    """Start the next revision because new inspection results are available.

    The observation summary must be the one prepared for the later cutoff; the earlier summary is
    never carried over, and neither is the earlier wall-clock cutoff, which is given again or left
    unset. Results, requests and coverage accumulate across revisions.
    """
    if not inspection_results:
        raise ValueError("a new revision starts with a new inspection result")
    if as_of_s < previous.as_of_s:
        raise ValueError("a revision cannot move the cutoff backwards")
    if as_of_s == previous.as_of_s or summary is previous.summary:
        raise ValueError("a new revision needs observations prepared for its own cutoff")
    return replace(
        previous,
        revision=previous.revision + 1,
        as_of_s=as_of_s,
        as_of_utc=as_of_utc,
        summary=summary,
        source_sha256=None,
        inspection_results=(*previous.inspection_results, *inspection_results),
        inspection_requests=(*previous.inspection_requests, *inspection_requests),
        process_coverage=(*previous.process_coverage, *process_coverage),
    )
