"""Evidence registry construction for one analysis snapshot.

The registry holds source rows, derived observation representation rows and derived agent report
rows. Source rows name themselves as their root; a representation names its observation sources;
a report names the union of the roots of everything it consumed. Hashes are taken over the
the plain form of the content, which is the contract hash of the message as written.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from verum.agents.common.ids import require_source_id
from verum.agents.common.numbers import stable_hash, to_plain
from verum.contracts.agent_interfaces import PREFIXES

SOURCE_KINDS = (
    "observation_window",
    "declared_reference",
    "inspection_result",
    "inspection_request",
    "history",
)


class EvidenceRegistry:
    """An ordered, collision-free set of evidence rows bound to one context."""

    def __init__(self, context: dict[str, Any]) -> None:
        self.context = copy.deepcopy(context)
        self._rows: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_rows(
        cls, context: dict[str, Any], rows: Iterable[dict[str, Any]]
    ) -> EvidenceRegistry:
        """Start from rows taken from an existing request, for example an upstream registry."""
        registry = cls(context)
        for row in rows:
            registry.add_row(row)
        return registry

    def rows(self) -> list[dict[str, Any]]:
        """Return copies of the rows in insertion order."""
        return [copy.deepcopy(row) for row in self._rows.values()]

    def row(self, evidence_id: str) -> dict[str, Any]:
        """Return a copy of one row."""
        return copy.deepcopy(self._rows[evidence_id])

    def add_row(self, row: dict[str, Any]) -> None:
        """Add a complete row, or accept an identical repeat of a row already present."""
        known = self._rows.get(row["evidence_id"])
        if known is not None:
            if known != row:
                raise ValueError("evidence identifier already holds different content")
            return
        if row["kind"] != "agent_report":
            require_source_id(row["evidence_id"])
        self._rows[row["evidence_id"]] = copy.deepcopy(row)

    def add_source(
        self, evidence_id: str, kind: str, locator: str, available_at_s: float, content_sha256: str
    ) -> None:
        """Add an original source row that is its own root."""
        if kind not in SOURCE_KINDS:
            raise ValueError(f"{kind!r} is not a source kind")
        prefix, provenance = PREFIXES[kind]
        self._add_new({
            "evidence_id": evidence_id, "kind": kind, "source_ref": prefix + locator,
            "available_at_s": float(available_at_s), "content_sha256": content_sha256,
            "root_evidence_ids": [evidence_id], "provenance": provenance,
        })

    def add_json_source(
        self, evidence_id: str, kind: str, locator: str, available_at_s: float, content: Any
    ) -> None:
        """Add a source row whose hash is taken over its JSON content."""
        self.add_source(evidence_id, kind, locator, available_at_s, stable_hash(content))

    def add_representation(
        self, evidence_id: str, locator: str, available_at_s: float, payload: Any,
        root_ids: list[str],
    ) -> None:
        """Add a derived observation representation bound to the payload that is supplied."""
        if available_at_s > self.context["as_of_s"]:
            raise ValueError("future content cannot enter an agent request")
        for root in root_ids:
            source = self._rows.get(root)
            if source is None or source["kind"] != "observation_window":
                raise ValueError("a representation needs observation window roots")
            if source["available_at_s"] > available_at_s:
                raise ValueError("derived evidence predates its source")
        prefix, provenance = PREFIXES["observation_representation"]
        self._add_new({
            "evidence_id": evidence_id, "kind": "observation_representation",
            "source_ref": prefix + locator, "available_at_s": float(available_at_s),
            "content_sha256": stable_hash(payload), "root_evidence_ids": sorted(set(root_ids)),
            "provenance": provenance,
        })

    def add_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Register an upstream report and return the plain copy to embed."""
        embedded: dict[str, Any] = to_plain(report)
        if embedded["context"] != self.context:
            raise ValueError("report belongs to a different analysis snapshot")
        identifier = embedded["report_id"]
        roots: set[str] = set()
        for consumed in embedded["consumed_evidence_ids"]:
            if consumed not in self._rows:
                raise ValueError("report consumed evidence that the registry does not hold")
            roots.update(self._rows[consumed]["root_evidence_ids"])
        prefix, provenance = PREFIXES["agent_report"]
        self._add_new({
            "evidence_id": identifier, "kind": "agent_report", "source_ref": prefix + identifier,
            "available_at_s": float(self.context["as_of_s"]),
            "content_sha256": stable_hash(embedded), "root_evidence_ids": sorted(roots),
            "provenance": provenance,
        })
        return embedded

    def _add_new(self, row: dict[str, Any]) -> None:
        if row["evidence_id"] in self._rows:
            raise ValueError("duplicate evidence identifier")
        self.add_row(row)
