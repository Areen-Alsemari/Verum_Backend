"""Fail-closed release gate for dataset tiers.

Inputs: a tier name, the release policy (loaded from ``config/`` unless one is
supplied) and, for the highest tier, the set of gates that have passed.

Outputs: ``None`` when the tier may be produced; otherwise an exception.
Key assumptions:
    * The gate refuses by default. An unknown tier, an unreadable policy or a
      tier absent from the policy's ``allowed_now`` list is refused.
    * ``production_candidate`` is refused while
      ``production_generation_enabled`` is false. When the flag is true it is
      still refused unless every gate named in the policy has passed, so
      flipping the flag alone does not open the tier.
    * The policy names the middle tier ``restricted_benchmark_no_physical_fault_training``
      while the documents call it ``restricted_benchmark``; the mapping below
      is the only place that reconciles the two.
    * Passing the gate authorises generation of a tier. It does not assert
      that any physics is validated.

Source: ``dataset_release_policy.json``; ``VERUM_INTEGRATION_README.md``
section E; ``revised/05_simulation_validation_dataset.md`` section 1.5.
"""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum

from verum.contracts.policy import ReleasePolicy, load_policy


class ReleaseTier(StrEnum):
    """Dataset release tiers, lowest to highest."""

    ANALYTIC_VERIFICATION = "analytic_verification"
    RESTRICTED_BENCHMARK = "restricted_benchmark"
    PRODUCTION_CANDIDATE = "production_candidate"


class ReleaseNotAllowed(Exception):
    """Raised when a dataset tier may not be produced."""


_POLICY_NAME = {
    ReleaseTier.ANALYTIC_VERIFICATION: "analytic_verification",
    ReleaseTier.RESTRICTED_BENCHMARK: "restricted_benchmark_no_physical_fault_training",
}


def _as_tier(tier: str) -> ReleaseTier:
    try:
        return ReleaseTier(tier)
    except ValueError:
        raise ReleaseNotAllowed(f"unknown release tier {tier!r}") from None


def _check_production(policy: ReleasePolicy, passed_gates: Collection[str]) -> None:
    if not policy.production_generation_enabled:
        raise ReleaseNotAllowed(
            "production_candidate is not allowed: production_generation_enabled is false"
        )
    missing = [g for g in policy.required_gates if g not in passed_gates]
    if missing:
        raise ReleaseNotAllowed(f"production_candidate requires passed gates: {missing}")


def assert_release_allowed(
    tier: str,
    policy: ReleasePolicy | None = None,
    passed_gates: Collection[str] = (),
) -> None:
    """Raise ``ReleaseNotAllowed`` unless ``tier`` may be produced now."""
    resolved = _as_tier(tier)
    active = policy if policy is not None else load_policy()
    if resolved is ReleaseTier.PRODUCTION_CANDIDATE:
        _check_production(active, passed_gates)
        return
    if _POLICY_NAME[resolved] not in active.allowed_now:
        raise ReleaseNotAllowed(f"{resolved.value} is not listed in the policy's allowed_now")
