# Dataset card

The fields follow the template of section 6.11 of `revised/05_simulation_validation_dataset.md`.
A field that cannot be filled from the present work is marked **unresolved**.

| Field | Value |
| --- | --- |
| schema version of the card | 0.6.0 |
| name | VERUM synthetic gasoline-terminal dataset |
| release identifier | unresolved (no release has been made) |
| dataset tier | `analytic_verification` for episodes without a flagged validity window; `restricted_benchmark` for episodes with one (decision D37). `production_candidate` is refused while `production_generation_enabled` is false |

**Synthetic statement.** All records are produced by a simulator. No record is a measurement of a
real facility. Parameters are DESIGN, SIM or CALC selections unless a parameter register says
otherwise.

**Intended uses.** Developing and comparing diagnostic agents on a synthetic terminal; testing
data contracts, leakage controls and evaluation procedures.
**Out of scope.** Operating, safeguarding or certifying a real terminal; estimating real failure
frequencies, detection performance or savings; claiming validated hydraulics.

## Restricted episodes

**The S0u-E episode (fill to the high-high level, emergency isolation) is `restricted_benchmark`
and must not be used in diagnostic scoring.** Its closure of the receipt valve under the 10 barg
cap produces a flow collapse of about 0.19 s, shorter than ten pressure-wave round trips of the
path (decision D22). The rigid-column model does not represent that interval, and the pressure
values around it (the clipped PT-001 reading and its relaxation) are not credible as physics.
The episode is kept for infrastructure tests only. The rule applies to every episode whose record
lists a validity window (`validity_windows` in `episode.json`); the hidden join utility
`verum.evaluation.attach_window_ids` marks the observation rows that fall inside a window.

## Composition

Families: hydraulic only; no faults are implemented. Scenario classes: healthy delivery, healthy
receipt, concurrent receipt and delivery, receipt switch, fill to high-high with isolation,
set-point step, delivery with a downstream demand process, delivery in the inland stratum, and
two rejected starts. Episode count and horizon: **unresolved** (a campaign has not been defined);
the shipped scenarios last 3600 s.

## Generation

Campaign seed: unresolved. Solver version `path-dynamics-radau-1`. The code commit, the lockfile
hash and the configuration hash are written to each episode record and `provenance.json`.

## Model assumptions

Fluid: the audited reference fluid contract, vapor pressure per scenario, provisional. Pump: a
synthetic curve with no manufacturer data. Delivery boundary: a flow-dependent downstream law with
a demand factor (decision D23). Rigid-column path dynamics (D22), dead-leg pressures (D39),
instrument model with selected noise, delay and dropout (D27 to D33), and an independent
high-high detector (D33). Unresolved parameters: those of the parameter register that are not
selected, the detector and noise parameters beyond the selections of the decisions, and the
pending sensitivity studies (D38).

## Validation

Analytic and code-verification tests are in `tests/`; the verification ladder of the transient engine is described in `docs/transient_engine.md`. **Self-consistency checks are not
independent validation.** No independent validation exists: **none**.

## Known limitations

- No wave dynamics in the episodes; peak surge pressure and sub-second events are not resolved.
  A standalone transient engine exists (`docs/transient_engine.md`); it is not integrated, it does
  not change any tier (D47) and it has no cavitation model.
- Faults, damaged-seal and fitting multipliers, and inspection outcomes do not exist yet.
- Dead-leg pressures relax with a selected time constant; trapped-liquid thermal and
  compressibility effects are not modelled (D39).
- The sensor noise, dropout, quantisation and delay values are selections, not measurements.
- The alarm uses the level-transmitter chain; the high-high trip uses a detector with a selected
  offset and delay (D33, D40).
- The inland stratum rests on an elevation recalled from memory and to be confirmed.
- The derived volatility classes (`RVP_9_0`, `RVP_9_5`) rest on the AP-42 correlation and a
  verification gate that could be run only on the tabulated points available (decision D46); the
  Saudi domestic RVP limit is not established.
- The pump curve is synthetic; no practising engineer reviewed the design, which was checked
  against general engineering rules of thumb only (D48).
- The receipt branch velocity of 5.2 m/s and the suction branch velocity of 2.6 m/s exceed
  common design guidance (an unsourced recollection); inlet-jet and static-charge effects are
  not modelled (D48).
- The meter loss coefficient K = 1 is probably low (D48; the sweep of D50 is in the Phase 5
  study).
- There are no pump strainers, vapor handling, vent or vapor-recovery hardware, and no pump
  start, trip or changeover (D48).
- The inspection catalog is empty: no catalog exists in the audited package.
- Pressure convention (velocity head): static pressure is `rho g (H - z) - rho v^2 / 2` at the
  end of an edge, as described in `docs/steady_hydraulics.md`.

## Visibility policy

Agent-visible: assets, observations, history, the inspection catalog, performed inspection
results. Evaluator only: fault truth, hydraulic state, boundary state, validity windows, solver
diagnostics, mass ledger, observation audit, simulation_rejected, episode records.

## Splits and evaluation protocol

Unit and proportions: **unresolved**. Evaluation protocol: section 6.8 of the simulation
document.
