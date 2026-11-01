# VERUM backend

VERUM is a synthetic simulator of a gasoline receipt, storage and distribution terminal. It produces physically consistent hidden state, a separate set of instrument observations derived from that state, and simulated inspection results, so that diagnostic reasoning over several assets can be studied without field data.

This repository is the backend of a larger system. A frontend will live in a separate repository and will consume the JSON schemas published here.

## What the repository contains

- **Inputs and contracts**
  - The audited input package, vendored unmodified under `vendor/verum_audited/` with SHA-256 hashes in `vendor/MANIFEST.sha256`.
  - The six interface schemas in `schemas/` and the machine-readable contracts in `config/`, both copied unchanged from the audited package.
  - A parameter model in which an unresolved value cannot be read (`verum.params`), and loaders and validators for the contracts and schemas (`verum.contracts`).
- **Plant model**
  - A graph view of the topology with lineup-dependent connectivity and route geometry (`verum.graph`).
  - Tank calibration, roof state and the response-headroom screen (`verum.tanks`), the sixteen operating lineups with their transition rules (`verum.lineups`), and inventory ledgers driven by prescribed flows (`verum.ledger`).
  - Steady-state network hydraulics with friction, pump, boundaries, fitting profiles and the phase and NPSH gate (`verum.hydraulics`; see `docs/steady_hydraulics.md`).
  - The independent protection state machine, as pure logic (`verum.protection`).
- **Episodes**
  - The path-dynamics engine, the operations controller and the hidden truth store (`verum.sim`, `verum.ops`, `verum.truth`; see `docs/path_dynamics_engine.md`), with named random streams and configuration provenance (`verum.rng`, `verum.provenance`).
  - A scenario names a healthy variability profile: `off`, `v1`, or `v2` with demand regimes and a moving receipt set-point (see `docs/dataset_card.md`).
- **Observations**
  - The sensor chain from truth to observations (`verum.sensors`; see `docs/observation_chain.md`) and the read-only gateway (`verum.api`).
- **Inspection**
  - The catalog of seven inspection actions, the request and approval workflow with an approval emulator, the outcome models, a synthetic history and the gateway functions that serve them (`verum.inspection`, `verum.api`; see `docs/inspection_model.md`). The outcome models are simulation selections and not field performance.
- **Faults**
  - Single faults can be injected into an episode through `verum.faults`: a pipe leak, a valve restriction, a pump head degradation, sensor faults and valve misrouting (see `docs/fault_models.md`).
  - A restriction is `position_visible` or `obstruction`, and a fault on an asset that is not active in the lineup is labelled latent.
  - An audit asks what an agent could see of each fault from the observed tags and the design model, over windows of 60, 300 and 900 s, with calibrated and scaled thresholds and severity classes (`verum.evaluation.agent_audit`, `config/severity_classes.json`; see `docs/fault_models.md`).
- **Transient engine**
  - A standalone first-order method of characteristics on the 28 edges (`verum.transient`; see `docs/transient_engine.md`), with its own verification ladder.
  - The episode engine does not call it, and it changes no dataset tier.
- **Release gate**
  - A fail-closed gate (`verum.gates`). The release policy in `config/dataset_release_policy.json` keeps `production_generation_enabled` false, and the gate refuses the `production_candidate` tier while it is false.
- **Tests and decisions**
  - Tests for all of the above, and a record of design decisions in `docs/design_decisions.md`.

Paired-fault episodes and a resumable campaign generator are implemented. Agents are not implemented. Evaluator probability scores and an evaluator-only inventory of unaudited campaign faults are available; the complete scoring and relabelling protocol remains in progress.

## Data provenance

All physical values are synthetic simulation or design selections. They do not describe an as-built terminal, and none is a measurement. Parameters that are not selected are represented as unresolved and raise an error when read.

## Layout

| Path | Contents |
| --- | --- |
| `vendor/` | Audited input package, read-only, with hash manifest |
| `config/` | Machine-readable contracts used by the loaders |
| `schemas/` | JSON Schemas that define the interface contract |
| `src/verum/` | Package: `params`, `contracts`, `gates`, `graph`, `tanks`, `lineups`, `ledger`, `protection`, `hydraulics`, `sim`, `ops`, `truth`, `sensors`, `rng`, `provenance`, `api`, `transient`, `faults`, `inspection` |
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


## Mechanical and vapour extension

The restricted mechanical extension adds persistent rim-seal and fitting defects, a reduced roof hang-up state and a travel-triggered secondary seal-tear cascade. Inspection results use these states through the existing approval workflow. The extension preserves its healthy parent's split and hydraulic observations; it does not model mechanical forces feeding back into hydraulics.

Generate a new directory with `python tools/vapour_campaign.py --base data/campaign --output data/mechanical_extension_v1 --n 180`, then validate it with `python tools/validate_vapour_campaign.py --base data/campaign --root data/mechanical_extension_v1 --report local/mechanical_extension_validation.json`. The output remains restricted_benchmark. Its 30-day constant-condition vapour component estimates include explicit SIM proxies and are not complete facility emissions or observations (D121).

New extension runs use prospective seeded tank assignment and retain cascade trials without a child. Previously stored extensions keep their original identities and limitations; they are not repaired by a generator change. The separately tested one-sided roof support model changes the engine's liquid displacement and head during withdrawal, but is not used by the archived mechanical extension and supplies no structural rupture law.

## Training qualification

The stored datasets are not qualified for physical diagnostic training. Run `python tools/training_readiness.py --root data/campaign --report local/training_audit/campaign_readiness.json` to inspect the blockers; an unqualified dataset returns exit status 2. Software verification, valid schemas and a completed generation count do not establish physical validity. See `docs/training_qualification.md` for the supported scope and unresolved inputs.
