"""Schema checks with the validators built once.

Building the validator of a schema loads and checks every schema of the registry, so a check that
builds it for each row is slow. This module keeps one validator for each schema name and raises the
same error as the contract module.

See D100.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import Any

from jsonschema.protocols import Validator

from verum.contracts import ContractError, validator


@cache
def _validator(name: str) -> Validator:
    return validator(name)


def check(name: str, document: Mapping[str, Any]) -> None:
    """Raise ``ContractError`` if ``document`` does not satisfy the named schema."""
    errors = sorted(_validator(name).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        raise ContractError(f"{name} document rejected: {detail}")
