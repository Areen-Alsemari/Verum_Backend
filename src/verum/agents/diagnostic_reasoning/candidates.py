"""Candidates from the residual pattern of the anomaly window assessment, for windows without any.

When the classifier proposes nothing and the anomaly window is alarming, the expected-residual
table of the mechanism module is read backwards: every family whose expected residuals are all
exceeded becomes a candidate. A candidate states its family and supporting residuals, names an
asset or tag only when the Agent 2 event of its residual names one, and carries no score. A known
non-persistent alarm suppresses candidates; unknown persistence does not.
See reports/agent5_candidates_design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from verum.agents.diagnostic_reasoning.mechanism import (
    FLOW_METER,
    LEAK_BETWEEN_METERS,
    LEVEL_SENSOR,
    NO_FAMILY,
    PRESSURE_FAMILIES,
    PUMP_HEAD_LOSS,
    PUMP_INLET_VALVE,
    PUMP_OUTLET_VALVE,
    RECEIPT_RESTRICTION,
    RESIDUAL_IDS,
    Family,
    family_of,
    quality_tags,
    usable_assessment,
)
from verum.agents.diagnostic_reasoning.rules import (
    LOW_SUPPORT_MECHANISMS,
    _is_stub_or_failed,
    enrich_hypothesis_with_rules,
    valid_component,
)

CANDIDATE_RANKING: Final = "residual_pattern_fixed_order"
PUMP_RUN_TAGS: Final = ("P-101A", "P-101B")
SHARED_TAGS: Final = frozenset({"PT-202A", "PT-202B"})
EVENT_CATEGORY: Final = "reported_signal_departure"

RESTRICTION_NOTE: Final = (
    "The residuals cannot tell a restriction with a visible valve position from an obstruction, "
    "so the mechanism names the kind of fault only."
)
SENSOR_NOTE: Final = (
    "The residuals cannot tell bias, drift and stuck apart, so the mechanism names the kind of "
    "fault only."
)
LEVEL_NOTE: Final = (
    "The residuals cannot tell a drifting level reading from a stuck one, so the mechanism names "
    "the kind of fault only."
)
UNLOCALISED_NOTE: Final = (
    "The anomaly report names no single asset for this kind of fault, so the hypothesis is not "
    "localised."
)
PERSISTENCE_NOTE: Final = (
    "Whether the alarm persists over earlier windows is unknown, so the window result alone "
    "raised this candidate."
)


@dataclass(frozen=True)
class Spec:
    """A family that can be a candidate, the mechanism standing for it, and what can name it."""

    family: Family
    mechanism: str
    note: str | None
    tag: str | None = None
    names_pump: bool = False


TABLE: Final[tuple[Spec, ...]] = (
    Spec(PUMP_HEAD_LOSS, "pump", None, names_pump=True),
    Spec(PUMP_INLET_VALVE, "restriction_position_visible", RESTRICTION_NOTE),
    Spec(PUMP_OUTLET_VALVE, "restriction_position_visible", RESTRICTION_NOTE),
    Spec(RECEIPT_RESTRICTION, "restriction_position_visible", RESTRICTION_NOTE),
    Spec(LEAK_BETWEEN_METERS, "leak", None),
    Spec(FLOW_METER, "drift", SENSOR_NOTE),
    Spec(LEVEL_SENSOR, "drift", LEVEL_NOTE),
    *(Spec(family, "drift", SENSOR_NOTE, tag=tag) for tag, family in PRESSURE_FAMILIES.items()),
)


def exceeded_keys(assessment: dict[str, Any]) -> set[str]:
    """Short keys (R1 to R4) of the residuals the assessment reports as exceeded."""
    states = {row["residual_id"]: row["state"] for row in assessment["residuals"]}
    return {key for key, rid in RESIDUAL_IDS.items() if states.get(rid) == "exceeded"}


def event_tags(report: dict[str, Any], keys: tuple[str, ...]) -> set[str] | None:
    """Tags named by the residual events of the given residuals, or None if none is found."""
    suffixes = tuple(f"-residual-{key}" for key in keys)
    found = [
        event
        for event in (report.get("result") or {}).get("events", [])
        if event.get("category") == EVENT_CATEGORY
        and str(event.get("event_id", "")).endswith(suffixes)
    ]
    if not found:
        return None
    return {tag for event in found for tag in event.get("tag_ids", [])}


def target_of(spec: Spec, named: set[str] | None) -> tuple[bool, str | None]:
    """Whether the family stays a candidate, and the asset or tag the evidence names for it."""
    if spec.tag in SHARED_TAGS:
        return (named is not None and spec.tag in named), spec.tag
    if spec.tag is not None:
        return True, (spec.tag if named is not None and spec.tag in named else None)
    if spec.names_pump and named is not None:
        pumps = [tag for tag in PUMP_RUN_TAGS if tag in named]
        return True, (pumps[0] if len(pumps) == 1 else None)
    return True, None


def alarming(inputs: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any] | None:
    """The usable assessment of an alarming window that persistence does not rule out."""
    if report is None or _is_stub_or_failed(report):
        return None
    assessment = usable_assessment(report)
    if assessment is None or assessment.get("exceeded") is not True:
        return None
    persistence = inputs.get("persistence")
    if isinstance(persistence, dict) and persistence.get("alarming") is False:
        return None
    return assessment


def slug(text: str) -> str:
    """Lower-case words joined by hyphens, for identifiers."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def matches(exceeded: set[str], report: dict[str, Any]) -> list[tuple[Spec, str | None, set[str]]]:
    """Families whose expected residuals are all exceeded, in the fixed order, with targets."""
    found = []
    for order, spec in enumerate(TABLE):
        expected = spec.family.expected
        if not expected or not set(expected) <= exceeded:
            continue
        named = event_tags(report, expected)
        kept, target = target_of(spec, named)
        if kept:
            found.append((-len(expected), order, spec, target, named or set()))
    found.sort(key=lambda row: (row[0], row[1]))
    return [(spec, target, named) for _, _, spec, target, named in found]


def questions_of(spec: Spec, target: str | None, unknown_persistence: bool) -> list[str]:
    """The family statement and the caveats of one candidate."""
    residuals = ", ".join(RESIDUAL_IDS[key] for key in spec.family.expected)
    text = [
        f"Raised from the residual pattern of the anomaly window assessment, not by the "
        f"observation classifier: {spec.family.name}, supported by {residuals} exceeded. It "
        "carries no score, and its rank follows a fixed order that is not evidence."
    ]
    text += [spec.note] if spec.note else []
    text += [] if target else [UNLOCALISED_NOTE]
    text += [PERSISTENCE_NOTE] if unknown_persistence else []
    return text


def raw_candidate(
    rank: int, spec: Spec, target: str | None, questions: list[str]
) -> dict[str, Any]:
    """A hypothesis for one family, before the upstream comparisons."""
    tag = target if spec.tag is not None else None
    component = valid_component(spec.mechanism, target, tag)
    return {
        "hypothesis_id": f"HYP-A2-{rank:02d}-{slug(spec.family.name)}-{target or 'family-level'}",
        "components": [component],
        "score": None,
        "support_evidence_ids": [],
        "conflict_evidence_ids": [],
        "unresolved_questions": questions,
    }


def finish(hypothesis: dict[str, Any], report: dict[str, Any], named: set[str]) -> dict[str, Any]:
    """Cite the anomaly report as support and drop text that describes classifier output."""
    support = list(hypothesis["support_evidence_ids"])
    if report["report_id"] not in support:
        support.append(report["report_id"])
    dropped = {NO_FAMILY, *LOW_SUPPORT_MECHANISMS.values()}
    questions = [q for q in hypothesis["unresolved_questions"] if q not in dropped]
    poor = sorted(named & quality_tags(report))
    if poor and family_of(hypothesis) is None:
        questions.append(
            "Data-quality caveat: the anomaly report lists "
            f"{', '.join(poor)} as missing or not good, which this hypothesis relies on."
        )
    return {**hypothesis, "support_evidence_ids": support, "unresolved_questions": questions}


def residual_candidates(
    inputs: dict[str, Any], obs_evidence_ids: list[str]
) -> list[dict[str, Any]]:
    """Candidates for an alarming window, compared with the upstream reports like any other."""
    report = inputs.get("anomaly_report")
    assessment = alarming(inputs, report)
    if assessment is None or report is None:
        return []
    persistence = inputs.get("persistence")
    unknown = not (isinstance(persistence, dict) and persistence.get("alarming") is True)
    out = []
    for rank, (spec, target, named) in enumerate(matches(exceeded_keys(assessment), report), 1):
        raw = raw_candidate(rank, spec, target, questions_of(spec, target, unknown))
        enriched = enrich_hypothesis_with_rules(raw, inputs, obs_evidence_ids)
        out.append(finish(enriched, report, named))
    return out
