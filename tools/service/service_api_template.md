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

{{HEALTH}}
The facility is taken from the topology contract, the canonical sensor contract and the sensor specifications of the repository. Nothing is added: there are no drawing coordinates, a tag is placed on the element its measured-variable reference names, and a tag the contract withholds has status `withheld` and no reading.

{{FACILITY}}
`/api/episodes?mode=replay|live` lists the episodes a run can be created on, with their split and window count.

{{EPISODES}}
## Creating a run

`POST /api/runs` takes a JSON object: `mode` (`replay` or `live`, required), `speed` (a number above 0 and at most 1000000, default 60), `episode_id` (optional; by default the episode with the most windows) and `reveal_truth` (boolean, default false). It answers 201 with the run and the links of its routes.

{{CREATE}}
A live run is created the same way.

{{LIVE_CREATE}}
{{BAD_SPEED}}
## The event stream

`GET /api/runs/{id}/events` is a Server-Sent Events stream. A frame is three lines and a blank line: `id` (the sequence number), `event` (the type) and `data` (one JSON object). A comment line `: keepalive` is sent when nothing happens. The stream ends after the `done` event. To resume after a dropped connection send the header `Last-Event-ID` or the query `?after=` with the last sequence number received; a late reader receives the whole run from the start.

{{FRAME}}
Each window gives `sensor_reading`, then `window_result`, then `alert` if the persistence rule fires, and the run ends with one `done`.

```javascript
const source = new EventSource(`http://localhost:8765/api/runs/${runId}/events`);
for (const type of ["sensor_reading", "window_result", "alert", "done"]) {
  source.addEventListener(type, (message) => handle(type, JSON.parse(message.data)));
}
```

`sensor_reading` holds the tags of the window: the latest value, the mean, minimum and maximum over the 300 s window, the quality and the availability. A tag that is a contact has no statistics.

{{SENSOR}}
`window_result` holds the status of each of the eight agents in the order of the interface manifest (`status` is null and `runner_issue_codes` says why when an agent failed), the decision of Agent 8 with its fixed flags, the persistence statement that the runner gave Agent 8, and the notes of the runner. The decision never authorises an action and never confirms an equipment condition; the flags say so.

{{RESULT}}
`alert` is sent when the persistence rule that Agent 2 published (k of the last n windows above the threshold) is satisfied in this window.

{{ALERT}}
`done` ends the run. `status` is `completed`, `failed` (with the type of the error) or `stopped`.

{{DONE}}
This is a `window_result` of a live run; it has the same shape.

{{LIVE_RESULT}}
## Run status, report and truth

{{STATUS}}
`GET /api/runs/{id}/report` is the maintenance report of Agent 7, built by the existing report assembly from the verified bundle of a window. It answers 409 until the run has finished. By default it is the last window; `?window=N` selects another by its window index. The report carries the wording of the agents' own findings, which is why it is a separate route and not part of the event stream.

{{REPORT}}
{{NOT_FOUND}}
`GET /api/runs/{id}/truth` answers only for a run created with `reveal_truth` true on a validation episode, and says in its `label` that the content is simulation truth that the agents never see. Do not mix it into the event stream of the screen the agents are judged on.

{{TRUTH}}
{{TRUTH_OFF}}
## Cross-origin use

The origin `http://localhost:5173` is echoed in `Access-Control-Allow-Origin` on every response, with `Vary: Origin`; other origins get no such header. A preflight `OPTIONS` answers 204 with the methods GET, POST and OPTIONS and the headers Content-Type and Last-Event-ID.
