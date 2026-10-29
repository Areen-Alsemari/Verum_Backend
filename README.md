# VERUM backend

VERUM is a synthetic simulator of a gasoline receipt, storage and distribution
terminal. It is intended to produce physically consistent hidden state, a
separate set of instrument observations derived from that state, and simulated
inspection results, so that diagnostic reasoning over several assets can be
studied without field data.

This repository is the backend of a larger system. It holds the configuration
contracts, the JSON schemas that define the data interface, the parameter and
release-gate infrastructure, and, in later phases, the simulation engine. A
frontend will live in a separate repository and will consume the schemas
published here.

## Scope of the current phase

Phases 0 to 2 cover infrastructure, topology, tanks, lineups, the inventory
ledger, the protection logic and steady-state hydraulics. They contain:

- the audited input package, vendored unmodified under `vendor/verum_audited/`
  with SHA-256 hashes in `vendor/MANIFEST.sha256`;
- the six interface schemas in `schemas/` and the machine-readable contracts in
  `config/`, both copied unchanged from the audited package;
- a parameter model in which an unresolved value cannot be read
  (`verum.params`);
- loaders and validators for the contracts and schemas (`verum.contracts`);
- a graph view of the topology with lineup-dependent connectivity and route
  geometry (`verum.graph`);
- tank calibration, roof state and the response-headroom screen
  (`verum.tanks`);
- the sixteen operating lineups and their transition rules
  (`verum.lineups`);
- inventory ledgers driven by prescribed flows (`verum.ledger`);
- steady-state network hydraulics: friction, pump, boundaries, fitting profiles,
  phase and NPSH gate (`verum.hydraulics`; see `docs/steady_hydraulics.md`);
- the independent protection state machine, as pure logic
  (`verum.protection`);
- a fail-closed dataset release gate (`verum.gates`);
- tests for the above and a record of design decisions in
  `docs/design_decisions.md`.

Transient hydraulics, faults and sensors are not implemented; ledgers and
protection are driven by prescribed or injected signals. The release policy
in `config/dataset_release_policy.json` keeps `production_generation_enabled`
false, and the gate refuses the `production_candidate` tier while it is false.

## Data provenance

All physical values are synthetic simulation or design selections. They do not
describe an as-built terminal, and none is a measurement. Parameters that are
not selected are represented as unresolved and raise an error when read.

## Layout

| Path | Contents |
| --- | --- |
| `vendor/` | Audited input package, read-only, with hash manifest |
| `config/` | Machine-readable contracts used by the loaders |
| `schemas/` | JSON Schemas that define the interface contract |
| `src/verum/` | Package: `params`, `contracts`, `gates`, `graph`, `tanks`, `lineups`, `ledger`, `protection`, `hydraulics`, `api` |
| `tests/` | `analytic`, `schema`, `leakage`, `regression` |
| `docs/` | Design records |

## Setup and tests

Python 3.11 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --group dev
```

```bash
uv run pytest
```

Repository conventions are described in `CONTRIBUTING.md`.
