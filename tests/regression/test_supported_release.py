"""Supported scope, inspection provenance and portable training bundles reject unsafe substitutions.

Literal fixtures distinguish valid numeric evidence from unknown condition and unsupported physics.
"""

from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from _dataset_fixture import fixture_source
from verum.training.dataset import build_dataset_release
from verum.training.features import reference_supervision
from verum.training.inspection_records import inspection_example
from verum.training.packaging import (
    materialize_roles,
    package_training,
    verify_roles,
    verify_training_archive,
)
from verum.training.pipeline import campaign_config, generate_dataset, load_recipe


def inspection() -> dict[str, Any]:
    return {
        "request": {"action_id": "ACT-INSP-05", "t_requested_sim_s": 100.0},
        "timeline": {
            "t_requested_s": 100.0,
            "t_decision_s": 200.0,
            "t_start_s": 300.0,
            "t_performed_s": 3000.0,
            "t_visible_s": 3120.0,
            "reason": None,
        },
        "result": {
            "workflow_status": "performed",
            "performed_at_t_sim_s": 3000.0,
            "evidence_status": "low_confidence",
            "findings": {
                "primary_metric": {
                    "name": "manual_innage_level",
                    "value": 7000.0,
                    "unit": "mm",
                    "uncertainty_k2": 1.5,
                }
            },
        },
    }


def test_clear_visibility_cannot_admit_out_of_scope_mechanics() -> None:
    """A clear mechanical label remains unknown even in an otherwise eligible analytic window.

    Independent: yes, because the forbidden mechanism is explicitly supplied in the fixture.
    """
    record = {
        "tier": "analytic_verification",
        "faults": [
            {
                "fault_type": "FITTING_DAMAGE",
                "subtype": "fitting",
                "asset_id": "TK-101",
                "onset_s": 0.0,
                "ramp_s": 0.0,
                "class": "clear",
                "activity": "active",
            }
        ],
    }
    result = reference_supervision(record, 2000.0, 300.0, 900.0, [])
    assert result["supervised_loss_mask"] is False
    assert result["injected_components"] is None
    assert "outside_project_scope" in result["mask_reasons"]


def test_numeric_inspection_does_not_establish_equipment_acceptance() -> None:
    """A process-covered, ordered raw reading is usable without asserting equipment health.

    Independent: yes, because the complete timeline and measurement are literal inputs.
    """
    result = inspection_example(inspection(), 3600.0, legacy=False)["target"]
    assert result["raw_measurement_supported"] is True
    assert result["workflow_timing_valid"] is True
    assert result["equipment_condition"] is None
    assert result["condition_acceptance_supported"] is False


@pytest.mark.parametrize(
    "change",
    [
        "before_request",
        "unknown_timeline",
        "negative_uncertainty",
        "wrong_unit",
        "missing_value",
        "nonfinite_value",
        "shortened_work",
        "cancelled_result",
    ],
)
def test_invalid_measurements_or_timelines_cannot_be_supported(change: str) -> None:
    """Timing, numeric and unit failures hold a reading despite an in-horizon performed timestamp.

    Independent: yes, because each mutation has a known invalid field rather than inferred physics.
    """
    item = inspection()
    metric = item["result"]["findings"]["primary_metric"]
    if change == "before_request":
        item["timeline"]["t_start_s"] = 50.0
    elif change == "unknown_timeline":
        del item["timeline"]
    elif change == "negative_uncertainty":
        metric["uncertainty_k2"] = -1.0
    elif change == "wrong_unit":
        metric["unit"] = "psi"
    elif change == "missing_value":
        metric["value"] = None
    elif change == "shortened_work":
        item["timeline"]["t_performed_s"] = 500.0
        item["result"]["performed_at_t_sim_s"] = 500.0
    elif change == "cancelled_result":
        item["cancellation"] = [400.0, "WORK_CONDITION_FAILED"]
    else:
        metric["value"] = float("nan")
    result = inspection_example(item, 3600.0, legacy=False)["target"]
    assert result["raw_measurement_supported"] is False
    assert result["equipment_condition"] is None


def test_ambient_legacy_directory_is_not_a_release_input(tmp_path: Path) -> None:
    """A nearby legacy archive cannot silently alter the export, and explicit use is refused.

    Independent: yes, because the unsupported dataset identity is a literal fixture.
    """
    source = fixture_source(tmp_path)
    old = tmp_path / "mechanical_extension_full_v1/evaluator"
    old.mkdir(parents=True)
    (old / "manifest.json").write_text(json.dumps({"dataset": "mechanical_extension"}))
    report = build_dataset_release(source, tmp_path / "supported")
    assert report["inspection_exercises"] == []
    with pytest.raises(ValueError, match="outside project scope"):
        build_dataset_release(source, tmp_path / "forbidden", inspection_sources=(old.parent,))
    assert not (tmp_path / "forbidden").exists()


def prepared_release(root: Path) -> Path:
    source = fixture_source(root)
    release = root / "release"
    report = build_dataset_release(source, release)
    (release / "generation_recipe.json").write_text(json.dumps({"recipe": load_recipe()}))
    (release / "release_summary.json").write_text(json.dumps({"episodes": report["episodes"]}))
    (release / "TEAM_DATA_GUIDE.md").write_text("Use inputs only; honour target masks.\n")
    materialize_roles(release)
    return release


def test_compact_bundle_contains_all_roles_without_raw_or_hidden_data(tmp_path: Path) -> None:
    """The portable archive contains 24 role files and excludes raw/evaluator source files.

    Independent: no, because this exercises the materializer, packager and verifier together.
    """
    release = prepared_release(tmp_path)
    assert verify_roles(release)["role_files"] == 24
    target = tmp_path / "training.zip"
    result = package_training(release, target)
    assert result["evaluator_truth_included"] is False
    assert result["raw_observations_included"] is False
    assert verify_training_archive(target)["integrity_passed"]
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert sum(n.startswith("role_views/") for n in names) == 24
        assert not any(n.startswith(("evaluator/", "observations/")) for n in names)
        assert "project_scope.json" in names and "generation_recipe.json" in names
    with pytest.raises(FileExistsError):
        package_training(release, target)


def test_role_and_archive_corruption_is_detected(tmp_path: Path) -> None:
    """Post-export edits fail both the standalone role and archive hash checks.

    Independent: yes, because literal bytes are altered after the hashes are recorded.
    """
    release = prepared_release(tmp_path)
    target = tmp_path / "training.zip"
    package_training(release, target)
    altered = tmp_path / "altered.zip"
    with zipfile.ZipFile(target) as original, zipfile.ZipFile(altered, "w") as archive:
        for name in original.namelist():
            payload = original.read(name)
            archive.writestr(
                name, payload + b"changed" if name == "project_scope.json" else payload
            )
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_training_archive(altered)
    path = release / "role_views/predictive_health/test.jsonl.gz"
    with gzip.open(path, "wt") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="changed"):
        verify_roles(release)


def test_generation_recipe_preserves_existing_campaign_selections() -> None:
    """The committed seed, horizon and slot count preserve the existing campaign configuration.

    Independent: yes, because the expected values are the existing frozen campaign selections.
    """
    config = campaign_config(load_recipe())
    assert config.seed == 20261101
    assert config.n == 3004
    assert config.duration_s == 3600.0
    assert config.block.healthy == 18 and config.block.size == 100


def test_pipeline_produces_all_roles_without_running_a_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tiny source records exercise orchestration with supplied simulation stages.

    Independent: no, because the integrated pipeline uses the same materializer and exporter.
    """
    from verum.training import pipeline

    source = fixture_source(tmp_path)
    roof = tmp_path / "roof/evaluator"
    roof.mkdir(parents=True)
    (roof / "manifest.json").write_text(
        json.dumps({"dataset": "coupled_roof_reference", "episodes": []})
    )
    monkeypatch.setattr(pipeline, "git_state", lambda: ("fixture", False))
    monkeypatch.setattr(pipeline, "_campaign", lambda *args: source)
    monkeypatch.setattr(pipeline, "_roof", lambda *args: roof.parent)
    report = generate_dataset(tmp_path / "generated", workers=1)
    assert report["agents_built"] is False
    assert report["archive"]["verification"]["role_files"] == 24
    assert verify_training_archive(tmp_path / "generated/verum_reference_v2_training.zip")
