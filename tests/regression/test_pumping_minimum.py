"""Configured pumping-minimum levels: consistency with the solver and with the geometry minimum.

Each stored level is the smallest level, to 1e-4 m, at which the solved operating point passes the
screen. The checks use the production solver, so they confirm that the stored file matches the study
and are not an independent validation of the screen itself. The 1.8 m geometry minimum of the
topology is separate from these levels.

See D7.
"""

from __future__ import annotations

import pytest

from _hydraulic_cases import TANKS, delivery_case
from verum.contracts import ContractError, Topology
from verum.hydraulics import HydraulicModel, pumping_minimum_level
from verum.params import UnresolvedParameter

STRATA = (25.0, 35.0, 45.0)
PROFILES = ("pipe_only", "reference_fittings")
COEFFICIENTS = (2.5, 4.0, 6.0)
COMBINATIONS = [(t, s, p, c) for t in TANKS for s in STRATA for p in PROFILES for c in COEFFICIENTS]


def _passes(
    model: HydraulicModel, tank: str, level: float, temp: float, profile: str, coeff: float
) -> bool:
    inputs = delivery_case(tank, level, profile=profile, temperature_c=temp, npsh3=coeff)
    return model.solve(inputs).phase.status == "OK"


def test_there_are_54_combinations() -> None:
    """The table has 54 combinations of tank, temperature, fitting profile and NPSH3 coefficient.
    Independent: yes, because the count is arithmetic on the grid.
    """
    assert len(COMBINATIONS) == 54


@pytest.mark.parametrize(("tank", "temp", "profile", "coeff"), COMBINATIONS)
def test_stored_level_is_the_lowest_passing_level(
    model: HydraulicModel, tank: str, temp: float, profile: str, coeff: float
) -> None:
    """Each stored level passes the screen, a level 1e-3 m lower does not, and an unresolved entry
    never passes. Independent: no, because the check uses the production solver and only confirms
    that the file matches the study.
    """
    record = pumping_minimum_level(tank, temp, profile, coeff)
    if not record.is_resolved:
        assert not _passes(model, tank, 12.0, temp, profile, coeff)
        with pytest.raises(UnresolvedParameter):
            _ = record.value
        return
    level = record.value
    assert 1.8 <= level <= 12.0
    assert _passes(model, tank, level, temp, profile, coeff)
    if level > 1.8:
        assert not _passes(model, tank, level - 2e-4, temp, profile, coeff)


def test_levels_never_decrease_with_temperature_or_npsh3(model: HydraulicModel) -> None:
    """The stored levels never fall as the temperature or the NPSH3 coefficient rises. Independent:
    yes, because only monotonicity is checked.
    """
    def value(t: str, s: float, p: str, c: float) -> float:
        record = pumping_minimum_level(t, s, p, c)
        return record.value if record.is_resolved else float("inf")

    for tank in TANKS:
        for profile in PROFILES:
            for coeff in COEFFICIENTS:
                v = [value(tank, s, profile, coeff) for s in STRATA]
                assert v == sorted(v)
            for temp in STRATA:
                v = [value(tank, temp, profile, c) for c in COEFFICIENTS]
                assert v == sorted(v)


def test_reference_fittings_never_lower_the_minimum(model: HydraulicModel) -> None:
    """The reference fittings never give a lower minimum level than the pipe-only profile.
    Independent: yes, because only the ordering is checked.
    """
    for tank, temp, coeff in [(t, s, c) for t in TANKS for s in STRATA for c in COEFFICIENTS]:
        a = pumping_minimum_level(tank, temp, "pipe_only", coeff)
        b = pumping_minimum_level(tank, temp, "reference_fittings", coeff)
        va = a.value if a.is_resolved else float("inf")
        vb = b.value if b.is_resolved else float("inf")
        assert vb >= va - 1e-9


def test_member_one_minimum_is_unchanged_and_separate(topology: Topology) -> None:
    """The 1.8 m geometry minimum is unchanged, and the pumping minimum is a separate record with
    provenance. Independent: yes, because the expected value is the contract constant.
    """
    assert all(t.dimensions_m["normal_min_level_m"] == 1.8 for t in topology.tanks)
    record = pumping_minimum_level("TK-103", 45.0, "pipe_only", 4.0)
    assert record.value > 1.8 and record.provenance_id


def test_unknown_combination_is_a_contract_error() -> None:
    """An unknown combination is a contract error. Independent: yes, because the expected outcome is
    the validation rule.
    """
    with pytest.raises(ContractError):
        pumping_minimum_level("TK-104", 25.0, "pipe_only", 4.0)
    with pytest.raises(ContractError):
        pumping_minimum_level("TK-101", 30.0, "pipe_only", 4.0)
