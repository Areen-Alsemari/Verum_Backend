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

Phases 0 to 4 cover infrastructure, topology, tanks, lineups, the inventory
ledger, the protection logic, steady-state hydraulics, the path-dynamics engine and
healthy episodes, the sensor chain and a read-only gateway. They contain:

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
- the path-dynamics engine, the operations controller and the hidden truth
  store (`verum.sim`, `verum.ops`, `verum.truth`; see `docs/path_dynamics_engine.md`),
  with named random streams and configuration provenance (`verum.rng`,
  `verum.provenance`);
- the sensor chain from truth to observations (`verum.sensors`; see
  `docs/observation_chain.md`) and the read-only gateway (`verum.api`);
- a fail-closed dataset release gate (`verum.gates`);
- tests for the above and a record of design decisions in
  `docs/design_decisions.md`.

A standalone transient engine (`verum.transient`, a first-order method of characteristics
on the 28 edges; see `docs/transient_engine.md`) is a library with its own verification ladder.
It is not called by the episode engine and changes no dataset tier. Single faults (a pipe leak, a
valve restriction, a pump head degradation, sensor faults and valve misrouting) can be injected
into an episode through `verum.faults`; see `docs/fault_models.md`. A scenario names a healthy
variability profile (`off`, `v1`, or `v2` with demand regimes and a moving receipt set-point;
`docs/dataset_card.md`), a restriction is `position_visible` or `obstruction`, and a fault on an
asset that is not active in the lineup is labelled latent. Multi-fault episodes, a campaign
generator and agents are not implemented. The release policy
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
| `src/verum/` | Package: `params`, `contracts`, `gates`, `graph`, `tanks`, `lineups`, `ledger`, `protection`, `hydraulics`, `sim`, `ops`, `truth`, `sensors`, `rng`, `provenance`, `api`, `transient`, `faults` |
| `tests/` | `analytic`, `schema`, `leakage`, `regression` |
| `docs/` | Design records |
| `tools/` | Scripts that compute the studies and tables the documents quote (decision D57) |

## Setup and tests

Python 3.11 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --group dev
```

```bash
uv run pytest
```

Repository conventions are described in `CONTRIBUTING.md`.
