"""Alerts that put review before missing evidence in the decision of Agent 8.

A gap in evidence may block a state that says something is available, but it does not hide a
signal. Four alerts are read from what Agent 8 is given, in this order: a conflict of a reliable
family (the anomaly check of the diagnosis failed), a failed record check, a persistent alarm
(the persistence rule alarms), and a supported hypothesis unless persistence is known to be
false. The mapping from Agent 5 is fixed in named constants. Unknown persistence is never taken
as false. The wording names a departure of measured flows and pressures, never a place, a
fault, an approval, a confirmation of equipment condition or an action.
"""

from __future__ import annotations

from typing import Any, Final

ANOMALY_CHECK_ID: Final = "anomaly_report"
SUPPORTED_OUTCOME: Final = "pass"
RELIABLE_CONFLICT_OUTCOME: Final = "fail"
DIAGNOSIS_CONFLICT_PREFIX: Final = "diagnosis:"

RELIABLE_CONFLICT: Final = "reliable_conflict"
RECORD_FAILED: Final = "record_failed"
PERSISTENT_ALARM: Final = "persistent_alarm"
SUPPORTED_HYPOTHESIS: Final = "supported_hypothesis"
ALERT_ORDER: Final = (RELIABLE_CONFLICT, RECORD_FAILED, PERSISTENT_ALARM, SUPPORTED_HYPOTHESIS)
CONFLICT_ALERTS: Final = (RELIABLE_CONFLICT, RECORD_FAILED)

REASONS: Final = {
    RELIABLE_CONFLICT: (
        "the measured flows and pressures do not show the departure that a proposed candidate "
        "would produce"
    ),
    RECORD_FAILED: (
        "an inspection record check failed, two records disagree, or sources share original "
        "evidence"
    ),
    SUPPORTED_HYPOTHESIS: (
        "the measured flows and pressures show a departure that a proposed candidate would produce"
    ),
}
EVIDENCE_GAP: Final = "Required evidence or verification also remains unavailable."
COLLECT_TEXT: Final = (
    "Obtain and verify missing or unresolved evidence before making an assessment."
)
RECORDS_TEXT: Final = (
    "Review the conflicting records and the contradicted candidate without treating shared "
    "evidence as independent support."
)
SIGNAL_TEXT: Final = (
    "Review the window-level departure and the proposed candidates before any operational decision."
)


def anomaly_outcome(diagnosis: dict[str, Any] | None) -> str | None:
    """Outcome of the anomaly check in the diagnosis report, or None if there is none."""
    if diagnosis is None or diagnosis.get("result") is None:
        return None
    for check in diagnosis["result"].get("upstream_checks", []):
        if check["check_id"] == ANOMALY_CHECK_ID:
            outcome: str = check["outcome"]
            return outcome
    return None


def persistence_alarming(persistence: dict[str, Any] | None) -> bool | None:
    """True or False when persistence is known, None when unknown, absent or malformed."""
    value = persistence.get("alarming") if isinstance(persistence, dict) else None
    return value if isinstance(value, bool) else None


def record_conflict(conflict: dict[str, Any]) -> bool:
    """Whether a conflict entry comes from a plan or quality record, not from the diagnosis."""
    check_id = conflict.get("check_id") or ""
    return bool(check_id) and not check_id.startswith(DIAGNOSIS_CONFLICT_PREFIX)


def detect_alerts(
    diagnosis: dict[str, Any] | None,
    conflicts: list[dict[str, Any]],
    persistence: dict[str, Any] | None,
) -> list[str]:
    """The alerts that hold, in the fixed order."""
    outcome, alarming = anomaly_outcome(diagnosis), persistence_alarming(persistence)
    holds = {
        RELIABLE_CONFLICT: outcome == RELIABLE_CONFLICT_OUTCOME,
        RECORD_FAILED: any(record_conflict(c) for c in conflicts),
        PERSISTENT_ALARM: alarming is True,
        SUPPORTED_HYPOTHESIS: outcome == SUPPORTED_OUTCOME and alarming is not False,
    }
    return [kind for kind in ALERT_ORDER if holds[kind]]


def alarm_reason(persistence: dict[str, Any] | None) -> str:
    """The persistence alarm in words, with the published rule when it is present."""
    rule = persistence.get("rule") if isinstance(persistence, dict) else None
    if isinstance(rule, dict) and {"k", "n"} <= rule.keys():
        window = f"at least {rule['k']} of the last {rule['n']} windows"
    else:
        window = "several recent windows"
    return f"the measured flows and pressures have departed from their usual relations in {window}"


def alert_summary(
    kinds: list[str], persistence: dict[str, Any] | None, evidence_missing: bool
) -> str:
    """The summary: every alert that holds, in words, and that the condition is not confirmed."""
    reasons = [alarm_reason(persistence) if k == PERSISTENT_ALARM else REASONS[k] for k in kinds]
    text = "Review required: " + "; ".join(reasons) + ". Equipment condition is not confirmed."
    return text + (" " + EVIDENCE_GAP if evidence_missing else "")


def _step(kind: str, description: str, evidence_ids: list[str]) -> dict[str, Any]:
    return {"kind": kind, "description": description, "evidence_ids": sorted(set(evidence_ids))}


def alert_steps(
    kinds: list[str],
    conflicts: list[dict[str, Any]],
    diagnosis: dict[str, Any] | None,
    evidence_missing: bool,
) -> list[dict[str, Any]]:
    """Review steps for the alerts, and a step to collect evidence while evidence is missing."""
    steps = []
    if any(k in CONFLICT_ALERTS for k in kinds):
        ids = [ident for conflict in conflicts for ident in conflict["evidence_ids"]]
        steps.append(_step("review_records", RECORDS_TEXT, ids))
    if any(k not in CONFLICT_ALERTS for k in kinds):
        cited = [] if diagnosis is None else [diagnosis["report_id"]]
        steps.append(_step("human_review", SIGNAL_TEXT, cited))
    if evidence_missing:
        steps.append(_step("collect_evidence", COLLECT_TEXT, []))
    return steps
