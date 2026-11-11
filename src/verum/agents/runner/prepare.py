"""Shared preparation of one run: the context, the evidence registry and the common inputs.

Source evidence is registered once, in the identifiers the example messages use. Whatever the
snapshot does not supply is left empty or null and noted, never filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from verum.agents.common import (
    TAG_ORDER,
    EvidenceRegistry,
    attach_summary,
    make_context,
    stable_hash,
    to_plain,
)
from verum.agents.runner.facts import reference_facts
from verum.agents.runner.snapshot import Snapshot

SOURCE = "source-observations"
REFERENCE = "source-reference"
FEATURES = "features-summary"


@dataclass
class Prepared:
    """Everything the request builders read, fixed once per run."""

    snapshot: Snapshot
    context: dict[str, Any]
    registry: EvidenceRegistry
    observations: dict[str, Any]
    assets: list[dict[str, Any]]
    connections: list[dict[str, Any]]
    catalog: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    query_assets: list[str]
    forecast_tags: list[str]
    result_ids: list[str]
    notes: list[dict[str, str]] = field(default_factory=list)


def note(prep: Prepared, role: str, code: str, message: str) -> None:
    """Record that the snapshot or the reference lacked something a role would use."""
    prep.notes.append({"role": role, "code": code, "message": message})


def _add_rows(
    registry: EvidenceRegistry, kind: str, prefix: str, key: str, rows: tuple[dict[str, Any], ...],
    available_at_s: float,
) -> list[str]:
    ids = []
    for row in rows:
        identifier = f"{prefix}-{row[key]}"
        if identifier not in {r["evidence_id"] for r in registry.rows()}:
            registry.add_json_source(identifier, kind, row[key], available_at_s, to_plain(row))
        ids.append(identifier)
    return ids


def prepare(snapshot: Snapshot, mode: str) -> Prepared:
    """Build the context and registry for a snapshot and collect its public inputs."""
    cutoff = float(snapshot.as_of_s)
    context = make_context(
        case_id=snapshot.case_id, revision=snapshot.revision, as_of_s=cutoff,
        execution_mode=mode, reference_snapshot_sha256=snapshot.reference_snapshot_sha256,
    )
    registry = EvidenceRegistry(context)
    window_hash = snapshot.source_sha256 or stable_hash(snapshot.summary)
    registry.add_source(SOURCE, "observation_window", f"cutoff-{cutoff}", cutoff, window_hash)
    registry.add_source(
        REFERENCE, "declared_reference", "public_reference", 0.0, snapshot.reference_snapshot_sha256
    )
    observations = attach_summary(
        registry, snapshot.summary, evidence_id=FEATURES, locator=f"summary-{cutoff}",
        root_ids=[SOURCE], available_at_s=cutoff,
    )
    reference = snapshot.reference
    assets = to_plain(reference.get("assets", []))
    units = {i["tag_id"]: i["unit"] for i in reference.get("instruments", [])}
    prep = Prepared(
        snapshot=snapshot, context=context, registry=registry, observations=observations,
        assets=assets, connections=to_plain(reference.get("connections", [])),
        catalog=to_plain(reference.get("inspection_catalog", [])),
        facts=reference_facts(reference, REFERENCE),
        query_assets=list(snapshot.query_asset_ids or [a["asset_id"] for a in assets]),
        forecast_tags=[t for t in TAG_ORDER if t in units and units[t] != "bool"],
        result_ids=[],
    )
    if snapshot.source_sha256 is None:
        note(prep, "all", "SOURCE_ROWS_NOT_SUPPLIED",
             "The source window is bound to the prepared summary because no source hash was given.")
    prep.result_ids = _add_rows(
        registry, "inspection_result", "inspection-result", "result_id",
        snapshot.inspection_results, cutoff,
    )
    _add_rows(
        registry, "inspection_request", "inspection-request", "request_id",
        snapshot.inspection_requests, cutoff,
    )
    _add_rows(registry, "history", "history", "record_id", snapshot.history, cutoff)
    return prep
