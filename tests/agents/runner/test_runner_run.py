"""Checks of the runner: a normal run, failing agents, bad upstream input and agent replacement."""

from __future__ import annotations

import sys
import time
import types
from typing import Any

import pytest

from _runner_cases import placeholders, run
from verum.agents.common import ROLES, StubAgent, attached_report_ids, report_id
from verum.agents.runner import load_agent, verify_bundle
from verum.agents.runner.wiring import UPSTREAM, workflow_stages

KINDS = ["raises", "not_object", "schema", "timeout", "wrong_revision", "fixture_mode", "ignores"]


class Faulty:
    """An agent that answers with a placeholder response damaged in a chosen way."""

    def __init__(self, role: str, kind: str) -> None:
        self.role, self.kind, self.inner = role, kind, StubAgent(role)

    def run(self, request: dict[str, Any]) -> Any:
        response = self.inner.run(request)
        if self.kind == "raises":
            raise RuntimeError("model file missing")
        if self.kind == "not_object":
            return "done"
        if self.kind == "schema":
            del response["result"]
        elif self.kind == "timeout":
            time.sleep(0.5)
        elif self.kind == "wrong_revision":
            response["context"]["revision"] = 5
        elif self.kind == "fixture_mode":
            response["context"]["execution_mode"] = "contract_fixture"
        elif self.kind == "ignores":
            attached = set(attached_report_ids(request))
            response["consumed_evidence_ids"] = [
                i for i in response["consumed_evidence_ids"] if i not in attached
            ]
        return response


def test_a_normal_run_answers_every_role_in_manifest_order() -> None:
    """All eight roles answer, in the order of the manifest stages, with no issue.

    Independent: yes, because the order is read from the manifest and the bundle is verified.
    """
    bundle = run()
    order = [role for stage in workflow_stages() for role in stage]
    assert list(bundle.requests) == order and set(order) == set(ROLES)
    assert bundle.issues == [] and all(bundle.reports[r] is not None for r in ROLES)
    verified = verify_bundle(bundle)
    assert set(verified.responses) == set(ROLES)
    assert order.index("predictive_health") < order.index("anomaly_detection")
    assert order.index("inspection_quality_documentation") < order.index("diagnostic_reasoning")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("kind", KINDS)
def test_a_failing_agent_becomes_a_null_report_and_the_run_continues(role: str, kind: str) -> None:
    """A failure gives a null report and an issue, adds no evidence and stops nothing.

    Independent: yes, because the registry and the other reports are inspected directly.
    """
    agents: dict[str, Any] = placeholders()
    agents[role] = Faulty(role, kind)
    bundle = run(agents=agents, timeout_s=0.1 if kind == "timeout" else None)
    reports_attached = bool(UPSTREAM.get(role))
    if kind == "ignores" and not reports_attached:
        assert bundle.reports[role] is not None and bundle.issues == []
        return
    assert bundle.reports[role] is None
    assert [i["role"] for i in bundle.issues] == [role]
    request = bundle.requests[role]
    lost = report_id(role, bundle.context["analysis_id"], request["request_id"])
    assert lost not in {row["evidence_id"] for row in bundle.registry.rows()}
    assert all(bundle.reports[r] is not None for r in ROLES if r != role)
    for consumer, fields in UPSTREAM.items():
        for field, producer in fields.items():
            if producer == role and consumer in bundle.requests:
                assert bundle.requests[consumer]["input"][field] is None
    verify_bundle(bundle)


@pytest.mark.parametrize(
    "kind, code",
    [("raises", "AGENT_ERROR"), ("not_object", "AGENT_INVALID_RESPONSE"),
     ("schema", "AGENT_INVALID_RESPONSE"), ("timeout", "AGENT_TIMEOUT"),
     ("wrong_revision", "AGENT_INVALID_RESPONSE"), ("fixture_mode", "AGENT_INVALID_RESPONSE")],
)
def test_each_failure_kind_has_its_own_issue_code(kind: str, code: str) -> None:
    """The issue code tells an exception, a timeout and an invalid response apart.

    Independent: yes, because the codes are literals.
    """
    agents: dict[str, Any] = placeholders()
    agents["predictive_health"] = Faulty("predictive_health", kind)
    bundle = run(agents=agents, timeout_s=0.1)
    assert [i["code"] for i in bundle.issues] == [code]
    assert "predictive_health" == bundle.issues[0]["role"]


def test_null_upstream_reports_leave_unknown_checks() -> None:
    """With Agent 1 and Agent 7 down, Agent 5 still answers and marks those checks unknown.

    Independent: yes, because the checks are read from the response, not from the runner.
    """
    agents: dict[str, Any] = placeholders()
    for role in ("predictive_health", "inspection_quality_documentation"):
        agents[role] = Faulty(role, "raises")
    bundle = run(agents=agents)
    diagnosis = bundle.reports["diagnostic_reasoning"]
    assert diagnosis is not None
    outcomes = {c["check_id"]: c["outcome"] for c in diagnosis["result"]["upstream_checks"]}
    assert set(outcomes.values()) == {"unknown"}
    assert bundle.requests["diagnostic_reasoning"]["input"]["forecast_report"] is None


def test_a_wrong_context_upstream_report_is_not_attached() -> None:
    """A report from another revision is rejected where it is returned and never reused.

    Independent: yes, because the registry and the downstream request are inspected directly.
    """
    agents: dict[str, Any] = placeholders()
    agents["predictive_health"] = Faulty("predictive_health", "wrong_revision")
    bundle = run(agents=agents)
    assert bundle.requests["anomaly_detection"]["input"]["forecast_report"] is None


def test_a_fixture_mode_report_in_a_runtime_run_is_rejected() -> None:
    """A report that declares the fixture mode cannot enter a runtime analysis.

    Independent: yes, because the issue text is read from the run.
    """
    agents: dict[str, Any] = placeholders()
    agents["topology_dependency"] = Faulty("topology_dependency", "fixture_mode")
    bundle = run(agents=agents)
    assert bundle.reports["topology_dependency"] is None
    assert bundle.issues[0]["code"] == "AGENT_INVALID_RESPONSE"
    assert "does not match" in bundle.issues[0]["message"]


def test_a_run_in_fixture_mode_is_valid_and_labelled() -> None:
    """The same run in fixture mode stays consistent and carries the fixture label.

    Independent: yes, because the label is a literal.
    """
    bundle = run("contract_fixture")
    assert bundle.context["execution_mode"] == "contract_fixture" and bundle.issues == []
    verify_bundle(bundle)


def test_replacing_a_placeholder_needs_no_runner_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A different agent class in the role's module is used by the next run as it is.

    Independent: yes, because the replacement is a separate class written by the test.
    """
    module = types.ModuleType("verum.agents.predictive_health.agent")

    class OwnerAgent(StubAgent):
        def __init__(self) -> None:
            super().__init__("predictive_health")

        def _implementation(self) -> dict[str, Any]:
            return {"name": "owner-model", "version": "9", "artifact_sha256": None,
                    "feature_profile_id": None}

    OwnerAgent.__module__ = module.__name__
    module.OwnerAgent = OwnerAgent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    agents = {r: a for r, a in placeholders().items() if r != "predictive_health"}
    bundle = run(agents=agents)
    report = bundle.reports["predictive_health"]
    assert report is not None and report["implementation"]["name"] == "owner-model"
    assert isinstance(load_agent("predictive_health"), OwnerAgent)


def test_discovery_prefers_a_factory_and_rejects_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A create_agent factory wins, and two agent classes in one module are an error.

    Independent: yes, because the modules are written by the test.
    """
    name = "verum.agents.anomaly_detection.agent"
    factory = types.ModuleType(name)
    factory.create_agent = lambda: StubAgent("anomaly_detection")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, name, factory)
    assert isinstance(load_agent("anomaly_detection"), StubAgent)
    two = types.ModuleType(name)
    for label in ("OneAgent", "TwoAgent"):
        cls = type(label, (), {"run": lambda self, request: {}, "__module__": name})
        setattr(two, label, cls)
    monkeypatch.setitem(sys.modules, name, two)
    with pytest.raises(LookupError):
        load_agent("anomaly_detection")
    with pytest.raises(ValueError, match="unknown agent role"):
        load_agent("nonsense")


def test_an_undiscoverable_agent_is_an_issue_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A role module without an agent class gives a null report and the run goes on.

    Independent: yes, because the empty module is written by the test.
    """
    name = "verum.agents.topology_dependency.agent"
    monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    agents = {r: a for r, a in placeholders().items() if r != "topology_dependency"}
    bundle = run(agents=agents)
    assert bundle.reports["topology_dependency"] is None
    assert bundle.issues[0]["code"] == "AGENT_ERROR"
    assert bundle.reports["diagnostic_reasoning"] is not None
