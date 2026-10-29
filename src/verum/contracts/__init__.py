"""Loaders and validators for the VERUM schemas and machine-readable contracts.

Each loader reads a file from ``config/`` or ``schemas/``, validates it and
returns an immutable typed object, or raises ``ContractError``.
Source: ``VERUM_INTEGRATION_README.md`` section G (how to use the package).
"""

from verum.contracts.errors import ContractError
from verum.contracts.fluid import FluidContract, load_fluid_contract
from verum.contracts.policy import ReleasePolicy, load_policy
from verum.contracts.schemas import (
    ALL_SCHEMA_NAMES,
    PROPOSED_SCHEMA_NAMES,
    SCHEMA_NAMES,
    load_schema,
    validate,
    validator,
)
from verum.contracts.sensors import SensorContract, load_sensor_contract
from verum.contracts.topology import Topology, load_topology

__all__ = [
    "ALL_SCHEMA_NAMES",
    "PROPOSED_SCHEMA_NAMES",
    "SCHEMA_NAMES",
    "ContractError",
    "FluidContract",
    "ReleasePolicy",
    "SensorContract",
    "Topology",
    "load_fluid_contract",
    "load_policy",
    "load_schema",
    "load_sensor_contract",
    "load_topology",
    "validate",
    "validator",
]
