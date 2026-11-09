
"""Deterministic admission checks for Agent 8 evidence proposals.

A proposal is usable only when time, provenance, quality, and scope
are all positively established. Unknown is never treated as a pass.
"""

from __future__ import annotations

from typing import Any


def _check_provenance(
    claimed_ids: list[str],
    missing_ids: list[str],
    future_ids: list[str],
    admissible: list[dict[str, Any]],
    source_ref: str,
) -> tuple[bool | None, list[str]]:
    """Verify provenance against all claimed evidence."""
    reasons = []
    # Check 2: source and provenance.
    source_matches = all(row["source_ref"] == source_ref for row in admissible)

    if not claimed_ids:
        provenance_verified: bool | None = None
        reasons.append("No evidence identifiers were supplied.")
    elif missing_ids:
        provenance_verified = False
        reasons.append("One or more claimed evidence identifiers are not registered.")
    elif future_ids:
        provenance_verified = None
        reasons.append("Future evidence cannot establish provenance at this cutoff.")
    elif not source_matches:
        provenance_verified = False
        reasons.append("The claimed source does not match registered evidence.")
    else:
        provenance_verified = True

    return provenance_verified, reasons


def _registry_rows(
    claimed_ids: list[str],
    evidence: dict[str, dict[str, Any]],
    as_of_s: float,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Partition registered evidence by availability."""
    # Inspect registry metadata only; never inspect measurement values.
    registered = [evidence[ident] for ident in claimed_ids if ident in evidence]
    missing_ids = [ident for ident in claimed_ids if ident not in evidence]

    admissible = [row for row in registered if row["available_at_s"] <= as_of_s]
    future_ids = [row["evidence_id"] for row in registered if row["available_at_s"] > as_of_s]

    return admissible, missing_ids, future_ids


def _check_time_and_provenance(
    claimed_ids: list[str],
    claimed_time: float | None,
    source_ref: str,
    evidence: dict[str, dict[str, Any]],
    as_of_s: float,
) -> tuple[bool | None, bool | None, list[dict[str, Any]], list[str]]:
    """Check registered evidence timing and provenance."""
    reasons = []
    admissible, missing_ids, future_ids = _registry_rows(claimed_ids, evidence, as_of_s)

    # Check 1: time admissibility.
    if future_ids:
        time_admissible: bool | None = False
        reasons.append("Registered evidence is later than the analysis cutoff.")
    elif claimed_time is None or missing_ids or not claimed_ids:
        time_admissible = None
        reasons.append("Evidence availability cannot be fully established.")
    else:
        time_admissible = True

    provenance_verified, source_reasons = _check_provenance(
        claimed_ids, missing_ids, future_ids, admissible, source_ref
    )
    reasons.extend(source_reasons)

    return time_admissible, provenance_verified, admissible, reasons


def _quality_scope_reasons(
    quality_acceptable: bool | None,
    scope_supported: bool | None,
) -> list[str]:
    """Explain quality and scope failures or unknowns."""
    reasons = []
    # Check 3: quality.
    # This must come from verified quality evidence, not from a claim.
    if quality_acceptable is False:
        reasons.append("Evidence quality is unacceptable.")
    elif quality_acceptable is None:
        reasons.append("Evidence quality has not been independently established.")

    # Check 4: supported scope.
    # A matching hash or source reference does not prove physical scope.
    if scope_supported is False:
        reasons.append("Evidence is outside the supported scope.")
    elif scope_supported is None:
        reasons.append("Supported evidence scope has not been established.")

    return reasons


def _proposal_usability(
    time_admissible: bool | None,
    provenance_verified: bool | None,
    quality_acceptable: bool | None,
    scope_supported: bool | None,
) -> bool | None:
    """Combine four admission checks without treating unknown as pass."""
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

    return usable


def _proposal_result(
    proposal_id: str,
    time_admissible: bool | None,
    provenance_verified: bool | None,
    quality_acceptable: bool | None,
    scope_supported: bool | None,
    usable: bool | None,
    reasons: list[str],
    admissible: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the evidence verification result."""
    return {
        "proposal_id": proposal_id,
        "time_admissible": time_admissible,
        "provenance_verified": provenance_verified,
        "quality_acceptable": quality_acceptable,
        "scope_supported": scope_supported,
        "usable": usable,
        "reasons": reasons,
        "evidence_ids": [row["evidence_id"] for row in admissible],
    }


def _future_claim_result(proposal_id: str) -> dict[str, Any]:
    """Reject evidence claimed after the analysis cutoff."""
    return {
        "proposal_id": proposal_id,
        "time_admissible": False,
        "provenance_verified": None,
        "quality_acceptable": None,
        "scope_supported": None,
        "usable": False,
        "reasons": ["Claimed evidence is later than the analysis cutoff."],
        "evidence_ids": [],
    }


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
        return _future_claim_result(proposal_id)

    time_admissible, provenance_verified, admissible, admission_reasons = (
        _check_time_and_provenance(
            claimed_ids, claimed_time, source_ref, evidence, as_of_s
        )
    )
    reasons.extend(admission_reasons)

    reasons.extend(_quality_scope_reasons(quality_acceptable, scope_supported))

    usable = _proposal_usability(
        time_admissible, provenance_verified, quality_acceptable, scope_supported
    )

    return _proposal_result(
        proposal_id,
        time_admissible,
        provenance_verified,
        quality_acceptable,
        scope_supported,
        usable,
        reasons,
        admissible,
    )
