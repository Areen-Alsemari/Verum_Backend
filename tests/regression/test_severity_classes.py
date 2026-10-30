"""Severity class boundaries of the agent-side audit.

Every entry is a parameter record: a boundary that the audit reached is provisional and carries a
value in the units of the severity coordinate, and one that it did not reach inside the range is
unresolved and raises when read. A fault has a marginal and a clear boundary for each asset class,
the clear boundary is not less severe than the marginal one, and a resolved value lies inside the
severity range of the fault. The ranges are written here as hand arithmetic.

See D60 to D64, D78 and D79.
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
    """The stored file loads and every fault and asset class has both a marginal and a clear
    boundary. Independent: yes, because the expected structure is the stated rule.
    """
    groups = _groups()
    assert groups
    for (fault, _), pair in groups.items():
        assert fault in RANGES, fault
        assert set(pair) == {"marginal_from", "clear_from"}


def test_an_unreached_boundary_is_unresolved_and_raises() -> None:
    """A boundary that the audit did not reach is unresolved and raises when its value is read.
    Independent: yes, because the expected outcome is the rule that nothing replaces an unresolved
    parameter.
    """
    for pair in _groups().values():
        for value in pair.values():
            if value.status == "unresolved":
                with pytest.raises(UnresolvedParameter):
                    _ = value.value
            else:
                assert value.status == "provisional" and value.evidence_tag == "SIM"
                assert value.provenance_id == "VERUM-DD-D79-v1.0"


def test_boundaries_lie_in_the_range_and_are_ordered() -> None:
    """Resolved boundaries lie inside the severity range of their fault and the clear boundary is
    not less severe than the marginal one. Independent: yes, because the ranges are hand arithmetic.
    """
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
