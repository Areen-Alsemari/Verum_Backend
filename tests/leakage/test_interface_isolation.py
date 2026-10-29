"""Isolation of agent-visible interfaces from hidden truth, at schema level.

Inputs: the schemas in ``schemas/``, the sensor contract and the ``verum.api``
package source. Outputs: pass/fail.
Key assumptions: only structural isolation is testable in Phase 0. Agent-visible
schemas must refuse unknown fields (so a truth field cannot ride along), the
evaluator-only schemas must carry a mandatory ``hidden`` marker, and the api
package must stay empty until a read-only interface is designed.

Source: ``revised/05_simulation_validation_dataset.md`` sections 7.2 and 9.4;
``revised/02_hydraulic_model.md`` section 6.3 item 5.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import SensorContract, load_schema, validator

AGENT_VISIBLE = ["observation", "inspection_request", "inspection_result"]
EVALUATOR_ONLY = ["fault_truth", "observation_audit"]
TRUTH_FIELDS = [
    "fault_type",
    "fault_instance_id",
    "causal_parent_fault_instance_id",
    "severity_trajectory",
    "mechanism",
    "hidden",
    "t_source_s",
    "max_truth_time_used_s",
    "true_value",
    "ground_truth",
]
OBSERVATION: dict[str, Any] = {
    "schema_version": "0.5.0",
    "dataset": "observations",
    "episode_id": "EP-EXAMPLE-0001",
    "tag_id": "LT-101",
    "t_sim_s": 600.0,
    "t_available_s": 600.2,
    "timestamp_utc": "2026-01-01T00:10:00.000Z",
    "value": 9.0012,
    "unit": "m",
    "quality_flag": "good",
    "availability_status": "measured",
}


@pytest.mark.parametrize("name", AGENT_VISIBLE)
def test_agent_visible_schemas_refuse_unknown_fields(name: str) -> None:
    schema = load_schema(name)
    assert schema["additionalProperties"] is False
    assert "hidden" not in schema["properties"]


@pytest.mark.parametrize("name", EVALUATOR_ONLY)
def test_evaluator_schemas_require_the_hidden_marker(name: str) -> None:
    schema = load_schema(name)
    assert "hidden" in schema["required"]
    assert schema["properties"]["hidden"] == {"const": True}


@pytest.mark.parametrize("field", TRUTH_FIELDS)
def test_observation_rows_refuse_truth_fields(field: str) -> None:
    assert not validator("observation").is_valid({**OBSERVATION, field: "x"})


def test_observation_schema_has_no_truth_vocabulary() -> None:
    names = set(load_schema("observation")["properties"])
    assert not {n for n in names if re.search(r"fault|truth|severity|hidden|source", n)}


def test_inspection_request_has_no_result_fields() -> None:
    names = set(load_schema("inspection_request")["properties"])
    assert not names & {"findings", "evidence_status", "validation_status", "performed_at_t_sim_s"}


def test_withheld_tags_are_never_in_the_emitted_set(sensors: SensorContract) -> None:
    assert not set(sensors.withheld_tags) & set(sensors.emitted_tags)


def test_every_emitted_tag_fits_the_observation_tag_pattern(sensors: SensorContract) -> None:
    pattern = re.compile(load_schema("observation")["properties"]["tag_id"]["pattern"])
    assert all(pattern.fullmatch(tag) for tag in sensors.emitted_tags)


def test_api_package_holds_only_the_gateway(root: Path) -> None:
    """Phase 4 designed the read-only interface (a library, no server): the package is the
    gateway module and its re-exporting init, nothing else."""
    files = sorted(p.name for p in (root / "src" / "verum" / "api").iterdir() if p.suffix == ".py")
    assert files == ["__init__.py", "gateway.py"]
    tree = ast.parse((root / "src" / "verum" / "api" / "__init__.py").read_text(encoding="utf-8"))
    imported = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert [n.module for n in imported] == ["verum.api.gateway"]
