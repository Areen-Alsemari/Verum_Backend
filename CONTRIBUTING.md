# Contributing

This document states the rules that apply to every change to this repository.

## Data exposure

1. Any interface served to a frontend or an agent exposes only the
   agent-visible datasets: assets, observations, history, the inspection
   catalog, and performed inspection results. An inspection result is visible
   only when its `workflow_status` is `performed`.
2. The following datasets are never served: `ground_truth`, `hydraulic_state`,
   `fault_truth`, `solver_diagnostics`, `mass_ledger`, `observation_audit` and
   `simulation_rejected`. A quantity from hidden state reaches an agent only
   through a defined instrument and its measurement chain.
3. The schemas in `schemas/` are the interface contract. They are versioned,
   and consumers generate their types and validators from them rather than
   copying them. A breaking change to a schema is a major version change.

Truth and observation code stay in separate packages, and the observation
package imports no truth type. The `verum.api` package contains no code until a
read-only interface is designed; the leakage tests check that.

## Inputs and configuration

- The audited input package is kept locally under `vendor/verum_audited/`, is
  never edited, and is not tracked. `vendor/MANIFEST.sha256` records the hash of
  every file and is committed. `config/reference/` holds unmodified copies of
  the machine-readable files that tests need; a regression test checks them
  against the manifest. Checks that need the full package live in
  `local/checks/`.
- `schemas/` stays byte-identical to the reference schemas. A contract in
  `config/` that differs from its reference copy is changed only through a patch
  file in `config/patches/`, with the field path, old value, new value and
  reason; a test applies the patches to the reference and compares the result.
- Every physical or numerical parameter is a `ParamValue` with a unit, a status,
  an evidence tag and, when it has a value, a provenance identifier. A parameter
  that has not been selected is unresolved. Reading it raises
  `UnresolvedParameter`. No code supplies a default, a zero or a typical value
  in its place.
- Internal units are SI. Every pressure states its basis (absolute or gauge).
- Random numbers come from named, seeded streams. No global seed is used.
- All values in the configuration are synthetic selections. They are not
  measurements and are not described as validated.

## Release gate

`verum.gates.assert_release_allowed` refuses the `production_candidate` tier
while `production_generation_enabled` is false in
`config/dataset_release_policy.json`, and, when it is true, until every required
gate has passed. Failures to simulate are stored as rejected candidates and are
never shown to an agent.

## Tests

- Tests are never skipped, weakened or deleted to make a change pass. A failing
  test is investigated and the cause is recorded.
- Tests of a reduced model are not independent validation of the full model and
  are not described as such.
- A phase is closed only when the complete suite (both marker groups, `fast` and `slow`),
  `ruff`, `mypy` and `local/checks` pass after the last edit of the phase. A run made before a
  later edit, including an edit to a test, a document or a configuration file, does not close
  the phase; a partial re-run of the affected tests is a check, not a closing run.
- Tests live in `tests/analytic`, `tests/schema`, `tests/leakage` and
  `tests/regression`.

```bash
uv sync --group dev
```

```bash
uv run pytest
```

```bash
uv run ruff check src tests
```

```bash
uv run mypy
```

## Code conventions

- Python 3.11 or later, `src` layout, package name `verum`.
- Every `.py` file, including every test file, begins with a module docstring
  that states what the module does, its inputs and outputs, its key
  assumptions, and the source document and section it implements. A test checks
  this.
- Comments explain why, not what. Code is not narrated.
- Type hints are used throughout and `mypy --strict` passes. Functions are short.
- Dependencies are locked in `uv.lock`. Changing a dependency means updating the
  lock file in the same commit.
- Code, documentation and commit messages use a neutral, professional voice. They
  contain no emojis and no mention of the tools used to write them.

## Commits

- One commit per task or significant change.
- The message is a single imperative line, for example "Add topology loader".
- No trailers. History is not rewritten once shared.

## Design decisions

Modelling and numerical decisions are recorded in `docs/design_decisions.md` as
versioned records. A change adds a new version of a record; it does not edit the
old one.
