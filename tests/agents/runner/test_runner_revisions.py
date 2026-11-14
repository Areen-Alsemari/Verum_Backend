"""Checks that a new inspection result starts a new analysis and reuses nothing."""

from __future__ import annotations

import copy
import json

import pytest

from _runner_cases import inspection_request, inspection_result, run, snapshot, summary
from verum.agents.runner import BundleError, Snapshot, next_revision, run_analysis, verify_bundle
from verum.agents.runner.bundle import check_revision


def _next() -> tuple[Snapshot, Snapshot]:
    s0 = snapshot()
    s1 = next_revision(
        s0, as_of_s=500.0, summary=copy.deepcopy(summary()),
        inspection_results=(inspection_result(),), inspection_requests=(inspection_request(),),
    )
    return s0, s1


def test_a_new_result_starts_a_new_revision_with_a_new_analysis() -> None:
    """The next run has the next revision, a new analysis identifier and fresh report identifiers.

    Independent: yes, because the identifiers are literal formats.
    """
    s0, s1 = _next()
    first = run(snapshot=s0)
    second = run(snapshot=s1, previous=verify_bundle(first))
    assert (first.context["revision"], first.context["analysis_id"]) == (0, "AN-C7-r0")
    assert (second.context["revision"], second.context["analysis_id"]) == (1, "AN-C7-r1")
    old = {r["report_id"] for r in first.reports.values() if r}
    new = {r["report_id"] for r in second.reports.values() if r}
    assert old.isdisjoint(new) and len(new) == 8


def test_everything_is_rerun_and_no_old_report_is_attached() -> None:
    """All eight roles run again, and no earlier report appears in any later request.

    Independent: yes, because the serialised requests are searched for old identifiers.
    """
    s0, s1 = _next()
    first, second = run(snapshot=s0), run(snapshot=s1)
    text = json.dumps(second.requests)
    assert all(rid not in text for rid in (r["report_id"] for r in first.reports.values() if r))
    assert set(second.requests) == set(first.requests) and second.issues == []
    quality = second.requests["inspection_quality_documentation"]["input"]
    assert [r["result_id"] for r in quality["inspection_results"]] == ["RES-INSP-00001"]
    assert len(quality["result_evidence_ids"]) == 1


def test_a_later_revision_verifies_against_the_earlier_bundle() -> None:
    """The later bundle verifies against the earlier one, and the earlier one stays valid.

    Independent: yes, because the contract validators judge every message.
    """
    s0, s1 = _next()
    first = verify_bundle(run(snapshot=s0))
    second = run(snapshot=s1)
    verify_bundle(second, first)


@pytest.mark.parametrize("how", ["same_revision", "analysis_unchanged", "backwards"])
def test_a_bundle_that_is_not_a_new_revision_is_rejected(how: str) -> None:
    """The same revision, an unchanged analysis identifier and an earlier cutoff are refused.

    Independent: yes, because each rejection comes from one literal change.
    """
    s0, s1 = _next()
    previous = verify_bundle(run(snapshot=s0))
    if how == "same_revision":
        with pytest.raises(BundleError, match="revision does not increase"):
            run_analysis(s0, "runtime", previous=previous)
        return
    bundle = run(snapshot=s1)
    if how == "analysis_unchanged":
        bundle.context["analysis_id"] = previous.context["analysis_id"]
        with pytest.raises(BundleError, match="did not change"):
            check_revision(bundle, previous)
    else:
        previous.context["as_of_s"] = 900.0
        with pytest.raises(BundleError, match="backwards"):
            verify_bundle(bundle, previous)


def test_a_revision_needs_a_result_a_later_cutoff_and_new_observations() -> None:
    """A revision without a result, with an earlier cutoff or reused observations is refused.

    Independent: yes, because the refused inputs are literals.
    """
    s0 = snapshot()
    fresh = copy.deepcopy(summary())
    with pytest.raises(ValueError, match="new inspection result"):
        next_revision(s0, as_of_s=500.0, summary=fresh, inspection_results=())
    with pytest.raises(ValueError, match="backwards"):
        next_revision(s0, as_of_s=100.0, summary=fresh, inspection_results=(inspection_result(),))
    with pytest.raises(ValueError, match="own cutoff"):
        next_revision(
            s0, as_of_s=500.0, summary=s0.summary, inspection_results=(inspection_result(),)
        )
    with pytest.raises(ValueError, match="own cutoff"):
        next_revision(s0, as_of_s=300.0, summary=fresh, inspection_results=(inspection_result(),))


def test_results_accumulate_across_revisions() -> None:
    """A second revision keeps the first result and adds the new one.

    Independent: yes, because the identifiers are literals.
    """
    s0, s1 = _next()
    later = inspection_result() | {"result_id": "RES-INSP-00002", "performed_at_t_sim_s": 550.0}
    s2 = next_revision(
        s1, as_of_s=600.0, summary=copy.deepcopy(summary()), inspection_results=(later,)
    )
    assert [r["result_id"] for r in s2.inspection_results] == ["RES-INSP-00001", "RES-INSP-00002"]
    assert s2.revision == 2 and s0.revision == 0 and s1.revision == 1
    assert run(snapshot=s2).context["analysis_id"] == "AN-C7-r2"
