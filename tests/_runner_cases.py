"""Shared cases for the runner tests: a reference, a snapshot and sample inspection records.

The reference is built from the repository configuration, so no extracted release is needed.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from typing import Any

from verum.agents.common import ROLES, StubAgent, stable_hash
from verum.agents.runner import Bundle, Snapshot, run_analysis
from verum.contracts.agent_interfaces import contract_directory
from verum.training.dataset import public_reference


@cache
def _reference() -> dict[str, Any]:
    return public_reference()


def reference() -> dict[str, Any]:
    """A fresh copy of the public reference."""
    return copy.deepcopy(_reference())


def summary() -> dict[str, Any]:
    """The prepared observation summary of the example request."""
    path = contract_directory() / "examples" / "predictive_health.request.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    value: dict[str, Any] = loaded["input"]["observations"]["summary"]
    return value


def snapshot(**changes: Any) -> Snapshot:
    """A snapshot of case C7 at revision 0, with fields replaced by the keyword arguments."""
    ref = reference()
    fields: dict[str, Any] = {
        "case_id": "C7", "revision": 0, "as_of_s": 300.0, "summary": summary(),
        "reference": ref, "reference_snapshot_sha256": stable_hash(ref),
    }
    return Snapshot(**{**fields, **changes})


def inspection_request() -> dict[str, Any]:
    """An approved inspection request made at 300 s."""
    return {
        "schema_version": "0.5.0", "dataset": "inspection_requests",
        "request_id": "REQ-INSP-00001", "t_requested_sim_s": 300.0, "action_id": "ACT-INSP-04",
        "target_asset": "E002",
        "justification": {
            "competing_hypotheses": ["a", "b"], "agent_reported_information_gain_bits": 1.0,
            "estimated_cost_usd": 350.0,
        },
        "human_approval": {
            "status": "APPROVED", "approver_id": "approver-1", "work_permit_number": "WP-1",
        },
    }


def inspection_result() -> dict[str, Any]:
    """A performed inspection result at 400 s for the request above."""
    return {
        "schema_version": "0.5.0", "dataset": "inspection_results",
        "result_id": "RES-INSP-00001", "request_id": "REQ-INSP-00001",
        "action_id": "ACT-INSP-04", "workflow_status": "performed", "evidence_status": "valid",
        "performed_at_t_sim_s": 400.0, "technician_id": "T-1",
        "findings": {
            "outcome_category": "NORMAL_INTACT",
            "primary_metric": {
                "name": "metric", "value": 1.0, "unit": "unit", "uncertainty_k2": 0.1,
            },
            "secondary_observations": [],
        },
        "validation_status": "PASSED_QA",
    }


def placeholders() -> dict[str, StubAgent]:
    """A placeholder agent for every role."""
    return {role: StubAgent(role) for role in ROLES}


def run(mode: str = "runtime", **kwargs: Any) -> Bundle:
    """Run the placeholders on the default snapshot."""
    agents = kwargs.pop("agents", placeholders())
    return run_analysis(kwargs.pop("snapshot", snapshot()), mode, agents=agents, **kwargs)
