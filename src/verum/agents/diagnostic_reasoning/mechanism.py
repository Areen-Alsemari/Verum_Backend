"""Mechanism rule: what the window assessment of the anomaly report says about a hypothesis.

Inputs: a hypothesis and the anomaly report. Only the window assessment is read (a state for
each of four residuals and whether the window was complete), never the events. Each family of
fault has a fixed set of residuals that the layout says should move. An exceeded expected
residual supports the hypothesis. Its absence contradicts it only for a family that was
reliable on validation windows, and only when the window was complete. Everything else is
unknown: an unknown residual, a family with no expected residual, an unmapped hypothesis, or no
usable assessment. Quality events add a caveat and never turn silence into a conflict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

QUALITY_CATEGORIES: Final = frozenset({"missing_reading", "non_good_quality"})
RESIDUAL_IDS: Final = {
    "R1": "R1_mass_balance",
    "R2": "R2_pump_head",
    "R3": "R3_discharge_loss",
    "R4": "R4_receipt_line",
}
STATES: Final = frozenset({"exceeded", "within_normal", "unknown"})
SUPPORT, CONFLICT, UNKNOWN = "support", "conflict", "unknown"


@dataclass(frozen=True)
class Family:
    """A kind of fault, the residuals expected to move, and whether silence counts against it."""

    name: str
    expected: tuple[str, ...]
    reliable: bool


# Expectation sets are written from the topology (an extra loss between two measured points
# moves the residual that spans them; a loss upstream of the suction header moves none) and are
# fixed here before any scoring; see section 4c of the evidence report. The validation figure
# next to each family is the share of validation windows with that fault in which the expected
# residual exceeded. Only the pump families are marked reliable.
PUMP_HEAD_LOSS: Final = Family("pump head loss", ("R2",), True)  # 72 of 72 = 1.000
PUMP_INLET_VALVE: Final = Family("restriction at a pump inlet valve", ("R2",), True)  # 44 of 50
PUMP_OUTLET_VALVE: Final = Family("restriction at a pump outlet valve", ("R3",), True)  # 58 of 67
RECEIPT_RESTRICTION: Final = Family("restriction at a receipt-side valve", ("R4",), False)  # 0 of 4
TANK_OUTLET: Final = Family("restriction at a tank-outlet valve", (), False)
LEAK_BETWEEN_METERS: Final = Family("leak between the two meters", ("R1",), False)  # 43 of 54
LEAK_OUTSIDE: Final = Family("leak outside the mass balance", (), False)
FLOW_METER: Final = Family("flow-meter sensor fault", ("R1",), False)  # drift 23 of 31
LEVEL_SENSOR: Final = Family("level-sensor drift or stuck", ("R1",), False)  # 19 of 19, 13 of 13
LEVEL_BIAS: Final = Family("level-sensor bias", (), False)
MISROUTING: Final = Family("valve misrouting", (), False)

INLET_VALVES: Final = frozenset({"XV-PAI", "XV-PBI"})
OUTLET_VALVES: Final = frozenset({"XV-PAO", "XV-PBO"})
RECEIPT_VALVES: Final = frozenset({"XV-R000", "XV-R101", "XV-R102", "XV-R103"})
TANK_OUTLET_VALVES: Final = frozenset({"XV-S101", "XV-S102", "XV-S103"})
OUTSIDE_EDGES: Final = frozenset({"E001", "E-D2"})
FLOW_METERS: Final = frozenset({"FT-001", "FT-201"})
LEVEL_SENSORS: Final = frozenset({"LT-101", "LT-102", "LT-103"})
SENSOR_MECHANISMS: Final = frozenset({"bias", "drift", "stuck"})
RESTRICTIONS: Final = frozenset({"restriction_position_visible", "restriction_obstruction"})

NO_ASSESSMENT: Final = (
    "The anomaly report has no usable window assessment, so it can neither support nor "
    "contradict this hypothesis."
)
NO_FAMILY: Final = (
    "This hypothesis maps to no kind of fault that the anomaly window assessment covers, so the "
    "report can neither support nor contradict it."
)
NO_EXPECTATION: Final = (
    "No residual of the anomaly window assessment is expected to move for this kind of fault "
    "({family}), so the report can neither support nor contradict it."
)


def restriction_family(asset: str | None) -> Family | None:
    """The family of a valve restriction, from where the valve sits on the line."""
    if asset in INLET_VALVES:
        return PUMP_INLET_VALVE
    if asset in OUTLET_VALVES:
        return PUMP_OUTLET_VALVE
    if asset in RECEIPT_VALVES:
        return RECEIPT_RESTRICTION
    return TANK_OUTLET if asset in TANK_OUTLET_VALVES else None


def sensor_family(mechanism: str, tag: str | None) -> Family | None:
    """The family of a sensor fault; only flow meters and level transmitters are covered."""
    if tag in FLOW_METERS:
        return FLOW_METER
    if tag in LEVEL_SENSORS:
        return LEVEL_BIAS if mechanism == "bias" else LEVEL_SENSOR
    return None


def family_of(hypothesis: dict[str, Any]) -> Family | None:
    """The family of a single-component hypothesis, or None when it maps to none."""
    components = hypothesis["components"]
    if len(components) != 1:
        return None
    mechanism, asset = components[0]["mechanism"], components[0].get("asset_id")
    if mechanism == "pump":
        return PUMP_HEAD_LOSS
    if mechanism in RESTRICTIONS:
        return restriction_family(asset)
    if mechanism == "leak" and asset is not None:
        return (
            LEAK_OUTSIDE
            if asset in OUTSIDE_EDGES
            else (LEAK_BETWEEN_METERS if asset.startswith("E") else None)
        )
    if mechanism == "misroute_a":
        return MISROUTING
    tag = components[0].get("tag_id") or asset
    return sensor_family(mechanism, tag) if mechanism in SENSOR_MECHANISMS else None


def usable_assessment(report: dict[str, Any]) -> dict[str, Any] | None:
    """The window assessment of a report if it has the four residuals and the complete flag."""
    result = report.get("result")
    found = result.get("window_assessment") if isinstance(result, dict) else None
    if not isinstance(found, dict) or not isinstance(found.get("complete"), bool):
        return None
    rows = found.get("residuals")
    if not isinstance(rows, list):
        return None
    ids = [row.get("residual_id") if isinstance(row, dict) else None for row in rows]
    if sorted(ids, key=str) != sorted(RESIDUAL_IDS.values()):
        return None
    if any(row.get("state") not in STATES for row in rows):
        return None
    return found


def residual_states(assessment: dict[str, Any], family: Family) -> list[tuple[str, str, Any]]:
    """Identifier, state and reason of each expected residual of a family."""
    by_id = {row["residual_id"]: row for row in assessment["residuals"]}
    rows = [by_id[RESIDUAL_IDS[key]] for key in family.expected]
    return [(row["residual_id"], row["state"], row.get("reason")) for row in rows]


def judge(assessment: dict[str, Any], family: Family) -> tuple[str, str | None]:
    """Support, conflict or unknown for a family, with the question that explains unknown."""
    states = residual_states(assessment, family)
    if any(state == "exceeded" for _, state, _ in states):
        return SUPPORT, None
    unknown = [(rid, why) for rid, state, why in states if state == "unknown"]
    if unknown:
        rid, why = unknown[0]
        return UNKNOWN, (
            f"An expected residual ({rid}) is unknown in the anomaly window assessment"
            f"{f' ({why})' if why else ''}, so the report neither supports nor contradicts "
            f"this hypothesis ({family.name})."
        )
    names = ", ".join(rid for rid, _, _ in states)
    if family.reliable and assessment["complete"]:
        return CONFLICT, None
    if family.reliable:
        return UNKNOWN, (
            f"The expected residual ({names}) is within normal, but the window assessment is "
            f"incomplete, so its absence is not held against this hypothesis ({family.name})."
        )
    return UNKNOWN, (
        f"The expected residual ({names}) is within normal; for this kind of fault "
        f"({family.name}) the absence of the residual is weak evidence, so it is not held "
        "against the hypothesis."
    )


def quality_tags(report: dict[str, Any]) -> set[str]:
    """Tags named by data-quality events: reported missing or not good."""
    events = (report.get("result") or {}).get("events", [])
    return {
        tag
        for event in events
        if event.get("category") in QUALITY_CATEGORIES
        for tag in event.get("tag_ids", [])
    }


def apply_mechanism_rule(
    report: dict[str, Any],
    hypothesis: dict[str, Any],
    tags: set[str],
    support: list[str],
    conflicts: list[str],
    questions: list[str],
) -> None:
    """Add the report to support or conflict, or a question saying why it does neither.

    A data-quality event on a tag the hypothesis relies on adds a caveat and keeps silence from
    becoming a conflict.
    """
    assessment = usable_assessment(report)
    family = family_of(hypothesis)
    if assessment is None:
        questions.append(NO_ASSESSMENT)
        return
    if family is None:
        questions.append(NO_FAMILY)
        return
    if not family.expected:
        questions.append(NO_EXPECTATION.format(family=family.name))
        return
    verdict, question = judge(assessment, family)
    named = sorted(tags & quality_tags(report))
    if named:
        questions.append(
            "Data-quality caveat: the anomaly report lists "
            f"{', '.join(named)} as missing or not good, which this hypothesis relies on."
        )
    if verdict == CONFLICT and named:
        verdict, question = (
            UNKNOWN,
            (
                "The expected residual is within normal, but a tag this hypothesis relies on is "
                "reported missing or not good, so the absence is not held against it."
            ),
        )
    if verdict == SUPPORT and report["report_id"] not in support:
        support.append(report["report_id"])
    elif verdict == CONFLICT and report["report_id"] not in conflicts:
        conflicts.append(report["report_id"])
    if question:
        questions.append(question)
