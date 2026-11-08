
"""Deterministic admission checks for Agent 8 evidence proposals.

A proposal is usable only when time, provenance, quality, and scope
are all positively established. Unknown is never treated as a pass.
"""

from __future__ import annotations

from typing import Any


def check_proposal(
    proposal: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    as_of_s: float,
    *,
    quality_acceptable: bool | None = None,
    scope_supported: bool | None = None,
) -> dict[str, Any]:
    """Evaluate four independent evidence-admission requirements."""
    proposal_id: str = proposal["proposal_id"]
    source_ref: str = proposal["source_ref"]
    claimed_ids: list[str] = proposal["claimed_evidence_ids"]
    claimed_time: float | None = proposal["claimed_available_at_s"]

    reasons: list[str] = []

    # Reject a future claim before accessing any referenced evidence.
    if claimed_time is not None and claimed_time > as_of_s:
        return {
            "proposal_id": proposal_id,
            "time_admissible": False,
            "provenance_verified": None,
            "quality_acceptable": None,
            "scope_supported": None,
            "usable": False,
            "reasons": [
                "Claimed evidence is later than the analysis cutoff."
            ],
            "evidence_ids": [],
        }

    # Inspect registry metadata only; never inspect measurement values.
    registered = [
        evidence[ident]
        for ident in claimed_ids
        if ident in evidence
    ]
    missing_ids = [
        ident
        for ident in claimed_ids
        if ident not in evidence
    ]

    admissible = [
        row
        for row in registered
        if row["available_at_s"] <= as_of_s
    ]
    future_ids = [
        row["evidence_id"]
        for row in registered
        if row["available_at_s"] > as_of_s
    ]

    # Check 1: time admissibility.
    if future_ids:
        time_admissible: bool | None = False
        reasons.append(
            "Registered evidence is later than the analysis cutoff."
        )
    elif claimed_time is None or missing_ids or not claimed_ids:
        time_admissible = None
        reasons.append(
            "Evidence availability cannot be fully established."
        )
    else:
        time_admissible = True

    # Check 2: source and provenance.
    source_matches = all(
        row["source_ref"] == source_ref
        for row in admissible
    )

    if not claimed_ids:
        provenance_verified: bool | None = None
        reasons.append("No evidence identifiers were supplied.")
    elif missing_ids:
        provenance_verified = False
        reasons.append(
            "One or more claimed evidence identifiers are not registered."
        )
    elif future_ids:
        provenance_verified = None
        reasons.append(
            "Future evidence cannot establish provenance at this cutoff."
        )
    elif not source_matches:
        provenance_verified = False
        reasons.append(
            "The claimed source does not match registered evidence."
        )
    else:
        provenance_verified = True

    # Check 3: quality.
    # This must come from verified quality evidence, not from a claim.
    if quality_acceptable is False:
        reasons.append("Evidence quality is unacceptable.")
    elif quality_acceptable is None:
        reasons.append(
            "Evidence quality has not been independently established."
        )

    # Check 4: supported scope.
    # A matching hash or source reference does not prove physical scope.
    if scope_supported is False:
        reasons.append("Evidence is outside the supported scope.")
    elif scope_supported is None:
        reasons.append(
            "Supported evidence scope has not been established."
        )

    checks = (
        time_admissible,
        provenance_verified,
        quality_acceptable,
        scope_supported,
    )

    if any(check is False for check in checks):
        usable: bool | None = False
    elif all(check is True for check in checks):
        usable = True
    else:
        usable = None

    return {
        "proposal_id": proposal_id,
        "time_admissible": time_admissible,
        "provenance_verified": provenance_verified,
        "quality_acceptable": quality_acceptable,
        "scope_supported": scope_supported,
        "usable": usable,
        "reasons": reasons,
        "evidence_ids": [
            row["evidence_id"]
            for row in admissible
        ],
    }
