"""Checks of the number rule and the identifier rules of the shared agent helpers."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from verum.agents.common import ROLES, analysis_id, report_id, stable_hash, to_plain
from verum.agents.common.ids import require_source_id
from verum.contracts.agent_interfaces import content_hash


def test_numbers_keep_their_type_and_hash_as_the_contract_hashes() -> None:
    """The helper hash equals the contract hash, so 300 and 300.0 differ on purpose.

    Independent: yes, because the contract hash is a separate routine and the values are literals.
    """
    message = {"a": [300, {"b": 0}], "c": 300.0, "d": -0.0}
    assert stable_hash(message) == content_hash(message)
    assert stable_hash({"a": 300}) != stable_hash({"a": 300.0})
    plain = to_plain(message)
    assert plain == message and isinstance(plain["c"], float) and isinstance(plain["a"][0], int)
    assert to_plain(True) is True and to_plain(2.0**60) == 2.0**60
    assert to_plain((1, 2.0)) == [1, 2.0]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(value: float) -> None:
    """NaN and infinities cannot enter a message.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(ValueError, match="non-finite"):
        to_plain({"x": [value]})
    with pytest.raises(ValueError, match="non-finite"):
        to_plain({"x": np.float64(value)})


def test_numpy_scalars_become_python_numbers() -> None:
    """Numpy scalars are converted to the matching Python type, keeping their value.

    Independent: yes, because the expected values and types are literals.
    """
    numpy_message = {"f": np.float64(1.5), "g": np.float32(2.0), "i": np.int64(3), "b": np.bool_(1)}
    plain = to_plain(numpy_message)
    assert plain == {"f": 1.5, "g": 2.0, "i": 3, "b": True}
    assert [type(plain[k]) for k in "fgib"] == [float, float, int, bool]
    assert stable_hash({"f": np.float64(1.5)}) == content_hash({"f": 1.5})


def test_numpy_arrays_and_unsupported_values_are_rejected() -> None:
    """An array, a set or a non-text key is refused instead of being converted.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(TypeError, match="arrays"):
        to_plain({"x": np.array([1.0])})
    with pytest.raises(TypeError):
        to_plain({1: "a"})
    with pytest.raises(TypeError):
        to_plain({"x": {1, 2}})


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
