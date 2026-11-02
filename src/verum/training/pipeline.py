"""Reproducible generation of the supported reference dataset and compact training archive.

A committed recipe fixes the existing campaign seed and design; supplemental inputs are explicit.
Campaign generation resumes by stored slot records, while completed releases are immutable.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verum.campaign import runner
from verum.campaign.plan import Block, CampaignConfig
from verum.contracts.paths import config_dir, repo_root
from verum.provenance import git_state
from verum.training.dataset import build_dataset_release, verify_dataset_release
from verum.training.packaging import materialize_roles, package_training, verify_roles
from verum.training.reference import build_roof_reference


def load_recipe() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        (config_dir() / "extensions/reference_recipe_v2.json").read_text()
    )
    return value


def campaign_config(recipe: dict[str, Any]) -> CampaignConfig:
    raw = recipe["campaign"]
    return CampaignConfig(raw["seed"], raw["n"], Block(**raw["block"]), raw["duration_s"])


def _campaign(root: Path, config: CampaignConfig, supplied: Path | None, workers: int) -> Path:
    if supplied is not None:
        if runner.load_config(supplied) != config:
            raise ValueError("supplied campaign differs from the committed generation recipe")
        _complete_campaign(supplied, config)
        return supplied
    target = root / "campaign"
    if (target / runner.CONFIG_FILE).exists() and runner.load_config(target) != config:
        raise ValueError("stored campaign differs from the committed generation recipe")
    runner.run_campaign(config, target, workers)
    _complete_campaign(target, config)
    return target


def _complete_campaign(source: Path, config: CampaignConfig) -> None:
    manifest = json.loads((source / "evaluator/manifest.json").read_text())
    records = manifest["episodes"]
    if (
        len(records) != config.n
        or {r["index"] for r in records} != set(range(config.n))
        or any(r["status"] not in ("completed", "gap") for r in records)
    ):
        raise ValueError("campaign is incomplete; resume all recipe slots before exporting")


def _roof(root: Path, source: Path, supplied: Path | None, workers: int) -> Path:
    target = supplied if supplied is not None else root / "roof_reference_v1"
    if supplied is None:
        build_roof_reference(source, target, workers=workers)
    if (target / "BUILDING.json").exists():
        raise ValueError("roof reference is incomplete")
    metadata = json.loads((target / "evaluator/manifest.json").read_text())
    from verum.training.dataset import digest

    if metadata.get("source_manifest_sha256") != digest(source / "evaluator/manifest.json"):
        raise ValueError("roof references belong to another source campaign")
    return target


def generate_dataset(
    root: Path,
    *,
    workers: int = 1,
    campaign: Path | None = None,
    roof_reference: Path | None = None,
) -> dict[str, Any]:
    """Build all eight supported role views from the recipe or explicitly supplied source data."""
    commit, dirty = git_state()
    if dirty or workers < 1:
        raise ValueError("generation requires committed sources and a positive worker count")
    recipe = load_recipe()
    release = root / recipe["dataset_name"]
    if release.exists():
        raise FileExistsError("release already exists; verify it or use a new output root")
    root.mkdir(parents=True, exist_ok=True)
    config = campaign_config(recipe)
    source = _campaign(root, config, campaign, workers)
    supplemental = (
        (_roof(root, source, roof_reference, workers),)
        if recipe["include_coupled_roof_reference"]
        else ()
    )
    report = build_dataset_release(
        source, release, workers=workers, inspection_sources=supplemental
    )
    lineage = {
        "recipe": recipe,
        "code_commit": commit,
        "campaign": asdict(config),
        "source_manifest_sha256": report["source_manifest_sha256"],
        "inspection_source_manifest_sha256": [
            r["source_manifest_sha256"] for r in report["inspection_exercises"]
        ],
    }
    (release / "generation_recipe.json").write_text(json.dumps(lineage, indent=2) + "\n")
    shutil.copyfile(repo_root() / "docs/data_generation.md", release / "TEAM_DATA_GUIDE.md")
    shutil.copyfile(repo_root() / "docs/project_scope.md", release / "project_scope.md")
    roles = materialize_roles(release)
    summary = {k: v for k, v in report.items() if k != "records"}
    summary["role_views"] = roles
    summary["generation_recipe"] = lineage
    summary["verification"] = verify_dataset_release(release)
    summary["role_verification"] = verify_roles(release)
    (release / "release_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    archive = package_training(release, root / (recipe["dataset_name"] + "_training.zip"))
    return {
        "release": str(release),
        "archive": archive,
        "code_commit": commit,
        "agents_built": False,
    }
