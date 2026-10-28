"""Exception type shared by the contract and schema loaders.

Inputs: none.

Outputs: ``ContractError``, raised when a contract file or a
document checked against a schema does not satisfy its definition.
Key assumption: loaders fail closed; a malformed contract is an error, never a
silently reduced configuration.

Source: ``VERUM_INTEGRATION_README.md`` section E (release policy must fail
closed).
"""

from __future__ import annotations


class ContractError(ValueError):
    """Raised when a contract or a schema-checked document is invalid."""
