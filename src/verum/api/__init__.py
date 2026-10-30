"""Read-only interface that exposes the agent-visible data of an episode.

The gateway returns the observations available at a given time, the asset list and the static
inspection catalog, all validated against closed schemas. Ground truth, hydraulic state, fault
truth, solver diagnostics, the mass ledger, audit rows, validity windows, the dataset tier, scenario
names and rejected simulations are never exposed.
"""

from verum.api.gateway import Gateway, GatewayViolation, check_allowlist, query

__all__ = ["Gateway", "GatewayViolation", "check_allowlist", "query"]
