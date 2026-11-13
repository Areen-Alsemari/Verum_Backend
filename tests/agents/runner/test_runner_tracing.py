"""Checks of the optional tracing of the runner: off by default, summaries only, never fatal.

No test here opens a network connection except the one that needs the real langsmith package,
which points it at a closed local port and is skipped when the package is not installed.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
import types
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from _runner_cases import placeholders, run, snapshot
from verum.agents.common import ROLES, StubAgent
from verum.agents.runner import Bundle, BundleError, verify_bundle
from verum.agents.runner import tracing as tr
from verum.agents.runner.wiring import workflow_stages
from verum.contracts.agent_interfaces import FORBIDDEN, contract_directory
from verum.faults import spec as fault_spec

ON = {tr.ENV_SWITCH: "true", tr.ENV_KEY: "test-value"}
FAULT_WORDS = (
    {fault_spec.LEAK, fault_spec.RESTRICTION, fault_spec.PUMP, fault_spec.SENSOR,
     fault_spec.MISROUTING, *fault_spec.RESTRICTION_MODES}
    | {v for variants in fault_spec.VARIANTS.values() for v in variants}
    | {"ground_truth", "injected", "label", "fault_type", "truth"}
)  # fmt: skip


class Recorder:
    """A sink that keeps what it is given, standing in for the LangSmith client."""

    def __init__(self, fail_on: Sequence[str] = ()) -> None:
        self.fail_on = tuple(fail_on)
        self.spans: list[dict[str, Any]] = []

    def start(
        self, name: str, inputs: Mapping[str, Any], tags: Sequence[str],
        metadata: Mapping[str, Any], parent: Any | None,
    ) -> Any:
        if "start" in self.fail_on or ("child_start" in self.fail_on and parent is not None):
            raise ConnectionError("unreachable")
        span = {"id": len(self.spans), "name": name, "inputs": copy.deepcopy(dict(inputs)),
                "tags": list(tags), "metadata": copy.deepcopy(dict(metadata)), "parent": parent,
                "outputs": None, "error": "open"}
        self.spans.append(span)
        return span["id"]

    def end(self, handle: Any, outputs: Mapping[str, Any], error: str | None) -> None:
        if "end" in self.fail_on:
            raise ConnectionError("unreachable")
        self.spans[handle].update(outputs=copy.deepcopy(dict(outputs)), error=error)

    def names(self) -> list[str]:
        return [s["name"] for s in self.spans]


def traced(recorder: Recorder, **kwargs: Any) -> Bundle:
    return run(tracer=tr.Tracer(recorder), **kwargs)


def bytes_of(bundle: Bundle) -> str:
    """Every request and report of a bundle as canonical text, to compare byte for byte."""
    both = {"requests": bundle.requests, "reports": bundle.reports, "issues": bundle.issues,
            "notes": bundle.notes, "evidence": bundle.registry.rows()}  # fmt: skip
    return json.dumps(both, sort_keys=True, default=str)


def strings_of(value: Any) -> list[str]:
    """All keys and string values of a nested structure."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [str(k), *strings_of(v)]]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in strings_of(v)]
    return [value] if isinstance(value, str) else []


def leaks(span: dict[str, Any]) -> list[str]:
    """Forbidden keys or fault words found in what a span carries."""
    payload = [span["inputs"], span["outputs"], span["tags"]]
    metadata = {k: v for k, v in span["metadata"].items() if k != "episode_id"}
    texts = [s for part in (*payload, metadata) for s in strings_of(part)]
    found = [t for t in texts if t in FORBIDDEN]
    found += [t for t in texts if any(w.lower() in t.lower() for w in FAULT_WORDS)]
    return found


def test_tracing_is_off_unless_the_switch_and_a_key_are_both_present(
    fake_langsmith: type[FakeRunTree],
) -> None:
    """Without the switch or the key the tracer is inert; with both it is live.

    Independent: yes, because the environment is given explicitly, and the package is a fake that
    could be used, so only the environment decides.
    """
    assert tr.tracer_from_environment(ON).enabled
    assert not tr.tracer_from_environment({}).enabled
    assert not tr.tracer_from_environment({tr.ENV_SWITCH: "true"}).enabled
    assert not tr.tracer_from_environment({tr.ENV_KEY: "test-value"}).enabled
    assert not tr.tracer_from_environment({**ON, tr.ENV_SWITCH: "false"}).enabled
    assert not tr.tracer_from_environment({**ON, tr.ENV_KEY: "  "}).enabled


def test_tracing_without_langsmith_installed_falls_back_to_an_inert_tracer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled by the environment but with no package, the tracer is inert and nothing raises.

    Independent: yes, because the import is made to fail on purpose.
    """
    real = importlib.import_module

    def refuse(name: str, *args: Any) -> Any:
        if name.startswith("langsmith"):
            raise ModuleNotFoundError(name)
        return real(name, *args)

    monkeypatch.setattr(importlib, "import_module", refuse)
    assert not tr.tracer_from_environment(ON).enabled


def counting(calls: list[str], name: str) -> Any:
    """A stand-in for a summary builder that records that it was called."""

    def stand_in(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        return {}

    return stand_in


def test_with_tracing_off_nothing_is_imported_built_or_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run with the switch off imports no tracing package, builds no summary, holds no trace.

    Independent: yes, because the calls are counted by replacing the summary builders.
    """
    monkeypatch.delenv(tr.ENV_SWITCH, raising=False)
    monkeypatch.delenv(tr.ENV_KEY, raising=False)
    calls: list[str] = []
    imported: list[str] = []
    real = importlib.import_module

    def spy_import(name: str, *args: Any) -> Any:
        imported.append(name)
        return real(name, *args)

    monkeypatch.setattr(importlib, "import_module", spy_import)
    for builder in ("request_summary", "role_outcome", "bundle_summary", "verify_inputs",
                    "verify_outputs", "window_metadata"):  # fmt: skip
        monkeypatch.setattr(tr, builder, counting(calls, builder))
    bundle = run()
    verify_bundle(bundle)
    assert calls == [] and imported == []
    assert bundle.trace is tr.NO_TRACE and not bundle.trace.tracer.enabled


def test_the_requests_and_reports_are_byte_identical_with_and_without_tracing() -> None:
    """The same snapshot gives the same bytes off, with a recording sink, and with a failing one.

    Independent: yes, because the comparison is of the serialised messages themselves.
    """
    off = bytes_of(run())
    assert off == bytes_of(traced(Recorder()))
    assert off == bytes_of(traced(Recorder(fail_on=["start"])))
    assert off == bytes_of(traced(Recorder(fail_on=["end"])))


def test_a_window_is_one_parent_with_a_child_per_agent_and_one_for_the_verification() -> None:
    """The names, the parent links and the order follow the run.

    Independent: yes, because the roles and their order are read from the manifest.
    """
    sink = Recorder()
    bundle = traced(sink)
    verify_bundle(bundle)
    order = [role for stage in workflow_stages() for role in stage]
    assert sink.names() == [tr.RUN_NAME, *[f"verum.agent.{r}" for r in order], tr.VERIFY_NAME]
    root = sink.spans[0]
    assert root["parent"] is None
    assert all(s["parent"] == root["id"] for s in sink.spans[1:])
    assert all(s["error"] is None for s in sink.spans)
    assert set(order) == set(ROLES)


def test_each_agent_child_carries_its_status_and_the_parent_the_roles_that_answered() -> None:
    """The status of every child is the status of the report; the parent lists the roles.

    Independent: yes, because the expected values are read from the bundle's own reports.
    """
    sink = Recorder()
    bundle = traced(sink)
    for span in sink.spans[1:]:
        role = span["name"].removeprefix("verum.agent.")
        report = bundle.reports[role]
        assert report is not None
        assert span["outputs"]["status"] == report["status"] and span["outputs"]["placeholder"]
        assert span["outputs"]["report"]["report_id"] == report["report_id"]
    root = sink.spans[0]["outputs"]
    assert root["roles_answered"] == sorted(ROLES) and root["roles_failed"] == []
    decision = bundle.reports[tr.DECISION_ROLE]
    assert decision is not None
    named = next(s for s in sink.spans if s["name"].endswith(tr.DECISION_ROLE))
    assert named["outputs"]["report"]["decision_state"] == decision["result"]["decision_state"]
    assert named["outputs"]["report"]["fixed_flags"]["automatic_action_authorized"] is False


def test_a_failed_agent_gives_a_failed_child_with_the_runner_issue_code() -> None:
    """A role that raises appears as a failed child and an issue code, and the run goes on.

    Independent: yes, because the failure is injected and the code is the runner's own.
    """

    class Broken:
        def run(self, request: dict[str, Any]) -> Any:
            raise RuntimeError("model file missing")

    sink = Recorder()
    agents: dict[str, Any] = {**placeholders(), "anomaly_detection": Broken()}
    traced(sink, agents=agents)
    child = next(s for s in sink.spans if s["name"] == "verum.agent.anomaly_detection")
    assert child["outputs"]["outcome"] == "failed"
    assert child["outputs"]["issue_code"] == "AGENT_ERROR" and child["outputs"]["status"] is None
    assert "anomaly_detection" in sink.spans[0]["outputs"]["roles_failed"]
    assert "model file missing" not in json.dumps(sink.spans)


def test_the_tags_and_metadata_name_the_window_the_contract_and_the_commit() -> None:
    """Every span carries the tags and the metadata of the window, and a synthetic tag.

    Independent: yes, because the expected values come from the snapshot and the manifest.
    """
    sink = Recorder()
    traced(sink, episode_id="EP-9", window_index=4)
    manifest = json.loads(
        (contract_directory() / "manifest.json").read_text(encoding="utf-8")
    )
    for span in sink.spans:
        version = manifest["interface_version"]
        assert "synthetic" in span["tags"] and f"contract:{version}" in span["tags"]
        meta = span["metadata"]
        assert meta["episode_id"] == "EP-9" and meta["window_index"] == 4
        assert meta["case_id"] == "C7" and meta["revision"] == 0 and meta["as_of_s"] == 300.0
        assert meta["contract_version"] == manifest["interface_version"]
        assert isinstance(meta["git_commit"], str) and meta["git_commit"]
    assert "episode_id" in sink.spans[0]["metadata"]


def test_the_window_index_is_derived_only_from_a_whole_number_of_steps() -> None:
    """A cutoff on the step grid gives its index; any other cutoff gives none, not a guess.

    Independent: yes, because the cases are chosen by hand.
    """
    assert tr.window_index_of(0.0) == 0 and tr.window_index_of(900.0) == 3
    assert tr.window_index_of(450.0) is None
    sink = Recorder()
    traced(sink, snapshot=snapshot(as_of_s=900.0))
    assert sink.spans[0]["metadata"]["window_index"] == 3
    other = Recorder()
    traced(other, snapshot=snapshot(as_of_s=450.0))
    assert other.spans[0]["metadata"]["window_index"] is None
    assert other.spans[0]["metadata"]["episode_id"] == "C7"


def test_no_payload_holds_a_forbidden_key_a_fault_word_or_a_label() -> None:
    """No span carries a hidden-supervision key or a fault name, even when an agent text does.

    Independent: yes, because the words come from the fault specification and the contract list,
    and the agent texts that hold them are planted.
    """

    class Wordy(StubAgent):
        def run(self, request: dict[str, Any]) -> dict[str, Any]:
            response = super().run(request)
            response["limitations"].append("PIPE_LEAK at E001; SENSOR_DRIFT; injected fault")
            if isinstance(response["result"].get("summary"), str):
                response["result"]["summary"] += " VALVE_RESTRICTION"
            return response

    sink = Recorder()
    agents = {role: Wordy(role) for role in ROLES}
    bundle = traced(sink, agents=agents)
    verify_bundle(bundle)
    assert any("PIPE_LEAK" in json.dumps(r) for r in bundle.reports.values())
    assert sink.spans and [leaks(s) for s in sink.spans] == [[] for _ in sink.spans]
    assert leaks({"inputs": {"ground_truth": 1}, "outputs": {}, "tags": [], "metadata": {}})
    assert leaks({"inputs": {}, "outputs": {"x": "SENSOR_DRIFT"}, "tags": [], "metadata": {}})


def test_no_request_or_report_body_is_sent() -> None:
    """The payloads are small summaries: none holds the text of a request or of a report.

    Independent: yes, because the check is on the serialised payload against the messages.
    """
    sink = Recorder()
    bundle = traced(sink)
    sent = json.dumps([[s["inputs"], s["outputs"]] for s in sink.spans])
    for role, request in bundle.requests.items():
        assert json.dumps(request["input"], sort_keys=True)[:200] not in sent
        report = bundle.reports[role]
        assert report is not None and report["limitations"][0] not in sent
    assert len(sent) < 20000


@pytest.mark.parametrize(
    "fail_on", [["start"], ["child_start"], ["end"], ["start", "end"], ["child_start", "end"]]
)
def test_a_failing_sink_never_breaks_the_run_or_the_verification(fail_on: list[str]) -> None:
    """A sink that raises on every call is swallowed; the run, the bundle and verification hold.

    Independent: yes, because the sink raises ConnectionError on every call it is given.
    """
    bundle = traced(Recorder(fail_on=fail_on))
    assert bundle.issues == [] and set(verify_bundle(bundle).responses) == set(ROLES)


def test_a_summary_that_cannot_be_built_is_dropped_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A builder that raises costs the span its payload, not the analysis its result.

    Independent: yes, because the builders are replaced by ones that raise.
    """

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise KeyError("shape changed")

    sink = Recorder()
    for builder in ("request_summary", "role_outcome", "bundle_summary"):
        monkeypatch.setattr(tr, builder, boom)
    assert bytes_of(traced(sink)) == bytes_of(run())
    assert sink.names()[0] == tr.RUN_NAME and len(sink.spans) == 9


def test_metadata_that_cannot_be_built_leaves_the_run_untraced_not_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the metadata of the window fails, no span is opened and the analysis is unchanged.

    Independent: yes, because the builder is replaced by one that raises.
    """

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("git unavailable")

    monkeypatch.setattr(tr, "window_metadata", boom)
    sink = Recorder()
    assert bytes_of(traced(sink)) == bytes_of(run()) and sink.spans == []


def test_an_error_inside_a_traced_block_is_recorded_by_type_and_still_raised() -> None:
    """A verification that fails ends its span with the error type and raises as before.

    Independent: yes, because the failing input is a bundle with a request removed.
    """
    sink = Recorder()
    bundle = traced(sink)
    del bundle.requests["predictive_health"]
    with pytest.raises(BundleError):
        verify_bundle(bundle)
    last = sink.spans[-1]
    assert last["name"] == tr.VERIFY_NAME and last["error"] == "BundleError"
    assert "predictive_health" not in (last["error"] or "")


def test_a_run_that_is_rejected_closes_its_parent_with_the_error_type() -> None:
    """A run refused for placeholders raises as before and its parent span records the type.

    Independent: yes, because the refusal is the runner's existing rule.
    """
    sink = Recorder()
    with pytest.raises(BundleError):
        traced(sink, allow_placeholders=False)
    assert sink.spans[0]["name"] == tr.RUN_NAME and sink.spans[0]["error"] == "BundleError"


def test_a_copy_of_a_bundle_shares_its_live_trace() -> None:
    """Copying a bundle never tries to copy the client behind its trace.

    Independent: yes, because identity is checked.
    """
    bundle = traced(Recorder())
    assert copy.deepcopy(bundle).trace is bundle.trace
    assert bundle == copy.copy(bundle) and "trace" not in repr(bundle)


class FakeRunTree:
    """The part of langsmith's RunTree that the sink uses, recording and optionally failing."""

    posted: list[FakeRunTree] = []
    unreachable = False

    def __init__(self, **fields: Any) -> None:
        self.fields = fields
        self.parent: FakeRunTree | None = None
        self.ended: dict[str, Any] | None = None

    def create_child(self, **fields: Any) -> FakeRunTree:
        child = FakeRunTree(**fields)
        child.parent = self
        return child

    def post(self) -> None:
        if FakeRunTree.unreachable:
            raise ConnectionError("endpoint unreachable")
        FakeRunTree.posted.append(self)

    def end(self, *, outputs: dict[str, Any], error: str | None) -> None:
        self.ended = {"outputs": outputs, "error": error}

    def patch(self) -> None:
        if FakeRunTree.unreachable:
            raise ConnectionError("endpoint unreachable")


@pytest.fixture
def fake_langsmith(monkeypatch: pytest.MonkeyPatch) -> type[FakeRunTree]:
    """Make `langsmith.run_trees` resolve to a module holding the fake run tree."""
    FakeRunTree.posted, FakeRunTree.unreachable = [], False
    module = types.ModuleType("langsmith.run_trees")
    module.RunTree = FakeRunTree  # type: ignore[attr-defined]
    real = importlib.import_module
    monkeypatch.setattr(
        importlib, "import_module",
        lambda name, *a: module if name == "langsmith.run_trees" else real(name, *a),
    )
    for key, value in ON.items():
        monkeypatch.setenv(key, value)
    return FakeRunTree


def test_the_environment_switch_gives_the_langsmith_sink_and_posts_the_spans(
    fake_langsmith: type[FakeRunTree],
) -> None:
    """With the switch and a key, a run posts a parent and a child per role through the sink.

    Independent: yes, because the run tree is a recording fake and the names are the contract's.
    """
    bundle = run()
    verify_bundle(bundle)
    names = [r.fields["name"] for r in fake_langsmith.posted]
    assert names[0] == tr.RUN_NAME and names[-1] == tr.VERIFY_NAME and len(names) == 10
    root = fake_langsmith.posted[0]
    assert all(r.parent is root for r in fake_langsmith.posted[1:])
    assert all(r.ended is not None and r.ended["error"] is None for r in fake_langsmith.posted)
    assert root.fields["tags"][:2] == ["synthetic", "verum"]
    assert bytes_of(bundle) == bytes_of(traced(Recorder()))


def test_an_unreachable_endpoint_does_not_break_a_run(
    fake_langsmith: type[FakeRunTree],
) -> None:
    """If every post and patch raises a connection error the run and its checks are unchanged.

    Independent: yes, because the failure is injected at the transport and the output compared.
    """
    expected = bytes_of(traced(Recorder()))
    fake_langsmith.unreachable = True
    bundle = run()
    assert bytes_of(bundle) == expected and fake_langsmith.posted == []
    assert set(verify_bundle(bundle).responses) == set(ROLES)


def test_the_real_package_with_a_closed_local_port_does_not_break_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the real langsmith pointed at a closed port, the run completes with the same bytes.

    Independent: yes, because the endpoint is a port nothing listens on and the output compared.
    """
    pytest.importorskip("langsmith")
    expected = bytes_of(run())
    for key, value in {**ON, "LANGSMITH_ENDPOINT": "http://127.0.0.1:9"}.items():
        monkeypatch.setenv(key, value)
    utils = importlib.import_module("langsmith.utils")
    utils.get_env_var.cache_clear()
    bundle = run()
    verify_bundle(bundle)
    assert bytes_of(bundle) == expected
    assert "langsmith" in sys.modules
