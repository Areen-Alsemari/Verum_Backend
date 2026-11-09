"""Validate Agent 8's benchmark adapter against official reference targets."""

from pathlib import Path

from verum.agents.common.loader import iter_role_records
from verum.agents.evidence_verification_decision.evaluation import (
    evaluate_reference_example,
)


def test_reference_admission_targets() -> None:
    """Independent: reference admission targets."""
    root = Path(__file__).resolve().parents[3] / "data/reference_release_v2/verum_reference_v2"
    count = 0

    for record in iter_role_records(root, "evidence_verification_decision", "test"):
        if record.use != "reference_input_target_pair":
            continue

        actual = evaluate_reference_example(record.example_id, record.input)
        assert actual == record.target, record.example_id
        count += 1

    assert count == 7008
