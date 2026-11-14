# Run service API

A local HTTP service that plays analysed windows of the synthetic terminal to a frontend. It uses the Python standard library only, serves JSON and one Server-Sent Events stream per run, and holds no physics and no agent logic: a run either replays stored bundles of the 181-window sample or runs the real runner on a validation episode. Every example below is a real response of a run of the service; the lists that were cut for length are named under each example.

## Starting the service

From the repository root:

```bash
PYTHONPATH=src python -m verum.service --port 8765 --replay-dir local/replay_sample --release data/reference_release_v2/verum_reference_v2
```

`--replay-dir` is the output folder of the sample script (`sample.json` and `bundles/`); without it replay is off. `--release` is the release folder; without it live is off, and with it the process installs an audit hook that refuses any open under the release other than the knowledge folder, the role-view inventory and the validation role views and examples. The test split is never read. `--port 0` picks a free port and the first line printed says which. The service binds to 127.0.0.1 and allows the browser origin `http://localhost:5173` only (`--origin` adds more).

## Conventions

- Every response and event is JSON. Every event carries `mode` (`replay` or `live`), `run_id`, a sequence number `seq`, `time_compression` and a `data` field that says the data is synthetic.
- `speed` in the request is a time compression: the windows are 300 s apart in episode time, and the service waits 300 / speed seconds of wall time between them. It changes no value and no result. Every event repeats the factor with a note.
- A replay reads the stored bundles; it does not call the runner, so it makes no trace. A live run calls the runner window by window with its own assessment log, so two runs share nothing but read-only data. If the tracing variables of the runner are set, a live run is traced exactly as any run of the runner is.
- Events never contain a ground-truth label, a fault name, a truth file or free text of an agent. The simulation truth is a separate route, off unless the run was created with `reveal_truth` true and only for validation episodes.
- Errors are `{"error": "..."}` with status 400 (bad request), 404 (unknown run, route, episode or disabled truth), 409 (the report of a run that has not finished) or 500.

## Health, facility and episodes

**GET /api/health (status 200)**

```json
{
  "status": "ok",
  "service": "verum run service",
  "modes": {
    "replay": true,
    "live": true
  }
}
```

The facility is taken from the topology contract, the canonical sensor contract and the sensor specifications of the repository. Nothing is added: there are no drawing coordinates, a tag is placed on the element its measured-variable reference names, and a tag the contract withholds has status `withheld` and no reading.

**GET /api/facility (status 200)**

```json
{
  "source": "repository config: topology contract and canonical sensor contract",
  "nodes": [
    "CV-PA",
    "CV-PB"
  ],
  "edges": [
    {
      "edge_id": "E001",
      "from_node": "PIPELINE_RECEIPT_BOUNDARY",
      "to_node": "RECEIPT_METER",
      "route_id": "R-MAIN",
      "length_m": 30.0,
      "nominal_size": "DN300",
      "inner_diameter_m": 0.30318,
      "z_from_m": 1.0,
      "z_to_m": 1.0
    },
    {
      "edge_id": "E002",
      "from_node": "RECEIPT_METER",
      "to_node": "XV-R000",
      "route_id": "R-MAIN",
      "length_m": 15.0,
      "nominal_size": "DN300",
      "inner_diameter_m": 0.30318,
      "z_from_m": 1.0,
      "z_to_m": 1.0
    }
  ],
  "routes": {
    "R-MAIN": 150.0,
    "R-101": 45.0,
    "S-101": 60.0,
    "R-102": 80.0,
    "S-102": 90.0,
    "R-103": 115.0,
    "S-103": 120.0,
    "S-HEADER": 35.0,
    "P-A": 20.0,
    "P-B": 20.0,
    "D-MAIN": 250.0
  },
  "tanks": {
    "TK-101": {
      "diameter_m": 30,
      "shell_height_m": 15,
      "initial_level_m": 9.0,
      "inlet_z_m": 0.6,
      "outlet_z_m": 0.4,
      "normal_min_level_m": 1.8,
      "normal_max_level_m": 12,
      "high_alarm_m": 12.5,
      "independent_high_high_m": 13,
      "critical_model_limit_m": 14
    },
    "TK-102": {
      "diameter_m": 30,
      "shell_height_m": 15,
      "initial_level_m": 7.0,
      "inlet_z_m": 0.6,
      "outlet_z_m": 0.4,
      "normal_min_level_m": 1.8,
      "normal_max_level_m": 12,
      "high_alarm_m": 12.5,
      "independent_high_high_m": 13,
      "critical_model_limit_m": 14
    },
    "TK-103": {
      "diameter_m": 30,
      "shell_height_m": 15,
      "initial_level_m": 5.0,
      "inlet_z_m": 0.6,
      "outlet_z_m": 0.4,
      "normal_min_level_m": 1.8,
      "normal_max_level_m": 12,
      "high_alarm_m": 12.5,
      "independent_high_high_m": 13,
      "critical_model_limit_m": 14
    }
  },
  "pumps": [
    "P-101A",
    "P-101B"
  ],
  "valves": [
    "XV-PAI",
    "XV-PAO"
  ],
  "assets": [
    {
      "asset_id": "TK-101",
      "kind": "tank"
    },
    {
      "asset_id": "TK-102",
      "kind": "tank"
    }
  ],
  "tags": [
    {
      "tag_id": "FT-001",
      "status": "emit",
      "element_id": "E001",
      "quantity": "flow_m3s",
      "unit": "m3/h",
      "kind": "continuous",
      "range_lo": 0.0,
      "range_hi": 800.0,
      "sample_interval_s": 1.0
    },
    {
      "tag_id": "PT-001",
      "status": "emit",
      "element_id": "E002",
      "quantity": "p_from_pa_abs",
      "unit": "barg",
      "kind": "continuous",
      "range_lo": 0.0,
      "range_hi": 10.0,
      "sample_interval_s": 1.0
    }
  ],
  "excluded_nonbaseline_assets": [
    "CV-201",
    "ZT-201"
  ]
}
```

Shortened here, complete in the real response: `nodes` has 29 items; 2 are shown; `edges` has 28 items; 2 are shown; `valves` has 11 items; 2 are shown; `assets` has 49 items; 2 are shown; `tags` has 36 items; 2 are shown.

`/api/episodes?mode=replay|live` lists the episodes a run can be created on, with their split and window count.

**GET /api/episodes?mode=replay (status 200)**

```json
{
  "mode": "replay",
  "episodes": [
    {
      "episode_id": "EP-017E75669BA2",
      "split": "validation",
      "windows": 1
    },
    {
      "episode_id": "EP-01F931B162A9",
      "split": "validation",
      "windows": 1
    }
  ]
}
```

Shortened here, complete in the real response: `episodes` has 100 items; 2 are shown.

## Creating a run

`POST /api/runs` takes a JSON object: `mode` (`replay` or `live`, required), `speed` (a number above 0 and at most 1000000, default 60), `episode_id` (optional; by default the episode with the most windows) and `reveal_truth` (boolean, default false). It answers 201 with the run and the links of its routes.

**POST /api/runs with {"mode": "replay", "speed": 1000000, "episode_id": "EP-83C470077267", "reveal_truth": true} (status 201)**

```json
{
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "speed": 1000000.0,
  "episode_id": "EP-83C470077267",
  "split": "validation",
  "reveal_truth": true,
  "status": "running",
  "events": 0,
  "links": {
    "events": "/api/runs/R-6553c35b6022/events",
    "report": "/api/runs/R-6553c35b6022/report",
    "truth": "/api/runs/R-6553c35b6022/truth",
    "status": "/api/runs/R-6553c35b6022/status"
  }
}
```

A live run is created the same way.

**POST /api/runs for a live run (status 201)**

```json
{
  "run_id": "R-6e483e43a0ad",
  "mode": "live",
  "speed": 1000000.0,
  "episode_id": "EP-01E1FFAC9D2E",
  "split": "validation",
  "reveal_truth": false,
  "status": "running",
  "events": 0,
  "links": {
    "events": "/api/runs/R-6e483e43a0ad/events",
    "report": "/api/runs/R-6e483e43a0ad/report",
    "truth": "/api/runs/R-6e483e43a0ad/truth",
    "status": "/api/runs/R-6e483e43a0ad/status"
  }
}
```

**POST /api/runs with speed 0 (status 400)**

```json
{
  "error": "speed must be above 0 and at most 1e+06"
}
```

## The event stream

`GET /api/runs/{id}/events` is a Server-Sent Events stream. A frame is three lines and a blank line: `id` (the sequence number), `event` (the type) and `data` (one JSON object). A comment line `: keepalive` is sent when nothing happens. The stream ends after the `done` event. To resume after a dropped connection send the header `Last-Event-ID` or the query `?after=` with the last sequence number received; a late reader receives the whole run from the start.

```
id: 1
event: window_result
data: {"type":"window_result","seq":1,"run_id":"R-6553c35b6022","mode":"replay","time_compression":{"factor":1000000.0,"note":"playback speed compresses the 300 s window cadence; it changes no value"},"data":"synthetic data from the simulator, not plant data","window_index":1,"as_of_s":300.0,"agents":{"predictive_health":{"status":"complete","report_id":"predictive_healt ...
```

Each window gives `sensor_reading`, then `window_result`, then `alert` if the persistence rule fires, and the run ends with one `done`.

```javascript
const source = new EventSource(`http://localhost:8765/api/runs/${runId}/events`);
for (const type of ["sensor_reading", "window_result", "alert", "done"]) {
  source.addEventListener(type, (message) => handle(type, JSON.parse(message.data)));
}
```

`sensor_reading` holds the tags of the window: the latest value, the mean, minimum and maximum over the 300 s window, the quality and the availability. A tag that is a contact has no statistics.

**event sensor_reading**

```json
{
  "type": "sensor_reading",
  "seq": 0,
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "time_compression": {
    "factor": 1000000.0,
    "note": "playback speed compresses the 300 s window cadence; it changes no value"
  },
  "data": "synthetic data from the simulator, not plant data",
  "window_index": 1,
  "as_of_s": 300.0,
  "lookback_s": 300.0,
  "readings": [
    {
      "tag_id": "FT-001",
      "unit": "m3/h",
      "value": 0.12207217517357137,
      "mean": 0.07873655298695353,
      "minimum": 0.0,
      "maximum": 0.537117570763714,
      "quality": "good",
      "availability": "measured"
    },
    {
      "tag_id": "FT-201",
      "unit": "m3/h",
      "value": 328.11474784466316,
      "mean": 327.3117418173495,
      "minimum": 326.16922255283436,
      "maximum": 328.2368200198367,
      "quality": "good",
      "availability": "measured"
    }
  ]
}
```

Shortened here, complete in the real response: `readings` has 30 items; 2 are shown.

`window_result` holds the status of each of the eight agents in the order of the interface manifest (`status` is null and `runner_issue_codes` says why when an agent failed), the decision of Agent 8 with its fixed flags, the persistence statement that the runner gave Agent 8, and the notes of the runner. The decision never authorises an action and never confirms an equipment condition; the flags say so.

**event window_result**

```json
{
  "type": "window_result",
  "seq": 1,
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "time_compression": {
    "factor": 1000000.0,
    "note": "playback speed compresses the 300 s window cadence; it changes no value"
  },
  "data": "synthetic data from the simulator, not plant data",
  "window_index": 1,
  "as_of_s": 300.0,
  "agents": {
    "predictive_health": {
      "status": "complete",
      "report_id": "predictive_health-AN-E0054-r0-8cc9bac9",
      "runner_issue_codes": []
    },
    "topology_dependency": {
      "status": "complete",
      "report_id": "topology_dependency-AN-E0054-r0-a11690c6",
      "runner_issue_codes": []
    },
    "historical_asset_intelligence": {
      "status": "degraded",
      "report_id": "historical_asset_intelligence-AN-E0054-r0-7e3d9965",
      "runner_issue_codes": []
    },
    "inspection_quality_documentation": {
      "status": "degraded",
      "report_id": "inspection_quality_documentation-AN-E0054-r0-01dbf66e",
      "runner_issue_codes": []
    },
    "anomaly_detection": {
      "status": "complete",
      "report_id": "anomaly_detection-AN-E0054-r0-77542686",
      "runner_issue_codes": []
    },
    "diagnostic_reasoning": {
      "status": "degraded",
      "report_id": "diagnostic_reasoning-AN-E0054-r0-bc374b40",
      "runner_issue_codes": []
    },
    "inspection_planning": {
      "status": "insufficient_evidence",
      "report_id": "inspection_planning-AN-E0054-r0-8c96e50a",
      "runner_issue_codes": []
    },
    "evidence_verification_decision": {
      "status": "degraded",
      "report_id": "evidence_verification_decision-AN-E0054-r0-724a289b",
      "runner_issue_codes": []
    }
  },
  "decision": {
    "decision_state": "more_evidence_required",
    "advisory_only": true,
    "human_decision_required": true,
    "automatic_action_authorized": false,
    "equipment_condition_confirmed": false
  },
  "persistence": {
    "rule": {
      "k": 2,
      "n": 3,
      "threshold": 1.741168691251317
    },
    "windows_held": 1,
    "windows_exceeding": 0,
    "windows_unknown": 0,
    "alarming": null
  },
  "runner_note_codes": [
    "ASSETS_NOT_IN_DECLARED_GRAPH",
    "NO_BUDGET"
  ]
}
```

Shortened here, complete in the real response: `runner_note_codes` has 9 items; 2 are shown.

`alert` is sent when the persistence rule that Agent 2 published (k of the last n windows above the threshold) is satisfied in this window.

**event alert**

```json
{
  "type": "alert",
  "seq": 12,
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "time_compression": {
    "factor": 1000000.0,
    "note": "playback speed compresses the 300 s window cadence; it changes no value"
  },
  "data": "synthetic data from the simulator, not plant data",
  "window_index": 10,
  "as_of_s": 3000.0,
  "source": "anomaly_detection",
  "rule": {
    "k": 2,
    "n": 3,
    "threshold": 1.741168691251317
  },
  "windows_exceeding": 2,
  "windows_held": 3,
  "message": "2 of the last 3 windows are above the threshold"
}
```

`done` ends the run. `status` is `completed`, `failed` (with the type of the error) or `stopped`.

**event done**

```json
{
  "type": "done",
  "seq": 19,
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "time_compression": {
    "factor": 1000000.0,
    "note": "playback speed compresses the 300 s window cadence; it changes no value"
  },
  "data": "synthetic data from the simulator, not plant data",
  "status": "completed",
  "windows": 8,
  "error_type": null
}
```

This is a `window_result` of a live run; it has the same shape.

**event window_result, live**

```json
{
  "type": "window_result",
  "seq": 1,
  "run_id": "R-6e483e43a0ad",
  "mode": "live",
  "time_compression": {
    "factor": 1000000.0,
    "note": "playback speed compresses the 300 s window cadence; it changes no value"
  },
  "data": "synthetic data from the simulator, not plant data",
  "window_index": 1,
  "as_of_s": 300.0,
  "agents": {
    "predictive_health": {
      "status": "complete",
      "report_id": "predictive_health-AN-R-6e483e43a0ad-r0-dde2a95d",
      "runner_issue_codes": []
    },
    "topology_dependency": {
      "status": "complete",
      "report_id": "topology_dependency-AN-R-6e483e43a0ad-r0-3a41c003",
      "runner_issue_codes": []
    },
    "historical_asset_intelligence": {
      "status": "degraded",
      "report_id": "historical_asset_intelligence-AN-R-6e483e43a0ad-r0-1e52c352",
      "runner_issue_codes": []
    },
    "inspection_quality_documentation": {
      "status": "degraded",
      "report_id": "inspection_quality_documentation-AN-R-6e483e43a0ad-r0-c4c3d9c5",
      "runner_issue_codes": []
    },
    "anomaly_detection": {
      "status": "complete",
      "report_id": "anomaly_detection-AN-R-6e483e43a0ad-r0-5a7d3a9f",
      "runner_issue_codes": []
    },
    "diagnostic_reasoning": {
      "status": "degraded",
      "report_id": "diagnostic_reasoning-AN-R-6e483e43a0ad-r0-75b2f9a9",
      "runner_issue_codes": []
    },
    "inspection_planning": {
      "status": "insufficient_evidence",
      "report_id": "inspection_planning-AN-R-6e483e43a0ad-r0-8f57d108",
      "runner_issue_codes": []
    },
    "evidence_verification_decision": {
      "status": "degraded",
      "report_id": "evidence_verification_decision-AN-R-6e483e43a0ad-r0-1e6892aa",
      "runner_issue_codes": []
    }
  },
  "decision": {
    "decision_state": "more_evidence_required",
    "advisory_only": true,
    "human_decision_required": true,
    "automatic_action_authorized": false,
    "equipment_condition_confirmed": false
  },
  "persistence": {
    "rule": {
      "k": 2,
      "n": 3,
      "threshold": 1.741168691251317
    },
    "windows_held": 1,
    "windows_exceeding": 0,
    "windows_unknown": 0,
    "alarming": null
  },
  "runner_note_codes": [
    "ASSETS_NOT_IN_DECLARED_GRAPH",
    "NO_BUDGET"
  ]
}
```

Shortened here, complete in the real response: `runner_note_codes` has 9 items; 2 are shown.

## Run status, report and truth

**GET /api/runs/{id}/status (status 200)**

```json
{
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "speed": 1000000.0,
  "episode_id": "EP-83C470077267",
  "split": "validation",
  "reveal_truth": true,
  "status": "completed",
  "events": 20
}
```

`GET /api/runs/{id}/report` is the maintenance report of Agent 7, built by the existing report assembly from the verified bundle of a window. It answers 409 until the run has finished. By default it is the last window; `?window=N` selects another by its window index. The report carries the wording of the agents' own findings, which is why it is a separate route and not part of the event stream.

**GET /api/runs/{id}/report (status 200)**

```json
{
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "window_index": 12,
  "windows_available": [
    1,
    2
  ],
  "report": {
    "report_version": "1.0.0",
    "report_id": "maintenance-AN-E0054-r0",
    "context": {
      "case_id": "E0054",
      "analysis_id": "AN-E0054-r0",
      "revision": 0,
      "as_of_s": 3600.0,
      "as_of_utc": null,
      "data_release": "verum_reference_v2",
      "reference_snapshot_sha256": "06a342dfb9839b9eca042dc95fded016d91d11fdbeb5b7f58d31357b39e20403",
      "scope_id": "verum_supported_reference_v2",
      "execution_mode": "runtime"
    },
    "report_type": "maintenance_assessment",
    "title": "Maintenance assessment",
    "review_status": "human_review_required",
    "assessment_state": "review_required",
    "source_reports": [
      {
        "report_id": "anomaly_detection-AN-E0054-r0-77542686",
        "agent": "anomaly_detection",
        "content_sha256": "adb55853ab2f075d9f687ac304d6d885ddab9ed9e1511976bf8e3b15bab51f6e"
      },
      {
        "report_id": "diagnostic_reasoning-AN-E0054-r0-bc374b40",
        "agent": "diagnostic_reasoning",
        "content_sha256": "27afb9fb4aaa5f203a53cea7cce1a6d05eb7bee49fe93406f472d4503d1b5a27"
      }
    ],
    "findings": [
      {
        "finding_id": "assessment-evidence_verification_decision-AN-E0054-r0-724a289b",
        "kind": "assessment",
        "statement": "Review required: the measured flows and pressures have departed from their usual relations in at least 2 of the last 3 windows. Equipment condition is not confirmed. Required evidence or verification also remains unavailable.",
        "measurement": null,
        "source_report_id": "evidence_verification_decision-AN-E0054-r0-724a289b",
        "evidence_ids": [
          "diagnostic_reasoning-AN-E0054-r0-bc374b40",
          "inspection_planning-AN-E0054-r0-8c96e50a"
        ]
      },
      {
        "finding_id": "hypothesis-HYP-01-bias-unlocalised",
        "kind": "hypothesis",
        "statement": "Unconfirmed hypothesis: bias (asset=None, tag=None); score: decision_score=0.464509, method=ovr_hist_gradient_boosting_v1_low_support_uncalibrated, calibration=None",
        "measurement": null,
        "source_report_id": "diagnostic_reasoning-AN-E0054-r0-bc374b40",
        "evidence_ids": [
          "features-summary",
          "predictive_health-AN-E0054-r0-8cc9bac9"
        ]
      }
    ],
    "inspection_options": [],
    "next_steps": [
      {
        "description": "Review the window-level departure and the proposed candidates before any operational decision.",
        "source_report_id": "evidence_verification_decision-AN-E0054-r0-724a289b",
        "evidence_ids": [
          "diagnostic_reasoning-AN-E0054-r0-bc374b40"
        ]
      },
      {
        "description": "Obtain and verify missing or unresolved evidence before making an assessment.",
        "source_report_id": "evidence_verification_decision-AN-E0054-r0-724a289b",
        "evidence_ids": []
      }
    ],
    "missing_information": [
      "Failed agent report: inspection_planning status=insufficient_evidence; first issue: NO_COMPATIBLE_INSPECTION_OPTIONS",
      "Inspection options unavailable: inspection_planning status=insufficient_evidence; issues: NO_COMPATIBLE_INSPECTION_OPTIONS"
    ],
    "limitations": [
      "Forecast reports are not used as model features.",
      "Window score 170.56 (the largest computed residual, in fault-free scale units) against the window threshold 3.03: exceeded."
    ],
    "narrative": {
      "provider": "template",
      "model": null,
      "prompt_id": null,
      "text": "Review required: the measured flows and pressures have departed from their usual relations in at least 2 of the last 3 windows. Equipment condition is not confirmed. Required evidence or verification also remains unavailable.",
      "source_report_ids": [
        "evidence_verification_decision-AN-E0054-r0-724a289b"
      ]
    },
    "advisory_only": true,
    "human_decision_required": true,
    "automatic_action_authorized": false,
    "equipment_condition_confirmed": false
  }
}
```

Shortened here, complete in the real response: `windows_available` has 8 items; 2 are shown; `report.source_reports` has 8 items; 2 are shown; `report.findings.evidence_ids` has 3 items; 2 are shown; `report.missing_information` has 4 items; 2 are shown; `report.limitations` has 41 items; 2 are shown.

**GET /api/runs/R-000000000000/report (status 404)**

```json
{
  "error": "unknown run"
}
```

`GET /api/runs/{id}/truth` answers only for a run created with `reveal_truth` true on a validation episode, and says in its `label` that the content is simulation truth that the agents never see. Do not mix it into the event stream of the screen the agents are judged on.

**GET /api/runs/{id}/truth (status 200)**

```json
{
  "label": "simulation truth, not visible to the agents",
  "run_id": "R-6553c35b6022",
  "mode": "replay",
  "episode_id": "EP-83C470077267",
  "windows": [
    {
      "window_index": 11,
      "as_of_s": 3300.0,
      "fault": true,
      "asset_ids": [
        "E-PB2"
      ],
      "fault_types": [
        "PIPE_LEAK"
      ],
      "mechanisms": [
        "leak"
      ]
    },
    {
      "window_index": 12,
      "as_of_s": 3600.0,
      "fault": true,
      "asset_ids": [
        "E-PB2"
      ],
      "fault_types": [
        "PIPE_LEAK"
      ],
      "mechanisms": [
        "leak"
      ]
    }
  ]
}
```

Shortened here, complete in the real response: `windows` has 8 items; 2 are shown.

**GET /api/runs/{id}/truth without reveal_truth (status 404)**

```json
{
  "error": "truth is not enabled for this run"
}
```

## Cross-origin use

The origin `http://localhost:5173` is echoed in `Access-Control-Allow-Origin` on every response, with `Vary: Origin`; other origins get no such header. A preflight `OPTIONS` answers 204 with the methods GET, POST and OPTIONS and the headers Content-Type and Last-Event-ID.
