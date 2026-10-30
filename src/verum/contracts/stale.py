"""Detector for references that earlier documents used and the audit removed.

Only the machine-readable contracts are scanned, and the scan looks at where an item is used (a
sensor tag, a graph node, an element reference) and not at every string, because excluded assets are
legitimately named in exclusion lists. The expected edge count is stated here independently of the
contract header, so a header and list edited together are still caught.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

EXPECTED_EDGE_COUNT: Final = 28
EXCLUDED_ASSETS: Final = frozenset({"CV-201", "ZT-201"})
EXCLUDED_TAGS: Final = frozenset({"PT-101", "PT-102", "PT-103", "AT-101", "AT-102", "AT-103"})
REMOVED_ELEMENTS: Final = EXCLUDED_ASSETS | EXCLUDED_TAGS


def _ref_findings(tag: str, ref: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    record_type, element, field = ref.get("record_type"), ref.get("element_id"), ref.get("field")
    if element in REMOVED_ELEMENTS:
        found.append(f"{tag}: references removed element {element}")
    if field == "pressure":
        found.append(
            f"{tag}: bare 'pressure' field on {record_type} (use p_from_pa_abs/pressure_pa_abs)"
        )
    if tag.startswith("XV-") and (field == "position_frac" or record_type == "valve_state"):
        found.append(f"{tag}: mapped to actual valve position instead of contact state")
    if tag.startswith("LSHH-") and (record_type == "tank_state" or field == "level_m"):
        found.append(f"{tag}: mapped to tank level instead of an independent protection state")
    return found


def sensor_findings(sensor_contract: Mapping[str, Any]) -> list[str]:
    """Findings in the sensor contract."""
    found: list[str] = []
    for tag, entry in sensor_contract.get("sensors", {}).items():
        if tag in REMOVED_ELEMENTS:
            found.append(f"{tag}: removed tag is declared as a sensor")
        found.extend(_ref_findings(tag, entry.get("measured_variable_ref") or {}))
    return found


def topology_findings(topology_contract: Mapping[str, Any]) -> list[str]:
    """Findings in the topology contract."""
    found: list[str] = []
    edges = topology_contract.get("edges", [])
    if (
        len(edges) != EXPECTED_EDGE_COUNT
        or topology_contract.get("edge_count") != EXPECTED_EDGE_COUNT
    ):
        found.append(
            f"edge count is {len(edges)}/{topology_contract.get('edge_count')}, expected 28"
        )
    nodes = {n for e in edges for n in (e.get("from_node"), e.get("to_node"))}
    names = nodes | {e.get("edge_id") for e in edges} | set(topology_contract.get("pumps", []))
    names |= set(topology_contract.get("tanks", {}))
    found.extend(
        f"{n}: removed element appears in the graph" for n in sorted(names & REMOVED_ELEMENTS)
    )
    return found


def exclusion_findings(
    topology_contract: Mapping[str, Any],
    sensor_contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[str]:
    """Findings where an exclusion that must be declared is missing."""
    found: list[str] = []
    if not EXCLUDED_ASSETS <= set(topology_contract.get("excluded_nonbaseline_assets", [])):
        found.append("topology contract does not declare CV-201 and ZT-201 as excluded")
    if not REMOVED_ELEMENTS <= set(sensor_contract.get("nonbaseline_excluded", [])):
        found.append("sensor contract does not list every removed tag as nonbaseline_excluded")
    if policy.get("no_baseline_control_valve") != "CV-201":
        found.append("release policy does not state that CV-201 is not in the baseline")
    return found


def stale_findings(
    topology_contract: Mapping[str, Any],
    sensor_contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[str]:
    """All findings across the three contracts."""
    return (
        sensor_findings(sensor_contract)
        + topology_findings(topology_contract)
        + exclusion_findings(topology_contract, sensor_contract, policy)
    )


def assert_no_stale_references(
    topology_contract: Mapping[str, Any],
    sensor_contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    """Raise ``ValueError`` listing every finding, if there is any."""
    findings = stale_findings(topology_contract, sensor_contract, policy)
    if findings:
        raise ValueError("stale references present: " + "; ".join(findings))
