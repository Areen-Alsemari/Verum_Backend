"""Shared validation entry points with the schema validators loaded once.

An agent validates its request before inference and its response before returning it. Loading the
validators reads every schema, so the loaded set is cached for the process.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import jsonschema

from verum.contracts.agent_interfaces import validate_request, validate_response, validators


@cache
def shared_validators() -> dict[str, jsonschema.Draft202012Validator]:
    """Return the role validators, loading them on first use."""
    return validators()


def check_request(request: dict[str, Any]) -> None:
    """Raise if a request breaks the interface contract."""
    validate_request(request, shared_validators())


def check_response(request: dict[str, Any], response: dict[str, Any]) -> None:
    """Raise if a response breaks the contract or does not answer the request."""
    validate_response(request, response, shared_validators())
