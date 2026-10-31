# Dataset card

The fields follow the template of section 6.11 of `revised/05_simulation_validation_dataset.md`. A field that cannot be filled from the present work is marked **unresolved**.

| Field | Value |
| --- | --- |
| schema version of the card | 0.8.0 |
| name | VERUM synthetic gasoline-terminal dataset |
| release identifier | unresolved (no release has been made) |
| dataset tier | `analytic_verification` for episodes without a flagged validity window; `restricted_benchmark` for episodes with one (decision D37). `production_candidate` is refused while `production_generation_enabled` is false |

**Synthetic statement.** All records are produced by a simulator. No record is a measurement of a real facility. Parameters are DESIGN, SIM or CALC selections unless a parameter register says otherwise.

**Intended uses.** Developing and comparing diagnostic agents on a synthetic terminal; testing data contracts, leakage controls and evaluation procedures. **Out of scope.** Operating, safeguarding or certifying a real terminal; estimating real failure frequencies, detection performance or savings; claiming validated hydraulics.

## Restricted episodes

**The S0u-E episode is `restricted_benchmark` and must not be used in diagnostic scoring.** S0u-E (fill to the high-high level, emergency isolation): the 10 s closure of the receipt valve is 27.7 wave round trips, below the 50 of decision D53; the closure under the 10 barg cap produces a flow collapse of about 0.19 s, shorter than ten round trips (D22); and the source side of the closed valve is a dead leg that holds its pressure for 329 s (D54).

The rigid-column model does not represent that interval, and the pressure values around it (the clipped PT-001 reading and its relaxation) are not credible as physics.

S0u-D (receipt switch): the 10 s closure of the receipt valve at 600 s is judged at the instant its opening has fallen to 0.2, when the controller has already removed the flow, so it opens no window and the episode is `analytic_verification` (D58 version 2; version 1 flagged it at its starting flow). S0u-E is kept for infrastructure tests only.

The rule applies to every episode whose record lists a validity window (`validity_windows` in `episode.json`); the hidden join utility `verum.evaluation.attach_window_ids` marks the observation rows that fall inside a window.

## Composition

Families: hydraulic, with single injected faults available (a pipe leak, a valve restriction, a pump head degradation, sensor bias, drift and stuck-at, and valve misrouting; `docs/fault_models.md`), but no episode of the shipped scenarios carries a fault and no campaign of faulted episodes has been defined.

Scenario classes: healthy delivery, healthy receipt, concurrent receipt and delivery, receipt switch, fill to high-high with isolation, set-point step, delivery with a downstream demand process, delivery in the inland stratum, and two rejected starts. Episode count and horizon: **unresolved** (a campaign has not been defined); the shipped scenarios last 3600 s.

## Healthy variability profiles

A scenario file names a `variability_profile` (decision D73). `off` has no demand process; `v1` has the slow downstream factor of D23 (a log-normal process of standard deviation 0.05 and correlation time 1800 s, clipped to 0.8 to 1.25); both reproduce the earlier files bit for bit (a test compares the rows of S0-A, S0-B and S0-F over 900 s with digests taken before profile v2 existed).

Profile `v2` (scenarios `S0-A-v2`, `S0-B-v2`, `S0-C-v2`, each with its own seed) adds two things on named streams:

- The downstream factor follows regimes: a value log-uniform between 0.6502 and 8, held for a dwell uniform between 600 and 1800 s, entered by a 60 s linear ramp, multiplied by the OU factor and not smaller than 0.6502.
  - The lower bound is 0.6 raised to the smallest value that keeps the pump 5 m3/h inside its curve at a tank level of 12 m (flow 348.07 m3/h at 0.6, 344.99 m3/h at 0.6502; `tools/regime_bound.py`).
  - A regime that would leave the pump domain, fail the phase and NPSH screen or fall below the minimum stable flow of 90 m3/h (D49) at the state of the moment is redrawn, and the redraw is recorded (event `demand_regime`, episode record, `demand_regime_redraws`); in the shipped v2 scenarios none was needed (the flow at a factor of 10 is 167 m3/h).
- The receipt set-point is followed with a deviation: an OU process of standard deviation 2 percent of the set-point, correlation time 600 s, clipped to plus and minus 6 percent, after a headroom screen at 1.06 times the set-point (636 m3/h for 600 against 651.5 m3/h).

The pumping-minimum levels for v2 are tabulated at the factor 0.6502 (`..._fd0p6502.json`, one file per atmosphere and volatility class) and gate SG0 reads the table of the profile; the minimum rises by up to 1.28 m, and 2 to 4 cells per file that passed at 0.8 never pass at 0.6502 (`local/results/strata_tables_v2.md`).

The hidden `boundary_state` records the regime value and the nominal and effective receipt set-points.

Effect on the emitted tags (20 seeds, 2700 s, cross-seed standard deviation of the 60 s mean, S0-A, v1 against v2): FT-201 2.39 to 44.9 m3/h, PT-203 0.027 to 0.41 barg, PT-202A 0.018 to 0.27 barg, LT-101 0.0017 to 0.024 m; with a receipt, FT-001 0 to 12.9 m3/h and PT-001 0.027 barg.

A detector or a model that assumes the downstream law of v1 sees a baseline fourteen to nineteen times more variable on the tags that depend on the factor; the audit of `docs/fault_models.md` shows what that does to detectability. None of the regime values is measured; they are selections (D73).

## Generation

Campaign seed: unresolved. Solver version `path-dynamics-radau-1`. The code commit, the lockfile hash and the configuration hash are written to each episode record and `provenance.json`.

## Model assumptions

Fluid: the audited reference fluid contract, vapor pressure per scenario, provisional. Pump: a synthetic curve with no manufacturer data. Delivery boundary: a flow-dependent downstream law with a demand factor (decision D23). Rigid-column path dynamics (D22), dead-leg pressures (D39), instrument model with selected noise, delay and dropout (D27 to D33), and an independent high-high detector (D33).

Unresolved parameters: those of the parameter register that are not selected, the detector and noise parameters beyond the selections of the decisions, and the pending sensitivity studies (D38).

## Validation

Analytic and code-verification tests are in `tests/`; the verification ladder of the transient engine is described in `docs/transient_engine.md`. **Self-consistency checks are not independent validation.** No independent validation of the facility model exists: **none**.

The transient engine has been compared with single-phase water-hammer experiments of Jensen et al. 2018 (rungs R12 and R13) using parameters and results that were taken as given and not verified against the paper; that is a check of the numerical method for those pipes, not of the facility.

## Known limitations

- Agent-side detectability is limited and depends on the window length (D77 to D82, `docs/fault_models.md`).
  - From the observed tags and the design model, over windows of 60, 300 and 900 s, a leak is detected from about 1.4e-5 m2 on the discharge and pump-branch sides and 3.4e-5 m2 on the suction side with a 900 s window, and from about 3e-4 m2 with a 60 s window. Under the profile v2, 43 of 72 leak cells, 61 of 72 bias cells and 14 of 54 obstruction cells are detected.
  - Severity classes (`invisible`, `marginal`, `clear`) and their boundaries per fault type and asset class are in `config/severity_classes.json`. They use the scaled margin of D89: all thresholds of a lineup and profile are multiplied by one factor (1.28 to 1.35) chosen so that at most 1 percent of the calibration runs alarm on any feature. On 100 healthy runs not used in the derivation the rate is 1 to 3 percent. Under v2, 40 percent of a log-uniform leak sampling is invisible, 74 percent for an obstruction and 15 percent for a bias; a later sampler is to allocate equally across the classes a fault type populates.
  - Five of the 36 boundaries are unresolved because the margin stays below the level over the whole range. A boundary equal to the start of the range is listed in the class file with its floor mark (D89c): a floor means that the class begins at or below the start of the range and is not a detection threshold.
  - The visible restriction and misrouting populate only the clear class and cannot be balanced across classes. A restriction in mode `obstruction` cannot be told from a pump head degradation by the contact, which stays open.
  - A fault on an asset that is not active in the lineup is labelled `latent` in the episode record and is to be excluded from detection metrics (D76).
  - A leak on an idle branch connected to live fluid cannot be represented, because the steady network does not solve dead-end edges; such a candidate is rejected and never labelled.
  - None of this is validated against real data.
- Severe restrictions of a valve on the suction side of the duty pump are not representable.
  - A closure above about 0.67 (`XV-S103`), 0.72 (`XV-S102`) or 0.75 (`XV-S101`, `XV-PAI`, `XV-PBI`) of the opening is rejected by the phase and NPSH screen, and a forced opening of `XV-PBO` while pump A delivers has no steady state; such candidates are written as `simulation_rejected` and are never labelled healthy (decisions D66 and D74; `docs/fault_models.md`, "Representable range").
  - A leak on an edge that carries no determined pressure in the lineup is rejected in the same way.
- No wave dynamics in the episodes; peak surge pressure and sub-second events are not resolved.
  - A standalone transient engine exists (`docs/transient_engine.md`); it is not integrated, it does not change any tier (D47) and it has no cavitation model.
  - The rigid-column engine under-predicts the pressure peak of a valve closure unless the stroke lasts many wave round trips (D53) and does not represent the last 2 to 3 percent of an emergency closure, where the downstream face of the valve reaches the vapor pressure.
- A receipt set-point step excites an elastic oscillation of the pressure that the rigid-column engine does not represent.
  - In the transient engine after the step 600 to 300 m3/h (TK-101 at 9.28 m) the true PT-001 departs from its 2 s mean by up to 0.68 bar (135 noise standard deviations of 0.005 bar) between 1 and 5 s after the step, 0.41 bar (83 sigma) from 5 to 10 s, 0.26 bar (52 sigma) from 10 to 20 s and 0.15 bar (30 sigma) from 20 to 30 s, with periods of 1.0 s and 0.41 s.
  - The episodes contain only the mean (the inertial head of D22); a 1 s sample of a real PT-001 would carry the oscillation.
- The pumping-minimum tables make the feasible initial level depend on the fluid temperature (D35). For the baseline (RVP_9_0, NPSH3 4 m, reference fittings, f_d 0.8) the minimum level rises by 0.22, 0.26 and 0.30 m per degree (TK-101, TK-102, TK-103, coastal) or 0.28, 0.33 and 0.36 m per degree (inland) between 25 and 45 C, so that sampling the level uniformly in the feasible band gives a correlation of temperature and initial level of 0.31, 0.38 and 0.45 (coastal) and 0.43, 0.50 and 0.57 (inland): a high temperature goes with a high starting level, and an agent can read that from the data (`tools/feasibility_correlation.py`).
- Faults exist only as single, persistent faults of five types; damaged-seal and fitting multipliers, multi-fault episodes, recovery, vapor-related faults and inspection outcomes do not exist yet.
  - The fault laws, ranges and thresholds are selections (D60 to D65).
  - Some severities are not realisable (a valve stuck almost closed on the duty path is rejected by a gate at every severity of its range), some faults leave no trace (a restriction of a closed valve, a degraded stopped pump, a stuck-at on a constant signal), and several pairs of faults have almost the same signature in the emitted tags (a restriction of the pump inlet valve and a pump degradation, leaks in the same zone); the audit of `docs/fault_models.md` gives the numbers.
  - A leak is a rigid-column sink evaluated from the last accepted solve and valid above 10 kPa gauge only.
- Dead-leg pressures relax with a selected time constant; trapped-liquid thermal and compressibility effects are not modelled (D39).
- The sensor noise, dropout, quantisation and delay values are selections, not measurements.
- The alarm uses the level-transmitter chain; the high-high trip uses a detector with a selected offset and delay (D33, D40).
- The inland stratum rests on an elevation recalled from memory and to be confirmed.
- The derived volatility classes (`RVP_9_0`, `RVP_9_5`) rest on the AP-42 correlation and a verification gate that could be run only on the tabulated points available (decision D46); the Saudi domestic RVP limit is not established.
- The pump curve is synthetic; no practising engineer reviewed the design, which was checked against general engineering rules of thumb only (D48).
- The receipt branch velocity of 5.2 m/s and the suction branch velocity of 2.6 m/s exceed common design guidance (an unsourced recollection); inlet-jet and static-charge effects are not modelled (D48).
- The meter loss coefficient K = 1 is probably low (D48; the sweep of D50 is in the sensitivity study).
- There are no pump strainers, vapor handling, vent or vapor-recovery hardware, and no pump start, trip or changeover (D48).
- The inspection catalog is empty: no catalog exists in the audited package.
- Pressure convention (velocity head): static pressure is `rho g (H - z) - rho v^2 / 2` at the end of an edge, as described in `docs/steady_hydraulics.md`.

## Visibility policy

Agent-visible: assets, observations, history, the inspection catalog, performed inspection results. Evaluator only: fault truth, hydraulic state, boundary state, validity windows, solver diagnostics, mass ledger, observation audit, simulation_rejected, episode records.

## Splits and evaluation protocol

Unit and proportions: **unresolved**. Evaluation protocol: section 6.8 of the simulation document.
