"""Checks of the number rule and the identifier rules of the shared agent helpers."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from verum.agents.common import ROLES, analysis_id, normalise, report_id, stable_hash
from verum.agents.common.ids import require_source_id
from verum.contracts.agent_interfaces import content_hash


def test_integral_floats_and_integers_hash_alike() -> None:
    """The spellings 300 and 300.0 give one hash, also inside nested messages.

    Independent: no, because the hash is computed by the same canonical routine as the rule uses.
    """
    assert stable_hash({"a": [300, {"b": 0}]}) == stable_hash({"a": [300.0, {"b": -0.0}]})
    assert content_hash({"a": 300}) != content_hash({"a": 300.0})


def test_non_integral_and_huge_floats_are_kept() -> None:
    """A fractional value, and a float too large to be exact as an integer, are not rewritten.

    Independent: yes, because the expected values are literals.
    """
    assert normalise(0.5) == 0.5
    assert isinstance(normalise(2.0**60), float)
    assert isinstance(normalise(3.0), int)
    assert normalise(True) is True


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(value: float) -> None:
    """NaN and infinities cannot enter a message.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(ValueError, match="non-finite"):
        normalise({"x": [value]})


@pytest.mark.parametrize(
    "value", [np.float64(1.5), np.int64(3), np.bool_(True), np.array([1.0])]
)
def test_numpy_values_are_rejected(value: Any) -> None:
    """A numpy scalar or array is refused rather than silently converted.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(TypeError, match="numpy"):
        normalise({"x": value})


def test_unsupported_values_and_keys_are_rejected() -> None:
    """Only JSON-compatible values with text keys are accepted.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(TypeError):
        normalise({1: "a"})
    with pytest.raises(TypeError):
        normalise({"x": {1, 2}})


def test_analysis_identifier_format() -> None:
    """The analysis identifier names the case and the revision.

    Independent: yes, because the expected text is a literal.
    """
    assert analysis_id("C7", 0) == "AN-C7-r0"
    assert analysis_id("C7", 12) == "AN-C7-r12"


@pytest.mark.parametrize("case, revision", [("", 0), ("C7", -1), ("C7", True), ("C7", 1.0)])
def test_invalid_analysis_inputs_are_rejected(case: str, revision: Any) -> None:
    """An empty case, or a revision that is negative or not an integer, is refused.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(ValueError):
        analysis_id(case, revision)


def test_report_identifier_is_deterministic_and_role_prefixed() -> None:
    """The identifier is the role, the analysis and eight hex digits of the request hash.

    Independent: no, because the digest is recomputed with the same hash routine.
    """
    digest = content_hash({"request_id": "R1", "agent": "anomaly_detection"})[:8]
    identifier = report_id("anomaly_detection", "AN-C7-r0", "R1")
    assert identifier == f"anomaly_detection-AN-C7-r0-{digest}"
    assert identifier == report_id("anomaly_detection", "AN-C7-r0", "R1")
    assert identifier != report_id("anomaly_detection", "AN-C7-r0", "R2")
    assert identifier != report_id("anomaly_detection", "AN-C7-r1", "R1")


def test_report_identifier_needs_a_known_role() -> None:
    """An unknown role key is refused.

    Independent: yes, because the rejected value is a literal.
    """
    with pytest.raises(ValueError, match="unknown agent role"):
        report_id("topology", "AN-C7-r0", "R1")


@pytest.mark.parametrize("role", ROLES)
def test_source_evidence_cannot_use_a_report_prefix(role: str) -> None:
    """Source evidence identifiers cannot start like any report identifier, so they never collide.

    Independent: yes, because the identifiers are literals built from the role keys.
    """
    with pytest.raises(ValueError, match="role key"):
        require_source_id(f"{role}-AN-C7-r0-deadbeef")
    assert require_source_id("source-observations") == "source-observations"
