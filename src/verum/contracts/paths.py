"""Locations of the contract and schema directories in a source checkout.

Inputs: none.

Outputs: ``Path`` objects for ``config/`` and ``schemas/``.
Key assumptions: the package is used from a source checkout (editable install),
so the repository root is three levels above this file. A different location
can be supplied to every loader through its ``directory`` argument.

Source: ``revised/05_simulation_validation_dataset.md`` section 13.3
(repository layout).
"""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root of a source checkout."""
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    """Return the directory holding the machine-readable contracts."""
    return repo_root() / "config"


def schemas_dir() -> Path:
    """Return the directory holding the JSON Schemas."""
    return repo_root() / "schemas"
