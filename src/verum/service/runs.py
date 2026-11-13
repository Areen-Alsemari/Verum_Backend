"""Runs: one thread and one event log per run, paced by a time-compression factor.

Inputs: a window source and the playback speed. Outputs: an ordered event log that any number of
stream readers follow from any point, the final report of each window, and the simulation truth
of each window when the run was created with reveal_truth.
Assumptions: a run owns all of its state, including the assessment log inside its source, so two
runs share nothing but the read-only data. Speed is the factor by which the 300 s window cadence
is compressed; it never changes a value. A failure ends the run with a done event, not a crash.
Source: the service API design in the task for the run service.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from verum.agents.inspection_quality_documentation import build_report
from verum.agents.runner.wiring import workflow_stages
from verum.service import events
from verum.service.sources import WindowData

MAX_SPEED = 1_000_000.0
MAX_KEPT_RUNS = 50


class Source(Protocol):
    mode: str
    split: str
    episode_id: str

    def windows(self) -> Any: ...


@dataclass
class Run:
    """The state of one run: its parameters, its events, and what was built from its windows."""

    run_id: str
    source: Source
    speed: float
    reveal_truth: bool
    events: list[dict[str, Any]] = field(default_factory=list)
    reports: dict[int, dict[str, Any] | str] = field(default_factory=dict)
    truth: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False
    status: str = "running"
    stop: threading.Event = field(default_factory=threading.Event)
    cond: threading.Condition = field(default_factory=threading.Condition)

    def header(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "mode": self.source.mode, "speed": self.speed}

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        with self.cond:
            event = {**events.envelope(self.header(), kind, len(self.events)), **payload}
            self.events.append(event)
            self.finished = kind == "done"
            self.cond.notify_all()

    def read(self, after: int, timeout: float) -> list[dict[str, Any]]:
        """Events with a sequence number above `after`, waiting up to `timeout` for the first."""
        with self.cond:
            if len(self.events) <= after + 1 and not self.finished:
                self.cond.wait(timeout)
            return self.events[after + 1 :]

    def info(self) -> dict[str, Any]:
        with self.cond:
            return {**self.header(), "episode_id": self.source.episode_id,
                    "split": self.source.split, "reveal_truth": self.reveal_truth,
                    "status": self.status, "events": len(self.events)}  # fmt: skip


def validate_speed(value: Any) -> float:
    """A positive finite number no larger than the maximum, otherwise a ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("speed must be a number")
    speed = float(value)
    if not math.isfinite(speed) or not 0 < speed <= MAX_SPEED:
        raise ValueError(f"speed must be above 0 and at most {MAX_SPEED:g}")
    return speed


def _roles() -> list[str]:
    return [role for stage in workflow_stages() for role in stage]


def _pace(run: Run, started: float, first_s: float, as_of_s: float) -> bool:
    """Wait until the window is due at the playback speed; False if the run was stopped."""
    due = started + (as_of_s - first_s) / run.speed
    return not run.stop.wait(max(0.0, due - time.monotonic()))


def _publish(run: Run, window: WindowData, roles: list[str]) -> None:
    index = window.position
    run.emit("sensor_reading", events.sensor_event(window.record, index))
    run.emit("window_result", events.result_event(window.record, index, roles))
    alert = events.alert_event(window.record, index)
    if alert is not None:
        run.emit("alert", alert)
    run.reports[index] = _report_of(window)
    if run.reveal_truth and window.truth is not None:
        with run.cond:
            run.truth.append({"window_index": index, "as_of_s": window.as_of_s, **window.truth})


def _report_of(window: WindowData) -> dict[str, Any] | str:
    try:
        return build_report(window.verified) if window.verified is not None else "no bundle"
    except Exception as error:  # a report that cannot be built is reported, not raised
        return f"report not built: {type(error).__name__}"


def execute(run: Run) -> None:
    """The body of a run thread: play every window, then end with a done event."""
    roles, started, first, count = _roles(), time.monotonic(), None, 0
    status, error = "completed", None
    try:
        for window in run.source.windows():
            first = window.as_of_s if first is None else first
            if not _pace(run, started, first, window.as_of_s):
                status = "stopped"
                break
            _publish(run, window, roles)
            count += 1
    except Exception as failure:  # the run ends; the service stays up
        status, error = "failed", type(failure).__name__
    with run.cond:
        run.status = status
    run.emit("done", {"status": status, "windows": count, "error_type": error})


class RunRegistry:
    """All runs of the service, created from a source factory and kept up to a limit."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(
        self, make_source: Callable[[str], Source], speed: float, reveal_truth: bool
    ) -> Run:
        run_id = "R-" + secrets.token_hex(6)
        run = Run(run_id, make_source(run_id), speed, reveal_truth)
        with self._lock:
            self._runs[run_id] = run
            self._evict()
        threading.Thread(target=execute, args=(run,), daemon=True, name=run_id).start()
        return run

    def _evict(self) -> None:
        finished = [r for r in self._runs.values() if r.finished]
        while len(self._runs) > MAX_KEPT_RUNS and finished:
            del self._runs[finished.pop(0).run_id]

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def stop_all(self) -> None:
        with self._lock:
            for run in self._runs.values():
                run.stop.set()
