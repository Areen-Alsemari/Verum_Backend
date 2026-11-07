"""Agent class of the Evidence Verification and Decision role, currently a placeholder.

The class implements the run interface by answering with the conservative example result. The owner
of the role replaces this base class with the real implementation.
"""

from __future__ import annotations

from verum.agents.common import StubAgent

ROLE = "evidence_verification_decision"


class EvidenceVerificationDecisionAgent(StubAgent):
    """Placeholder agent for the Evidence Verification and Decision role."""

    def __init__(self) -> None:
        super().__init__(ROLE)
