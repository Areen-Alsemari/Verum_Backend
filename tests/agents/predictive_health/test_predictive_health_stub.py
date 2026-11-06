"""Placeholder checks for the predictive health agent.

The placeholder must accept the role's example request and return a response the contract accepts.
"""

from __future__ import annotations

from _agent_stubs import assert_stub_answers_example, example_request
from verum.agents.common import check_request, check_response
from verum.agents.predictive_health import PredictiveHealthAgent


def test_predictive_health_stub_passes_the_contract_on_its_example() -> None:
    """The placeholder answers its example request with a valid response marked as a stub.

    Independent: yes, because the contract validators are separate from the placeholder.
    """
    assert_stub_answers_example(PredictiveHealthAgent(), "predictive_health")


def test_predictive_health_stub_declines_when_its_example_does_not_fit() -> None:
    """A request for a channel the example does not cover gets an insufficient-evidence answer.

    Independent: yes, because the contract validators judge the fallback answer.
    """
    request = example_request("predictive_health")
    request["input"]["target_tag_ids"] = ["PT-001"]
    check_request(request)
    response = PredictiveHealthAgent().run(request)
    check_response(request, response)
    assert response["status"] == "insufficient_evidence" and response["result"] is None
    assert [issue["message"] for issue in response["issues"]] == ["stub, not implemented"]
