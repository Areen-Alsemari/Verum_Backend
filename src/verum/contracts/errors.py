"""Exception type shared by the contract and schema loaders.

Loaders fail closed: a malformed contract is an error and never a silently reduced configuration.
"""

from __future__ import annotations


class ContractError(ValueError):
    """Raised when a contract or a schema-checked document is invalid."""
