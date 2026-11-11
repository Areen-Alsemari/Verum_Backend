"""Declared asset facts read from the public reference, without adding any value.

Each scalar in an asset's declared record becomes one source-bearing fact. A unit and a parameter
status appear only where the reference states them; everywhere else they stay null.
"""

from __future__ import annotations

from typing import Any

STATUSES = frozenset({"provisional", "selected", "unresolved", "validated"})
SCALARS = (str, bool, int, float)


def _leaf(value: Any) -> bool:
    return isinstance(value, dict) and {"value", "unit", "status"} <= set(value)


def _fact(
    asset_id: str, path: str, value: Any, unit: Any, status: Any, locator: str, evidence: str
) -> dict[str, Any]:
    return {
        "fact_id": f"{asset_id}:{path}", "asset_id": asset_id, "field_path": path, "value": value,
        "unit": unit if isinstance(unit, str) else None, "source_locator": locator,
        "parameter_status": status if status in STATUSES else None, "evidence_ids": [evidence],
    }


def _walk(
    asset_id: str, path: str, node: Any, locator: str, evidence: str, out: list[dict[str, Any]]
) -> None:
    if _leaf(node):
        place = str(node.get("provenance_id") or locator)
        fact = _fact(asset_id, path, node["value"], node["unit"], node["status"], place, evidence)
        out.append(fact)
    elif isinstance(node, dict):
        for key, child in node.items():
            _walk(asset_id, f"{path}.{key}", child, locator, evidence, out)
    elif node is None or isinstance(node, SCALARS):
        out.append(_fact(asset_id, path, node, None, None, locator, evidence))


def reference_facts(reference: dict[str, Any], evidence_id: str) -> list[dict[str, Any]]:
    """Return one fact per declared scalar, in the order of the reference."""
    facts: list[dict[str, Any]] = []
    for asset_id, record in reference.get("asset_facts", {}).items():
        locator = str(record.get("source", ""))
        for key, child in record.items():
            if key != "source":
                _walk(asset_id, key, child, locator, evidence_id, facts)
    return facts
