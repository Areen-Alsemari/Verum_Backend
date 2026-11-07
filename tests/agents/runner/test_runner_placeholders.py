"""Checks of the placeholder note and of the option that rejects placeholder agents."""

from __future__ import annotations

from typing import Any

import pytest

from _runner_cases import placeholders, run, snapshot
from verum.agents.common import ROLES, StubAgent
from verum.agents.runner import BundleError, run_analysis, verify_bundle


class Plain:
    """An agent that is not a placeholder: it answers like one but carries no stub marking."""

    def __init__(self, role: str) -> None:
        self.role, self.inner = role, StubAgent(role)

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        response = self.inner.run(request)
        response["implementation"]["name"] = f"{self.role}-model"
        response["issues"] = []
        return response


class Disguised:
    """A wrapper that is not a placeholder class but returns a placeholder response."""

    def __init__(self, role: str) -> None:
        self.inner = StubAgent(role)

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.inner.run(request)


class BrokenStub(StubAgent):
    """A placeholder that fails when it runs."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("broken")


def _codes(bundle_notes: list[dict[str, str]]) -> set[str]:
    return {n["role"] for n in bundle_notes if n["code"] == "PLACEHOLDER_AGENT"}


def test_every_placeholder_role_gets_a_non_blocking_note() -> None:
    """The default run notes all eight placeholders and still verifies.

    Independent: yes, because the notes are read from the bundle.
    """
    bundle = run()
    assert _codes(bundle.notes) == set(ROLES) and bundle.issues == []
    assert len(verify_bundle(bundle).responses) == 8


def test_placeholders_are_rejected_when_not_allowed() -> None:
    """Both entry points refuse a bundle served by placeholders when the option is off.

    Independent: yes, because the rejection is read from the raised error.
    """
    with pytest.raises(BundleError, match="placeholder agents serve: anomaly_detection"):
        run_analysis(
            snapshot(), "runtime", agents=placeholders(), allow_placeholders=False
        )
    bundle = run()
    with pytest.raises(BundleError, match="placeholder agents serve"):
        verify_bundle(bundle, allow_placeholders=False)
    verify_bundle(bundle, allow_placeholders=True)


def test_real_agents_pass_when_placeholders_are_not_allowed() -> None:
    """A run in which no role is a placeholder has no note and passes the strict setting.

    Independent: yes, because the agents are written by the test.
    """
    agents: dict[str, Any] = {role: Plain(role) for role in ROLES}
    bundle = run_analysis(snapshot(), "runtime", agents=agents, allow_placeholders=False)
    assert _codes(bundle.notes) == set() and bundle.issues == []
    verify_bundle(bundle, allow_placeholders=False)


def test_one_remaining_placeholder_is_named() -> None:
    """With seven real agents the strict setting names the one placeholder left.

    Independent: yes, because the agents are written by the test.
    """
    agents: dict[str, Any] = {role: Plain(role) for role in ROLES}
    agents["topology_dependency"] = StubAgent("topology_dependency")
    bundle = run(agents=agents)
    assert _codes(bundle.notes) == {"topology_dependency"}
    with pytest.raises(BundleError, match="placeholder agents serve: topology_dependency$"):
        verify_bundle(bundle, allow_placeholders=False)


def test_a_wrapper_that_returns_a_placeholder_response_is_detected() -> None:
    """A role whose response carries the placeholder marking is a placeholder role.

    Independent: yes, because the wrapper is written by the test.
    """
    agents: dict[str, Any] = {role: Plain(role) for role in ROLES}
    agents["inspection_planning"] = Disguised("inspection_planning")
    bundle = run(agents=agents)
    assert _codes(bundle.notes) == {"inspection_planning"}
    with pytest.raises(BundleError, match="inspection_planning"):
        verify_bundle(bundle, allow_placeholders=False)


def test_a_failing_placeholder_is_still_noted() -> None:
    """A placeholder that raises gives a null report, an issue and the placeholder note.

    Independent: yes, because the failing class is written by the test.
    """
    agents: dict[str, Any] = placeholders()
    agents["predictive_health"] = BrokenStub("predictive_health")
    bundle = run(agents=agents)
    assert bundle.reports["predictive_health"] is None
    assert "predictive_health" in _codes(bundle.notes)
