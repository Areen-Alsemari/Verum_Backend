"""Coursework views preserve causality, unknown labels and source split membership.

Literal records test export boundaries without assuming any physical fault is observable.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from verum.training.dataset import (
    build_dataset_release,
    dataset_contract,
    digest,
    iter_role_examples,
    source_digest,
    verify_dataset_release,
)
from verum.training.features import (
    ObservationWindows,
    check_observation,
    reference_supervision,
)
from verum.training.inspection_records import inspection_example


def observation(t: float, value: float | None, *, available: float | None = None) -> dict[str, Any]:
    return {
        "episode_id": "EP-FIXTURE",
        "tag_id": "PT-201",
        "unit": "bar_gauge",
        "t_sim_s": t,
        "t_available_s": t if available is None else available,
        "value": value,
        "quality_flag": "good" if value is not None else "missing",
        "availability_status": "available" if value is not None else "missing",
    }


def test_future_records_cannot_change_current_features() -> None:
    """An extreme future value must not affect a current window.

    Independent: yes, because the future value and hand-computed current mean are literal.
    """
    rows = [observation(5, 2.0), observation(10, 4.0), observation(15, 9999.0)]
    first = ObservationWindows(rows[:2], {"PT-201": "bar_gauge"}).summary(10, 10)
    assert first == ObservationWindows(rows, {"PT-201": "bar_gauge"}).summary(10, 10)
    signal = first["signals"][0]
    assert signal["mean"] == 3.0
    assert signal["slope_per_s"] == pytest.approx(0.4)
    assert first["current_time_s"] == 0
    assert "episode_id" not in first


def test_missing_latest_reading_preserves_a_distinct_previous_value() -> None:
    """A missing current reading cannot become zero or an unmarked carried-forward reading.

    Independent: yes, because the last observed value and missing event are literal.
    """
    view = ObservationWindows(
        [observation(1, 7.0), observation(5, None)], {"PT-201": "bar_gauge"}
    ).summary(10, 10)["signals"][0]
    assert view["latest_value"] is None
    assert view["previous_measured_value"] == 7.0
    assert view["previous_measured_age_s"] == 9.0
    assert view["missing_samples"] == 1
    assert view["mean"] == 7.0


@pytest.mark.parametrize(
    "change", [{"unit": "psi"}, {"value": float("nan")}, {"t_available_s": 0.0}, {"t_sim_s": True}]
)
def test_observation_invariants_reject_invalid_records(change: dict[str, Any]) -> None:
    """Invalid units, values and measurement timing stop export.

    Independent: yes, because each mutation violates a literal input invariant.
    """
    row = observation(5.0, 1.0) | change
    with pytest.raises(ValueError):
        check_observation(row, {"PT-201": "bar_gauge"}, 10.0)


@pytest.mark.parametrize("visibility", ["invisible", "marginal", "unaudited"])
def test_uncertain_fault_is_unknown_instead_of_healthy(visibility: str) -> None:
    """Non-clear fault classes produce no supervised positive or negative label.

    Independent: yes, because the source class is supplied explicitly rather than inferred.
    """
    record: dict[str, Any] = {
        "tier": "analytic_verification",
        "faults": [
            {
                "onset_s": 10.0,
                "class": visibility,
                "ramp_s": 0.0,
                "fault_type": "SENSOR_BIAS",
                "subtype": "bias",
                "asset_id": "PT-201",
            }
        ],
    }
    target = reference_supervision(record, 2000.0, 300.0, 900.0, [])
    assert not target["supervised_loss_mask"]
    assert target["injected_change_present"] is None
    assert target["injected_components"] is None


def test_clear_injection_still_needs_context_and_valid_model() -> None:
    """A clear source label cannot override early context or validity restrictions.

    Independent: yes, because the onset, delay and invalid interval have literal boundaries.
    """
    record: dict[str, Any] = {
        "tier": "analytic_verification",
        "faults": [
            {
                "onset_s": 100.0,
                "class": "clear",
                "ramp_s": 200.0,
                "fault_type": "SENSOR_BIAS",
                "subtype": "bias",
                "asset_id": "PT-201",
            }
        ],
    }
    assert not reference_supervision(record, 900.0, 300.0, 900.0, [])["supervised_loss_mask"]
    target = reference_supervision(record, 1500.0, 300.0, 900.0, [])
    assert target["supervised_loss_mask"] and target["injected_change_present"]
    invalid = [{"t_start_s": 1300.0, "t_end_s": 1501.0, "affects_emitted_tags": True}]
    assert not reference_supervision(record, 1500.0, 300.0, 900.0, invalid)["supervised_loss_mask"]
    record["latent"] = True
    assert not reference_supervision(record, 1500.0, 300.0, 900.0, [])["supervised_loss_mask"]


def test_legacy_inspection_findings_cannot_become_condition_labels() -> None:
    """A claimed normal result outside process coverage is withheld as physical evidence.

    Independent: yes, because the exercise supplies an explicitly out-of-horizon result.
    """
    item = {
        "request": {"action_id": "ACT-INSP-01"},
        "result": {
            "workflow_status": "performed",
            "performed_at_t_sim_s": 4000.0,
            "evidence_status": "low_confidence",
            "findings": {
                "outcome_category": "NORMAL_INTACT",
                "primary_metric": {
                    "name": "gap",
                    "unit": "mm",
                    "value": 2.0,
                    "uncertainty_k2": 1.0,
                },
            },
        },
    }
    row = inspection_example(item, 3600.0, legacy=True)
    assert row["target"]["equipment_condition"] is None
    assert not row["target"]["raw_measurement_supported"]
    assert "process_horizon_does_not_cover_performance" in row["target"]["quality_flags"]
    assert "value" not in row["input"]["metric"]
    assert "NORMAL_INTACT" not in json.dumps(row)


def fixture_source(root: Path) -> Path:
    source = root / "source"
    episode = source / "evaluator/episodes/EP-FIXTURE"
    episode.mkdir(parents=True)
    visible = source / "agent_visible/episodes/EP-FIXTURE/observations.jsonl.gz"
    visible.parent.mkdir(parents=True)
    from verum.sensors.specs import load_sensor_config

    unit = load_sensor_config().tags["PT-201"].unit
    with gzip.open(visible, "wt") as handle:
        for t in (100.0, 400.0, 700.0):
            handle.write(json.dumps(observation(t, t) | {"unit": unit}) + "\n")
    (episode / "scenario.json").write_text(json.dumps({"duration_s": 900.0}))
    (episode / "labels.json").write_text(json.dumps({"faults": []}))
    for name in ("fault_truth.jsonl.gz", "validity_windows.jsonl.gz"):
        with gzip.open(episode / name, "wt"):
            pass
    record: dict[str, Any] = {
        "episode_id": "EP-FIXTURE",
        "status": "completed",
        "split": "test",
        "tier": "analytic_verification",
        "faults": [],
        "files": {
            p.relative_to(source).as_posix(): source_digest(p)
            for p in [visible, *episode.iterdir()]
        },
    }
    (source / "evaluator/manifest.json").write_text(json.dumps({"episodes": [record]}))
    return source


def test_portable_export_preserves_splits_bytes_and_all_eight_roles(tmp_path: Path) -> None:
    """The mini handoff keeps original bytes and all role views within the original test split.

    Independent: no, because this checks the exporter and verifier together on literal records.
    """
    source = fixture_source(tmp_path)
    before = digest(source / "agent_visible/episodes/EP-FIXTURE/observations.jsonl.gz")
    output = tmp_path / "portable"
    report = build_dataset_release(source, output)
    assert report["episodes"] == 1 and report["counts"]["snapshots"] == 3
    assert report["records"][0]["observation_sha256"] == before
    assert not report["physical_training_qualified"]
    assert verify_dataset_release(output)["integrity_passed"]
    assert len(dataset_contract()["roles"]) == 8
    for role in dataset_contract()["roles"]:
        assert not list(iter_role_examples(output, role["key"], "train"))
        examples = list(iter_role_examples(output, role["key"], "test"))
        assert 1 <= len(examples) <= 3
        assert all("lineage" not in row and "targets" not in row["input"] for row in examples)
    file = output / report["records"][0]["example_file"]
    file.write_bytes(file.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_dataset_release(output)
    with pytest.raises(ValueError, match="changed"):
        list(iter_role_examples(output, "anomaly_detection", "test"))


def test_incomplete_exports_cannot_be_loaded(tmp_path: Path) -> None:
    """A build sentinel blocks access before manifests or samples are opened.

    Independent: yes, because the sentinel is the only file supplied.
    """
    (tmp_path / "BUILDING.json").write_text("{}")
    with pytest.raises(ValueError, match="incomplete"):
        list(iter_role_examples(tmp_path, "anomaly_detection", "train"))


def test_old_contact_age_cannot_encode_episode_clock() -> None:
    """An unchanged old contact has the same censored age at successive observation cutoffs.

    Independent: yes, because a literal event at zero is outside both supplied windows.
    """
    row = observation(0.0, 1.0) | {"unit": "bool"}
    windows = ObservationWindows([row], {"PT-201": "bool"})
    first = windows.summary(600.0, 300.0)
    assert first == windows.summary(900.0, 300.0)
    signal = first["signals"][0]
    assert signal["latest_received_age_s"] == 300.0
    assert signal["latest_received_age_is_lower_bound"] is True
    assert signal["latest_value"] == 1.0
