"""Checks of the simulated, time-compressed inspection that the compressed workflow tool builds."""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import jsonschema
import pytest

from _runner_cases import reference, snapshot, summary
from verum.contracts.agent_interfaces import contract_directory

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "agents" / "run_compressed_workflow.py"
LABEL_WORDS = ("fault", "mechanism", "injected", "n_components", "labels")
RULE_FUNCTIONS = (
    "chosen_option", "competing", "make_request", "make_result", "make_coverage", "make_proposal",
    "simulate",
)


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compressed_workflow_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reports() -> dict[str, Any]:
    valve = next(a["asset_id"] for a in reference()["assets"] if a["kind"] == "isolation_valve")
    option = {
        "option_id": "OPT-1", "action_id": "ACT-INSP-02", "target_asset": valve,
        "addresses_hypothesis_ids": ["H-1"], "expected_information_gain_bits": None,
        "cost_usd": 90.0,
    }
    hypotheses = [{"hypothesis_id": "H-1"}, {"hypothesis_id": "H-2"}]
    return {
        "inspection_planning": {"result": {"options": [option]}},
        "diagnostic_reasoning": {"result": {"hypotheses": hypotheses}},
    }


def _objects(tool: ModuleType) -> dict[str, Any]:
    objects = tool.simulate(1, _reports(), 300.0, 600.0, reference()["inspection_catalog"])
    assert objects is not None
    return dict(objects)


def _schema(name: str) -> jsonschema.Draft202012Validator:
    path = ROOT / "schemas" / f"{name}.schema.json"
    return jsonschema.Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def test_every_simulated_object_carries_both_markers() -> None:
    """The request, result, coverage row and proposal each state that they are simulated.

    Independent: yes, because the marker strings are literals of the requirement.
    """
    tool = _tool()
    objects = _objects(tool)
    for name in ("request", "result", "coverage", "proposal"):
        text = json.dumps(objects[name])
        assert "SIMULATED INSPECTION" in text and "time_compressed: true" in text, name
    notes = objects["result"]["findings"]["secondary_observations"]
    assert "SIMULATED INSPECTION" in notes and "time_compressed: true" in notes


def test_the_simulated_objects_satisfy_the_schemas() -> None:
    """The markers sit in free-text fields, so the request and the result still validate.

    Independent: yes, because the schemas forbid extra fields and the check is the validator.
    """
    objects = _objects(_tool())
    _schema("inspection_request").validate(objects["request"])
    _schema("inspection_result").validate(objects["result"])


def test_an_action_without_a_catalogue_uncertainty_still_gives_a_valid_result() -> None:
    """The pump action states no uncertainty, so the rule gives 0.0 and the result validates.

    Independent: yes, because the schema is the validator and the catalogue is read as stored.
    """
    tool = _tool()
    catalog = reference()["inspection_catalog"]
    request = _objects(tool)["request"] | {"action_id": "ACT-INSP-03"}
    result = tool.make_result(1, request, catalog, 300.0)
    assert result["findings"]["primary_metric"]["uncertainty_k2"] == 0.0
    _schema("inspection_result").validate(result)


def test_the_simulated_result_is_a_valid_performed_result_without_a_condition() -> None:
    """The rule gives a valid, passed record whose category states no equipment condition.

    Independent: yes, because the expected values are the literals of rule R1.
    """
    result = _objects(_tool())["result"]
    assert (result["workflow_status"], result["evidence_status"]) == ("performed", "valid")
    assert result["validation_status"] == "PASSED_QA"
    assert result["findings"]["outcome_category"] == "TEST_INCONCLUSIVE"
    assert result["performed_at_t_sim_s"] == 300.0


def test_the_context_time_is_the_episode_start_plus_the_cutoff() -> None:
    """The wall-clock cutoff adds the cutoff seconds to the synthetic start of the episode.

    Independent: yes, because the sum is worked out by hand from the configured start.
    """
    tool = _tool()
    assert tool.episode_start_utc() == "2026-01-01T00:00:00.000Z"
    assert tool.utc_of("2026-01-01T00:00:00.000Z", 3600.0) == "2026-01-01T01:00:00.000Z"
    assert tool.utc_of("2026-01-01T00:00:00.000Z", 300.0) == "2026-01-01T00:05:00.000Z"


def test_the_rule_never_reads_a_label() -> None:
    """No function of the rule takes a window or a label, or names a label field.

    Independent: yes, because the check reads the signatures and the source text.
    """
    tool = _tool()
    for name in RULE_FUNCTIONS:
        function = getattr(tool, name)
        assert not {"w", "window", "label", "labels"} & set(inspect.signature(function).parameters)
        source = inspect.getsource(function).lower()
        assert not [word for word in LABEL_WORDS if word in source], name


def test_the_outcome_is_unchanged_when_the_labels_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The simulated objects written for a window are equal with and without its labels.

    Independent: yes, because the same call is made twice and only the window dict differs.
    """
    tool = _tool()
    seen: list[dict[str, Any]] = []

    def record(*args: Any) -> SimpleNamespace:
        seen.append(args[4])
        return SimpleNamespace(reports={}, issues=[])

    monkeypatch.setattr(tool, "second_pass", record)
    snap = snapshot()
    case = tool.Case(snap.reference, "0" * 64, {("E", 1): (summary(), 600.0)})
    bundle = SimpleNamespace(reports=_reports(), assessments=None)
    bare = {"window_id": "w", "episode_id": "E", "position": 0, "cutoff_s": 300.0}
    labelled = {
        **bare, "fault": True, "assets": ["XV-1"], "fault_types": ["x"], "mechanisms": ["pump"],
        "n_components": 1,
    }
    rows = []
    for index, window in enumerate((labelled, bare)):
        case.serial = 0
        rows.append(tool.follow_up(case, snap, bundle, window, tmp_path / str(index)))
    assert rows[0] == rows[1] and seen[0] == seen[1]
    files = [(tmp_path / str(i) / "simulated" / "w.json").read_text() for i in (0, 1)]
    assert files[0] == files[1]


def test_no_second_pass_is_reported_for_the_last_position() -> None:
    """A window without a later real window gets no simulated objects and says so.

    Independent: yes, because the expected text is the literal of the requirement.
    """
    tool = _tool()
    case = tool.Case(reference(), "0" * 64, {})
    bundle = SimpleNamespace(reports=_reports(), assessments=None)
    window = {"window_id": "w", "episode_id": "E", "position": 12, "cutoff_s": 3600.0}
    row = tool.follow_up(case, snapshot(), bundle, window, Path("unused"))
    assert row == {"second_pass": "no second pass available"} and case.serial == 0


STORED_RUN = ROOT / "reports" / "compressed_workflow_lf"


def _tracked_data_files() -> list[Path]:
    kinds = {".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".gz"}
    folders = ("tests", "contracts", "config", "schemas", "reports")
    return [
        p for f in folders for p in (ROOT / f).rglob("*")
        if p.is_file() and p.suffix in kinds and "__pycache__" not in p.parts
        and STORED_RUN not in p.parents
    ]


def test_no_simulated_marker_reaches_a_metrics_file_fixture_or_table() -> None:
    """No data file of the repository, outside the stored run itself, carries a marker.

    Independent: yes, because the check searches the files for the literal marker strings.
    """
    assert _tracked_data_files()
    for path in _tracked_data_files():
        if path.suffix == ".gz":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "SIMULATED INSPECTION" not in text and "time_compressed" not in text, path


def test_the_tool_writes_only_below_its_output_folder_and_nothing_imports_it() -> None:
    """The tool dumps only below its own output folder, and no other module uses it.

    Independent: yes, because the check reads the source text of the tool and its neighbours.
    """
    source = TOOL.read_text(encoding="utf-8")
    targets = re.findall(r"sample\.dump\(([^,]+),", source)
    assert targets and all(t.startswith(("out", "args.out")) for t in targets)
    others = [
        p for folder in ("src", "tools", "tests") for p in (ROOT / folder).rglob("*.py")
        if p != TOOL and p != Path(__file__) and "run_compressed_workflow" in p.read_text("utf-8")
    ]
    assert others == []
    assert contract_directory().is_dir()
