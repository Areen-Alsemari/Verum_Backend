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

An upstream report is registered with `registry.add_report(report)`. It returns the normalised copy that must be placed in the input, because the registered hash covers exactly that copy. The registry computes the report's roots, availability and source reference. Rebuild the request evidence from `registry.rows()` afterwards.

A response is built with `build_response(request, status=..., result=..., consumed_evidence_ids=..., implementation=implementation_block(name, version), issues=..., limitations=...)`. It copies the context exactly, derives the report identifier, and refuses a result next to an `error` or `insufficient_evidence` status, and either of those statuses without an issue. Call `check_request(request)` before inference and `check_response(request, response)` before returning. Both reuse the loaded schemas.

## Identifier rules

- The analysis identifier is `AN-<case_id>-r<revision>`.
- The report identifier is `<role>-<analysis_id>-<eight hex digits>`, where the digits are the start of the content hash of the request identifier and the role. The same request always gives the same report identifier.
- Source evidence identifiers may not start with a role key followed by a hyphen, so a source row can never collide with a report row. The registry refuses duplicates and the response builder refuses a report identifier already present in the request.

## The number rule

Integral numbers are written as integers: 300.0 becomes 300 before a message is hashed or embedded, so both spellings give one hash. `normalise` and `stable_hash` apply the rule, and the registry and builders call them for you. NaN, infinities and numpy scalars or arrays are rejected with an error rather than converted, so convert model outputs with `float(...)` before they enter a message. Hashes in the shipped example messages predate this rule and keep their original spelling; they are validated as they are.

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
