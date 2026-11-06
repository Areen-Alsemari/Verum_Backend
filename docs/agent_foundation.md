# Agent foundation

This page is for the five members building the eight agents. The foundation gives every role a package, a placeholder agent that already passes the message contract, and the shared helpers for identifiers, evidence, observations and data. Nobody needs to wait for another member: start from your placeholder and replace its behaviour.

## Where things live

| What | Location |
| --- | --- |
| Shared helpers | `src/verum/agents/common/` |
| One package per role | `src/verum/agents/<role>/` with `agent.py` holding the agent class |
| Tests of a role | `tests/agents/<role>/` |
| Tests of the shared helpers | `tests/agents/common/` |
| Per-role scripts | `tools/agents/`, which holds `check_stubs.py` to run every role's agent on its example request |
| Message contract | `contracts/agents/v1/` and `src/verum/contracts/agent_interfaces.py` |

The role keys are `predictive_health`, `anomaly_detection`, `topology_dependency`, `historical_asset_intelligence`, `diagnostic_reasoning`, `inspection_planning`, `inspection_quality_documentation` and `evidence_verification_decision`. The tuple `ROLES` in the helpers lists them in manifest order.

## The import rule

Agent code imports only `verum.contracts`, `verum.agents.common` and its own package. It never imports another role's package, `verum.training` or `verum.truth`. Importing the training package loads the truth store, so the shared reader in the helpers replaces it. The leakage tests enforce this, both by scanning the imports and by importing every agent module in a fresh interpreter.

## The placeholder

Each role package exposes an agent class, for example `PredictiveHealthAgent`, which implements `run(request) -> response`. The placeholder validates the request, answers with the role's conservative example result bound to the incoming request, validates its answer, and marks itself as a placeholder in its implementation name, its issue and its limitations. If the example result does not fit the request's evidence it returns `insufficient_evidence` with one issue instead. To implement a role, replace the base class in the role's `agent.py` and keep the class name and the `run` signature.

## Building messages

The helpers are re-exported from `verum.agents.common`. A typical runtime request is built like this:

```python
from verum.agents.common import (
    EvidenceRegistry, attach_summary, build_request, make_context_from_reference,
)

context = make_context_from_reference(
    reference_file, case_id="C7", revision=0, as_of_s=300.0, execution_mode="runtime"
)
registry = EvidenceRegistry(context)
registry.add_source("src-obs", "observation_window", "window-300", 300.0, window_sha256)
registry.add_source("src-ref", "declared_reference", "public_reference", 0.0, snapshot_sha256)
observations = attach_summary(
    registry, summary, evidence_id="feat-summary", locator="summary-300",
    root_ids=["src-obs"], available_at_s=300.0,
)
request = build_request("predictive_health", "REQ-1", registry, {
    "observations": observations, "target_tag_ids": ["FT-001"], "forecast_horizon_s": 300.0,
})
```

An upstream report is registered with `registry.add_report(report)`. It returns a plain copy of the report, equal to the original, and the registered hash is the contract hash of that copy. Place the report (or the returned copy) in the input unchanged: the validator hashes exactly what is embedded. The registry computes the report's roots, availability and source reference. Rebuild the request evidence from `registry.rows()` afterwards.

A response is built with `build_response(request, status=..., result=..., consumed_evidence_ids=..., implementation=implementation_block(name, version), issues=..., limitations=...)`. It copies the context exactly, derives the report identifier, and refuses a result next to an `error` or `insufficient_evidence` status, and either of those statuses without an issue. Every agent must list each upstream report attached to its request in `consumed_evidence_ids`, using the report's `report_id`, even when its result does not depend on the report. The runner rejects a response that leaves one out (`AGENT_INVALID_RESPONSE`) and `verify_bundle` raises `BundleError`; `attached_report_ids(request)` returns the identifiers to include. Call `check_request(request)` before inference and `check_response(request, response)` before returning. Both reuse the loaded schemas.

## Identifier rules

- The analysis identifier is `AN-<case_id>-r<revision>`.
- The report identifier is `<role>-<analysis_id>-<eight hex digits>`, where the digits are the start of the content hash of the request identifier and the role. The same request always gives the same report identifier.
- Source evidence identifiers may not start with a role key followed by a hyphen, so a source row can never collide with a report row. The registry refuses duplicates and the response builder refuses a report identifier already present in the request.

## The number rule

Numbers keep the type they have, and the helpers never rewrite them. The contract hashes a message exactly as written, so 300 and 300.0 give different hashes on purpose, and the helpers always hash what the validator hashes: `stable_hash(x)` equals the contract `content_hash(x)` for any plain message. Keep one spelling per value in your own code, since a client that rewrites 300.0 as 300 changes the hash of a report. NaN and infinities are rejected. Numpy scalars are converted to Python numbers at the boundary by `to_plain`, and numpy arrays are rejected, so convert arrays with `.tolist()` before they enter a message. The example messages shipped with the contract are used as they are.

## Observations and tag order

`TAG_ORDER` is the single fixed order of the 30 emitted tags, which is the sorted tag list of the public reference. Save it with every model's feature order. `summary_representation` and `attach_summary` wrap a prepared summary in the `summary_v1` request representation and put the signals in this order. A summary with a missing, extra or repeated tag is refused. There is no `sequence_v1` builder yet.

## Reading prepared data

`iter_role_records(release_root, role, split)` yields `RoleRecord` objects with `example_id`, `input`, `target` and `use`. It checks the role file against the release inventory unless `verify=False`. `episode_lookup(release_root, split)` returns a separate mapping from example identifier to `EpisodeRef`, read from the example lineage files. Use it to group or split by episode and never place it in a model input. It needs the full release folder, not only the training bundle.

## Tests

- Name test files `test_<role>_<topic>.py` inside `tests/agents/<role>/`. File names must be unique across the whole test tree because the folders are not packages.
- Every test docstring ends with a sentence starting `Independent:` that says why the check is or is not independent of the code under test.
- Module docstrings are required, and docstrings may not contain repository paths or file names.
- Run `uv run pytest -q tests/agents`, `uv run ruff check src tests` and `uv run mypy` before committing.

## Shared files

Edit the shared helpers, the contract validator, the schemas, `pyproject.toml` and `uv.lock` only through one reviewer so that parallel work does not collide. A new dependency is added with `uv add`, never by editing the lock file.

## Chained fixtures

The folder `tests/agents/fixtures/chained/` holds one runtime snapshot answered by all eight placeholders: a request and a response for every role, and `index.json` with the context, the run order and the report identifiers. Every request after the first carries the real, hashed reports of the roles it depends on, so you can test your agent against genuine upstream input instead of the empty contract examples. Load a request with `json.load`, call `check_request`, run your agent, and call `check_response`.

Regenerate the files with `uv run python tools/agents/build_chained_fixtures.py` from a checkout that has the extracted release folder. The `--release` option points at another release folder and `--output` at another target. The script always answers with the placeholders so that the files stay the same while owners replace their agents; add `--installed-agents` to see a run with whatever is installed. The `--check` option compares the files on disk with a fresh run and exits with status 1 if they differ. The files are indented, key-sorted JSON with a trailing newline, so a change shows as a readable diff. A fast test, `test_the_committed_chained_fixtures_are_not_stale`, runs the same comparison as `--check` with the placeholders and fails when the files are out of date. The rule: whenever you change the request builders, the runner, the shared helpers, the placeholders or the contract, run the script without options, review the diff, and commit the regenerated files together with your change. Never edit the files by hand.

## The runner

`verum.agents.runner` runs all eight roles on one snapshot. It is a plain function, with no framework and no role logic.

```python
from verum.agents.runner import Snapshot, next_revision, run_analysis, verify_bundle

snapshot = Snapshot(
    case_id="C7", revision=0, as_of_s=300.0, summary=summary, reference=reference,
    reference_snapshot_sha256=reference_file_sha256,
)
bundle = run_analysis(snapshot, "runtime")
verified = verify_bundle(bundle)
```

The summary is a prepared observation summary, for example the `observations` input of a role record, and the reference is the public reference. Optional snapshot fields carry what a caller can supply: the queried assets and direction, history, inspection results and requests, process coverage, constraint checks, a budget and evidence proposals. Whatever is not supplied is left at the contract's empty or null value, and `bundle.notes` records each such gap by role and code. Nothing is invented. Declared facts carry a unit or a parameter status only where the reference states one.

The roles run in the stage order of the interface manifest. Each request is built from the snapshot and the reports so far, validated, sent to the agent, and the response is validated again. A valid report is registered in the evidence registry with its roots and embedded unchanged in the requests that need it. If an agent raises, returns something invalid, returns a report of another snapshot or mode, ignores an attached report, or exceeds `timeout_s`, its report is null, `bundle.issues` gets a structured entry with the role and a code, nothing is added to the registry, and the run continues. The codes are `AGENT_ERROR`, `AGENT_TIMEOUT`, `AGENT_INVALID_RESPONSE` and `REQUEST_INVALID`. The timeout only stops the runner from waiting: the worker thread that runs the agent is abandoned, not killed, so a slow agent keeps running in the background until it returns. Leave `timeout_s` unset, which is the default, to call agents directly without a thread.

The runner finds the agent of a role by convention. The file `verum/agents/<role>/agent.py` must contain exactly one class whose name ends in `Agent` and which has a `run` method, or a function called `create_agent` that returns an agent; the factory wins if both exist, and two agent classes in one file are an error reported as `AGENT_ERROR`. Classes imported from elsewhere do not count, only those defined in the file. Replace the placeholder in that file and the runner uses it with no other change. Tests can pass `agents={role: instance}` to `run_analysis` instead.

Each role served by a placeholder gets a non-blocking note with the code `PLACEHOLDER_AGENT` in `bundle.notes`; a role counts as a placeholder when its agent is a `StubAgent` or its report carries the stub issue. Both `run_analysis` and `verify_bundle` take `allow_placeholders`, which is true by default. With `allow_placeholders=False` they raise `BundleError` naming the roles still served by placeholders, which is the setting to use once every role is implemented.

`verify_bundle` checks every message again and the rules that span the whole analysis: every report has the case, analysis, revision, cutoff, reference snapshot and execution mode of the bundle; no fixture-mode report appears in a runtime request; each response lists every report attached to its request among its consumed evidence; report identifiers are unique and never equal an evidence identifier; and each report is registered under its own content hash. It returns the context, the validated responses and the evidence rows, which is what Agent 7's report assembly receives.

A new inspection result starts a new analysis. Call `next_revision(snapshot, as_of_s=..., summary=..., inspection_results=...)` with observations prepared for the later cutoff, and run it again with `previous=verified` to check that the revision increased and the analysis identifier changed. The earlier results, requests and coverage carry over, and no earlier report is reused: all eight roles run again against a fresh registry.
