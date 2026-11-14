"""Signal-quality rules for the Anomaly Detection role.

The rules read the window summaries of a request and report missing readings, non-good quality
flags and signals whose tag or unit is not the expected one. They do not read any fitted value
and they do not judge equipment health.
"""

from __future__ import annotations

import math
from typing import Any

QUALITY_METHOD_ID = "quality_summary_rules_v1"
BOOL_UNIT = "bool"
NON_GOOD_QUALITY = ("suspect", "bad")
# A tag counts as observed in this window only if one of these holds a value. The previous
# measured value is left out on purpose: it can hold an old reading.
CURRENT_VALUE_FIELDS = ("latest_value", "mean", "minimum", "maximum")

EXPECTED_UNITS = {
    "FT-001": "m3/h", "FT-201": "m3/h", "LSHH-101": "bool", "LSHH-102": "bool",
    "LSHH-103": "bool", "LT-101": "m", "LT-102": "m", "LT-103": "m", "P-101A": "bool",
    "P-101B": "bool", "PT-001": "barg", "PT-201": "barg", "PT-202A": "barg",
    "PT-202B": "barg", "PT-203": "barg", "TT-001": "C", "TT-101": "C", "TT-102": "C",
    "TT-103": "C", "XV-PAI": "bool", "XV-PAO": "bool", "XV-PBI": "bool", "XV-PBO": "bool",
    "XV-R000": "bool", "XV-R101": "bool", "XV-R102": "bool", "XV-R103": "bool",
    "XV-S101": "bool", "XV-S102": "bool", "XV-S103": "bool",
}  # fmt: skip


def is_number(value: Any) -> bool:
    """Whether a value is a finite real number (a boolean is not)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value: Any) -> float:
    return float(value) if is_number(value) else 0.0


def tag_of(signal: dict[str, Any]) -> str:
    """The tag identifier of a signal summary."""
    return str(signal.get("tag_id"))


def find_invalid_unit_signals(signals: list[dict[str, Any]]) -> list[str]:
    """Identify signals with unknown tags or unexpected units."""
    return sorted(
        {
            tag_of(signal)
            for signal in signals
            if EXPECTED_UNITS.get(tag_of(signal)) != signal.get("unit")
        }
    )


def has_current_value(signal: dict[str, Any]) -> bool:
    """Whether the signal carries a reading from this window (a boolean counts for bool tags)."""
    is_bool_tag = signal.get("unit") == BOOL_UNIT
    return any(
        is_number(signal.get(name)) or (is_bool_tag and isinstance(signal.get(name), bool))
        for name in CURRENT_VALUE_FIELDS
    )


def make_event(
    *,
    event_id: str,
    category: str,
    tag_ids: list[str],
    evidence_ids: list[str],
    method_id: str,
    limitations: list[str],
    score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an event that follows the shared anomaly event contract."""
    return {
        "event_id": event_id,
        "tag_ids": sorted(set(tag_ids)),
        "asset_ids": [],
        "category": category,
        "score": score,
        "method_id": method_id,
        "evidence_ids": evidence_ids,
        "limitations": limitations,
    }


def build_quality_events(
    request_id: str, signals: list[dict[str, Any]], evidence_ids: list[str]
) -> list[dict[str, Any]]:
    """Rule events for missing readings and suspect or bad quality flags."""
    missing_tags = [
        tag_of(signal)
        for signal in signals
        if _count(signal.get("missing_samples")) > 0
        or signal.get("latest_availability") == "missing_sample"
        or not has_current_value(signal)
    ]
    quality_tags = [
        tag_of(signal)
        for signal in signals
        if _count(signal.get("bad_quality_samples")) > 0
        or signal.get("latest_quality") in NON_GOOD_QUALITY
    ]
    events = []
    for suffix, category, tags, text in (
        ("missing-reading", "missing_reading", missing_tags,
         "Identifies reported missing readings only."),
        ("non-good-quality", "non_good_quality", quality_tags,
         "Identifies reported signal quality conditions only."),
    ):  # fmt: skip
        if tags:
            events.append(
                make_event(
                    event_id=f"{request_id}-{suffix}",
                    category=category,
                    tag_ids=tags,
                    evidence_ids=evidence_ids,
                    method_id=QUALITY_METHOD_ID,
                    limitations=[text, "Does not establish equipment health."],
                )
            )
    return events
