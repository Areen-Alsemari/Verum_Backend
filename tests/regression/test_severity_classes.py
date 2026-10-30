"""Severity class boundaries of the agent-side audit (``config/severity_classes.json``).

Inputs: the stored file. Outputs: pass/fail.
Key assumptions (decisions D77 and D78):
    * Every entry is a ``ParamValue``: a boundary that the audit reached is provisional (evidence
      tag SIM) and carries a value in the units of the severity coordinate; one that it did not
      reach inside the range is unresolved and raises when read.
    * The key is ``<fault>/<asset class>/<marginal|clear>_from``; a fault has both boundaries for
      each asset class, the boundary of the clear class is not less severe than that of the marginal
      class, and a resolved value lies inside the severity range of the fault (decisions D60 to
      D64; the range of the leak area, the closure fraction ``1 - ceiling`` of a restriction, the
      head loss fraction ``1 - scale`` of a pump, the sensor fraction of span and the stuck
      opening).
    * Severity grows with the coordinate except for the stuck opening of misrouting (b), where it
      grows as the opening falls, so its clear boundary is the smaller opening.
Independence: the ranges are those of ``verum.faults.validate``, written here as hand arithmetic
(closure 1 - 0.9 to 1 - 0.15, loss 1 - 0.98 to 1 - 0.70).

Source: ``docs/design_decisions.md`` D77 and D78.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.contracts.paths import config_dir
from verum.params import ParamValue, UnresolvedParameter

RANGES = {
    "leak": (2.0e-6, 1.0e-3),
    "restriction_position_visible": (0.10, 0.85),
    "restriction_obstruction": (0.10, 0.85),
    "pump": (0.02, 0.30),
    "bias": (0.002, 0.05),
    "drift": (0.002, 0.05),
    "misroute_b": (0.005, 0.02),
}
TOL = 1e-9


def _load() -> dict[str, ParamValue]:
    raw: dict[str, Any] = json.loads((config_dir() / "severity_classes.json").read_text("utf-8"))
    assert set(raw) >= {"schema_version", "description", "source", "parameters"}
    return {k: ParamValue.from_mapping(v) for k, v in raw["parameters"].items()}


def _groups() -> dict[tuple[str, str], dict[str, ParamValue]]:
    out: dict[tuple[str, str], dict[str, ParamValue]] = {}
    for key, value in _load().items():
        fault, aclass, name = key.split("/")
        out.setdefault((fault, aclass), {})[name] = value
    return out


def test_the_file_loads_and_every_group_has_both_boundaries() -> None:
    groups = _groups()
    assert groups
    for (fault, _), pair in groups.items():
        assert fault in RANGES, fault
        assert set(pair) == {"marginal_from", "clear_from"}


def test_an_unreached_boundary_is_unresolved_and_raises() -> None:
    for pair in _groups().values():
        for value in pair.values():
            if value.status == "unresolved":
                with pytest.raises(UnresolvedParameter):
                    _ = value.value
            else:
                assert value.status == "provisional" and value.evidence_tag == "SIM"
                assert value.provenance_id == "VERUM-PHASE6B-AUDIT-V2"


def test_boundaries_lie_in_the_range_and_are_ordered() -> None:
    for (fault, aclass), pair in _groups().items():
        lo, hi = RANGES[fault]
        resolved = {k: v.value for k, v in pair.items() if v.status != "unresolved"}
        for name, x in resolved.items():
            assert lo - TOL <= x <= hi + TOL, (fault, aclass, name, x)
        if len(resolved) == 2:
            m, c = resolved["marginal_from"], resolved["clear_from"]
            if fault == "misroute_b":
                assert c <= m + TOL, (fault, aclass)
            else:
                assert m <= c + TOL, (fault, aclass)
        if "marginal_from" not in resolved:
            assert "clear_from" not in resolved  # a class cannot be clear if never marginal
