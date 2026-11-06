"""Agent class of the Topology and Dependency role, currently a placeholder.

The class implements the run interface by answering with the conservative example result. The owner
of the role replaces this base class with the real implementation.
"""

from __future__ import annotations

from verum.agents.common import StubAgent

ROLE = "topology_dependency"


class TopologyDependencyAgent(StubAgent):
    """Placeholder agent for the Topology and Dependency role."""

    def __init__(self) -> None:
        super().__init__(ROLE)
