"""Fail-closed qualification of datasets for physical diagnostic training.

Structural findings are read from immutable source records, without changing labels or signals.
Engineering evidence must be bound to the dataset, configuration and current source revision;
passing software tests or merely supplying a passed flag cannot qualify physical behaviour.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from verum.contracts import load_policy
from verum.gates import ReleaseNotAllowed, assert_release_allowed
from verum.provenance import config_hash, git_state

EVIDENCE_CHECKS = (
    "physical_model", "operating_envelope", "fault_mechanisms", "sensor_chain",
    "observability_supervision", "split_and_shortcut_audit",
)
EVIDENCE_BASES = ("independent_reference", "engineering_design_validation", "field_calibration")


class TrainingNotReady(ValueError):
    """The proposed data lacks qualification for its diagnostic training use."""


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review(name: str, record: dict[str, Any], path: Path) -> list[str]:
    failures = []
    if record.get("status") != "passed" or record.get("basis") not in EVIDENCE_BASES:
        return [f"MISSING_EVIDENCE:{name}"]
    artifact, expected = record.get("artifact"), record.get("sha256")
    if not isinstance(artifact, str) or not isinstance(expected, str):
        return [f"UNBOUND_EVIDENCE:{name}"]
    target = (path.parent / artifact).resolve()
    if not target.is_relative_to(path.parent.resolve()) or not target.is_file():
        failures.append(f"INVALID_EVIDENCE_ARTIFACT:{name}")
    elif _hash(target) != expected:
        failures.append(f"EVIDENCE_HASH_MISMATCH:{name}")
    if not isinstance(record.get("scope"), str) or not record["scope"].strip():
        failures.append(f"MISSING_EVIDENCE_SCOPE:{name}")
    return failures


def _evidence(manifest_hash: str, path: Path | None) -> tuple[list[str], list[str]]:
    if path is None:
        return [f"MISSING_EVIDENCE:{name}" for name in EVIDENCE_CHECKS], []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("manifest_sha256") != manifest_hash:
        return ["EVIDENCE_DATASET_MISMATCH"], []
    commit, dirty = git_state()
    if dirty or raw.get("code_commit") != commit or raw.get("config_hash") != config_hash():
        return ["EVIDENCE_SOURCE_MISMATCH"], []
    failures = []
    for name in EVIDENCE_CHECKS:
        failures.extend(_review(name, raw.get("checks", {}).get(name, {}), path))
    passed = []
    for name in load_policy().required_gates:
        problems = _review(name, raw.get("release_gates", {}).get(name, {}), path)
        failures.extend(problems)
        if not problems:
            passed.append(name)
    return failures, passed


def audit_dataset(root: Path, evidence: Path | None = None) -> dict[str, Any]:
    """Assess training qualification without rewriting observations, labels or split membership."""
    manifest_path = root / "evaluator" / "manifest.json"
    manifest_hash = _hash(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    blockers, passed = _evidence(manifest_hash, evidence)
    try:
        assert_release_allowed("production_candidate", passed_gates=passed)
    except ReleaseNotAllowed:
        blockers.append("PHYSICAL_RELEASE_GATES_NOT_QUALIFIED")
    episodes = [e for e in manifest["episodes"] if e.get("status", "completed") == "completed"]
    if not episodes:
        blockers.append("EMPTY_DATASET")
    if any(e.get("tier", e.get("dataset_tier")) == "restricted_benchmark" for e in episodes):
        blockers.append("RESTRICTED_PHYSICAL_EPISODES")
    windows: Counter[float] = Counter()
    onsets: list[float] = []
    faulted = 0
    unaudited = 0
    parents: dict[str, set[str]] = {}
    for episode in episodes:
        ident = episode["episode_id"]
        directory = root / "evaluator" / "episodes" / ident
        scenario = json.loads((directory / "scenario.json").read_text(encoding="utf-8"))
        windows[float(scenario["duration_s"])] += 1
        faults = episode["faults"]
        faulted += bool(faults)
        unaudited += sum(f.get("class") == "unaudited" for f in faults)
        onsets.extend(float(f["onset_s"]) for f in faults)
        parent = episode.get("parent_episode_id", ident)
        parents.setdefault(parent, set()).add(episode["split"])
    if any(len(splits) > 1 for splits in parents.values()):
        blockers.append("PARENT_SPLIT_LEAKAGE")
    if manifest.get("dataset") == "mechanical_extension":
        blockers.extend(("REDUCED_MECHANICS_WITHOUT_HYDRAULIC_FEEDBACK",
                         "UNCALIBRATED_DAMAGE_AND_INSPECTION_LAWS",
                         "REFERENCE_VAPOUR_IS_NOT_A_COMPLETE_EMISSION_MODEL"))
        if manifest.get("sampling_protocol") != "prospective_experimental_v2":
            blockers.append("FUTURE_CONDITIONED_TARGET_AND_CASCADE_SELECTION")
            blockers.append("EXTRAPOLATED_INSPECTION_RESULTS")
    if unaudited:
        blockers.append("UNAUDITED_VISIBILITY_IS_NOT_A_SUPPORTED_DIAGNOSIS_TARGET")
    return {
        "schema_version": "1.0.0", "training_ready": not blockers,
        "manifest_sha256": manifest_hash, "episodes": len(episodes),
        "blockers": sorted(set(blockers)), "evidence_checks_required": list(EVIDENCE_CHECKS),
        "profile": {"horizon_s_counts": dict(windows), "faulted_episodes": faulted,
                    "faulted_fraction": faulted / len(episodes) if episodes else None,
                    "onset_s_min": min(onsets) if onsets else None,
                    "onset_s_max": max(onsets) if onsets else None,
                    "preexisting_fault_instances": sum(t == 0 for t in onsets),
                    "unaudited_visibility_instances": unaudited,
                    "distinct_parent_groups": len(parents)},
        "interpretation": "Experimental sampling is not an estimate of industrial fault frequency.",
        "data_modified": False,
        "production_generation_enabled": load_policy().production_generation_enabled,
    }


def assert_training_ready(root: Path, evidence: Path | None = None) -> dict[str, Any]:
    """Refuse training preparation unless structural, engineering and release checks all pass."""
    report = audit_dataset(root, evidence)
    if not report["training_ready"]:
        raise TrainingNotReady("training refused: " + ", ".join(report["blockers"]))
    return report
