"""Checks for the eight agent message boundaries and their causal evidence contracts.

Literal mutations exercise wiring, source identity, unknowns and scope without running models.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from verum.contracts.agent_interfaces import (
    content_hash,
    contract_directory,
    validate_request,
    validate_response,
    validators,
)

ROLES = (
    "predictive_health", "anomaly_detection", "topology_dependency",
    "historical_asset_intelligence", "diagnostic_reasoning", "inspection_planning",
    "inspection_quality_documentation", "evidence_verification_decision",
)


@pytest.fixture(scope="module")
def checks() -> dict[str, jsonschema.Draft202012Validator]:
    return validators()


def messages(role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    base = contract_directory() / "examples"
    request = json.loads((base / f"{role}.request.json").read_text())
    response = json.loads((base / f"{role}.response.json").read_text())
    return request, response


@pytest.mark.parametrize("role", ROLES)
def test_each_role_has_a_valid_request_and_response(
    role: str, checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """All roles accept the versioned conservative connection examples.

    Independent: no, because examples and schemas belong to the same contract definition.
    """
    request, response = messages(role)
    validate_request(request, checks)
    validate_response(request, response, checks)


@pytest.mark.parametrize("key", ["labels", "supervised_loss_mask", "future_value"])
def test_extra_training_fields_are_rejected(
    key: str, checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """An input cannot carry undeclared supervision or a future target.

    Independent: yes, because the forbidden payload is a literal extra field.
    """
    request, _ = messages("predictive_health")
    request["input"][key] = 1
    with pytest.raises(jsonschema.ValidationError):
        validate_request(request, checks)


@pytest.mark.parametrize("change", ["case_id", "analysis_id", "revision", "as_of_s"])
def test_response_must_match_the_requested_snapshot(
    change: str, checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A response for a different request context cannot be attached silently.

    Independent: yes, because each mutation changes one known identity or time.
    """
    request, response = messages("predictive_health")
    response["context"][change] = 1 if change in {"revision", "as_of_s"} else "another"
    with pytest.raises(ValueError, match="does not match"):
        validate_response(request, response, checks)


def test_future_observation_evidence_is_rejected(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """An evidence source available after the query cannot enter an input.

    Independent: yes, because 301 seconds is later than the fixture cutoff of 300 seconds.
    """
    request, _ = messages("predictive_health")
    request["evidence"][0]["available_at_s"] = 301
    with pytest.raises(ValueError, match="future content"):
        validate_request(request, checks)


def test_changed_observations_need_matching_source_content(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """Changing an observation while retaining its digest fails its binding.

    Independent: yes, because the content changes without changing its source identity.
    """
    request, _ = messages("predictive_health")
    request["input"]["observations"]["summary"]["signals"][0]["mean"] = -1
    with pytest.raises(ValueError, match="not bound"):
        validate_request(request, checks)


def _attach_forecast(request: dict[str, Any]) -> dict[str, Any]:
    _, forecast = messages("predictive_health")
    request["input"]["forecast_report"] = forecast
    request["evidence"].append({
        "evidence_id": forecast["report_id"], "kind": "agent_report",
        "source_ref": "report:" + forecast["report_id"], "available_at_s": 300,
        "content_sha256": content_hash(forecast),
        "root_evidence_ids": ["source-observations", "source-reference"],
        "provenance": "derived_agent_output",
    })
    return forecast


def test_a_current_forecast_can_be_connected_to_anomaly_detection(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """Two independently named messages connect through a sourced report reference.

    Independent: yes, because the dependency edge is assembled separately from stored examples.
    """
    request, _ = messages("anomaly_detection")
    _attach_forecast(request)
    validate_request(request, checks)


@pytest.mark.parametrize("change", ["stale", "changed", "fixture_as_runtime"])
def test_invalid_upstream_report_cannot_connect(
    change: str, checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A stale, changed or fixture-only report cannot masquerade as a current result.

    Independent: yes, because the report is changed after its evidence reference is attached.
    """
    request, _ = messages("anomaly_detection")
    forecast = _attach_forecast(request)
    if change == "stale":
        forecast["context"]["as_of_s"] = 299
    elif change == "changed":
        forecast["limitations"].append("Unbound content change.")
    else:
        request["context"]["execution_mode"] = "runtime"
    with pytest.raises(ValueError):
        validate_request(request, checks)


def test_forecast_units_must_match_observation_units(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A flow forecast cannot be silently relabelled as pressure.

    Independent: yes, because the literal unit differs from the requested channel.
    """
    request, response = messages("predictive_health")
    response["result"]["forecasts"][0]["unit"] = "barg"
    with pytest.raises(ValueError, match="unit differs"):
        validate_response(request, response, checks)


def test_graph_output_cannot_introduce_a_new_connection(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A connection absent from supplied public topology cannot be returned as fact.

    Independent: yes, because the connection is a literal absent from the input graph.
    """
    request, response = messages("topology_dependency")
    response["result"]["direct_connections"] = [
        {"edge_id": "not-declared", "from_node": "one", "to_node": "two"}
    ]
    with pytest.raises(ValueError, match="connection was not supplied"):
        validate_response(request, response, checks)


def test_history_retrieval_cannot_create_a_record(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A source with no history cannot claim that historical records are available.

    Independent: yes, because the fixture contains no historical records.
    """
    request, response = messages("historical_asset_intelligence")
    response["result"]["history_status"] = "simulated_records_available"
    with pytest.raises(ValueError, match="no supplied records"):
        validate_response(request, response, checks)


def test_missing_upstream_evidence_remains_unknown(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A missing forecast cannot be claimed to support a diagnostic candidate.

    Independent: yes, because the request contains an explicit null forecast.
    """
    request, response = messages("diagnostic_reasoning")
    response["result"]["upstream_checks"][0]["outcome"] = "pass"
    with pytest.raises(ValueError, match="missing upstream evidence"):
        validate_response(request, response, checks)


def _option(request: dict[str, Any]) -> dict[str, Any]:
    action = request["input"]["catalog"][0]
    return {
        "option_id": "option-one", "action_id": action["action_id"], "target_asset": "TK-101",
        "addresses_hypothesis_ids": [], "feasibility": "unknown", "precondition_checks": [],
        "cost_usd": action["cost_usd"], "duration_min": action["duration_min"],
        "expected_information_gain_bits": None, "information_gain_method_id": None,
        "limitations": ["Preconditions unassessed."], "evidence_ids": ["source-reference"],
    }


def test_inspection_information_gain_can_remain_unknown(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """Planning can preserve a source-matched action without inventing information gain.

    Independent: yes, because the action fields come directly from the input catalog.
    """
    request, response = messages("inspection_planning")
    response["result"]["options"] = [_option(request)]
    validate_response(request, response, checks)


@pytest.mark.parametrize("change", ["price", "eligibility", "information_gain", "recommendation"])
def test_unjustified_inspection_options_are_rejected(
    change: str, checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """An inspection cannot gain a price, eligibility or ranking through an unsupported default.

    Independent: yes, because each mutation violates a separately stated catalog or policy rule.
    """
    request, response = messages("inspection_planning")
    option = _option(request)
    response["result"]["options"] = [option]
    if change == "price":
        option["cost_usd"] += 1
    elif change == "eligibility":
        option["feasibility"] = "eligible_for_human_review"
    elif change == "information_gain":
        option["expected_information_gain_bits"] = 0
    else:
        response["result"]["recommended_option_id"] = option["option_id"]
    with pytest.raises(ValueError):
        validate_response(request, response, checks)


def test_nonperformed_inspection_cannot_enter_quality_inputs(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A requested inspection provides no performed result for an agent to inspect.

    Independent: yes, because the literal workflow state is requested rather than performed.
    """
    request, _ = messages("inspection_quality_documentation")
    request["input"]["inspection_results"] = [{
        "schema_version": "0.5.0", "dataset": "inspection_results",
        "result_id": "RES-INSP-00001", "request_id": "REQ-INSP-00001",
        "action_id": "ACT-INSP-02", "workflow_status": "requested",
    }]
    with pytest.raises(jsonschema.ValidationError):
        validate_request(request, checks)


def test_future_evidence_proposal_is_metadata_only_and_rejected(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A future proposal is assessable without disclosing its measurements.

    Independent: yes, because the proposal availability is explicitly later than its query.
    """
    request, response = messages("evidence_verification_decision")
    request["input"]["evidence_proposals"] = [{
        "proposal_id": "later-result", "source_ref": "inspection_result:RES-INSP-00001",
        "claimed_available_at_s": 301, "claimed_evidence_ids": [],
    }]
    row = {
        "proposal_id": "later-result", "time_admissible": False, "provenance_verified": None,
        "quality_acceptable": None, "scope_supported": None, "usable": False,
        "reasons": ["Not available at cutoff."], "evidence_ids": [],
    }
    response["result"]["evidence_checks"] = [row]
    validate_response(request, response, checks)
    row["time_admissible"] = True
    with pytest.raises(ValueError, match="future evidence must be rejected"):
        validate_response(request, response, checks)


@pytest.mark.parametrize("role,field", [
    ("inspection_planning", "dispatch_authorized"),
    ("evidence_verification_decision", "automatic_action_authorized"),
    ("evidence_verification_decision", "equipment_condition_confirmed"),
])
def test_advisory_outputs_cannot_authorize_control_or_qualified_condition(
    role: str, field: str, checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A result cannot open control or qualification through a boolean field.

    Independent: yes, because the literal true value contradicts the supported scope.
    """
    request, response = messages(role)
    response["result"][field] = True
    with pytest.raises(jsonschema.ValidationError):
        validate_response(request, response, checks)


def test_empty_diagnosis_cannot_produce_an_available_assessment(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """An absent diagnostic report cannot become an available supported assessment.

    Independent: yes, because the request contains no diagnosis report.
    """
    request, response = messages("evidence_verification_decision")
    response["result"]["decision_state"] = "assessment_available"
    with pytest.raises(ValueError, match="assessment is unavailable"):
        validate_response(request, response, checks)


def test_interface_roles_match_the_existing_eight_role_contract(root: Path) -> None:
    """The new interfaces preserve the architecture's existing role identifiers.

    Independent: yes, because the identifiers are compared with a separately versioned contract.
    """
    source = json.loads((root / "config/extensions/agent_dataset_v1.json").read_text())
    manifest = json.loads((contract_directory() / "manifest.json").read_text())
    assert [(r["number"], r["key"]) for r in manifest["agents"]] == [
        (r["number"], r["key"]) for r in source["roles"]
    ]


def test_catalog_shape_matches_the_gateway_definition() -> None:
    """Catalog interfaces retain the existing gateway's action shape.

    Independent: yes, because the gateway schema is maintained outside the new contracts.
    """
    from verum.api.gateway import CATALOG_SCHEMA, OUTPUT_SCHEMA

    common = json.loads((contract_directory() / "common.schema.json").read_text())["$defs"]
    action = copy.deepcopy(common["catalog_action"])
    action["properties"]["outputs"]["items"] = common["catalog_output"]
    expected = copy.deepcopy(CATALOG_SCHEMA)
    expected["properties"]["action_id"] = action["properties"]["action_id"]
    for name in ("name", "unit"):
        assert common["catalog_output"]["properties"][name] == OUTPUT_SCHEMA["properties"][name]
    assert action == expected


def test_changed_report_roots_are_rejected(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """A derived report cannot disguise its observation roots as separate reference evidence.

    Independent: yes, because the report still consumes observations after its roots are changed.
    """
    request, _ = messages("anomaly_detection")
    _attach_forecast(request)
    request["evidence"][-1]["root_evidence_ids"] = ["source-reference"]
    with pytest.raises(ValueError, match="discarded or changed"):
        validate_request(request, checks)


def test_all_eight_role_boundaries_connect_with_conservative_reports(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """The full dependency graph composes without an agent implementation or invented predictions.

    Independent: yes, because dependency messages are assembled separately from the fixtures.
    """
    requests, responses = {}, {}
    for role in ROLES:
        requests[role], responses[role] = messages(role)
    dependencies = {
        "anomaly_detection": {"forecast_report": "predictive_health"},
        "diagnostic_reasoning": {
            "forecast_report": "predictive_health", "anomaly_report": "anomaly_detection",
            "topology_report": "topology_dependency",
            "asset_report": "historical_asset_intelligence",
            "inspection_quality_report": "inspection_quality_documentation",
        },
        "inspection_planning": {"diagnosis_report": "diagnostic_reasoning"},
        "evidence_verification_decision": {
            "diagnosis_report": "diagnostic_reasoning",
            "inspection_plan_report": "inspection_planning",
            "inspection_quality_report": "inspection_quality_documentation",
        },
    }
    for role in (
        "predictive_health", "anomaly_detection", "topology_dependency",
        "historical_asset_intelligence", "inspection_quality_documentation",
        "diagnostic_reasoning", "inspection_planning", "evidence_verification_decision",
    ):
        request = requests[role]
        sources = {row["evidence_id"]: row for row in request["evidence"]}
        for field, upstream in dependencies.get(role, {}).items():
            report = responses[upstream]
            request["input"][field] = report
            sources.update({row["evidence_id"]: row for row in requests[upstream]["evidence"]})
            roots = sorted({
                root for ident in report["consumed_evidence_ids"]
                for root in sources[ident]["root_evidence_ids"]
            })
            sources[report["report_id"]] = {
                "evidence_id": report["report_id"], "kind": "agent_report",
                "source_ref": "report:" + report["report_id"], "available_at_s": 300,
                "content_sha256": content_hash(report), "root_evidence_ids": roots,
                "provenance": "derived_agent_output",
            }
        request["evidence"] = list(sources.values())
        validate_response(request, responses[role], checks)


def test_sequence_and_summary_can_share_the_same_original_observation_roots(
    checks: dict[str, jsonschema.Draft202012Validator],
) -> None:
    """Different feature representations retain shared underlying evidence identity.

    Independent: yes, because a separate empty-sequence boundary is constructed explicitly.
    """
    request, _ = messages("predictive_health")
    sequence = {"lookback_s": 300.0, "channels": []}
    request["input"]["observations"] = {
        "representation": "sequence_v1", "sequence": sequence,
        "evidence_ids": ["features-sequence"],
    }
    request["evidence"].append({
        "evidence_id": "features-sequence", "kind": "observation_representation",
        "source_ref": "features:sequence-example", "available_at_s": 300,
        "content_sha256": content_hash(sequence), "root_evidence_ids": ["source-observations"],
        "provenance": "derived_observation",
    })
    validate_request(request, checks)
    assert request["evidence"][-1]["root_evidence_ids"] == ["source-observations"]
