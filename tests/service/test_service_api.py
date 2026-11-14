"""Checks of the run service over a local port: routes, stream framing, CORS, isolation, truth."""

from __future__ import annotations

import gzip
import http.client
import importlib
import json
import re
import socket
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from _runner_cases import placeholders
from _service_cases import (
    ORIGIN,
    PLANTED,
    FakeLiveData,
    call,
    events_of,
    get_json,
    parse_frames,
    serving,
    start_run,
    stream,
    write_sample,
)
from verum.agents.runner.wiring import workflow_stages
from verum.contracts.agent_interfaces import FORBIDDEN
from verum.contracts.paths import config_dir
from verum.faults import spec as fault_spec
from verum.service import sources
from verum.service.app import ServiceConfig
from verum.service.sources import LiveSource

ROLES_IN_ORDER = [role for stage in workflow_stages() for role in stage]
FAULT_WORDS = {
    fault_spec.LEAK, fault_spec.RESTRICTION, fault_spec.PUMP, fault_spec.SENSOR,
    fault_spec.MISROUTING, "ground_truth", "injected", "mechanism",
}  # fmt: skip


@pytest.fixture(scope="module")
def sample(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_sample(tmp_path_factory.mktemp("sample"))


def strings_of(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [str(k), *strings_of(v)]]
    if isinstance(value, list):
        return [s for v in value for s in strings_of(v)]
    return [value] if isinstance(value, str) else []


def truth_words() -> set[str]:
    planted = {w for spec in PLANTED.values() for part in spec[2:4] for w in part}
    return planted | FAULT_WORDS | FORBIDDEN


def without_tag_ids(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events with the tag identifiers of the readings removed: an asset may also be a tag."""
    stripped = json.loads(json.dumps(events))
    for event in stripped:
        for reading in event.get("readings", []):
            reading["tag_id"] = "TAG"
    return stripped  # type: ignore[no-any-return]


def test_health_and_facility_come_from_the_config_and_invent_nothing(sample: Path) -> None:
    """The facility holds the config's edges, tanks, pumps and tags and no drawing positions.

    Independent: yes, because the expected values are read from the config files themselves.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        assert get_json(port, "/api/health")["modes"] == {"replay": True, "live": False}
        facility = get_json(port, "/api/facility")
    topology = json.loads((config_dir() / "topology_contract.json").read_text())
    sensors = json.loads((config_dir() / "canonical_sensor_contract.json").read_text())
    assert [e["edge_id"] for e in facility["edges"]] == [e["edge_id"] for e in topology["edges"]]
    assert set(facility["tanks"]) == set(topology["tanks"])
    assert facility["pumps"] == topology["pumps"]
    assert [t["tag_id"] for t in facility["tags"]] == list(sensors["sensors"])
    drawn = {"x", "y", "position", "coordinates"}
    assert {k for e in facility["edges"] for k in e}.isdisjoint(drawn)
    assert any(a["kind"] == "isolation_valve" for a in facility["assets"])


def test_the_event_stream_is_framed_ordered_and_ends_with_one_done(sample: Path) -> None:
    """Each frame is id, event and data; events run window by window and end with done.

    Independent: yes, because the framing is parsed from the raw bytes of the response.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        run = start_run(port, mode="replay", episode_id="EP-A")
        status, head, text = stream(port, run)
    assert status == 200 and head["content-type"].startswith("text/event-stream")
    assert head["cache-control"] == "no-cache" and text.endswith("\n\n")
    frames = parse_frames(text)
    assert [int(f["id"]) for f in frames] == list(range(len(frames)))
    assert all(f["event"] == f["data"]["type"] and f["data"]["seq"] == int(f["id"]) for f in frames)
    kinds = [f["event"] for f in frames]
    assert set(kinds) <= {"sensor_reading", "window_result", "alert", "done"}
    assert kinds.count("done") == 1 and kinds[-1] == "done"
    assert frames[-1]["data"]["status"] == "completed" and frames[-1]["data"]["windows"] == 4
    windows = [f["data"]["window_index"] for f in frames if f["event"] == "sensor_reading"]
    assert windows == [1, 2, 3, 4]
    for index in windows:
        order = [k for k, f in zip(kinds, frames, strict=True)
                 if f["data"].get("window_index") == index]  # fmt: skip
        assert order[:2] == ["sensor_reading", "window_result"] and order[2:] in ([], ["alert"])


def test_every_event_is_labelled_with_its_mode_and_the_time_compression(sample: Path) -> None:
    """Replay says replay, and the speed is stated as a time compression with its note.

    Independent: yes, because the labels are read from the events themselves.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        run = start_run(port, mode="replay", episode_id="EP-B", speed=240)
        events = events_of(port, run)
    assert {e["mode"] for e in events} == {"replay"}
    assert {e["time_compression"]["factor"] for e in events} == {240.0}
    assert all("compress" in e["time_compression"]["note"] for e in events)
    assert all(e["data"].startswith("synthetic") for e in events)


def test_an_alert_follows_the_window_where_the_persistence_rule_fires(sample: Path) -> None:
    """Alerts appear exactly in the stored windows whose persistence statement is alarming.

    Independent: yes, because the windows that alarm are those planted in the stored requests.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        events = events_of(port, start_run(port, mode="replay", episode_id="EP-A"))
    alerts = [e for e in events if e["type"] == "alert"]
    assert [a["window_index"] for a in alerts] == [3, 4]
    assert alerts[0]["source"] == "anomaly_detection" and alerts[0]["rule"]["k"] >= 1
    assert not [e for e in events if e["type"] == "alert" and e["window_index"] < 3]


def test_a_replayed_window_has_the_agent_statuses_of_the_stored_bundle(sample: Path) -> None:
    """The status of every agent and the decision flags equal those of the stored bundle.

    Independent: yes, because the stored bundle is read directly from its file.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        events = events_of(port, start_run(port, mode="replay", episode_id="EP-A"))
    results = [e for e in events if e["type"] == "window_result"]
    assert len(results) == 4
    for result in results:
        path = sample / "bundles" / f"EP-A-w{result['window_index']}.json.gz"
        stored = json.load(gzip.open(path, "rt", encoding="utf-8"))
        assert list(result["agents"]) == ROLES_IN_ORDER
        for role, shown in result["agents"].items():
            report = stored["reports"][role]
            assert shown["status"] == report["status"] and shown["report_id"] == report["report_id"]
        decision = stored["reports"]["evidence_verification_decision"]
        assert result["decision"]["decision_state"] == decision["result"]["decision_state"]
        assert result["decision"]["automatic_action_authorized"] is False
        assert result["decision"]["human_decision_required"] is True
        assert result["decision"]["advisory_only"] is True


def test_the_sample_of_the_repository_replays_with_its_stored_statuses() -> None:
    """If the stored 181-window sample is present, an episode of it replays as it was stored.

    Independent: yes, because the stored bundles are read from their files.
    """
    folder = Path(__file__).resolve().parents[2] / "local" / "replay_sample"
    if not (folder / "sample.json").exists():
        pytest.skip("the stored sample is not present")
    with serving(ServiceConfig(replay_dir=folder)) as port:
        run = start_run(port, mode="replay")
        episode = get_json(port, f"/api/runs/{run}/status")["episode_id"]
        events = events_of(port, run)
    rows = json.loads((folder / "sample.json").read_text())["validation"]
    by_position = {r["position"]: r["window_id"] for r in rows if r["episode_id"] == episode}
    results = [e for e in events if e["type"] == "window_result"]
    assert len(results) == len(by_position) > 1 and events[-1]["status"] == "completed"
    for result in results:
        path = folder / "bundles" / f"{by_position[result['window_index']]}.json.gz"
        stored = json.load(gzip.open(path, "rt", encoding="utf-8"))
        assert {r: a["status"] for r, a in result["agents"].items()} == {
            r: (None if v is None else v["status"]) for r, v in stored["reports"].items()
        }


def test_no_event_of_a_replay_or_live_run_holds_a_label_a_fault_word_or_a_hidden_key(
    sample: Path,
) -> None:
    """The planted labels, the fault words and the hidden keys appear in no event, revealed or not.

    Independent: yes, because the words are those planted in the stored windows and in the specs.
    """
    config = ServiceConfig(replay_dir=sample)
    config.live, config.release = FakeLiveData(), Path("unused")
    with serving(config) as port:
        for reveal in (False, True):
            for mode in ("replay", "live"):
                run = start_run(port, mode=mode, episode_id="EP-A", reveal_truth=reveal)
                events = events_of(port, run)
                text = " ".join(strings_of(without_tag_ids(events)))
                words = truth_words() | {a for spec in PLANTED.values() for a in spec[1]}
                assert events and not [w for w in words if w in text], (mode, reveal)
                assert not set(keys_of(events)) & FORBIDDEN, (mode, reveal)


def keys_of(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value, *[k for v in value.values() for k in keys_of(v)]]
    if isinstance(value, list):
        return [k for v in value for k in keys_of(v)]
    return []


def test_the_truth_route_is_off_unless_asked_and_marked_when_on(sample: Path) -> None:
    """Without reveal_truth the route answers 404; with it the truth is marked as simulation truth.

    Independent: yes, because the planted labels are the expected content.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        off = start_run(port, mode="replay", episode_id="EP-A")
        assert call(port, "GET", f"/api/runs/{off}/truth")[0] == 404
        on = start_run(port, mode="replay", episode_id="EP-A", reveal_truth=True)
        events_of(port, on)
        truth = get_json(port, f"/api/runs/{on}/truth")
        train = {"mode": "replay", "episode_id": "EP-T", "reveal_truth": True}
        status, _, body = call(port, "POST", "/api/runs", train)
    assert truth["label"] == "simulation truth, not visible to the agents"
    assert len(truth["windows"]) == 4 and truth["windows"][0]["asset_ids"] == ["XV-R101"]
    assert truth["windows"][0]["fault_types"] == ["VALVE_RESTRICTION"]
    assert status == 400 and b"validation" in body


def test_unknown_runs_routes_and_bad_bodies_are_refused_with_a_status(sample: Path) -> None:
    """An unknown run gives 404 on every run route; bad requests give 400 or 404.

    Independent: yes, because the statuses are those of the HTTP routes asked for.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        for route in ("events", "report", "truth", "status"):
            assert call(port, "GET", f"/api/runs/R-000000000000/{route}")[0] == 404
            assert call(port, "GET", f"/api/runs/not-a-run/{route}")[0] == 404
        assert call(port, "GET", "/api/nothing")[0] == 404
        for bad in ({"mode": "other"}, {"mode": "live"}, {"mode": "replay", "speed": 0},
                    {"mode": "replay", "speed": "fast"}, {"mode": "replay", "speed": True},
                    {"mode": "replay", "reveal_truth": 1}):  # fmt: skip
            assert call(port, "POST", "/api/runs", bad)[0] == 400, bad
        assert call(port, "POST", "/api/runs", {"mode": "replay", "episode_id": "EP-X"})[0] == 404
        status, _, body = call(port, "POST", "/api/runs")
        assert status == 400 and json.loads(body)["error"]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/runs", body=b"{not json")
        assert conn.getresponse().status == 400


def test_cors_allows_the_frontend_origin_and_no_other(sample: Path) -> None:
    """The configured origin is echoed on GET, POST, the stream and the preflight; others get none.

    Independent: yes, because the headers are read from real responses on a local port.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        _, head, _ = call(port, "GET", "/api/health", headers={"Origin": ORIGIN})
        assert head["access-control-allow-origin"] == ORIGIN and head["vary"] == "Origin"
        _, other, _ = call(port, "GET", "/api/health", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in other
        assert "access-control-allow-origin" not in call(port, "GET", "/api/health")[1]
        status, head, _ = call(port, "POST", "/api/runs", {"mode": "replay"},
                               headers={"Origin": ORIGIN})  # fmt: skip
        assert status == 201 and head["access-control-allow-origin"] == ORIGIN
        pre, head, _ = call(port, "OPTIONS", "/api/runs", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
        assert pre == 204 and head["access-control-allow-origin"] == ORIGIN
        assert "POST" in head["access-control-allow-methods"]
        assert "Content-Type" in head["access-control-allow-headers"]
        run = start_run(port, mode="replay", episode_id="EP-B")
        _, head, _ = stream(port, run, headers={"Origin": ORIGIN})
        assert head["access-control-allow-origin"] == ORIGIN


def _trim(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events with the run identifier and the report identifiers (hashes of it) masked."""
    text = json.dumps(events).replace(events[0]["run_id"], "RUN")
    loaded: list[dict[str, Any]] = json.loads(re.sub(r'("report_id": )"[^"]*"', r'\1"ID"', text))
    return loaded


def _read_into(
    into: dict[str, list[dict[str, Any]]], port: int, episode: str, run: str
) -> None:
    into[episode] = events_of(port, run)


def test_two_simultaneous_runs_share_no_state(sample: Path) -> None:
    """Two runs started together give the same events as the same runs alone, each its own.

    Independent: yes, because each run is compared with a run of the same episode made alone.
    """
    config = ServiceConfig(replay_dir=sample)
    config.live, config.release = FakeLiveData(), Path("unused")
    with serving(config) as port:
        for mode in ("replay", "live"):
            alone = {e: _trim(events_of(port, start_run(port, mode=mode, episode_id=e, speed=2000)))
                     for e in ("EP-A", "EP-B")}  # fmt: skip
            runs = {e: start_run(port, mode=mode, episode_id=e, speed=2000) for e in alone}
            together: dict[str, list[dict[str, Any]]] = {}
            threads = [threading.Thread(target=_read_into, args=(together, port, *item))
                       for item in runs.items()]  # fmt: skip
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
            for episode, run in runs.items():
                assert {e["run_id"] for e in together[episode]} == {run}
                assert _trim(together[episode]) == alone[episode]
            ids = {e: {a["report_id"] for ev in together[e] if ev["type"] == "window_result"
                       for a in ev["agents"].values()} for e in runs}  # fmt: skip
            assert ids["EP-A"].isdisjoint(ids["EP-B"])


def test_a_live_run_keeps_its_own_persistence_log_and_calls_the_runner_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistence counts start from one in each run, and the runner is called as before.

    Independent: yes, because the runner call is recorded and its arguments compared with the run.
    """
    calls: list[dict[str, Any]] = []
    real = sources.run_analysis  # type: ignore[attr-defined]

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append({"case": args[0].case_id, **kwargs})
        return real(*args, **kwargs)

    monkeypatch.setattr(sources, "run_analysis", spy)
    data = FakeLiveData()
    held: list[list[int]] = []
    for case in ("CASE-1", "CASE-2"):
        source = LiveSource(data, case, "EP-A", agents=placeholders(), allow_placeholders=True)
        windows = list(source.windows())
        inputs = [w.record["requests"]["evidence_verification_decision"]["input"] for w in windows]
        held.append([i["persistence"]["windows_held"] for i in inputs])
        assert {w.record["context"]["case_id"] for w in windows} == {case}
    assert held[0] == held[1] and held[0][0] == 1 and held[0] == sorted(held[0])
    assert all("tracer" not in c for c in calls)  # tracing comes from the environment, unchanged
    assert [c["window_index"] for c in calls[:4]] == [1, 2, 3, 4]
    assert {c["episode_id"] for c in calls} == {"EP-A"}
    assert {c["case"] for c in calls} == {"CASE-1", "CASE-2"}


def test_a_live_run_is_traced_through_the_existing_hooks_when_the_environment_enables_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tracing variables set, a live window posts the parent, the children and the check.

    Independent: yes, because the tracing package is replaced by a recording fake.
    """
    posted: list[str] = []

    class Tree:
        def __init__(self, **fields: Any) -> None:
            self.fields = fields

        def create_child(self, **fields: Any) -> Tree:
            return Tree(**fields)

        def post(self) -> None:
            posted.append(self.fields["name"])

        def end(self, **fields: Any) -> None:
            pass

        def patch(self) -> None:
            pass

    module = types.ModuleType("langsmith.run_trees")
    module.RunTree = Tree  # type: ignore[attr-defined]
    real = importlib.import_module
    monkeypatch.setattr(importlib, "import_module",
                        lambda n, *a: module if n == "langsmith.run_trees" else real(n, *a))
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-value")
    source = LiveSource(FakeLiveData(), "CASE-T", "EP-B", agents=placeholders(),
                        allow_placeholders=True)  # fmt: skip
    list(source.windows())
    assert posted.count("verum.run_analysis") == 3 and posted.count("verum.verify_bundle") == 3
    assert posted.count("verum.agent.diagnostic_reasoning") == 3


def test_the_report_waits_for_the_end_of_the_run_and_then_is_built_from_the_bundle(
    sample: Path,
) -> None:
    """The report is refused with 409 while the run goes on, and is the Agent 7 report after.

    Independent: yes, because the report is checked against the context of the stored window.
    """
    with serving(ServiceConfig(replay_dir=sample)) as port:
        slow = start_run(port, mode="replay", episode_id="EP-A", speed=1)
        assert call(port, "GET", f"/api/runs/{slow}/report")[0] == 409
        run = start_run(port, mode="replay", episode_id="EP-A")
        events_of(port, run)
        body = get_json(port, f"/api/runs/{run}/report")
        earlier = get_json(port, f"/api/runs/{run}/report?window=2")
        missing = call(port, "GET", f"/api/runs/{run}/report?window=99")[0]
    assert body["window_index"] == 4 and body["windows_available"] == [1, 2, 3, 4]
    assert body["report"]["advisory_only"] is True and body["report"]["report_type"]
    assert earlier["window_index"] == 2 and earlier["report"]["context"]["as_of_s"] == 600.0
    assert missing == 404


def test_a_client_that_leaves_mid_stream_does_not_stop_the_service_or_the_run(
    sample: Path,
) -> None:
    """After a reader drops the connection the run finishes and the service still answers.

    Independent: yes, because the run is read to its end by a second client afterwards.
    """
    with serving(ServiceConfig(replay_dir=sample, keepalive_s=0.05)) as port:
        run = start_run(port, mode="replay", episode_id="EP-A", speed=1500)  # 0.2 s per window
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            raw.sendall(f"GET /api/runs/{run}/events HTTP/1.0\r\n\r\n".encode())
            head = b""
            while b"id:" not in head:  # read up to the first event, then leave
                head += raw.recv(4096)
            assert head.startswith(b"HTTP/1.0 200")
        # the connection is closed here, before the run has ended
        assert get_json(port, "/api/health")["status"] == "ok"
        events = events_of(port, run)
        assert events[-1]["type"] == "done" and events[-1]["status"] == "completed"
        assert get_json(port, f"/api/runs/{run}/status")["status"] == "completed"
        resumed = parse_frames(stream(port, run, headers={"Last-Event-ID": "2"})[2])
        assert [int(f["id"]) for f in resumed] == list(range(3, len(events)))
