"""Read-only interface that exposes agent-visible data of an episode.

The gateway returns observations that are available at a given time, the asset list and the
static inspection catalog, validated against closed schemas. Ground truth, hydraulic state,
fault truth, solver diagnostics, the mass ledger, observation audit rows, validity windows,
the dataset tier, scenario names and rejected simulations are never exposed.

Source: ``revised/05_simulation_validation_dataset.md`` section 7.2
(directory layout and visibility); ``CONTRIBUTING.md``.
"""

from verum.api.gateway import Gateway, GatewayViolation, check_allowlist, query

__all__ = ["Gateway", "GatewayViolation", "check_allowlist", "query"]
