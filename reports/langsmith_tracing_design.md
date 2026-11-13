# LangSmith tracing in the runner: design

Read-only survey made before any code. Branch `langsmith-tracing`, from `runner-agent6-targets` (cf27382). No file under `data/` was opened, no environment file or key was read.

## 1. Where the runner enters each window

| step | place | what happens |
|---|---|---|
| analysis of one window | `run_analysis`, `src/verum/agents/runner/run.py:106` | prepares the shared inputs (`prepare`, line 126), then runs every role of every manifest stage (lines 128-130), stores the assessment log, checks placeholders, and calls `verify_bundle` only when a `previous` verified bundle is passed (line 138) |
| one agent call | `_run_role`, `run.py:79`; the agent itself is reached in `_call`, `run.py:43-48` (`agent.run(request)`, in a worker thread when `timeout_s` is set) | builds and checks the request, calls the agent, validates the response, registers the report. A failing agent becomes an issue in the bundle, never an exception |
| verification | `verify_bundle`, `src/verum/agents/runner/bundle.py:176` | called inside `run_analysis` for a revision, and by the caller for a first revision (`chained.py:31`, `tools/agents/run_runner_sample.py:306-308`) |
| final report | `build_report`, `src/verum/agents/inspection_quality_documentation/report.py:292` | belongs to the Agent 7 package, takes a verified bundle, and is called by the caller after `verify_bundle` (`run_runner_sample.py:314`). The runner package does not call it |

Consequences for the design:

- The parent trace and one child per role can be placed in `run_analysis` and `_run_role`, inside the runner package.
- `verify_bundle` is usually called after `run_analysis` has returned. Its child is attached to the parent trace of the window through a handle kept on the bundle (a late child of a run that has already ended; LangSmith accepts this and shows it in the same trace).
- `build_report` is outside the runner package and the task forbids changing an agent, so it is not traced. This is stated in the docs as a limit.
- The window has no index in the runner. The snapshot carries `case_id`, `revision` and `as_of_s`. The case identifier is the run's identifier (`E0000` in the chained sample, the episode in later use); the window index is passed by the caller when known and otherwise derived as `as_of_s / 300` only if that is a whole number (300 s is the observation window of the sample). Nothing else is guessed.

## 2. The langsmith package

Not installed in `.venv` and not found anywhere on the machine. With the user's permission the wheel `langsmith-0.14.17-py3-none-any.whl` (941 kB, PyPI) was downloaded into the scratchpad only and unpacked there; it was not installed. The facts below come from its own source and metadata.

- Requires Python >= 3.10. Hard dependencies include `pydantic>=2`, `requests`, `httpx2`, `orjson`, `zstandard`, `websockets`, `anyio`, `xxhash`, `uuid-utils`. This is a large dependency set, which is why it must be an optional extra and not a requirement of `verum`.
- Switch: `langsmith.utils.tracing_is_enabled` (`utils.py:119`) reads, in this order, a tracing-context override, a current run, a global fallback, and then the environment variable `LANGSMITH_TRACING_V2` or `LANGSMITH_TRACING` (`LANGCHAIN_` prefix as fallback) equal to `"true"`. `get_env_var` (`utils.py:395`) is cached with `lru_cache`, so a variable changed after its first read is not seen again by the package. The runner therefore reads the switch itself, from `os.environ`, and does not depend on the package's reading.
- Other variables: `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`. Their values are never read, printed or stored by the runner code except that the key is checked for presence.
- Tracing API used: `langsmith.run_trees.RunTree` (`run_trees.py:403`) with `create_child` (line 706), `end`, `post` and `patch`, and `langsmith.Client` (`client.py:1017`; arguments include `api_url`, `api_key`, `auto_batch_tracing`, `hide_inputs`, `hide_outputs`, `hide_metadata`). `langsmith.run_helpers.trace` (`run_helpers.py:968`) is a context-manager alternative; it consults the ambient tracing state, so the explicit run tree is preferred here because it can be driven from a stub and does not read global state.
- Runs are posted to a background batching thread; a network failure is logged by the package and not raised into the caller in the normal path. The runner still wraps every call in `try/except` because that behaviour is the package's, not the runner's guarantee.

## 3. Design

A new module `src/verum/runner`-side file, `src/verum/agents/runner/tracing.py` (the runner package is `verum.agents.runner`; the task's `src/verum/runner/tracing.py` is read as that package).

1. A small internal interface, `Sink`, with `start(name, kind, inputs, tags, metadata, parent) -> Span` and `Span.end(outputs, error)`. The runner code talks only to this interface.
2. `NoopTracer`, the default: every method returns immediately; no import of `langsmith`, no environment read beyond the one switch check, no thread, no file.
3. `LangSmithSink`, the only code that imports `langsmith`, imported lazily inside the constructor, only when the switch is on and a key is present. If the import fails, the tracer falls back to the no-op.
4. A tracer is chosen once per `run_analysis` call by `tracer_for_run()`: off unless `LANGSMITH_TRACING` is `true` and `LANGSMITH_API_KEY` is non-empty. A test or caller may pass a sink explicitly (`tracer_with(sink)`), which is how the stub client is used without network.
5. Every call into the sink is wrapped so that any exception is swallowed, logged at debug level without the message payload, and the span becomes inert. The traced block itself runs outside the wrapper, so an exception from the analysis passes through unchanged.
6. Parent run `verum.run_analysis` (type chain), children `agent:<role>` (type chain) with status in the outputs, and `verum.verify_bundle`.
7. Inputs and outputs are summaries only (section 4).
8. Metadata: `case_id` (the episode or run identifier), `window_index`, `as_of_s`, `revision`, `execution_mode`, `contract_version`, `git_commit`, and `inspection_parameters_sha256` when `verum.inspection.parameters.parameters_digest` exists. That function is on the branch `inspection-review-fixes` and not on this branch, so here it is absent and the field is omitted. Tags: `synthetic`, `verum`, and `contract:<version>`.
9. The bundle gets one new optional field, `trace`, with `compare=False` and `repr=False`, which holds the parent handle for the late `verify_bundle` child. It is not part of any request or response, and the persistence code does not serialise the dataclass (checked: no `asdict` over the bundle in `src`).
10. Contract version: `interface_version` of `contracts/agents/v1/manifest.json`. Git commit: `git rev-parse HEAD`, read once, only when tracing is on; `unknown` if git is not available.

## 4. What is sent and what is not

Sent: identifiers (case, report ids), role names, report statuses, counts (issues, notes, evidence rows, requests, reports), the Agent 8 decision state and its three fixed flags (`human_decision_required`, `automatic_action_authorized`, `equipment_condition_confirmed`), the `advisory_only` flag of each report, the runner issue codes (`AGENT_TIMEOUT`, `AGENT_ERROR`, `AGENT_INVALID_RESPONSE`, `REQUEST_INVALID`), and a SHA-256 digest of each request and report.

Not sent: any request or response body, observation values, the reference, the history, free text of an agent (summary, limitations, issue messages), hypothesis names, agent issue codes (which may carry mechanism words), the sample row labels, `data/` contents, the API key. Ground-truth labels never reach the runner at all (the snapshot has no label field); the summaries are built from fixed keys, so an unexpected key cannot be forwarded.

## 5. Plan for gates

The 181-window byte-identity check needs the observation summaries of the sample, which come from the train and validation role views. It will be a script (`tools/agents/check_tracing_identical.py`) that reuses the sample code of `run_runner_sample.py` and runs under the audit hook (`tools/detector/guard.py`), and compares requests and reports with the stored bundles of the run `out_t6_after`, the baseline of this branch's parent. The pytest tests use the synthetic case of `tests/_runner_cases.py` and need no data. The bare full `pytest` is not run (about 78 minutes).

Environment limits found here: `uv` is not installed, so `uv.lock` cannot be regenerated by the tool; `langsmith` is not installed in `.venv`, so tests of the package-backed sink run only against a fake module, and the real-package tests skip.
