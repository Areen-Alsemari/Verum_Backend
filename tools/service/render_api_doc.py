"""Write the service API document with the responses and events of an actual run of the service.

Inputs: the stored sample folder for replay and the release folder for live, both optional but
both needed for the full document. Output: the markdown document, with every example taken from a
response of a server started on a free local port and run here, never typed by hand.
Assumptions: long lists are cut to their first items so the document stays readable; the cut is
stated under each example with the real length. Live data is read through the audit hook.
Source: the run service package.
"""

from __future__ import annotations

import argparse
import http.client
import json
import threading
from pathlib import Path
from typing import Any

from verum.service.app import ServiceConfig, make_server

KEEP = 2
ORIGIN = "http://localhost:5173"


def call(port: int, method: str, path: str, body: Any = None) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    payload = None if body is None else json.dumps(body)
    conn.request(method, path, body=payload, headers={"Origin": ORIGIN})
    response = conn.getresponse()
    return response.status, response.read().decode("utf-8")


def cut(value: Any, path: str, notes: list[str], tail: bool = False) -> Any:
    """Keep the first (or last) items of long lists and record the cut with the real length."""
    if isinstance(value, dict):
        return {k: cut(v, f"{path}.{k}" if path else k, notes, tail) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > KEEP:
            notes.append(f"`{path}` has {len(value)} items; {KEEP} are shown")
        kept = value[-KEEP:] if tail else value[:KEEP]
        return [cut(v, path, notes, tail) for v in kept]
    return value


def block(title: str, value: Any, status: int | None = None, tail: bool = False) -> str:
    notes: list[str] = []
    shown = cut(value, "", notes, tail)
    head = f"{title}" if status is None else f"{title} (status {status})"
    text = f"**{head}**\n\n```json\n{json.dumps(shown, indent=2)}\n```\n"
    if notes:
        said = "; ".join(dict.fromkeys(notes))
        text += f"\nShortened here, complete in the real response: {said}.\n"
    return text


def frames(text: str) -> list[dict[str, Any]]:
    found = []
    for chunk in text.split("\n\n"):
        if chunk.startswith("id:"):
            lines = chunk.split("\n")
            found.append({"event": lines[1][7:], "data": json.loads(lines[2][6:]), "raw": chunk})
    return found


def run_stream(port: int, body: dict[str, Any]) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    status, text = call(port, "POST", "/api/runs", body)
    created = json.loads(text)
    _, stream = call(port, "GET", created["links"]["events"])
    return created, stream, frames(stream)


def gather(replay: Path, release: Path) -> dict[str, Any]:
    server = make_server(ServiceConfig(replay_dir=replay, release=release), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = int(server.server_address[1])
    out: dict[str, Any] = {"health": call(port, "GET", "/api/health")}
    out["facility"] = call(port, "GET", "/api/facility")
    out["episodes"] = call(port, "GET", "/api/episodes?mode=replay")
    episodes = json.loads(out["episodes"][1])["episodes"]
    pick = None
    for episode in [e for e in episodes if e["split"] == "validation" and e["windows"] >= 6]:
        body = {"mode": "replay", "speed": 1_000_000, "episode_id": episode["episode_id"]}
        _, text, found = run_stream(port, body)
        if any(f["event"] == "alert" for f in found):
            pick = episode["episode_id"]
            break
    body = {"mode": "replay", "speed": 60, "episode_id": pick, "reveal_truth": True}
    status, created = call(port, "POST", "/api/runs", {**body, "speed": 1_000_000})
    out["create"] = (status, created, {**body, "speed": 1_000_000})
    run = json.loads(created)
    out["stream"] = call(port, "GET", run["links"]["events"])
    for name in ("status", "report", "truth"):
        out[name] = call(port, "GET", run["links"][name])
    out["report_early"] = call(port, "GET", "/api/runs/R-000000000000/report")
    plain = json.loads(call(port, "POST", "/api/runs", {"mode": "replay", "speed": 1_000_000,
                                                        "episode_id": pick})[1])
    out["truth_off"] = call(port, "GET", plain["links"]["truth"])
    out["bad_speed"] = call(port, "POST", "/api/runs", {"mode": "replay", "speed": 0})
    out["live_episodes"] = call(port, "GET", "/api/episodes?mode=live")
    live = json.loads(out["live_episodes"][1])["episodes"]
    shortest = min(live, key=lambda e: e["windows"])
    out["live_create"] = call(port, "POST", "/api/runs", {"mode": "live", "speed": 1_000_000,
                                                          "episode_id": shortest["episode_id"]})
    live_run = json.loads(out["live_create"][1])
    out["live_stream"] = call(port, "GET", live_run["links"]["events"])
    server.shutdown()
    return out


def reply(title: str, entry: tuple[int, str], tail: bool = False) -> str:
    """A documented response: its title, status and body, taken from the run."""
    return block(title, json.loads(entry[1]), entry[0], tail)


def event(frames_of: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(f for f in frames_of if f["event"] == kind)


def render(data: dict[str, Any]) -> str:
    template = Path(__file__).with_name("service_api_template.md").read_text(encoding="utf-8")
    seen, live = frames(data["stream"][1]), frames(data["live_stream"][1])
    parts = {
        "HEALTH": reply("GET /api/health", data["health"]),
        "FACILITY": reply("GET /api/facility", data["facility"]),
        "EPISODES": reply("GET /api/episodes?mode=replay", data["episodes"]),
        "CREATE": reply("POST /api/runs with " + json.dumps(data["create"][2]), data["create"][:2]),
        "LIVE_CREATE": reply("POST /api/runs for a live run", data["live_create"]),
        "BAD_SPEED": reply("POST /api/runs with speed 0", data["bad_speed"]),
        "FRAME": "```\n" + event(seen, "window_result")["raw"][:400] + " ...\n```\n",
        "SENSOR": block("event sensor_reading", event(seen, "sensor_reading")["data"]),
        "RESULT": block("event window_result", event(seen, "window_result")["data"]),
        "ALERT": block("event alert", event(seen, "alert")["data"]),
        "DONE": block("event done", event(seen, "done")["data"]),
        "LIVE_RESULT": block("event window_result, live", event(live, "window_result")["data"]),
        "STATUS": reply("GET /api/runs/{id}/status", data["status"]),
        "REPORT": reply("GET /api/runs/{id}/report", data["report"]),
        "NOT_FOUND": reply("GET /api/runs/R-000000000000/report", data["report_early"]),
        "TRUTH": reply("GET /api/runs/{id}/truth", data["truth"], tail=True),
        "TRUTH_OFF": reply("GET /api/runs/{id}/truth without reveal_truth", data["truth_off"]),
    }
    for key, text in parts.items():
        template = template.replace("{{" + key + "}}", text)
    return template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/service_api.md"))
    args = parser.parse_args()
    args.out.write_text(render(gather(args.replay_dir, args.release)), encoding="utf-8")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
