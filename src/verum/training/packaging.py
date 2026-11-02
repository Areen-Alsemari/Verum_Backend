"""Portable role files and a compact training bundle with independent integrity checks.

The default bundle excludes raw telemetry and evaluator truth; each row separates input and target.
All eight roles retain their original splits, explicit masks and reference-only task descriptions.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from verum.training.dataset import SPLITS, digest, iter_role_examples, verify_dataset_release


def materialize_roles(root: Path) -> list[dict[str, Any]]:
    """Write each role/split once and bind its stored bytes, row count and supervision coverage."""
    verify_dataset_release(root)
    if (root / "role_views").exists():
        raise FileExistsError("role views already exist; use a new release directory")
    contract = json.loads((root / "agent_data_contract.json").read_text())
    records = []
    for role in contract["roles"]:
        for split in SPLITS:
            path = root / "role_views" / role["key"] / f"{split}.jsonl.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            counts: Counter[str] = Counter({"examples": 0})
            with gzip.open(path, "xt", encoding="utf-8") as handle:
                for row in iter_role_examples(root, role["key"], split):
                    handle.write(json.dumps(row, allow_nan=False) + "\n")
                    counts["examples"] += 1
                    counts[row["use"]] += 1
                    target = row["target"].get("reference_supervision", row["target"])
                    if "supervised_loss_mask" in target:
                        counts["eligible"] += target["supervised_loss_mask"]
                        counts["masked"] += not target["supervised_loss_mask"]
                        counts["reference_positive"] += (
                            target.get("injected_change_present") is True
                        )
            records.append(
                {
                    "role": role["key"],
                    "split": split,
                    "file": path.relative_to(root).as_posix(),
                    "sha256": digest(path),
                    "counts": dict(counts),
                }
            )
    (root / "role_views_manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    return records


def verify_roles(root: Path) -> dict[str, Any]:
    """Check the complete role/split inventory, hashes, JSON values and input/target separation."""
    records = json.loads((root / "role_views_manifest.json").read_text())
    contract = json.loads((root / "agent_data_contract.json").read_text())
    expected = {(r["key"], split) for r in contract["roles"] for split in SPLITS}
    found: set[tuple[str, str]] = set()
    total = 0
    for entry in records:
        key = entry["role"], entry["split"]
        if key in found or key not in expected:
            raise ValueError("duplicated or unknown role/split")
        found.add(key)
        path = _inside(root, entry["file"])
        if digest(path) != entry["sha256"]:
            raise ValueError("materialized role file changed")
        count = 0
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line, parse_constant=_invalid_number)
                if set(row) != {"example_id", "input", "target", "use"}:
                    raise ValueError("unexpected role example fields")
                _check_input(row["input"])
                count += 1
        if count != entry["counts"]["examples"]:
            raise ValueError("role example count changed")
        total += count
    if found != expected:
        raise ValueError("missing role/split views")
    return {"role_files": len(found), "examples": total, "integrity_passed": True}


def _check_input(value: Any, path: tuple[Any, ...] = ()) -> None:
    if isinstance(value, dict):
        forbidden = {
            "target",
            "targets",
            "lineage",
            "ground_truth",
            "fault_truth",
            "hydraulic_state",
            "solver_diagnostics",
            "mass_ledger",
            "observation_audit",
            "simulation_rejected",
            "injected_components",
            "injected_change_present",
            "source_cutoff_s",
            "supervised_loss_mask",
            "fault_instance_id",
        }
        found = forbidden.intersection(value)
        if (
            len(path) == 3
            and path[:2] == ("reference", "inspection_catalog")
            and isinstance(value.get("targets"), str)
        ):
            found.discard("targets")
        if found:
            raise ValueError("hidden target or lineage exposed in model input")
        for key, child in value.items():
            _check_input(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_input(child, (*path, index))


def _invalid_number(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def _inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("artifact path leaves the release")
    return path


def package_training(root: Path, target: Path) -> dict[str, Any]:
    """Package only role examples and public knowledge, with hashes and an archive CRC check."""
    verify_dataset_release(root)
    verification = verify_roles(root)
    if target.exists():
        raise FileExistsError("training archive already exists")
    files = [
        root / name
        for name in (
            "role_views_manifest.json",
            "agent_data_contract.json",
            "project_scope.json",
            "knowledge/public_reference.json",
            "release_summary.json",
            "generation_recipe.json",
            "TEAM_DATA_GUIDE.md",
        )
    ]
    files.extend(sorted((root / "role_views").rglob("*.jsonl.gz")))
    if any(not path.is_file() for path in files):
        raise ValueError("package metadata is incomplete; use the end-to-end generation command")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    inventory = []
    with zipfile.ZipFile(
        partial, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as archive:
        for path in files:
            name = path.relative_to(root).as_posix()
            inventory.append({"file": name, "sha256": digest(path), "bytes": path.stat().st_size})
            archive.write(path, name)
        archive.writestr("BUNDLE_FILES.json", json.dumps(inventory, indent=2) + "\n")
    verify_training_archive(partial)
    partial.replace(target)
    report = {
        "file": target.name,
        "sha256": digest(target),
        "bytes": target.stat().st_size,
        "raw_observations_included": False,
        "evaluator_truth_included": False,
        "verification": verification,
    }
    target.with_name(target.name + ".sha256.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def verify_training_archive(path: Path) -> dict[str, Any]:
    """Check archive membership and every payload hash without extracting files."""
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("archive CRC failure")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicated archive entry")
        inventory = json.loads(archive.read("BUNDLE_FILES.json"))
        contract = json.loads(archive.read("agent_data_contract.json"))
        expected = {
            "role_views_manifest.json",
            "agent_data_contract.json",
            "project_scope.json",
            "knowledge/public_reference.json",
            "release_summary.json",
            "generation_recipe.json",
            "TEAM_DATA_GUIDE.md",
            "BUNDLE_FILES.json",
        }
        expected.update(
            f"role_views/{r['key']}/{split}.jsonl.gz" for r in contract["roles"] for split in SPLITS
        )
        if len(contract["roles"]) != 8 or set(names) != expected:
            raise ValueError("archive is not a complete eight-role training bundle")
        if set(names) != {r["file"] for r in inventory} | {"BUNDLE_FILES.json"}:
            raise ValueError("archive inventory differs from its payload")
        for record in inventory:
            name = record["file"]
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("unsafe archive path")
            with archive.open(name) as handle:
                actual = hashlib.sha256()
                while chunk := handle.read(1024 * 1024):
                    actual.update(chunk)
                if actual.hexdigest() != record["sha256"]:
                    raise ValueError("archive payload hash mismatch")
            if archive.getinfo(name).file_size != record["bytes"]:
                raise ValueError("archive payload size mismatch")
    return {"integrity_passed": True, "files": len(inventory)}
