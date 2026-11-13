"""Build the stream events of one window from its requests and reports.

Inputs: a window record, which holds the context, the requests, the reports and the runner's
issues and notes of one analysed window, the same shape for a stored and for a live window.
Outputs: sensor readings, the window result with the status of every agent and the decision of
Agent 8, and an alert when the persistence rule of Agent 2 fires.
Assumptions: every field is copied by name, so nothing that is not listed can reach an event; no
label, fault name or free text of an agent is copied. See the service API document.
Source: the runner bundle and the interface contract.
"""

from __future__ import annotations

from typing import Any

DECISION_ROLE = "evidence_verification_decision"
FORECAST_ROLE = "predictive_health"
SIGNAL_FIELDS = {
    "latest_value": "value", "mean": "mean", "minimum": "minimum", "maximum": "maximum",
    "latest_quality": "quality", "latest_availability": "availability",
}
SIMULATION = "synthetic data from the simulator, not plant data"
COMPRESSION_NOTE = "playback speed compresses the 300 s window cadence; it changes no value"


def envelope(run: dict[str, Any], kind: str, seq: int) -> dict[str, Any]:
    """The fields every event carries: type, run, mode and the labelled time compression."""
    return {
        "type": kind, "seq": seq, "run_id": run["run_id"], "mode": run["mode"],
        "time_compression": {"factor": run["speed"], "note": COMPRESSION_NOTE},
        "data": SIMULATION,
    }


def sensor_event(record: dict[str, Any], index: int) -> dict[str, Any]:
    """The tags of the window with the latest value, the window statistics and the quality."""
    request = record["requests"].get(FORECAST_ROLE)
    summary = {} if request is None else request["input"]["observations"]["summary"]
    readings = [
        {"tag_id": s["tag_id"], "unit": s.get("unit"),
         **{name: s.get(field) for field, name in SIGNAL_FIELDS.items()}}
        for s in summary.get("signals", [])
    ]
    return {
        "window_index": index, "as_of_s": record["context"]["as_of_s"],
        "lookback_s": summary.get("lookback_s"), "readings": readings,
    }


def _agent(role: str, record: dict[str, Any]) -> dict[str, Any]:
    report = record["reports"].get(role)
    codes = sorted({i["code"] for i in record["issues"] if i["role"] == role})
    return {
        "status": None if report is None else report["status"],
        "report_id": None if report is None else report["report_id"],
        "runner_issue_codes": codes,
    }


def _decision(record: dict[str, Any]) -> dict[str, Any] | None:
    report = record["reports"].get(DECISION_ROLE)
    if report is None or not isinstance(report.get("result"), dict):
        return None
    result = report["result"]
    flags = {k: v for k, v in result.items() if isinstance(v, bool)}
    head = {"decision_state": result.get("decision_state"),
            "advisory_only": report["advisory_only"]}  # fmt: skip
    return {**head, **flags}


def persistence_of(record: dict[str, Any]) -> dict[str, Any] | None:
    """The persistence statement the runner gave Agent 8 for this window, if any."""
    request = record["requests"].get(DECISION_ROLE)
    value = None if request is None else request["input"].get("persistence")
    return value if isinstance(value, dict) else None


def result_event(record: dict[str, Any], index: int, roles: list[str]) -> dict[str, Any]:
    """The status of every agent, Agent 8's decision with its fixed flags, and persistence."""
    return {
        "window_index": index, "as_of_s": record["context"]["as_of_s"],
        "agents": {role: _agent(role, record) for role in roles},
        "decision": _decision(record), "persistence": persistence_of(record),
        "runner_note_codes": sorted({n["code"] for n in record["notes"]}),
    }


def alert_event(record: dict[str, Any], index: int) -> dict[str, Any] | None:
    """An alert when the published persistence rule of Agent 2 is satisfied in this window."""
    held = persistence_of(record)
    if held is None or held.get("alarming") is not True:
        return None
    rule = held["rule"]
    return {
        "window_index": index, "as_of_s": record["context"]["as_of_s"],
        "source": "anomaly_detection", "rule": rule,
        "windows_exceeding": held["windows_exceeding"], "windows_held": held["windows_held"],
        "message": f"{rule['k']} of the last {rule['n']} windows are above the threshold",
    }
