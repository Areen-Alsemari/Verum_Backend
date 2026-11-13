"""The HTTP side of the run service: routes, JSON bodies, Server-Sent Events and CORS.

Inputs: requests on a local port. Outputs: JSON responses and an event stream per run, with the
cross-origin headers for the configured frontend origins only.
Assumptions: only the standard library is used; each connection has its own thread; a client that
disconnects ends its own stream and nothing else. The truth of a run is served by its own route
and only when the run was created with reveal_truth. Run state is never written to disk.
Source: the service API document.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from verum.service import sources
from verum.service.facility import facility
from verum.service.runs import Run, RunRegistry, Source, validate_speed

DEFAULT_ORIGINS = ("http://localhost:5173",)
MAX_BODY = 4096
RUN_PATH = re.compile(r"/api/runs/(R-[0-9a-f]{12})/(events|report|truth|status)")
TRUTH_LABEL = "simulation truth, not visible to the agents"


@dataclass
class ServiceConfig:
    """What the service was started with."""

    replay_dir: Path | None = None
    release: Path | None = None
    origins: tuple[str, ...] = DEFAULT_ORIGINS
    keepalive_s: float = 10.0
    live: sources.LiveData | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.release is not None:
            self.live = sources.LiveData(self.release)


class Refused(Exception):
    """A request the service answers with an error status and a message."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class ServiceServer(ThreadingHTTPServer):
    """The server, with the configuration and the registry that its handlers share."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: ServiceConfig) -> None:
        super().__init__(address, Handler)
        self.config = config
        self.registry = RunRegistry()

    def server_close(self) -> None:
        self.registry.stop_all()
        super().server_close()

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # a dropped connection is not an event worth a traceback


class Handler(BaseHTTPRequestHandler):
    server: ServiceServer
    server_version = "VerumService"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # --- plumbing -----------------------------------------------------------------------
    def _origin_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in self.server.config.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")

    def _send_json(self, status: HTTPStatus, body: Any) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self._origin_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _guarded(self, action: Any) -> None:
        try:
            action()
        except Refused as refusal:
            self._send_json(refusal.status, {"error": str(refusal)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as failure:  # never let one request take the service down
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(failure).__name__})

    # --- verbs --------------------------------------------------------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._origin_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Last-Event-ID")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._guarded(self._get)

    def do_POST(self) -> None:  # noqa: N802
        self._guarded(self._post)

    def _get(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/api/health":
            return self._send_json(HTTPStatus.OK, self._health())
        if url.path == "/api/facility":
            return self._send_json(HTTPStatus.OK, facility())
        if url.path == "/api/episodes":
            return self._send_json(HTTPStatus.OK, self._episodes(parse_qs(url.query)))
        found = RUN_PATH.fullmatch(url.path)
        if found:
            return self._run_route(found.group(1), found.group(2), parse_qs(url.query))
        raise Refused(HTTPStatus.NOT_FOUND, "no such route")

    def _post(self) -> None:
        if urlsplit(self.path).path != "/api/runs":
            raise Refused(HTTPStatus.NOT_FOUND, "no such route")
        try:
            run = self.server.registry.create(*self._plan(self._body()))
        except sources.UnknownEpisode as error:
            raise Refused(HTTPStatus.NOT_FOUND, str(error)) from None
        self._send_json(HTTPStatus.CREATED, {**run.info(), "links": _links(run.run_id)})

    # --- routes -------------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        config = self.server.config
        return {"status": "ok", "service": "verum run service",
                "modes": {"replay": config.replay_dir is not None,
                          "live": config.release is not None}}  # fmt: skip

    def _episodes(self, query: dict[str, list[str]]) -> dict[str, Any]:
        mode = query.get("mode", ["replay"])[0]
        config = self.server.config
        if mode == "replay" and config.replay_dir is not None:
            return {"mode": mode, "episodes": sources.ReplaySource.episodes(config.replay_dir)}
        if mode == "live" and config.live is not None:
            return {"mode": mode, "episodes": config.live.episode_list()}
        raise Refused(HTTPStatus.BAD_REQUEST, f"mode {mode!r} is not available")

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise Refused(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise Refused(HTTPStatus.BAD_REQUEST, "body is not JSON") from None
        if not isinstance(body, dict):
            raise Refused(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
        return body

    def _plan(self, body: dict[str, Any]) -> tuple[Any, float, bool]:
        config, mode = self.server.config, body.get("mode")
        try:
            speed = validate_speed(body.get("speed", 60))
        except ValueError as error:
            raise Refused(HTTPStatus.BAD_REQUEST, str(error)) from None
        reveal, episode = body.get("reveal_truth", False), body.get("episode_id")
        if not isinstance(reveal, bool) or not (episode is None or isinstance(episode, str)):
            raise Refused(HTTPStatus.BAD_REQUEST, "reveal_truth is a boolean, episode_id a string")
        make = self._source_factory(mode, episode, config)
        if reveal and make("probe").split != sources.VALIDATION:
            raise Refused(HTTPStatus.BAD_REQUEST, "truth is offered for validation episodes only")
        return make, speed, reveal

    def _source_factory(self, mode: Any, episode: str | None, config: ServiceConfig) -> Any:
        try:
            if mode == "replay" and config.replay_dir is not None:
                return lambda _id: sources.ReplaySource(config.replay_dir or Path(), episode)
            if mode == "live" and config.live is not None:
                data = config.live
                return lambda run_id: sources.LiveSource(data, run_id, episode)
        except sources.UnknownEpisode as error:
            raise Refused(HTTPStatus.NOT_FOUND, str(error)) from None
        raise Refused(HTTPStatus.BAD_REQUEST, "mode must be 'replay' or 'live', and configured")

    def _run_route(self, run_id: str, route: str, query: dict[str, list[str]]) -> None:
        run = self.server.registry.get(run_id)
        if run is None:
            raise Refused(HTTPStatus.NOT_FOUND, "unknown run")
        if route == "events":
            return self._stream(run, query)
        if route == "status":
            return self._send_json(HTTPStatus.OK, run.info())
        if route == "truth":
            return self._truth(run)
        self._report(run, query)

    def _truth(self, run: Run) -> None:
        if not run.reveal_truth:
            raise Refused(HTTPStatus.NOT_FOUND, "truth is not enabled for this run")
        with run.cond:
            windows = list(run.truth)
        self._send_json(HTTPStatus.OK, {
            "label": TRUTH_LABEL, "run_id": run.run_id, "mode": run.source.mode,
            "episode_id": run.source.episode_id, "windows": windows,
        })

    def _report(self, run: Run, query: dict[str, list[str]]) -> None:
        with run.cond:
            held = dict(run.reports)
            finished = run.finished
        if not finished:
            raise Refused(HTTPStatus.CONFLICT, "the run has not finished")
        if not held:
            raise Refused(HTTPStatus.NOT_FOUND, "the run produced no window")
        wanted = query.get("window", [None])[0]
        index = max(held) if wanted is None else int(wanted) if wanted.lstrip("-").isdigit() else -1
        if index not in held:
            raise Refused(HTTPStatus.NOT_FOUND, "no report for that window")
        report = held[index]
        if isinstance(report, str):
            raise Refused(HTTPStatus.INTERNAL_SERVER_ERROR, report)
        self._send_json(HTTPStatus.OK, {
            "run_id": run.run_id, "mode": run.source.mode, "window_index": index,
            "windows_available": sorted(held), "report": report,
        })

    # --- server-sent events -------------------------------------------------------------
    def _stream(self, run: Run, query: dict[str, list[str]]) -> None:
        last = self.headers.get("Last-Event-ID") or query.get("after", [""])[0]
        seen = int(last) if last.isdigit() else -1
        self.send_response(HTTPStatus.OK)
        self._origin_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self._follow(run, seen)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return  # the client left; the run goes on for any other reader

    def _follow(self, run: Run, seen: int) -> None:
        keepalive = self.server.config.keepalive_s
        while True:
            batch = run.read(seen, keepalive)
            if not batch:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                continue
            for event in batch:
                self.wfile.write(frame(event))
                seen = event["seq"]
            self.wfile.flush()
            if batch[-1]["type"] == "done":
                return


def frame(event: dict[str, Any]) -> bytes:
    """One event in the Server-Sent Events wire format: id, event name and a data line."""
    data = json.dumps(event, separators=(",", ":"))
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {data}\n\n".encode()


def _links(run_id: str) -> dict[str, str]:
    base = f"/api/runs/{run_id}"
    return {"events": f"{base}/events", "report": f"{base}/report", "truth": f"{base}/truth",
            "status": f"{base}/status"}  # fmt: skip


def make_server(config: ServiceConfig, host: str = "127.0.0.1", port: int = 0) -> ServiceServer:
    """A server bound to the given address; port 0 asks the system for a free one."""
    return ServiceServer((host, port), config)


__all__ = ["Source", "ServiceConfig", "ServiceServer", "frame", "make_server"]
