"""Find the agent of a role by convention, so a replacement needs no change to the runner.

The module for a role holds one class whose name ends in Agent and which defines run. A factory
function named create_agent in the same module takes precedence when it exists.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from verum.agents.common.roles import require_role
from verum.contracts.agent_interfaces import Agent


def load_agent(role: str) -> Agent:
    """Import the role's module afresh from the module table and return a new agent."""
    module = importlib.import_module(f"verum.agents.{require_role(role)}.agent")
    factory = getattr(module, "create_agent", None)
    if callable(factory):
        agent: Agent = factory()
        return agent
    classes = [
        member for _, member in inspect.getmembers(module, inspect.isclass)
        if member.__module__ == module.__name__ and member.__name__.endswith("Agent")
        and callable(getattr(member, "run", None))
    ]
    if len(classes) != 1:
        raise LookupError(f"expected one agent class for {role}, found {len(classes)}")
    instance: Any = classes[0]()
    agent = instance
    return agent
