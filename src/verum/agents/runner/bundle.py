"""The result of an analysis run: requests sent, reports received and what went wrong.

A failed role has a null report and an issue. The cross-cutting rules for a whole bundle are
checked separately before a bundle is handed on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from verum.agents.common import EvidenceRegistry


class BundleError(ValueError):
    """A set of messages breaks a rule that holds across the whole analysis."""


@dataclass
class Bundle:
    """Requests sent, reports received (null for a role that failed), and what went wrong."""

    context: dict[str, Any]
    registry: EvidenceRegistry
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    reports: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class VerifiedBundle:
    """Validated responses with the context and evidence that bind them."""

    context: dict[str, Any]
    responses: dict[str, dict[str, Any]]
    evidence: list[dict[str, Any]]
    issues: tuple[dict[str, str], ...]
