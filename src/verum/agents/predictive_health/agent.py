"""Agent class of the Predictive Health role, currently a placeholder.

The class implements the run interface by answering with the conservative example result. The owner
of the role replaces this base class with the real implementation.
"""

from __future__ import annotations

from verum.agents.common import StubAgent

ROLE = "predictive_health"


class PredictiveHealthAgent(StubAgent):
    """Placeholder agent for the Predictive Health role."""

    def __init__(self) -> None:
        super().__init__(ROLE)
