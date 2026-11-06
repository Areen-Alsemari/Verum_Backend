"""One number rule for messages: an integral value is written as an integer.

JSON producers disagree on whether 300.0 is written as 300, which changes the canonical text and so
the content hash. Every helper here normalises a message before hashing or embedding it, so both
spellings give one hash. Non-finite values and numpy scalars are rejected instead of converted.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from verum.contracts.agent_interfaces import content_hash

EXACT_INTEGER_LIMIT = 2**53  # beyond this a float no longer represents every integer exactly


def normalise(value: Any) -> Any:
    """Return a copy of a JSON-compatible value with integral floats written as integers."""
    if isinstance(value, np.generic | np.ndarray):
        raise TypeError("numpy values must be converted to Python numbers before use in a message")
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return _normalise_float(value)
    if isinstance(value, list | tuple):
        return [normalise(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("message objects need text keys")
        return {key: normalise(item) for key, item in value.items()}
    raise TypeError(f"unsupported message value of type {type(value).__name__}")


def _normalise_float(value: float) -> float | int:
    if not math.isfinite(value):
        raise ValueError("non-finite numeric value in message")
    if value.is_integer() and abs(value) < EXACT_INTEGER_LIMIT:
        return int(value)
    return value


def stable_hash(value: Any) -> str:
    """Hash the canonical JSON of the normalised value, so 300 and 300.0 agree."""
    return content_hash(normalise(value))
