"""Training qualification, immutable evidence bindings and complete fault-track loading.

Literal fixture manifests distinguish software verification from physical training approval.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import load_policy
from verum.training import (
    TrainingNotReady,
    assert_training_ready,
    audit_dataset,
    load_episode_truth,
    readiness,
)
from verum.vapour.campaign import _truth, write_rows
from verum.vapour.model import MechanicalFault


def dataset(root: Path, *, mechanical: bool = False) -> Path:
    directory = root / "evaluator" / "episodes" / "EP-TEST"
    directory.mkdir(parents=True)
    (directory / "scenario.json").write_text(json.dumps({"duration_s": 3600.0}))
    record: dict[str, Any] = {"episode_id": "EP-TEST", "status": "completed", "split": "train",
                              "tier": "analytic_verification", "faults": []}
    manifest: dict[str, Any] = {"episodes": [record]}
    if mechanical:
        manifest["dataset"] = "mechanical_extension"
        record["dataset_tier"] = "restricted_benchmark"
        record.pop("tier")
    path = root / "evaluator" / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def certificate(path: Path, manifest: Path) -> dict[str, Any]:
    artifact = path.parent / "engineering_reference.txt"
    artifact.write_text("A fixture for gate tests, not actual engineering approval.")
    record = {"status": "passed", "basis": "engineering_design_validation", "scope": "fixture",
              "artifact": artifact.name,
              "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    raw = {"manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
           "code_commit": "fixture", "config_hash": "fixture",
           "checks": {name: record for name in readiness.EVIDENCE_CHECKS},
           "release_gates": {name: record for name in load_policy().required_gates}}
    path.write_text(json.dumps(raw))
    return raw


def test_research_pass_flags_do_not_qualify_a_dataset_for_training(tmp_path: Path) -> None:
    """A software-verified research manifest cannot open training or bypass the physical gate.

    Independent: yes, because the fixture supplies no physical engineering evidence.
    """
    root = tmp_path / "dataset"
    path = dataset(root)
    raw = json.loads(path.read_text())
    raw["training_ready"] = True
    raw["all_tests_passed"] = True
    path.write_text(json.dumps(raw))
    report = audit_dataset(root)
    assert report["training_ready"] is False
    assert "PHYSICAL_RELEASE_GATES_NOT_QUALIFIED" in report["blockers"]
    assert any(reason.startswith("MISSING_EVIDENCE:") for reason in report["blockers"])
    before = path.read_bytes()
    with pytest.raises(TrainingNotReady):
        assert_training_ready(root)
    assert path.read_bytes() == before


def test_evidence_is_bound_to_data_source_and_artifact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An otherwise complete certificate fails when its reference artifact or source data changes.

    Independent: yes, because the files are changed after their recorded hashes were computed.
    """
    root = tmp_path / "dataset"
    manifest = dataset(root)
    evidence = tmp_path / "evidence" / "approval.json"
    evidence.parent.mkdir()
    certificate(evidence, manifest)
    monkeypatch.setattr(readiness, "git_state", lambda: ("fixture", False))
    monkeypatch.setattr(readiness, "config_hash", lambda: "fixture")
    (evidence.parent / "engineering_reference.txt").write_text("changed")
    report = audit_dataset(root, evidence)
    assert any(reason.startswith("EVIDENCE_HASH_MISMATCH:") for reason in report["blockers"])
    manifest.write_text(manifest.read_text() + " ")
    assert "EVIDENCE_DATASET_MISMATCH" in audit_dataset(root, evidence)["blockers"]


def test_complete_bound_evidence_reaches_the_release_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All required reference artifacts must pass before the full gate set is submitted.

    Independent: yes, because the expected gate names come from the policy, not the certificate.
    """
    root = tmp_path / "dataset"
    manifest = dataset(root)
    evidence = tmp_path / "approval.json"
    certificate(evidence, manifest)
    monkeypatch.setattr(readiness, "git_state", lambda: ("fixture", False))
    monkeypatch.setattr(readiness, "config_hash", lambda: "fixture")
    seen: list[str] = []

    def gate(tier: str, *, passed_gates: list[str]) -> None:
        assert tier == "production_candidate"
        seen.extend(passed_gates)

    monkeypatch.setattr(readiness, "assert_release_allowed", gate)
    assert audit_dataset(root, evidence)["training_ready"] is True
    assert set(seen) == set(load_policy().required_gates)


def test_mechanical_research_is_blocked_even_with_a_passed_flag(tmp_path: Path) -> None:
    """The reduced mechanical model remains unqualified independently of its file-integrity result.

    Independent: yes, because the fixture declares the known reduced-model dataset type.
    """
    root = tmp_path / "dataset"
    dataset(root, mechanical=True)
    reasons = audit_dataset(root)["blockers"]
    assert "REDUCED_MECHANICS_WITHOUT_HYDRAULIC_FEEDBACK" in reasons
    assert "FUTURE_CONDITIONED_TARGET_AND_CASCADE_SELECTION" in reasons
    assert "RESTRICTED_PHYSICAL_EPISODES" in reasons


def test_mechanical_truth_cannot_be_misread_as_a_healthy_episode(tmp_path: Path) -> None:
    """An empty hydraulic compatibility file must not hide mechanical fault instances.

    Independent: yes, because a single explicit mechanical fault is stored in the second track.
    """
    fault = MechanicalFault("mechanical-1", "RIM_SEAL_DETERIORATION", "TK-101", 600., 300., 1.)
    truth = _truth("EP-TEST", [fault])
    write_rows(tmp_path / "fault_truth.jsonl.gz", [])
    write_rows(tmp_path / "mechanical_fault_truth.jsonl.gz", truth)
    (tmp_path / "labels.json").write_text(json.dumps({"faults": [{"instance_id": "mechanical-1"}]}))
    assert [r["fault_instance_id"] for r in load_episode_truth(tmp_path)] == ["mechanical-1"]
    write_rows(tmp_path / "mechanical_fault_truth.jsonl.gz", [])
    with pytest.raises(ValueError, match="instances disagree"):
        load_episode_truth(tmp_path)
