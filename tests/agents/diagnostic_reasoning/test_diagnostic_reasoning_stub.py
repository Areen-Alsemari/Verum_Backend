"""Placeholder checks for the diagnostic reasoning agent.

The placeholder must accept the role's example request and return a response the contract accepts.
"""

from __future__ import annotations

from _agent_stubs import assert_stub_answers_example
from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent


def test_diagnostic_reasoning_stub_passes_the_contract_on_its_example() -> None:
    """The placeholder answers its example request with a valid response marked as a stub.

    Independent: yes, because the contract validators are separate from the placeholder.
    """
    assert_stub_answers_example(DiagnosticReasoningAgent(), "diagnostic_reasoning")
