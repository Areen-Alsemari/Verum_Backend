"""Shared cases for the run service tests: a stored sample, a server on a free port, a client.

The stored sample is made by running the placeholder agents through the runner, written in the
format of the sample script, so no release data and no network are needed. Labels are planted in
the stored windows so that the tests can show they never reach an event.
"""

from __future__ import annotations

import gzip
import http.client
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from _runner_cases import placeholders, reference, snapshot
from verum.agents.common import stable_hash
from verum.agents.runner import AssessmentLog, run_analysis, verify_bundle
from verum.service.app import ServiceConfig, make_server
from verum.service.sources import LiveData, LiveWindow

ORIGIN = "http://localhost:5173"
PLANTED = {
    "EP-A": (True, ["XV-R101"], ["VALVE_RESTRICTION"], ["restriction"], 4, "validation"),
    "EP-B": (False, [], [], [], 3, "validation"),
    "EP-T": (True, ["P-101A"], ["PUMP_HEAD_DEGRADATION"], ["pump"], 2, "train"),
}
STEP = 300.0


def _row(window_id: str, episode: str, position: int, spec: tuple[Any, ...]) -> dict[str, Any]:
    fault, assets, types, mechs, _count, _split = spec
    return {"window_id": window_id, "set": "sample", "episode_id": episode, "position": position,
            "cutoff_s": position * STEP, "fault": fault, "assets": assets, "fault_types": types,
            "mechanisms": mechs, "n_components": len(assets)}  # fmt: skip


def _analyse(case: str, position: int, log: AssessmentLog) -> Any:
    snap = snapshot(case_id=case, as_of_s=position * STEP)
    return run_analysis(snap, "runtime", agents=placeholders(), recent=log)


def write_sample(root: Path, alarm_from: int = 3) -> Path:
    """Write the sample index and the bundles of the planted episodes; return the folder."""
    (root / "bundles").mkdir(parents=True)
    sections: dict[str, list[dict[str, Any]]] = {"validation": [], "train_sanity": []}
    for n, (episode, spec) in enumerate(PLANTED.items()):
        log = AssessmentLog()
        for position in range(1, spec[4] + 1):
            wid = f"{episode}-w{position}"
            bundle = _analyse(f"E{n:04d}", position, log)
            log = bundle.assessments
            verify_bundle(bundle)
            row = _row(wid, episode, position, spec)
            sections["validation" if spec[5] == "validation" else "train_sanity"].append(row)
            requests = json.loads(json.dumps(bundle.requests))
            if episode == "EP-A" and position >= alarm_from:  # a stored window in which it fires
                requests["evidence_verification_decision"]["input"]["persistence"].update(
                    alarming=True, windows_exceeding=2, windows_held=3,
                    rule={"k": 2, "n": 3, "threshold": 1.0})
            stored = {"window": row, "context": bundle.context, "requests": requests,
                      "reports": bundle.reports, "issues": bundle.issues, "notes": bundle.notes,
                      "evidence": bundle.registry.rows()}  # fmt: skip
            with gzip.open(root / "bundles" / f"{wid}.json.gz", "wt", encoding="utf-8") as f:
                json.dump(stored, f, default=str)
    (root / "sample.json").write_text(json.dumps({"seed": 0, **sections}), encoding="utf-8")
    return root


class FakeLiveData(LiveData):
    """Validation windows held in memory, for live runs through the real runner."""

    def __init__(self) -> None:
        super().__init__(Path("unused"))

    def _read(self) -> dict[str, list[LiveWindow]]:
        self.reference = reference()
        self.reference_sha = stable_hash(self.reference)
        out: dict[str, list[LiveWindow]] = {}
        for episode, spec in PLANTED.items():
            if spec[5] != "validation":
                continue
            out[episode] = [LiveWindow(f"{episode}-w{p}", p, p * STEP, _summary()) for p in
                            range(1, spec[4] + 1)]  # fmt: skip
            for p in range(1, spec[4] + 1):
                self._truth[f"{episode}-w{p}"] = {"fault": spec[0], "asset_ids": spec[1],
                                                  "fault_types": spec[2], "mechanisms": spec[3]}
        return out


def _summary() -> dict[str, Any]:
    from _runner_cases import summary

    return summary()


@contextmanager
def serving(config: ServiceConfig) -> Iterator[int]:
    """Run a server on a free local port in a thread and yield the port."""
    server = make_server(config, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def call(
    port: int, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    """One request; returns the status, the lower-cased headers and the body."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        payload = None if body is None else json.dumps(body)
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json",
                                                         **(headers or {})})
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def get_json(port: int, path: str) -> Any:
    status, _, body = call(port, "GET", path)
    assert status == 200, (status, body)
    return json.loads(body)


def start_run(port: int, **body: Any) -> str:
    status, _, raw = call(port, "POST", "/api/runs", {"speed": 1_000_000, **body})
    assert status == 201, (status, raw)
    return str(json.loads(raw)["run_id"])


def parse_frames(text: str) -> list[dict[str, Any]]:
    """Split an event stream into frames; every frame must be id, event and data lines."""
    frames = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        lines = block.split("\n")
        assert [line.split(":", 1)[0] for line in lines] == ["id", "event", "data"], block
        frames.append({"id": lines[0][4:], "event": lines[1][7:], "data": json.loads(lines[2][6:])})
    return frames


def stream(port: int, run_id: str, headers: dict[str, str] | None = None) -> tuple[
    int, dict[str, str], str
]:
    status, head, body = call(port, "GET", f"/api/runs/{run_id}/events", headers=headers)
    return status, head, body.decode("utf-8")


def events_of(port: int, run_id: str) -> list[dict[str, Any]]:
    """Every event of a run, read to the end of its stream."""
    return [f["data"] for f in parse_frames(stream(port, run_id)[2])]
