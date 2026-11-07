"""Which upstream report each role accepts, and the stage order of the interface manifest.

The mapping names the input field that carries a report and the role that produces it. A test
compares it with the message schemas, so it cannot drift from the contract.
"""

from __future__ import annotations

import json
from typing import Final

from verum.contracts.agent_interfaces import contract_directory

UPSTREAM: Final[dict[str, dict[str, str]]] = {
    "anomaly_detection": {"forecast_report": "predictive_health"},
    "diagnostic_reasoning": {
        "forecast_report": "predictive_health",
        "anomaly_report": "anomaly_detection",
        "topology_report": "topology_dependency",
        "asset_report": "historical_asset_intelligence",
        "inspection_quality_report": "inspection_quality_documentation",
    },
    "inspection_planning": {"diagnosis_report": "diagnostic_reasoning"},
    "evidence_verification_decision": {
        "diagnosis_report": "diagnostic_reasoning",
        "inspection_plan_report": "inspection_planning",
        "inspection_quality_report": "inspection_quality_documentation",
    },
}


def workflow_stages() -> list[list[str]]:
    """Return the role stages in the order the manifest lists them."""
    manifest = json.loads((contract_directory() / "manifest.json").read_text(encoding="utf-8"))
    stages: list[list[str]] = manifest["workflow"]
    return stages
