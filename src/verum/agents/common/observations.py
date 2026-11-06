"""Adapter from a prepared observation summary to the summary_v1 request representation.

Every agent receives channels in one fixed tag order, so a saved feature order means the same thing
to all owners. The order is the sorted list of emitted tags in the public reference; a test checks
it against the sensor configuration. Only the summary representation is built here.
"""

from __future__ import annotations

from typing import Any, Final

from verum.agents.common.numbers import normalise
from verum.agents.common.registry import EvidenceRegistry

TAG_ORDER: Final[tuple[str, ...]] = (
    "FT-001", "FT-201", "LSHH-101", "LSHH-102", "LSHH-103", "LT-101", "LT-102", "LT-103",
    "P-101A", "P-101B", "PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203", "TT-001",
    "TT-101", "TT-102", "TT-103", "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO", "XV-R000",
    "XV-R101", "XV-R102", "XV-R103", "XV-S101", "XV-S102", "XV-S103",
)
SUMMARY_KEYS: Final = frozenset({"clock_basis", "current_time_s", "lookback_s", "signals"})


def ordered_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised copy of a summary whose signals follow the fixed tag order."""
    clean: dict[str, Any] = normalise(summary)
    if set(clean) != SUMMARY_KEYS:
        raise ValueError("a summary has exactly its clock, lookback and signal fields")
    by_tag = {signal["tag_id"]: signal for signal in clean["signals"]}
    if len(by_tag) != len(clean["signals"]):
        raise ValueError("duplicate signal channel")
    if set(by_tag) != set(TAG_ORDER):
        raise ValueError("the summary does not hold exactly the emitted tags")
    clean["signals"] = [by_tag[tag] for tag in TAG_ORDER]
    return clean


def summary_representation(summary: dict[str, Any], evidence_ids: list[str]) -> dict[str, Any]:
    """Wrap a prepared summary in the summary_v1 representation of an agent request."""
    return {
        "representation": "summary_v1",
        "summary": ordered_summary(summary),
        "evidence_ids": list(evidence_ids),
    }


def attach_summary(
    registry: EvidenceRegistry, summary: dict[str, Any], *, evidence_id: str, locator: str,
    root_ids: list[str], available_at_s: float,
) -> dict[str, Any]:
    """Register a summary as derived evidence and return its request representation."""
    observations = summary_representation(summary, [evidence_id])
    registry.add_representation(
        evidence_id, locator, available_at_s, observations["summary"], root_ids
    )
    return observations
