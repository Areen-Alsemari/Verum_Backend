"""Optional tracing of the runner to LangSmith, as summaries of synthetic analyses only.

Inputs: the snapshot and bundle of a run, and the environment. Outputs: one parent trace per
analysed window with a child per agent call and one for the verification; they hold identifiers,
statuses, decisions, fixed flags, counts and digests, never a message body, label or fault name.
Assumptions: off unless LANGSMITH_TRACING is "true" and LANGSMITH_API_KEY is set; off means a
pass-through that imports, reads, builds and sends nothing. Every failure of the tracing side is
swallowed. The langsmith package is optional and is imported only by the sink that needs it.
Source: reports/langsmith_tracing_design.md.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Protocol

from verum.agents.common import stable_hash
from verum.agents.runner.snapshot import Snapshot
from verum.contracts.agent_interfaces import contract_directory

ENV_SWITCH = "LANGSMITH_TRACING"
ENV_KEY = "LANGSMITH_API_KEY"
WINDOW_STEP_S = 300.0  # the observation window of the sample, used only to derive a window index
RUN_NAME = "verum.run_analysis"
VERIFY_NAME = "verum.verify_bundle"
DECISION_ROLE = "evidence_verification_decision"
BASE_TAGS = ("synthetic", "verum")
SHA256 = re.compile(r"[0-9a-f]{64}")

log = logging.getLogger(__name__)


class Sink(Protocol):
    """Where spans go. The only implementation that needs a network is the LangSmith one."""

    def start(
        self, name: str, inputs: Mapping[str, Any], tags: Sequence[str],
        metadata: Mapping[str, Any], parent: Any | None,
    ) -> Any: ...

    def end(self, handle: Any, outputs: Mapping[str, Any], error: str | None) -> None: ...


class LangSmithSink:
    """Posts spans as LangSmith run trees. The package is imported here and nowhere else."""

    def __init__(self, client: Any | None = None) -> None:
        self._run_tree: Any = importlib.import_module("langsmith.run_trees").RunTree
        self._client = client

    def start(
        self, name: str, inputs: Mapping[str, Any], tags: Sequence[str],
        metadata: Mapping[str, Any], parent: Any | None,
    ) -> Any:
        fields: dict[str, Any] = {
            "name": name, "run_type": "chain", "inputs": dict(inputs), "tags": list(tags),
            "extra": {"metadata": dict(metadata)},
        }
        if parent is not None:
            run = parent.create_child(**fields)
        else:
            run = self._run_tree(**fields, **({} if self._client is None else {
                "client": self._client}))
        run.post()
        return run

    def end(self, handle: Any, outputs: Mapping[str, Any], error: str | None) -> None:
        handle.end(outputs=dict(outputs), error=error)
        handle.patch()


class Tracer:
    """Guards a sink: every call is swallowed on failure, and without a sink nothing happens."""

    def __init__(self, sink: Sink | None) -> None:
        self._sink = sink

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def start(
        self, name: str, inputs: Mapping[str, Any], tags: Sequence[str],
        metadata: Mapping[str, Any], parent: Any | None = None,
    ) -> Any | None:
        """Open a span and return its handle, or None when tracing is off or has failed."""
        if self._sink is None:
            return None
        try:
            return self._sink.start(name, inputs, tags, metadata, parent)
        except Exception as error:  # tracing must never reach the analysis
            log.debug("tracing start failed: %s", type(error).__name__)
            return None

    def end(self, handle: Any | None, outputs: Mapping[str, Any], error: str | None) -> None:
        """Close a span; a missing handle or a failing sink is ignored."""
        if self._sink is None or handle is None:
            return
        try:
            self._sink.end(handle, outputs, error)
        except Exception as failure:
            log.debug("tracing end failed: %s", type(failure).__name__)


def tracer_from_environment(env: Mapping[str, str] | None = None) -> Tracer:
    """A LangSmith tracer when the environment enables it, otherwise one that does nothing."""
    values = os.environ if env is None else env
    if values.get(ENV_SWITCH, "").strip().lower() != "true" or not values.get(ENV_KEY, "").strip():
        return Tracer(None)
    try:
        return Tracer(LangSmithSink())
    except Exception as error:  # langsmith not installed, or unusable
        log.debug("langsmith unavailable: %s", type(error).__name__)
        return Tracer(None)


@dataclass
class Box:
    """What the body of a traced step reports back: the outputs of its span."""

    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class WindowTrace:
    """The trace of one window: its tracer, parent span and the tags and metadata of the run."""

    tracer: Tracer
    parent: Any | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __deepcopy__(self, memo: dict[int, Any]) -> WindowTrace:
        return self  # a live trace holds a client and threads; a copy of a bundle shares it

    def begin(self, name: str, inputs: Callable[[], Mapping[str, Any]]) -> Any | None:
        """Open a child span; the inputs are built only when tracing is on."""
        if not self.tracer.enabled or self.parent is None:
            return None
        return self.tracer.start(name, _safe(inputs), self.tags, self.metadata, self.parent)

    def finish(
        self, handle: Any | None, outputs: Callable[[], Mapping[str, Any]], error: str | None = None
    ) -> None:
        if handle is not None:
            self.tracer.end(handle, _safe(outputs), error)

    @contextmanager
    def step(self, name: str, inputs: Callable[[], Mapping[str, Any]]) -> Iterator[Box]:
        """A child span around a block; an exception ends it with the exception type and goes on."""
        box = Box()
        handle = self.begin(name, inputs)
        try:
            yield box
        except BaseException as error:
            self.finish(handle, lambda: box.outputs, type(error).__name__)
            raise
        self.finish(handle, lambda: box.outputs)

    def role_started(self, role: str, request: Mapping[str, Any]) -> Any | None:
        """Open the child of one agent call."""
        return self.begin(f"verum.agent.{role}", lambda: request_summary(role, request))

    def role_finished(
        self, handle: Any | None, role: str, response: Mapping[str, Any] | None,
        problem: Mapping[str, str] | None, placeholder: bool,
    ) -> None:
        """Close the child of one agent call with its status."""
        self.finish(handle, lambda: role_outcome(role, response, problem, placeholder))

    def close(self, bundle: Any | None, error: BaseException | None) -> None:
        """Close the parent span with the summary of the bundle, or with the error type."""
        outputs = (lambda: bundle_summary(bundle)) if bundle is not None else dict
        self.finish(self.parent, outputs, None if error is None else type(error).__name__)


NO_TRACE = WindowTrace(Tracer(None))


def trace_of(bundle: Any) -> WindowTrace:
    """The trace a bundle belongs to, or the inert one."""
    held = getattr(bundle, "trace", None)
    return held if isinstance(held, WindowTrace) else NO_TRACE


def _safe(build: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
    try:
        return build()
    except Exception as error:  # a summary that cannot be built is dropped, not raised
        log.debug("tracing summary failed: %s", type(error).__name__)
        return {}


def request_summary(role: str, request: Mapping[str, Any]) -> dict[str, Any]:
    """Identifiers, a count and a digest of a request; the request body is not included."""
    return {
        "role": role, "request_id": request["request_id"],
        "evidence_rows": len(request["evidence"]), "request_sha256": stable_hash(request),
    }


def report_summary(role: str, report: Mapping[str, Any]) -> dict[str, Any]:
    """Status, fixed flags, counts and a digest of a report; no text of the report."""
    result = report.get("result")
    flags = {} if not isinstance(result, dict) else {
        key: value for key, value in result.items() if isinstance(value, bool)
    }
    summary: dict[str, Any] = {
        "report_id": report["report_id"], "status": report["status"],
        "advisory_only": report["advisory_only"], "fixed_flags": flags,
        "issue_count": len(report["issues"]),
        "consumed_evidence_count": len(report["consumed_evidence_ids"]),
        "report_sha256": stable_hash(report),
    }
    if role == DECISION_ROLE and isinstance(result, dict):
        summary["decision_state"] = result.get("decision_state")
    return summary


def role_outcome(
    role: str, response: Mapping[str, Any] | None, problem: Mapping[str, str] | None,
    placeholder: bool,
) -> dict[str, Any]:
    """The outputs of an agent call: answered or failed, the status, and the runner issue code."""
    out: dict[str, Any] = {
        "outcome": "answered" if response is not None else "failed", "placeholder": placeholder,
        "status": None, "issue_code": None if problem is None else problem["code"],
    }
    if response is not None:
        out.update(status=response["status"], report=report_summary(role, response))
    return out


def bundle_summary(bundle: Any) -> dict[str, Any]:
    """Which roles answered, the runner's issue and note codes, and the report identifiers."""
    reports = bundle.reports
    return {
        "roles_answered": sorted(r for r, v in reports.items() if v is not None),
        "roles_failed": sorted(r for r, v in reports.items() if v is None),
        "issue_codes": sorted({i["code"] for i in bundle.issues}),
        "note_codes": sorted({n["code"] for n in bundle.notes}),
        "report_ids": {r: v["report_id"] for r, v in sorted(reports.items()) if v is not None},
    }


def verify_inputs(bundle: Any, has_previous: bool) -> dict[str, Any]:
    """The inputs of the verification span: the roles checked and whether a revision is checked."""
    return {"roles_requested": sorted(bundle.requests), "has_previous": has_previous}


def verify_outputs(verified: Any) -> dict[str, Any]:
    """The outputs of the verification span."""
    return {
        "verified": True, "roles_verified": sorted(verified.responses),
        "issue_count": len(verified.issues),
    }


@cache
def _contract_version() -> str:
    manifest = json.loads((contract_directory() / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest["interface_version"])


@cache
def _git_commit() -> str:
    """The commit of the checkout, or "unknown"; asked of git once, and only when tracing is on."""
    try:
        done = subprocess.run(
            ["git", "-C", str(contract_directory()), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() or "unknown"


def window_index_of(as_of_s: float) -> int | None:
    """The index of the window when the cutoff is a whole number of window steps."""
    index = as_of_s / WINDOW_STEP_S
    return int(index) if index == int(index) else None


def window_metadata(
    snapshot: Snapshot, mode: str, episode_id: str | None, window_index: int | None,
    parameters_sha256: str | None = None,
) -> dict[str, Any]:
    """Metadata of a window's trace; the git commit and digest are read once per process."""
    data: dict[str, Any] = {
        "episode_id": episode_id or snapshot.case_id, "case_id": snapshot.case_id,
        "window_index": window_index if window_index is not None
        else window_index_of(snapshot.as_of_s),
        "as_of_s": snapshot.as_of_s, "revision": snapshot.revision, "execution_mode": mode,
        "contract_version": _contract_version(), "git_commit": _git_commit(),
    }
    if parameters_sha256 is not None and SHA256.fullmatch(parameters_sha256):
        data["inspection_parameters_sha256"] = parameters_sha256  # a malformed value is dropped
    return data


def window_trace(
    tracer: Tracer, snapshot: Snapshot, mode: str, episode_id: str | None = None,
    window_index: int | None = None, parameters_sha256: str | None = None,
) -> WindowTrace:
    """Open the parent span of a window; with tracing off this returns the inert trace."""
    if not tracer.enabled:
        return NO_TRACE
    try:
        metadata = window_metadata(snapshot, mode, episode_id, window_index, parameters_sha256)
        tags = (*BASE_TAGS, f"contract:{metadata['contract_version']}")
        inputs = {"case_id": snapshot.case_id, "revision": snapshot.revision,
                  "as_of_s": snapshot.as_of_s, "execution_mode": mode}
        parent = tracer.start(RUN_NAME, inputs, tags, metadata)
    except Exception as error:
        log.debug("tracing setup failed: %s", type(error).__name__)
        return NO_TRACE
    return WindowTrace(tracer, parent, tags, metadata)
