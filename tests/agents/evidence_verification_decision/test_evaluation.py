"""Test Agent 8 synthetic labels and validated role-view evaluation."""

from pathlib import Path

import pytest

from verum.agents.common.loader import iter_role_records
from verum.agents.evidence_verification_decision.evaluation import (
    evaluate_reference_dataset,
    evaluate_reference_example,
)

ROOT = Path(__file__).resolve().parents[3] / "data/reference_release_v2/verum_reference_v2"
ROLE = "evidence_verification_decision"


@pytest.mark.skipif(not ROOT.exists(), reason="Reference dataset not available")
def test_reference_admission_targets() -> None:
    """Independent: preserve legacy synthetic adapter compatibility."""
    count = 0
    for record in iter_role_records(ROOT, ROLE, "test"):
        if record.use != "reference_input_target_pair":
            continue
        actual = evaluate_reference_example(record.example_id, record.input)
        assert actual == record.target, record.example_id
        count += 1
    assert count == 7008


@pytest.mark.skipif(not ROOT.exists(), reason="Reference dataset not available")
def test_full_agent_evaluation() -> None:
    """Independent: validate full Agent 8 test-split evaluation."""
    records = iter_role_records(ROOT, ROLE, "test")
    summary = evaluate_reference_dataset(records)

    assert summary["agent_run_evaluation"]["reference_count"] == 7008
    assert summary["agent_run_evaluation"]["inspection_count"] == 2
    assert summary["agent_run_evaluation"]["error_count"] == 0
    assert sum(summary["agent_run_evaluation"]["decision_states"].values()) == 7008
    assert sum(summary["agent_run_evaluation"]["inspection_decision_states"].values()) == 2
    assert summary["synthetic_label_diagnostics"]["time_rules_compared"] == 7008
    assert summary["synthetic_label_diagnostics"]["time_rules_agreed"] == 7008
    assert summary["label_meaning"]
    assert summary["evaluation_limitations"]


@pytest.mark.skipif(not ROOT.exists(), reason="Reference dataset not available")
def test_all_inspection_records() -> None:
    """Independent: process all twelve inspection review records."""
    records = (
        record
        for split in ("train", "validation", "test")
        for record in iter_role_records(ROOT, ROLE, split)
        if record.use == "inspection_record_quality"
    )
    summary = evaluate_reference_dataset(records)

    assert summary["agent_run_evaluation"]["reference_count"] == 0
    assert summary["agent_run_evaluation"]["inspection_count"] == 12
    assert summary["agent_run_evaluation"]["error_count"] == 0
    assert sum(summary["agent_run_evaluation"]["inspection_decision_states"].values()) == 12
    assert summary["synthetic_label_diagnostics"]["time_rules_compared"] == 0


def test_agent_rejects_unverified_provenance() -> None:
    """Independent: reject evidence with mismatched provenance."""
    from verum.agents.evidence_verification_decision.evaluation import (
        _new_request,
        evaluate_full_agent_request,
    )

    request = _new_request("provenance-negative")
    request["input"]["evidence_proposals"] = [
        {
            "proposal_id": "provenance-negative",
            "source_ref": "reference:public_reference",
            "claimed_available_at_s": 300.0,
            "claimed_evidence_ids": ["source-observations"],
        }
    ]

    result = evaluate_full_agent_request(request)["result"]
    check = result["evidence_checks"][0]

    assert check["provenance_verified"] is False
    assert check["usable"] is False
    assert result["decision_state"] == "more_evidence_required"
    assert result["automatic_action_authorized"] is False


def test_agent_rejects_future_evidence() -> None:
    """Independent: reject evidence claimed after the decision cutoff."""
    from verum.agents.evidence_verification_decision.evaluation import (
        _new_request,
        evaluate_full_agent_request,
    )

    request = _new_request("future-negative")
    request["input"]["evidence_proposals"] = [
        {
            "proposal_id": "future-negative",
            "source_ref": "observations:training-prefix-at-300",
            "claimed_available_at_s": 301.0,
            "claimed_evidence_ids": ["source-observations"],
        }
    ]

    result = evaluate_full_agent_request(request)["result"]
    check = result["evidence_checks"][0]

    assert check["time_admissible"] is False
    assert check["usable"] is False
    assert result["decision_state"] == "more_evidence_required"
    assert result["automatic_action_authorized"] is False


def test_agent_distinguishes_valid_and_future_time() -> None:
    """Independent: distinguish timely evidence from future evidence."""
    from verum.agents.evidence_verification_decision.evaluation import (
        _new_request,
        evaluate_full_agent_request,
    )

    outcomes = {}
    for name, available_at in (("timely", 300.0), ("future", 301.0)):
        request = _new_request(f"time-{name}")
        request["input"]["evidence_proposals"] = [
            {
                "proposal_id": f"time-{name}",
                "source_ref": "observations:training-prefix-at-300",
                "claimed_available_at_s": available_at,
                "claimed_evidence_ids": ["source-observations"],
            }
        ]
        result = evaluate_full_agent_request(request)["result"]
        check = result["evidence_checks"][0]
        outcomes[name] = check["time_admissible"]

        assert result["automatic_action_authorized"] is False
        assert result["equipment_condition_confirmed"] is False
        assert result["human_decision_required"] is True

    assert outcomes == {"timely": True, "future": False}
