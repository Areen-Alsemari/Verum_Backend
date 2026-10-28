"""Parameter value with explicit status, evidence tag and unit.

Inputs: a mapping that conforms to ``schemas/paramvalue.schema.json``
(``urn:verum:paramvalue:0.4.0``), or the equivalent constructor arguments.

Outputs: an immutable ``ParamValue``. Reading ``value`` on an unresolved
parameter raises ``UnresolvedParameter``.

Key assumptions:
    * A missing value is never replaced by a default, a zero or a "typical"
      number. Callers either handle ``UnresolvedParameter`` or the code path
      stops.
    * The invariants below are the ones the JSON Schema enforces, restated in
      code so that objects built without going through a schema still cannot
      violate them. ``tests/schema`` checks that both agree on the same cases.
    * Non-finite numbers and booleans are rejected; JSON has no representation
      for the former and the latter are not quantities.

Source: ``revised/05_simulation_validation_dataset.md`` section 7.5
(ParamValue) and section 13.1 rule 1; ``revised/02_hydraulic_model.md``
section 6.1 (unresolved parameters are not permission to use zero).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

STATUSES: Final = ("resolved", "provisional", "unresolved")
EVIDENCE_TAGS: Final = ("REF", "CALC", "DESIGN", "SIM", "OPEN")
_SELECTED_TAGS: Final = ("REF", "CALC", "DESIGN", "SIM")
_FIELDS: Final = frozenset(
    {
        "value",
        "unit",
        "status",
        "evidence_tag",
        "provenance_id",
        "uncertainty",
        "unresolved_reason",
    }
)


class UnresolvedParameter(Exception):
    """Raised when the value of an unresolved parameter is requested."""


class ParamValueError(ValueError):
    """Raised when a parameter record violates the ParamValue invariants."""


@dataclass(frozen=True)
class ParamValue:
    """A physical or numerical parameter together with its provenance.

    ``resolved`` and ``provisional`` records carry a finite number, a selected
    evidence tag and a non-empty provenance identifier. ``unresolved`` records
    carry no number and the ``OPEN`` tag.
    """

    unit: str
    status: str
    evidence_tag: str
    _value: float | None
    provenance_id: str | None = None
    uncertainty: Mapping[str, Any] | None = None
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str) or not self.unit:
            raise ParamValueError("unit must be a non-empty string")
        if self.status not in STATUSES:
            raise ParamValueError(f"unknown status {self.status!r}")
        if self.evidence_tag not in EVIDENCE_TAGS:
            raise ParamValueError(f"unknown evidence_tag {self.evidence_tag!r}")
        if self.status == "unresolved":
            self._check_unresolved()
        else:
            self._check_selected()

    def _check_unresolved(self) -> None:
        if self._value is not None:
            raise ParamValueError("an unresolved parameter must not carry a value")
        if self.evidence_tag != "OPEN":
            raise ParamValueError("an unresolved parameter must be tagged OPEN")

    def _check_selected(self) -> None:
        if self.evidence_tag not in _SELECTED_TAGS:
            raise ParamValueError(f"a {self.status} parameter cannot be tagged OPEN")
        if isinstance(self._value, bool) or not isinstance(self._value, (int, float)):
            raise ParamValueError(f"a {self.status} parameter requires a numeric value")
        if not math.isfinite(self._value):
            raise ParamValueError("parameter values must be finite")
        if not isinstance(self.provenance_id, str) or not self.provenance_id:
            raise ParamValueError(f"a {self.status} parameter requires a provenance_id")

    @property
    def is_resolved(self) -> bool:
        """True when a number is available (status resolved or provisional)."""
        return self.status != "unresolved"

    @property
    def value(self) -> float:
        """The numeric value, or ``UnresolvedParameter`` if none was selected."""
        if self._value is None:
            reason = self.unresolved_reason or "no reason recorded"
            raise UnresolvedParameter(f"parameter in {self.unit!r} is unresolved: {reason}")
        return float(self._value)

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> ParamValue:
        """Build a ``ParamValue`` from a schema-shaped mapping."""
        unknown = set(record) - _FIELDS
        if unknown:
            raise ParamValueError(f"unknown fields: {sorted(unknown)}")
        missing = {"value", "unit", "status", "evidence_tag"} - set(record)
        if missing:
            raise ParamValueError(f"missing fields: {sorted(missing)}")
        return cls(
            unit=record["unit"],
            status=record["status"],
            evidence_tag=record["evidence_tag"],
            _value=record["value"],
            provenance_id=record.get("provenance_id"),
            uncertainty=record.get("uncertainty"),
            unresolved_reason=record.get("unresolved_reason"),
        )

    @classmethod
    def selected(
        cls,
        value: float,
        unit: str,
        evidence_tag: str,
        provenance_id: str,
        status: str = "provisional",
    ) -> ParamValue:
        """Build a provisional (default) or resolved parameter."""
        return cls(
            unit=unit,
            status=status,
            evidence_tag=evidence_tag,
            _value=value,
            provenance_id=provenance_id,
        )

    @classmethod
    def unresolved(cls, unit: str, reason: str | None = None) -> ParamValue:
        """Build an unresolved parameter."""
        return cls(
            unit=unit,
            status="unresolved",
            evidence_tag="OPEN",
            _value=None,
            unresolved_reason=reason,
        )
