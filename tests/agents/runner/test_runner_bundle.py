"""Checks of the bundle rules that the message validators do not enforce."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from _runner_cases import run
from verum.agents.common import attached_report_ids, stable_hash
from verum.agents.runner import Bundle, BundleError, verify_bundle
from verum.agents.runner.bundle import check_exchange

CHANGES: dict[str, Any] = {
    "case_id": "other-case", "analysis_id": "AN-C7-r9", "revision": 4, "as_of_s": 299.0,
    "reference_snapshot_sha256": "cd" * 32,
}


def _bundle() -> Bundle:
    return run()


@pytest.mark.parametrize("name", sorted(CHANGES))
def test_an_upstream_report_from_another_snapshot_is_rejected(name: str) -> None:
    """A report that differs in case, analysis, revision, cutoff or reference is refused.

    Independent: yes, because each rejection comes from one literal change of the context.
    """
    bundle = _bundle()
    report = bundle.requests["anomaly_detection"]["input"]["forecast_report"]
    report["context"][name] = CHANGES[name]
    with pytest.raises(BundleError, match=f"{name} differs"):
        verify_bundle(bundle)


def test_a_fixture_mode_report_inside_a_runtime_request_is_rejected() -> None:
    """A report labelled as a fixture cannot sit inside a runtime request.

    Independent: yes, because the label is changed by the test.
    """
    bundle = _bundle()
    report = bundle.requests["anomaly_detection"]["input"]["forecast_report"]
    report["context"]["execution_mode"] = "contract_fixture"
    with pytest.raises(BundleError, match="fixture-mode report inside a runtime request"):
        verify_bundle(bundle)


def test_a_request_from_another_snapshot_is_rejected() -> None:
    """A request whose context differs from the analysis is refused.

    Independent: yes, because the context is changed by the test.
    """
    bundle = _bundle()
    bundle.requests["topology_dependency"]["context"]["as_of_s"] = 1.0
    with pytest.raises(BundleError, match="as_of_s differs"):
        verify_bundle(bundle)


def test_a_response_that_ignores_an_attached_report_is_rejected() -> None:
    """Every attached upstream report must appear in the consumed evidence.

    Independent: yes, because the response is edited by the test.
    """
    bundle = _bundle()
    request = bundle.requests["diagnostic_reasoning"]
    response = copy.deepcopy(bundle.reports["diagnostic_reasoning"])
    assert response is not None and len(attached_report_ids(request)) == 5
    check_exchange(request, response)
    response["consumed_evidence_ids"] = response["consumed_evidence_ids"][:3]
    with pytest.raises(BundleError, match="ignores attached upstream report"):
        check_exchange(request, response)


def test_a_report_identifier_that_collides_with_evidence_is_rejected() -> None:
    """A response whose identifier already names an evidence row is refused.

    Independent: yes, because the collision is built by the test.
    """
    bundle = _bundle()
    request = copy.deepcopy(bundle.requests["predictive_health"])
    response = bundle.reports["predictive_health"]
    assert response is not None
    request["evidence"][0]["evidence_id"] = response["report_id"]
    with pytest.raises(BundleError, match="collides"):
        check_exchange(request, response)
    bundle.reports["topology_dependency"] = copy.deepcopy(response)
    with pytest.raises(BundleError, match="share one identifier"):
        verify_bundle(bundle)


def test_a_changed_report_no_longer_matches_its_registered_hash() -> None:
    """A report edited after registration fails against its evidence row.

    Independent: yes, because the registered hash is recomputed.
    """
    bundle = _bundle()
    report = bundle.reports["inspection_planning"]
    assert report is not None
    report["limitations"].append("edited later")
    assert stable_hash(report) != bundle.registry.row(report["report_id"])["content_sha256"]
    with pytest.raises(BundleError):
        verify_bundle(bundle)


def test_a_runtime_analysis_identifier_must_follow_the_case_and_revision() -> None:
    """An analysis identifier that does not follow the rule is refused in runtime.

    Independent: yes, because the identifier is changed by the test.
    """
    bundle = _bundle()
    bundle.context["analysis_id"] = "AN-C7-r7"
    with pytest.raises(BundleError, match="does not follow"):
        verify_bundle(bundle)


def test_the_verified_bundle_carries_context_responses_and_evidence() -> None:
    """The verified bundle holds copies of the context, responses and evidence rows.

    Independent: yes, because the contents are compared with the bundle.
    """
    bundle = _bundle()
    verified = verify_bundle(bundle)
    assert verified.context == bundle.context and verified.issues == ()
    assert {r["evidence_id"] for r in verified.evidence} >= {
        r["report_id"] for r in verified.responses.values()
    }
    verified.responses["predictive_health"]["limitations"].append("x")
    assert "x" not in (bundle.reports["predictive_health"] or {})["limitations"]
