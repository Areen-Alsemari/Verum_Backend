"""Loader for the dataset release policy.

The policy fails closed. The production switch must be a JSON boolean, so the string "false" is an
error and not a truthy value, and a missing or unreadable policy file is an error and never a
permissive default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir

FILENAME: Final = "dataset_release_policy.json"


@dataclass(frozen=True)
class ReleasePolicy:
    """Which dataset tiers may currently be produced, and the gates for the last tier."""

    production_generation_enabled: bool
    allowed_now: tuple[str, ...]
    prohibited_until_full_solver_validation: tuple[str, ...]
    required_gates: tuple[str, ...]
    withheld_tags: tuple[str, ...]


def _strings(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    values = raw.get(key)
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ContractError(f"release policy: {key} must be a list of strings")
    return tuple(values)


def parse_policy(raw: dict[str, Any]) -> ReleasePolicy:
    """Validate a decoded release policy."""
    enabled = raw.get("production_generation_enabled")
    if not isinstance(enabled, bool):
        raise ContractError("release policy: production_generation_enabled must be a boolean")
    profile = raw.get("current_observation_profile", {})
    return ReleasePolicy(
        production_generation_enabled=enabled,
        allowed_now=_strings(raw, "allowed_now"),
        prohibited_until_full_solver_validation=_strings(
            raw, "prohibited_until_full_solver_validation"
        ),
        required_gates=_strings(raw, "required_gates"),
        withheld_tags=_strings(profile, "withheld_until_qualified"),
    )


def load_policy(directory: Path | None = None) -> ReleasePolicy:
    """Load and validate the release policy."""
    path = (directory or config_dir()) / FILENAME
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return parse_policy(decoded)
