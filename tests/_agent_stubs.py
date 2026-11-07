"""Shared checks for the placeholder agent of each role.

The per-role tests call one function so every role proves the same behaviour on its own example.
"""

from __future__ import annotations

import json
from typing import Any

from verum.agents.common import check_request, check_response
from verum.contracts.agent_interfaces import contract_directory


def example_request(role: str) -> dict[str, Any]:
    """Load the example request of a role."""
    path = contract_directory() / "examples" / f"{role}.request.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def assert_stub_answers_example(agent: Any, role: str) -> dict[str, Any]:
    """Run the agent on the role's example request and check the contract and the stub marking."""
    request = example_request(role)
    check_request(request)
    response: dict[str, Any] = agent.run(request)
    check_response(request, response)
    assert response["agent"] == role
    assert response["request_id"] == request["request_id"]
    assert response["context"] == request["context"]
    assert "stub" in response["implementation"]["name"]
    assert any(issue["message"] == "stub, not implemented" for issue in response["issues"])
    assert response["advisory_only"] is True
    return response
