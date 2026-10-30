"""Locations of the contract and schema directories in a source checkout.

The package is used from a source checkout, so the repository root is three levels above this file.
Every loader accepts another directory through its own argument.
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
