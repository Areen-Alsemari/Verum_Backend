# Run service: results

Branch `run-service`, from `langsmith-tracing` (a966b87). Three commits, none pushed, under the repository identity, no trailers. No agent, contract, schema, config or runner file was changed (the diff against the parent touches only `src/verum/service/`, `tests/`, `tools/service/` and `docs/`). The runner is called as it already is, with keywords it already had.

## 1. What was built

`src/verum/service/`, standard library only, no new dependency:

| file | role |
|---|---|
| `app.py` | the HTTP server (`ThreadingHTTPServer`), routes, JSON bodies, Server-Sent Events, CORS |
| `runs.py` | one thread and one event log per run, paced by the playback speed; `RunRegistry` |
| `sources.py` | `ReplaySource` (stored bundles) and `LiveSource` (the real runner, one assessment log per run) |
| `events.py` | builds `sensor_reading`, `window_result` and `alert` from a window record, by copying named fields only |
| `facility.py` | the facility from the topology contract, the canonical sensor contract and the sensor specifications |
| `guard.py` | audit hook that confines live mode to the validation split of the release |
| `__main__.py` | the command line |

Routes: `GET /api/health`, `GET /api/facility`, `GET /api/episodes?mode=replay|live` (added so a frontend can choose an episode), `POST /api/runs`, `GET /api/runs/{id}/events` (SSE; resumable with `Last-Event-ID` or `?after=`), `GET /api/runs/{id}/report` (`?window=N`), `GET /api/runs/{id}/truth`, `GET /api/runs/{id}/status`. The API, with a real example of every response and event, is in `docs/service_api.md`; `tools/service/render_api_doc.py` rewrites that document from a run of the service, so the examples are not typed by hand (long lists are cut to two items and each cut is named under its example).

How the requirements were met:

- **Per-run state.** A run owns its source; a live source creates its own `AssessmentLog` inside its window loop, and its case identifier is the run identifier. Nothing mutable is shared except the read-only validation data and the registry.
- **Labels.** Every event carries `mode`, `run_id`, `seq`, a `time_compression` object (factor and a note that it compresses the 300 s cadence and changes no value) and a `data` field saying the data is synthetic. Events are built from named fields, so nothing else can reach them; no agent free text, hypothesis name, label or fault name is copied.
- **Truth.** A separate route, 404 unless the run was created with `reveal_truth` true; refused (400) for a train episode; labelled "simulation truth, not visible to the agents". Replay keeps the stored labels apart from the records; live reads them from the validation role view and never forwards them.
- **Data access.** Live mode installs `guard.py` before the first read. It allows the knowledge folder, the inventory and the validation role views and examples, rejects paths with dots, and judges relative paths where they point. The first draft used the path as written, which let a relative path through; this was found while writing the test and fixed.
- **Tracing.** The live source calls `run_analysis` without a tracer, so the environment decides exactly as for any run, and passes the validation episode identifier and the window position as the existing trace metadata. A replay does not call the runner and makes no trace.

## 2. Gates

| gate | result |
|---|---|
| fast tests with `data/` | 2350 passed, 297 deselected, 0 failed, 0 skipped |
| ruff (`src tests tools`) | all checks passed |
| strict mypy (348 files) | no issues |
| interface check | 8 interfaces, 16 examples, passed |
| isolation checks (`tests/leakage`, the guard and import-boundary tests of the service) | 60 passed |
| documentation style tests | passed (the service files and `docs/service_api.md` are inside the fast run) |
| bare full `pytest` | not run, as instructed |
| mutation check | not run, as instructed |

The 31 new tests (`tests/service/`, helpers in `tests/_service_cases.py`) use a server on an ephemeral port on 127.0.0.1 and cover: the routes and the facility against the config; stream framing from raw bytes; event order and the single `done`; labels and time compression; alerts; a replayed window's agent statuses equal to the stored bundle, and the same for the real 181-window sample when `local/replay_sample` exists (it did here and the test ran); no planted label, fault word or hidden key in any event, revealed or not, replay or live; the truth switch; 404 for an unknown run on every run route and 400 or 404 for bad requests; CORS on GET, POST, the stream and the preflight, and no header for another origin; two simultaneous runs, replay and live, each equal to the same run alone; the live source calling the runner with unchanged arguments and its own persistence log; the tracing hooks posting spans when the environment enables them (against a fake package); the report refused with 409 and then built; a client disconnecting mid-stream, after which the run completes, the service answers and a second reader resumes from an event number; the guard; a fresh import of the service loading no truth, training, simulation, fault or sensor package; and one live run through the real runner on a validation episode, in a started process.

## 3. Commands run

```bash
git checkout -b run-service
PYTHONPATH=src .venv/bin/python -m verum.service --port 8799 --replay-dir local/replay_sample          # manual replay checks with curl
PYTHONPATH=src .venv/bin/python -m verum.service --port 8798 --release data/reference_release_v2/verum_reference_v2   # manual live check
.venv/bin/python -m pytest tests/service -q -p no:cacheprovider
PYTHONPATH=src .venv/bin/python tools/service/render_api_doc.py --replay-dir local/replay_sample --release data/reference_release_v2/verum_reference_v2
.venv/bin/ruff check src tests tools
.venv/bin/mypy
PYTHONPATH=src .venv/bin/python tools/check_agent_interfaces.py
.venv/bin/python -m pytest tests/leakage tests/service/test_service_guard.py -q -p no:cacheprovider
.venv/bin/python -m pytest -m fast -q -p no:cacheprovider
```

In the manual live check a validation episode of 5 windows ran in about 10 s at a speed of 1,000,000, with the data load taking about 3 s on the first request.

## 4. What could not be done, and limits

- **The stored sample is not in the repository.** The 181 stored bundles live in an output folder of an earlier run, in a temporary folder of a past session. They were copied to `local/replay_sample` (ignored by git, 6.4 MB) so that replay could be exercised. To rebuild them: `python tools/agents/run_runner_sample.py --chain --out local/replay_sample` (about 6 minutes, under the audit hook). Without that folder replay is off, and the one test that reads the real sample skips.
- **No browser was used.** The stream was checked with curl and with raw sockets and `http.client`, not with a browser `EventSource`. The headers are the standard ones (`text/event-stream`, `Cache-Control: no-cache`, CORS echo), but a browser pass remains to be done by whoever builds the frontend.
- **Steps 1 to 4 are one commit.** The endpoints, per-run state, labelling and tracing pass-through are one code base that cannot be split without commits that do not import; the tests and the documentation have a commit each.
- **Report scope.** `report` is the Agent 7 report of one window (the last by default), because a run covers many windows; the report of a run as a whole does not exist in the current report assembly, which was not changed.
- **Not protected, not scaled.** The service is for localhost: no authentication, no limit on concurrent live runs (each is a thread running the real agents), 50 runs kept in memory and evicted oldest-finished first, nothing written to disk. The audit hook, once installed, stays for the life of the process.
- **Replay of train windows.** The stored sample holds 12 train windows; they can be replayed but have no truth route, by design.
- **Pre-existing local changes.** `.gitignore` carried an uncommitted `.env` line and `reports/inspection_review_fixes.md` was untracked before this work; neither was committed.

## 5. Start command

From the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m verum.service --port 8765 --replay-dir local/replay_sample --release data/reference_release_v2/verum_reference_v2
```

It prints `verum service listening on http://127.0.0.1:8765`. Replay and live are independent: leave out `--release` for replay only, or `--replay-dir` for live only. `--port 0` picks a free port.
