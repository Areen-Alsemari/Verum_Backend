"""Friction law and straight-pipe losses at the audited reference flows.

Inputs: ``verum.hydraulics.friction`` and the audited bores. Outputs: pass/fail.

Derivation of the expected values (hand arithmetic, DN200, 300 m3/h):
    Q = 300/3600 = 0.083333 m3/s; A = pi 0.20274^2 / 4 = 0.032283 m2;
    v = 2.5813 m/s; Re = 750 x 2.5813 x 0.20274 / 0.0005 = 7.85e5 (turbulent).
    eps/D = 4.5e-5/0.20274 = 2.2196e-4; (2.2196e-4/3.7)^1.11 = 2.055e-5;
    6.9/Re = 8.79e-6; sum 2.934e-5; log10 = -4.5326; 1/sqrt(f) = 8.1587;
    f = 0.015023. Head loss over 250 m: 0.015023 x (250/0.20274) x (v^2/2g =
    0.33964 m) = 6.292 m by hand, which the audited document gives as 6.296 m.
Independence: the document figures (6.296, 0.279, 0.504, 1.875 m) were produced
by the audit's script, and the hand arithmetic above is separate from the
package. The friction law itself (D14) is the same law in the package, the
document and ``_reference_hydraulics``; the tests therefore do not check the
law's physical validity, only its correct implementation.

Source: ``revised/02_hydraulic_model.md`` section 3 (loss figures); decision D14.
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
    assert loss(q_m3h, d, length) == pytest.approx(document, abs=0.0015)
    assert loss(q_m3h, d, length) == pytest.approx(ref.loss(q_m3h / 3600, d, length), rel=1e-12)


def test_hand_arithmetic_for_the_250_m_case() -> None:
    assert loss(300, ref.D200, 250.0) == pytest.approx(6.292, abs=0.01)


def test_laminar_friction_is_64_over_re() -> None:
    for re in (1.0, 500.0, 1000.0, 2299.0):
        assert friction_factor(re, 2e-4) == pytest.approx(64 / re, rel=1e-14)


def test_the_blend_is_continuous_at_both_ends() -> None:
    rr = 4.5e-5 / ref.D200
    assert friction_factor(2300.0, rr) == pytest.approx(64 / 2300, rel=1e-12)
    assert friction_factor(2300.0 + 1e-9, rr) == pytest.approx(64 / 2300, rel=1e-6)
    assert friction_factor(4000.0, rr) == pytest.approx(
        friction_factor(4000.0 + 1e-9, rr), rel=1e-6
    )


def test_the_blend_is_linear_in_re() -> None:
    rr = 4.5e-5 / ref.D200
    low, high = friction_factor(2300.0, rr), friction_factor(4000.0, rr)
    assert friction_factor(3150.0, rr) == pytest.approx((low + high) / 2, rel=1e-12)
    assert friction_factor(2725.0, rr) == pytest.approx(low + 0.25 * (high - low), rel=1e-12)


def test_turbulent_values_follow_haaland() -> None:
    rr = 4.5e-5 / ref.D200
    for re in (4001.0, 1e5, 1e6, 1e7):
        assert friction_factor(re, rr) == pytest.approx(ref.friction(re, ref.D200), rel=1e-12)


def test_head_loss_is_odd_in_the_flow() -> None:
    for q in (1e-6, 1e-3, 0.05, 0.2):
        assert head_loss(-q, ref.D200, 100.0, 2.0, **ARGS) == -head_loss(
            q, ref.D200, 100.0, 2.0, **ARGS
        )
    assert head_loss(0.0, ref.D200, 100.0, 2.0, **ARGS) == 0.0


def test_head_loss_increases_strictly_with_flow_over_all_regimes() -> None:
    flows = [10 ** (-9 + 0.05 * i) for i in range(0, 140)]
    losses = [head_loss(q, ref.D200, 80.0, 0.0, **ARGS) for q in flows]
    assert all(b > a for a, b in zip(losses, losses[1:], strict=False))


def test_local_loss_uses_the_local_velocity() -> None:
    q = 300 / 3600
    v = q / (math.pi * ref.D200**2 / 4)
    pure_k = head_loss(q, ref.D200, 0.0, 5.0, **ARGS)
    assert pure_k == pytest.approx(5.0 * v * v / (2 * 9.80665), rel=1e-12)


def test_non_positive_reynolds_number_is_refused() -> None:
    with pytest.raises(ValueError):
        friction_factor(0.0, 1e-4)
