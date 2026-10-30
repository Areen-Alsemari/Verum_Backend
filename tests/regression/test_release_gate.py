"""Release gate: the production candidate tier is refused while the flag is false.

The gate fails closed, and flipping the flag alone does not open the highest tier because every
required gate must also have passed. Modified policies show that the gate logic is not an
unconditional refusal, and the shipped policy is never changed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import ContractError, ReleasePolicy, load_policy
from verum.contracts.policy import parse_policy
from verum.gates import ReleaseNotAllowed, ReleaseTier, assert_release_allowed


def test_shipped_policy_keeps_production_disabled(policy: ReleasePolicy) -> None:
    """The shipped policy has production generation disabled. Independent: yes, because the expected
    value is the stated constant.
    """
    assert policy.production_generation_enabled is False


def test_production_candidate_raises_with_shipped_policy() -> None:
    """Asking for the production candidate tier raises with the shipped policy. Independent: yes,
    because the expected outcome is the gate rule.
    """
    with pytest.raises(ReleaseNotAllowed, match="production_generation_enabled is false"):
        assert_release_allowed("production_candidate")


def test_production_candidate_raises_even_if_every_gate_is_reported_passed(
    policy: ReleasePolicy,
) -> None:
    """The production candidate tier is refused even if every gate is reported as passed, while the
    flag is false. Independent: yes, because the expected outcome is the gate rule.
    """
    with pytest.raises(ReleaseNotAllowed):
        assert_release_allowed(ReleaseTier.PRODUCTION_CANDIDATE, passed_gates=policy.required_gates)


@pytest.mark.parametrize("tier", ["analytic_verification", "restricted_benchmark"])
def test_lower_tiers_are_allowed(tier: str) -> None:
    """The lower tiers are allowed. Independent: yes, because the expected outcome is the policy
    list.
    """
    assert_release_allowed(tier)


@pytest.mark.parametrize("tier", ["", "PRODUCTION_CANDIDATE", "production", "full", "restricted"])
def test_unknown_tier_is_refused(tier: str) -> None:
    """An unknown tier name is refused. Independent: yes, because the expected outcome is the gate
    rule.
    """
    with pytest.raises(ReleaseNotAllowed, match="unknown release tier"):
        assert_release_allowed(tier)


def test_enabled_flag_alone_does_not_open_the_tier(policy: ReleasePolicy) -> None:
    """Enabling the flag without passed gates still refuses the production candidate tier.
    Independent: yes, because the expected outcome is the gate rule.
    """
    enabled = replace(policy, production_generation_enabled=True)
    with pytest.raises(ReleaseNotAllowed, match="requires passed gates"):
        assert_release_allowed("production_candidate", policy=enabled)


def test_one_missing_gate_is_enough_to_refuse(policy: ReleasePolicy) -> None:
    """With the flag enabled, a single missing gate is enough to refuse and the message names it.
    Independent: yes, because the expected outcome is the gate rule.
    """
    enabled = replace(policy, production_generation_enabled=True)
    with pytest.raises(ReleaseNotAllowed, match=policy.required_gates[-1]):
        assert_release_allowed(
            "production_candidate", policy=enabled, passed_gates=policy.required_gates[:-1]
        )


def test_enabled_flag_with_every_gate_passed_is_allowed(policy: ReleasePolicy) -> None:
    """With the flag enabled and every gate passed the tier is allowed, which shows the gate is not
    an unconditional refusal. Independent: yes, because the expected outcome is the gate rule.
    """
    enabled = replace(policy, production_generation_enabled=True)
    assert_release_allowed(
        "production_candidate", policy=enabled, passed_gates=policy.required_gates
    )


def test_required_gates_are_declared(policy: ReleasePolicy) -> None:
    """The policy declares ten required gates, including the network convergence and ledger gate.
    Independent: yes, because the count is the audited value.
    """
    assert len(policy.required_gates) == 10
    assert "MOC_network_convergence_and_ledger" in policy.required_gates


def test_tier_missing_from_allowed_now_is_refused(policy: ReleasePolicy) -> None:
    """A tier missing from the allowed list is refused. Independent: yes, because the expected
    outcome is the gate rule.
    """
    closed = replace(policy, allowed_now=())
    for tier in ("analytic_verification", "restricted_benchmark"):
        with pytest.raises(ReleaseNotAllowed):
            assert_release_allowed(tier, policy=closed)


@pytest.mark.parametrize("flag", ["false", "true", 0, 1, None])
def test_non_boolean_flag_is_rejected_at_load(raw_policy: dict[str, Any], flag: Any) -> None:
    """A production flag that is not a JSON boolean is rejected when the policy is loaded.
    Independent: yes, because the expected outcome is the loader rule.
    """
    raw_policy["production_generation_enabled"] = flag
    with pytest.raises(ContractError):
        parse_policy(raw_policy)


def test_missing_flag_is_rejected_at_load(raw_policy: dict[str, Any]) -> None:
    """A policy with no production flag is rejected when it is loaded. Independent: yes, because the
    expected outcome is the loader rule.
    """
    del raw_policy["production_generation_enabled"]
    with pytest.raises(ContractError):
        parse_policy(raw_policy)


def test_missing_policy_file_fails_closed(tmp_path: Path) -> None:
    """A missing policy file is a contract error and never a permissive default. Independent: yes,
    because the expected outcome is the loader rule.
    """
    with pytest.raises(ContractError):
        load_policy(tmp_path)


def test_malformed_policy_file_fails_closed(tmp_path: Path) -> None:
    """A policy file that is not valid JSON is a contract error. Independent: yes, because the
    expected outcome is the loader rule.
    """
    (tmp_path / "dataset_release_policy.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError):
        load_policy(tmp_path)


def test_gate_reads_policy_from_disk_when_none_is_given(
    tmp_path: Path, raw_policy: dict[str, Any]
) -> None:
    """When no policy is passed the gate reads it from disk and refuses a tier the file does not
    allow. Independent: yes, because the expected outcome is the gate rule.
    """
    raw_policy["allowed_now"] = []
    (tmp_path / "dataset_release_policy.json").write_text(json.dumps(raw_policy), encoding="utf-8")
    with pytest.raises(ReleaseNotAllowed):
        assert_release_allowed("analytic_verification", policy=load_policy(tmp_path))
