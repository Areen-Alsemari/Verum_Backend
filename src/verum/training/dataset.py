"""Portable reference-model data views for Verum's eight fixed logical roles.

Inputs contain causal observation summaries and public reference records, never simulator truth.
Reference injection labels live in separate targets with explicit masks and model limitations.
The export does not implement agents, certify plant behaviour or change physical release gates.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from verum.contracts import load_topology
from verum.contracts.paths import config_dir
from verum.inspection.assets import load_assets
from verum.inspection.catalog import load_catalog
from verum.params import ParamValue
from verum.provenance import canonical_json, config_hash, git_state
from verum.sensors.specs import load_sensor_config
from verum.training.features import (
    ObservationWindows,
    check_observation,
    quality_target,
    reference_supervision,
)
from verum.training.scope import project_scope
from verum.training.truth import load_episode_truth

SPLITS = ("train", "validation", "test")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def source_digest(path: Path) -> str:
    """Match the campaign convention: compressed sources are hashed after decompression."""
    if path.suffix != ".gz":
        return digest(path)
    with gzip.open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def dataset_contract() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        (config_dir() / "extensions" / "agent_dataset_v1.json").read_text()
    )
    return value


def _parameters(contract: dict[str, Any]) -> dict[str, float]:
    return {
        name: ParamValue.from_mapping(value).value for name, value in contract["parameters"].items()
    }


def public_reference() -> dict[str, Any]:
    """Export declared graph and instrument facts without actual hidden operating state."""
    topology = load_topology()
    sensors = load_sensor_config()
    geometry = json.loads((config_dir() / "tank_geometry.json").read_text())
    facts: dict[str, Any] = {
        tank.tank_id: {
            "declared_dimensions_m": tank.dimensions_m,
            "roof_geometry_parameters": geometry["parameters"],
            "source": geometry["source"],
            "field_qualified": False,
        }
        for tank in topology.tanks
    }
    for edge in topology.edges:
        facts[edge.edge_id] = {
            "length_m": edge.length_m,
            "inner_diameter_m": edge.inner_diameter_m,
            "elevation_from_m": edge.z_from_m,
            "elevation_to_m": edge.z_to_m,
            "route_id": edge.route_id,
            "source": edge.provenance,
            "field_qualified": False,
        }
    return {
        "assets": load_assets().listing(),
        "asset_facts": facts,
        "connections": [
            {"edge_id": e.edge_id, "from_node": e.from_node, "to_node": e.to_node}
            for e in topology.edges
        ],
        "instruments": [
            {
                "tag_id": tag,
                "unit": spec.unit,
                "sampling_kind": spec.kind,
                "sample_interval_s": spec.interval_s,
                "lag_s": spec.lag_s,
                "communication_delay_s": spec.comms_delay_s,
            }
            for tag, spec in sorted(sensors.tags.items())
        ],
        "inspection_catalog": load_catalog().agent_view(),
        "history": [],
        "history_status": "no_verified_past_maintenance_supplied",
        "limits": [
            "declared_representative_design",
            "contact_is_not_true_valve_position",
            "no_invented_maintenance",
            "no_continuous_VOC_or_withheld_motor_channels",
        ],
    }


def _reference_targets(index: int, reference: dict[str, Any]) -> dict[str, Any]:
    assets = reference["assets"]
    asset = assets[index % len(assets)]
    ident = asset["asset_id"]
    connections = [
        c
        for c in reference["connections"]
        if c["edge_id"] == ident
        or any(c[k] == ident or c[k].startswith(ident + ":") for k in ("from_node", "to_node"))
    ]
    action = reference["inspection_catalog"][index % len(reference["inspection_catalog"])]
    return {
        "topology_dependency": {
            "query": {"asset_id": ident},
            "answer": {"direct_connections": connections, "actual_routing_confirmed": False},
        },
        "historical_asset_intelligence": {
            "query": {"asset_id": ident},
            "answer": {
                "asset_record": asset,
                "declared_specifications": reference["asset_facts"].get(ident),
                "maintenance_history": None,
                "history_status": reference["history_status"],
                "evidence_ref": "knowledge/public_reference.json",
            },
        },
        "inspection_planning": {
            "query": {"action_id": action["action_id"]},
            "answer": {
                "action_record": action,
                "information_gain_bits": None,
                "best_action_label": None,
                "dispatch_authorized": False,
                "decision": "verify_preconditions_and_seek_human_approval",
            },
        },
    }


def _admissibility_example(
    rows: list[dict[str, Any]],
    cutoff: float,
    want_future: bool,
) -> dict[str, Any]:
    """Metadata-only future proposals never expose their future numerical measurement."""
    before = [r for r in rows if r["t_available_s"] <= cutoff and r["unit"] != "bool"]
    after = [r for r in rows if r["t_available_s"] > cutoff and r["unit"] != "bool"]
    chosen = after[0] if want_future and after else before[-1]
    released = chosen["t_available_s"] <= cutoff
    return {
        "proposal": {
            "tag_id": chosen["tag_id"],
            "unit": chosen["unit"],
            "available_relative_s": chosen["t_available_s"] - cutoff,
            "quality_flag": chosen["quality_flag"] if released else None,
            "value_present": chosen["value"] is not None if released else None,
            "numerical_value_withheld": True,
        },
        "answer": {
            "time_admissible": released,
            "measurement_usable": released
            and chosen["value"] is not None
            and chosen["quality_flag"] == "good",
            "equipment_condition_confirmed": False,
        },
    }


def _build_episode(job: tuple[Path, Path, dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    source, output, record, contract = job
    ident = record["episode_id"]
    directory = source / "evaluator" / "episodes" / ident
    scenario_path = directory / "scenario.json"
    scenario_key = scenario_path.relative_to(source).as_posix()
    if digest(scenario_path) != record["files"][scenario_key]:
        raise ValueError(f"scenario hash mismatch: {ident}")
    duration = float(json.loads(scenario_path.read_text())["duration_s"])
    for name in ("fault_truth.jsonl.gz", "labels.json"):
        target_path = directory / name
        if (
            source_digest(target_path)
            != record["files"][target_path.relative_to(source).as_posix()]
        ):
            raise ValueError(f"target source hash mismatch: {ident}")
    truth = load_episode_truth(directory)
    if {f["fault_instance_id"] for f in truth} != {f["instance_id"] for f in record["faults"]}:
        raise ValueError("source manifest and canonical truth disagree")
    observation_key = f"agent_visible/episodes/{ident}/observations.jsonl.gz"
    observation_path = source / observation_key
    if source_digest(observation_path) != record["files"][observation_key]:
        raise ValueError(f"observation hash mismatch: {ident}")
    raw = _rows(observation_path)
    cfg = load_sensor_config()
    units = {tag: spec.unit for tag, spec in cfg.tags.items()}
    for row in raw:
        if row["episode_id"] != ident:
            raise ValueError("observation episode identity mismatch")
        check_observation(row, units, duration)
    raw.sort(key=lambda r: (r["t_available_s"], r["tag_id"]))
    windows_key = f"evaluator/episodes/{ident}/validity_windows.jsonl.gz"
    if source_digest(source / windows_key) != record["files"][windows_key]:
        raise ValueError(f"validity-file hash mismatch: {ident}")
    validity = _rows(source / windows_key)
    params = _parameters(contract)
    step, lookback = params["snapshot_step_s"], params["lookback_s"]
    stops = [step * k for k in range(1, int(duration // step) + 1) if step * k >= lookback]
    observer = ObservationWindows(raw, units)
    summaries = {t: observer.summary(t, lookback) for t in stops}
    reference = public_reference()
    counters: Counter[str] = Counter()
    examples = output / "examples" / record["split"] / f"{ident}.jsonl.gz"
    examples.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(examples, "wt", encoding="utf-8") as handle:
        for index, cutoff in enumerate(stops):
            supervision = reference_supervision(
                record, cutoff, lookback, params["diagnosis_context_delay_s"], validity
            )
            counters["snapshots"] += 1
            counters["reference_label_eligible"] += supervision["supervised_loss_mask"]
            counters["reference_label_positive"] += bool(
                supervision["supervised_loss_mask"] and supervision["injected_change_present"]
            )
            future = summaries.get(cutoff + params["forecast_horizon_s"])
            forecast = (
                None
                if future is None
                else [
                    {
                        k: s[k]
                        for k in (
                            "tag_id",
                            "unit",
                            "mean",
                            "measured_count",
                            "missing_samples",
                            "bad_quality_samples",
                        )
                    }
                    for s in future["signals"]
                    if s["unit"] != "bool"
                ]
            )
            key = hashlib.sha256(canonical_json([ident, cutoff]).encode()).hexdigest()[:24]
            selector = int(hashlib.sha256((key + "/reference-query").encode()).hexdigest()[:16], 16)
            forecast_mask = (
                future is not None
                and record["tier"] == "analytic_verification"
                and not any(
                    w.get("affects_emitted_tags", True)
                    and w["t_start_s"] <= cutoff + params["forecast_horizon_s"]
                    and w["t_end_s"] >= cutoff - lookback
                    for w in validity
                )
            )
            row = {
                "example_id": key,
                "input": summaries[cutoff],
                "targets": {
                    "predictive_health": {
                        "future_measurements": forecast if forecast_mask else None,
                        "supervised_loss_mask": forecast_mask,
                        "forecast_horizon_s": params["forecast_horizon_s"],
                        "health_score": None,
                        "remaining_useful_life": None,
                    },
                    "anomaly_detection": {
                        "data_quality": quality_target(summaries[cutoff]),
                        "reference_supervision": supervision,
                    },
                    "diagnostic_reasoning": supervision,
                    "inspection_quality_documentation": {
                        "observed_record_quality": quality_target(summaries[cutoff]),
                        "inspection_measurements_not_invented": True,
                    },
                    "evidence_verification_decision": _admissibility_example(
                        raw, cutoff, index % 2 == 0
                    ),
                    **_reference_targets(selector, reference),
                },
                "lineage": {
                    "episode_id": ident,
                    "source_cutoff_s": cutoff,
                    "parent_group": ident,
                    "split": record["split"],
                },
            }
            handle.write(canonical_json(row) + "\n")
    target = output / "observations" / ident / "observations.jsonl.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(observation_path, target)
    if digest(target) != digest(observation_path):
        raise ValueError("copied observation bytes changed")
    if source_digest(target) != record["files"][observation_key]:
        raise ValueError("copied observations changed")
    evaluator_files = {}
    for name in (
        "scenario.json",
        "labels.json",
        "fault_truth.jsonl.gz",
        "validity_windows.jsonl.gz",
    ):
        copied = output / "evaluator" / "source_episodes" / ident / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(directory / name, copied)
        evaluator_files[copied.relative_to(output).as_posix()] = digest(copied)
    return {
        "evaluator_files": evaluator_files,
        "episode_id": ident,
        "split": record["split"],
        "observation_rows": len(raw),
        "source_observation_sha256": record["files"][observation_key],
        "observation_file": target.relative_to(output).as_posix(),
        "observation_sha256": digest(target),
        "example_file": examples.relative_to(output).as_posix(),
        "example_sha256": digest(examples),
        "counts": dict(counters),
    }


def build_dataset_release(
    source: Path, output: Path, *, workers: int = 1, inspection_sources: tuple[Path, ...] = ()
) -> dict[str, Any]:
    """Build a new portable research handoff without editing source cases or physical gates."""
    if output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise ValueError("output must be a new directory outside the source campaign")
    if workers < 1:
        raise ValueError("workers must be positive")
    for supplement in inspection_sources:
        if (supplement / "BUILDING.json").exists():
            raise ValueError("inspection source is incomplete")
        metadata = json.loads((supplement / "evaluator/manifest.json").read_text())
        if metadata.get("dataset") != "coupled_roof_reference":
            raise ValueError("inspection dataset is outside project scope")
    if len({p.resolve() for p in inspection_sources}) != len(inspection_sources):
        raise ValueError("inspection sources must be distinct")
    manifest_path = source / "evaluator" / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    records = [r for r in manifest["episodes"] if r["status"] == "completed"]
    if len({r["episode_id"] for r in records}) != len(records):
        raise ValueError("source episode identifiers must be unique")
    if not records or any(r["split"] not in SPLITS for r in records):
        raise ValueError("nonempty source with known splits is required")
    output.mkdir(parents=True)
    contract = dataset_contract()
    _write(output / "BUILDING.json", {"complete": False})
    _write(output / "knowledge" / "public_reference.json", public_reference())
    _write(output / "agent_data_contract.json", contract)
    _write(output / "project_scope.json", project_scope())
    _write(output / "evaluator" / "source_manifest.json", manifest)
    jobs = [(source, output, record, contract) for record in records]
    results = []
    if workers == 1:
        iterator = map(_build_episode, jobs)
        for item in iterator:
            results.append(item)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for item in pool.map(_build_episode, jobs, chunksize=1):
                results.append(item)
                if len(results) % 100 == 0:
                    print(
                        f"{len(results)}/{len(records)} episodes checked and exported", flush=True
                    )
    counters: Counter[str] = Counter()
    for result in results:
        counters.update(result["counts"])
    from verum.training.inspection_records import build_inspection_exercises

    inspections = []
    splits = {r["episode_id"]: r["split"] for r in records}
    for index, inspection_source in enumerate(inspection_sources):
        folder = output / "inspection_records" / f"source_{index:02d}"
        folder.mkdir(parents=True)
        bank = build_inspection_exercises(inspection_source, folder, splits, native=True)
        bank["file"] = (folder / "inspection_quality.jsonl").relative_to(output).as_posix()
        inspections.append(bank)
    shared_files = [
        "project_scope.json",
        "knowledge/public_reference.json",
        "agent_data_contract.json",
        "evaluator/source_manifest.json",
    ]
    commit, dirty = git_state()
    report = {
        "schema_version": "2.0.0",
        "export_complete": True,
        "scope_id": project_scope()["scope_id"],
        "scope": "reduced_simulation_and_evidence_handling",
        "physical_training_qualified": False,
        "production_enabled": False,
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "code_commit": commit,
        "code_dirty": dirty,
        "config_hash": config_hash(),
        "episodes": len(results),
        "splits": dict(Counter(r["split"] for r in results)),
        "observation_rows": sum(r["observation_rows"] for r in results),
        "counts": dict(counters),
        "roles": contract["roles"],
        "records": results,
        "limitations": contract["limitations"],
        "source_data_modified": False,
        "inspection_exercises": inspections,
        "shared_files": {p: digest(output / p) for p in shared_files},
        "agents_built": False,
    }
    _write(output / "release_manifest.json", report)
    (output / "BUILDING.json").unlink()
    return report


def iter_role_examples(root: Path, role: str, split: str) -> Iterator[dict[str, Any]]:
    """Yield model input/target pairs; simulator lineage is never included in the model input."""
    if (root / "BUILDING.json").exists():
        raise ValueError("export is incomplete")
    manifest = json.loads((root / "release_manifest.json").read_text())
    contract = json.loads((root / "agent_data_contract.json").read_text())
    if split not in SPLITS or role not in {r["key"] for r in contract["roles"]}:
        raise ValueError("unknown role or split")
    for name, expected in manifest["shared_files"].items():
        if digest(root / name) != expected:
            raise ValueError("shared reference file changed after export")
    reference = json.loads((root / "knowledge" / "public_reference.json").read_text())
    reference_queries_seen: set[str] = set()
    for record in manifest["records"]:
        if record["split"] != split:
            continue
        if digest(root / record["example_file"]) != record["example_sha256"]:
            raise ValueError("example file changed after export")
        for row in _rows(root / record["example_file"]):
            target = row["targets"][role]
            inputs: dict[str, Any] = {"observations": row["input"]}
            if role in (
                "topology_dependency",
                "historical_asset_intelligence",
                "inspection_planning",
            ):
                query_key = canonical_json(target["query"])
                if query_key in reference_queries_seen:
                    continue
                reference_queries_seen.add(query_key)
                inputs["query"] = target["query"]
                inputs["reference"] = reference
                target = target["answer"]
            elif role == "evidence_verification_decision":
                inputs = {"proposal": target["proposal"], "query_time_s": 0.0}
                target = target["answer"]
            reference_only = role in (
                "topology_dependency",
                "historical_asset_intelligence",
                "inspection_planning",
            )
            yield {
                "example_id": row["example_id"],
                "input": inputs,
                "target": target,
                "use": "public_reference_fixture_not_independent_test"
                if reference_only
                else "reference_input_target_pair",
            }

    if role in ("inspection_quality_documentation", "evidence_verification_decision"):
        for bank in manifest["inspection_exercises"]:
            path = root / bank["file"]
            if digest(path) != bank["sha256"]:
                raise ValueError("inspection quality exercise changed")
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    if row["split"] == split:
                        yield {
                            "example_id": row["example_id"],
                            "input": row["input"],
                            "target": row["target"],
                            "use": "inspection_record_quality",
                        }


def verify_dataset_release(root: Path) -> dict[str, Any]:
    """Check portable file integrity, split membership and all target masks independently."""
    if (root / "BUILDING.json").exists():
        raise ValueError("export is incomplete")
    manifest = json.loads((root / "release_manifest.json").read_text())
    for name, expected in manifest["shared_files"].items():
        if digest(root / name) != expected:
            raise ValueError(f"shared reference hash mismatch: {name}")
    source = json.loads((root / "evaluator/source_manifest.json").read_text())
    membership = {
        r["episode_id"]: r["split"] for r in source["episodes"] if r["status"] == "completed"
    }
    roles = {r["key"] for r in dataset_contract()["roles"]}
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    episodes: set[str] = set()
    for record in manifest["records"]:
        ident = record["episode_id"]
        if ident in episodes or membership[ident] != record["split"]:
            raise ValueError("episode duplicated or source split changed")
        episodes.add(ident)
        for name, expected in record["evaluator_files"].items():
            if digest(root / name) != expected:
                raise ValueError("evaluator source copy changed")
        for path_key, hash_key in (
            ("example_file", "example_sha256"),
            ("observation_file", "observation_sha256"),
        ):
            if digest(root / record[path_key]) != record[hash_key]:
                raise ValueError(f"export hash mismatch: {ident}")
        for row in _rows(root / record["example_file"]):
            if row["example_id"] in seen or set(row["targets"]) != roles:
                raise ValueError("duplicated example or incomplete role coverage")
            seen.add(row["example_id"])
            if row["lineage"]["split"] != record["split"]:
                raise ValueError("example split differs from parent")
            features = row["input"]
            if features["current_time_s"] != 0 or "episode_id" in features:
                raise ValueError("episode identity/absolute clock leaked into features")
            for signal in features["signals"]:
                for key in ("latest_received_age_s", "previous_measured_age_s"):
                    if signal[key] is not None and not 0 <= signal[key] <= features["lookback_s"]:
                        raise ValueError("uncensored age can expose the episode clock")
            for target in (
                row["targets"]["diagnostic_reasoning"],
                row["targets"]["anomaly_detection"]["reference_supervision"],
            ):
                if not target["supervised_loss_mask"] and (
                    target["injected_components"] is not None
                    or target["injected_change_present"] is not None
                ):
                    raise ValueError("masked diagnosis incorrectly became a supervised label")
            counts[record["split"]] += 1
    if episodes != set(membership):
        raise ValueError("source episodes missing from portable handoff")
    for bank in manifest["inspection_exercises"]:
        if digest(root / bank["file"]) != bank["sha256"]:
            raise ValueError("inspection quality exercise changed")
        with (root / bank["file"]).open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row["split"] != "challenge" and (
                    membership[row["lineage"]["parent_group"]] != row["split"]
                ):
                    raise ValueError("inspection exercise crosses parent split")
                if row["target"]["equipment_condition"] is not None:
                    raise ValueError("unsupported inspection condition target")
    return {
        "integrity_passed": True,
        "episodes": len(episodes),
        "examples": len(seen),
        "examples_by_split": dict(counts),
        "roles": sorted(roles),
        "physical_training_qualified": False,
        "production_enabled": False,
    }
