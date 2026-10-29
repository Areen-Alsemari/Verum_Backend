"""Loading and checking documents against the VERUM JSON Schemas.

Inputs: schema files in ``schemas/`` (Draft 2020-12) and candidate documents.

Outputs: validators, and ``validate`` which raises ``ContractError`` on the
first group of violations.
Key assumptions:
    * The six audited schemas are ``SCHEMA_NAMES``; the eight hidden-dataset schemas
      of the engine are ``PROPOSED_SCHEMA_NAMES`` (version 0.7.0, marked
      ``x-status: backend-proposed`` for review by the schema owner).
    * ``fault_truth`` refers to ``urn:verum:paramvalue:0.4.0``; the registry
      built here resolves that reference locally, never over the network.
    * Format assertions (for example ``date-time``) are enabled; a schema that
      merely annotates formats would accept malformed timestamps.
    * A schema validating a document says nothing about physical plausibility.

Source: ``revised/05_simulation_validation_dataset.md`` section 7.5 and
section 8.9; ``tests/schema`` holds the positive and negative cases.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from verum.contracts.errors import ContractError
from verum.contracts.paths import schemas_dir

SCHEMA_NAMES: Final = (
    "paramvalue",
    "observation",
    "observation_audit",
    "fault_truth",
    "inspection_request",
    "inspection_result",
)


PROPOSED_SCHEMA_NAMES: Final = (
    "hydraulic_state",
    "solver_diagnostics",
    "mass_ledger",
    "events",
    "episode",
    "simulation_rejected",
    "boundary_state",
    "validity_windows",
)
ALL_SCHEMA_NAMES: Final = (*SCHEMA_NAMES, *PROPOSED_SCHEMA_NAMES)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ContractError(f"{path} does not contain a JSON object")
    return loaded


def load_schema(name: str, directory: Path | None = None) -> dict[str, Any]:
    """Load one schema by short name, for example ``"observation"``."""
    if name not in ALL_SCHEMA_NAMES:
        raise ContractError(f"unknown schema {name!r}")
    schema = _read_json((directory or schemas_dir()) / f"{name}.schema.json")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ContractError(f"schema {name} is not a valid Draft 2020-12 schema") from exc
    return schema


def schema_registry(directory: Path | None = None) -> Registry[Any]:
    """Return a registry in which every VERUM schema resolves by its ``$id``."""
    registry: Registry[Any] = Registry()
    for name in ALL_SCHEMA_NAMES:
        schema = load_schema(name, directory)
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema, DRAFT202012)
        )
    return registry


def validator(name: str, directory: Path | None = None) -> jsonschema.Draft202012Validator:
    """Return a validator for the named schema with format checking enabled."""
    return jsonschema.Draft202012Validator(
        load_schema(name, directory),
        registry=schema_registry(directory),
        format_checker=jsonschema.FormatChecker(),
    )


def validate(name: str, document: Mapping[str, Any], directory: Path | None = None) -> None:
    """Raise ``ContractError`` if ``document`` does not satisfy the named schema."""
    errors = sorted(validator(name, directory).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        raise ContractError(f"{name} document rejected: {detail}")
