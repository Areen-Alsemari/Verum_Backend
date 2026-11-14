"""Plain JSON values for messages, hashed exactly as the contract hashes them.

Numbers keep the type they have: 300 and 300.0 are different values with different hashes, because
the contract validators hash a message as written. These helpers therefore never rewrite a number.
They convert numpy scalars to Python numbers at the boundary and reject non-finite values, numpy
arrays and anything that is not plain JSON.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from verum.contracts.agent_interfaces import content_hash


def to_plain(value: Any) -> Any:
    """Return a deep copy made only of Python JSON types, with numbers left unchanged."""
    if isinstance(value, np.ndarray):
        raise TypeError("numpy arrays must be converted to lists before use in a message")
    if isinstance(value, np.generic):
        return to_plain(value.item())
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numeric value in message")
        return value
    if isinstance(value, list | tuple):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("message objects need text keys")
        return {key: to_plain(item) for key, item in value.items()}
    raise TypeError(f"unsupported message value of type {type(value).__name__}")


def stable_hash(value: Any) -> str:
    """Return the contract content hash of the plain form of a value."""
    return content_hash(to_plain(value))
