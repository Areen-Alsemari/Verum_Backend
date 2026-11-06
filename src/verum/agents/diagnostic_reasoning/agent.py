"""Agent class of the Diagnostic Reasoning role, currently a placeholder.

The class implements the run interface by answering with the conservative example result. The owner
of the role replaces this base class with the real implementation.
"""

from __future__ import annotations

from verum.agents.common import StubAgent

ROLE = "diagnostic_reasoning"


class DiagnosticReasoningAgent(StubAgent):
    """Placeholder agent for the Diagnostic Reasoning role."""

    def __init__(self) -> None:
        super().__init__(ROLE)
