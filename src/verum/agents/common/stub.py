"""Placeholder agent that answers every request with its role's conservative example result.

The stub implements the agent interface so the runner and the other roles can be wired before any
role logic exists. It is marked as a stub in its implementation block, issue and limitations. When
the example result cannot be bound to a request's evidence it reports insufficient evidence.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any, Final

import jsonschema

from verum.agents.common.envelope import build_response, implementation_block, make_issue
from verum.agents.common.roles import require_role
from verum.agents.common.validation import check_request, check_response
from verum.contracts.agent_interfaces import contract_directory

STUB_VERSION: Final = "0.0.0"
STUB_CODE: Final = "STUB_NOT_IMPLEMENTED"
STUB_MESSAGE: Final = "stub, not implemented"
STUB_LIMITATION: Final = "Stub implementation: no role logic is present; the result is unchanged."


@cache
def _example_response(role: str) -> dict[str, Any]:
    path = contract_directory() / "examples" / f"{role}.response.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


class StubAgent:
    """Answers with the role's example result when it fits the request, otherwise declines."""

    def __init__(self, role: str) -> None:
        self.role = require_role(role)

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate the request, answer it, and validate the answer before returning it."""
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")
        for build in (self._rebound, self._declined):
            try:
                response = build(request)
                check_response(request, response)
            except (ValueError, jsonschema.ValidationError):
                continue
            return response
        raise ValueError("stub could not produce a valid response")

    def _implementation(self) -> dict[str, Any]:
        return implementation_block(f"{self.role}-stub", STUB_VERSION)

    def _rebound(self, request: dict[str, Any]) -> dict[str, Any]:
        example = _example_response(self.role)
        known = {row["evidence_id"] for row in request["evidence"]}
        return build_response(
            request,
            status=example["status"],
            result=example["result"],
            consumed_evidence_ids=[i for i in example["consumed_evidence_ids"] if i in known],
            implementation=self._implementation(),
            issues=[make_issue(STUB_CODE, STUB_MESSAGE)],
            limitations=[STUB_LIMITATION],
        )

    def _declined(self, request: dict[str, Any]) -> dict[str, Any]:
        return build_response(
            request,
            status="insufficient_evidence",
            result=None,
            consumed_evidence_ids=[],
            implementation=self._implementation(),
            issues=[make_issue(STUB_CODE, STUB_MESSAGE)],
            limitations=[STUB_LIMITATION],
        )
