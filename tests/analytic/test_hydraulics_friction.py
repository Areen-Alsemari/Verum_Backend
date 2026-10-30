"""Friction law and straight-pipe losses at the documented reference flows.

The friction factor is checked in the laminar, blended and turbulent ranges, and the head loss for
odd symmetry, monotonicity and the use of the local velocity. The head loss at 300 m3/h in the DN200
line is derived by hand in the "Friction law" section of the verification notes. The tests check
that the law is implemented correctly and not that it is physically valid.

See D14.
"""

from __future__ import annotations

import math

import pytest

import _reference_hydraulics as ref
from verum.hydraulics import friction_factor, head_loss

ARGS = dict(rho=750.0, mu=5.0e-4, roughness=4.5e-5, gravity=9.80665)


def loss(q_m3h: float, d: float, length: float, k: float = 0.0) -> float:
    return head_loss(q_m3h / 3600, d, length, k, **ARGS)


@pytest.mark.parametrize(
    ("q_m3h", "d", "length", "document"),
    [
        (300, ref.D200, 250.0, 6.296),
        (300, ref.D250, 35.0, 0.279),
        (300, ref.D200, 20.0, 0.504),
        (600, ref.D300, 150.0, 1.875),
    ],
)
def test_pipe_only_losses_match_the_document(
    q_m3h: float, d: float, length: float, document: float
) -> None:
    """The pipe-only head losses at the reference flows match the documented values and the
    reference module. Independent: yes, because the figures come from the audit and the hand
    arithmetic, but the law is the same as in the package.
    """
    assert loss(q_m3h, d, length) == pytest.approx(document, abs=0.0015)
    assert loss(q_m3h, d, length) == pytest.approx(ref.loss(q_m3h / 3600, d, length), rel=1e-12)


def test_hand_arithmetic_for_the_250_m_case() -> None:
    """The head loss of 250 m of DN200 pipe at 300 m3/h equals the hand value of 6.292 m.
    Independent: yes, because the value is hand arithmetic.
    """
    assert loss(300, ref.D200, 250.0) == pytest.approx(6.292, abs=0.01)


def test_laminar_friction_is_64_over_re() -> None:
    """Below Re 2300 the friction factor is 64/Re. Independent: yes, because the expected value is
    the laminar formula.
    """
    for re in (1.0, 500.0, 1000.0, 2299.0):
        assert friction_factor(re, 2e-4) == pytest.approx(64 / re, rel=1e-14)


def test_the_blend_is_continuous_at_both_ends() -> None:
    """The friction factor is continuous at Re 2300 and Re 4000. Independent: yes, because only
    continuity is checked.
    """
    rr = 4.5e-5 / ref.D200
    assert friction_factor(2300.0, rr) == pytest.approx(64 / 2300, rel=1e-12)
    assert friction_factor(2300.0 + 1e-9, rr) == pytest.approx(64 / 2300, rel=1e-6)
    assert friction_factor(4000.0, rr) == pytest.approx(
        friction_factor(4000.0 + 1e-9, rr), rel=1e-6
    )


def test_the_blend_is_linear_in_re() -> None:
    """Between Re 2300 and Re 4000 the friction factor is linear in Re. Independent: yes, because
    the expected values are interpolated by hand.
    """
    rr = 4.5e-5 / ref.D200
    low, high = friction_factor(2300.0, rr), friction_factor(4000.0, rr)
    assert friction_factor(3150.0, rr) == pytest.approx((low + high) / 2, rel=1e-12)
    assert friction_factor(2725.0, rr) == pytest.approx(low + 0.25 * (high - low), rel=1e-12)


def test_turbulent_values_follow_haaland() -> None:
    """Above Re 4000 the friction factor equals the Haaland expression of the reference module.
    Independent: no, because the reference module uses the same law.
    """
    rr = 4.5e-5 / ref.D200
    for re in (4001.0, 1e5, 1e6, 1e7):
        assert friction_factor(re, rr) == pytest.approx(ref.friction(re, ref.D200), rel=1e-12)


def test_head_loss_is_odd_in_the_flow() -> None:
    """The head loss changes sign with the flow and is zero at zero flow. Independent: yes, because
    the expected outcome is a symmetry.
    """
    for q in (1e-6, 1e-3, 0.05, 0.2):
        assert head_loss(-q, ref.D200, 100.0, 2.0, **ARGS) == -head_loss(
            q, ref.D200, 100.0, 2.0, **ARGS
        )
    assert head_loss(0.0, ref.D200, 100.0, 2.0, **ARGS) == 0.0


def test_head_loss_increases_strictly_with_flow_over_all_regimes() -> None:
    """The head loss increases strictly with flow across laminar, blended and turbulent flow.
    Independent: yes, because only monotonicity is checked.
    """
    flows = [10 ** (-9 + 0.05 * i) for i in range(0, 140)]
    losses = [head_loss(q, ref.D200, 80.0, 0.0, **ARGS) for q in flows]
    assert all(b > a for a, b in zip(losses, losses[1:], strict=False))


def test_local_loss_uses_the_local_velocity() -> None:
    """A local loss coefficient gives K v^2 / (2 g) with the velocity in the same pipe. Independent:
    yes, because the expected value is the textbook formula.
    """
    q = 300 / 3600
    v = q / (math.pi * ref.D200**2 / 4)
    pure_k = head_loss(q, ref.D200, 0.0, 5.0, **ARGS)
    assert pure_k == pytest.approx(5.0 * v * v / (2 * 9.80665), rel=1e-12)


def test_non_positive_reynolds_number_is_refused() -> None:
    """A non-positive Reynolds number is refused. Independent: yes, because the expected outcome is
    the validation rule.
    """
    with pytest.raises(ValueError):
        friction_factor(0.0, 1e-4)
