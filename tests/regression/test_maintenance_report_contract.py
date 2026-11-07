"""Checks for the structured documentation boundary and its conservative example.

These checks cover JSON shape and fixture lineage, not factual verification of generated prose.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource

from verum.contracts.agent_interfaces import content_hash


def report_files(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    base = root / "contracts" / "reports"
    schema = json.loads((base / "maintenance_report.schema.json").read_text())
    example = json.loads((base / "maintenance_report.example.json").read_text())
    return schema, example


def report_validator(root: Path) -> jsonschema.Draft202012Validator:
    schema, _ = report_files(root)
    common = json.loads(
        (root / "contracts" / "agents" / "v1" / "common.schema.json").read_text()
    )
    registry: Registry[Any] = Registry().with_resource(
        common["$id"], Resource.from_contents(common),
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema, registry=registry, format_checker=jsonschema.FormatChecker(),
    )


def test_report_example_preserves_source_assessment(root: Path) -> None:
    """The example copies its source assessment without adding measured values.

    Independent: no, because the source is another conservative interface fixture.
    """
    _, report = report_files(root)
    report_validator(root).validate(report)
    source = json.loads((
        root / "contracts" / "agents" / "v1" / "examples"
        / "evidence_verification_decision.response.json"
    ).read_text())
    assert report["context"] == source["context"]
    assert report["assessment_state"] == source["result"]["decision_state"]
    assert report["source_reports"][0]["content_sha256"] == content_hash(source)
    assert report["findings"][0]["statement"] == source["result"]["summary"]
    assert report["findings"][0]["measurement"] is None


@pytest.mark.parametrize("field,value", [
    ("automatic_action_authorized", True),
    ("human_decision_required", False),
    ("equipment_condition_confirmed", True),
    ("review_status", "approved"),
    ("report_type", "maintenance_completed"),
    ("source_reports", []),
    ("limitations", []),
])
def test_report_rejects_unsupported_states(root: Path, field: str, value: Any) -> None:
    """The output cannot claim authorisation, completion or unsupported condition.

    Independent: yes, because prohibited assertions are literal counterexamples.
    """
    _, report = report_files(root)
    report[field] = value
    with pytest.raises(jsonschema.ValidationError):
        report_validator(root).validate(report)


def test_report_requires_units_and_source_links(root: Path) -> None:
    """A numeric finding needs a unit and a source report identifier.

    Independent: yes, because malformed measurements and links are literal mutations.
    """
    _, report = report_files(root)
    report["findings"][0]["measurement"] = {"value": 1}
    with pytest.raises(jsonschema.ValidationError):
        report_validator(root).validate(report)
    report["findings"][0]["measurement"] = None
    del report["findings"][0]["source_report_id"]
    with pytest.raises(jsonschema.ValidationError):
        report_validator(root).validate(report)


def test_optional_cohere_narrative_requires_model_and_prompt(root: Path) -> None:
    """An optional language-model narrative records its model and prompt identity.

    Independent: yes, because missing model metadata is a literal invalid state.
    """
    _, report = report_files(root)
    original = copy.deepcopy(report)
    report["narrative"]["provider"] = "cohere"
    with pytest.raises(jsonschema.ValidationError):
        report_validator(root).validate(report)
    report["narrative"].update(model="test-model-identifier", prompt_id="test-prompt")
    report_validator(root).validate(report)
    original["narrative"]["unverified_diagnosis"] = "unsupported"
    with pytest.raises(jsonschema.ValidationError):
        report_validator(root).validate(original)
