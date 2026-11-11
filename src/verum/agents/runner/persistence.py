"""Persistence of window assessments across the windows of one run.

The runner is a function of one snapshot, so the assessments of earlier windows are carried by an
immutable log that the caller passes in and receives back in the bundle. The runner reads the
rule that Agent 2 published with each assessment (k of the last n windows with a score above a
threshold) and applies it; it holds no knowledge of the method behind the score.

An answer is unknown (null) until n windows are held, and whenever a window of the last n has no
assessment or an assessment that does not settle it. Unknown is never turned into false. Only
Agent 5 and Agent 8 receive the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ANOMALY_ROLE = "anomaly_detection"
MAX_KEPT = 16
YES, NO, UNSETTLED = "yes", "no", "unsettled"
Entry = dict[str, Any]


@dataclass(frozen=True)
class AssessmentLog:
    """The assessments of one run so far, oldest first; an entry may hold no assessment."""

    case_id: str | None = None
    entries: tuple[Entry, ...] = ()

    def extended(
        self, case_id: str, as_of_s: float, assessment: dict[str, Any] | None
    ) -> AssessmentLog:
        """A new log with one more window; a log never moves backwards or changes case."""
        if self.case_id not in (None, case_id):
            raise ValueError("an assessment log belongs to one run")
        if self.entries and as_of_s <= self.entries[-1]["as_of_s"]:
            raise ValueError("a window must come after the last window of the log")
        entry = {"as_of_s": float(as_of_s), "window_assessment": assessment}
        return AssessmentLog(case_id, (*self.entries, entry)[-MAX_KEPT:])


def assessment_of(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """The window assessment inside a report, or None for a missing report or result."""
    try:
        result = report["result"] if report is not None else None
        found = result.get("window_assessment") if result is not None else None
    except (KeyError, TypeError, AttributeError):
        return None
    return found if isinstance(found, dict) else None


def latest_rule(entries: tuple[Entry, ...]) -> dict[str, Any] | None:
    """The rule of the newest entry that carries an assessment."""
    for entry in reversed(entries):
        if entry["window_assessment"] is not None:
            rule: dict[str, Any] = entry["window_assessment"]["persistence_rule"]
            return rule
    return None


def window_state(entry: Entry, rule: dict[str, Any]) -> str:
    """Whether a window is above the rule's threshold, certainly not, or not settled."""
    found = entry["window_assessment"]
    if found is None or found["persistence_rule"] != rule:
        return UNSETTLED
    if found["score"] > rule["threshold"]:
        return YES
    return NO if found["complete"] else UNSETTLED


def unknown_persistence(held: int, rule: dict[str, Any] | None = None) -> dict[str, Any]:
    """A persistence statement that settles nothing."""
    return {
        "rule": rule, "windows_held": held, "windows_exceeding": 0, "windows_unknown": held,
        "alarming": None,
    }  # fmt: skip


def persistence_of(entries: tuple[Entry, ...]) -> dict[str, Any]:
    """Apply the published rule to the last n windows; null unless the answer is settled."""
    rule = latest_rule(entries)
    if rule is None:
        return unknown_persistence(len(entries))
    recent = entries[-rule["n"] :]
    states = [window_state(entry, rule) for entry in recent]
    above, unsettled = states.count(YES), states.count(UNSETTLED)
    alarming: bool | None = None
    if len(recent) >= rule["n"]:
        if above >= rule["k"]:
            alarming = True
        elif unsettled == 0:
            alarming = False
    return {
        "rule": rule, "windows_held": len(recent), "windows_exceeding": above,
        "windows_unknown": unsettled, "alarming": alarming,
    }  # fmt: skip


def attach_fields(
    log: AssessmentLog, case_id: str, as_of_s: float, anomaly_report: dict[str, Any] | None
) -> dict[str, Any]:
    """The two request fields for this window; any failure leaves persistence unknown."""
    try:
        current = log.extended(case_id, as_of_s, assessment_of(anomaly_report))
        entries = current.entries
        rule = latest_rule(entries)
        shown = entries[-rule["n"] :] if rule is not None else entries
        return {"recent_anomaly_assessments": list(shown), "persistence": persistence_of(entries)}
    except Exception:  # noqa: BLE001 - unknown, never false, whatever went wrong
        return {"recent_anomaly_assessments": [], "persistence": unknown_persistence(0)}
