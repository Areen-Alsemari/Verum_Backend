# Design decisions

This log records the modelling and numerical decisions that fix the simulator
configuration for version 1. Each record is a versioned design record. A change
to a decision is made by adding a new version of its record and marking the old
version superseded; records are not edited in place.

## Conventions

- **Status.** `SIM` marks a selected synthetic model parameter or law. `DESIGN`
  marks a selection of method or scope. Neither is a measurement, a
  manufacturer value or a field-validated result. Every value below is a
  simulation selection for a representative terminal.
- **Sensitivity required.** The sweep or comparison that must accompany any
  result that depends on the decision. Where the decision log specified the
  sweep, it is stated as specified. Where it did not, the entry is marked
  *proposed* and is open to revision by the decision owner.
- **Notes.** Observations made while recording the decision that bear on its
  implementation. They are not part of the decision.
- Log version 14 (2026-10-31). Records are version 1.0 unless stated. A record
  with a later version states the version it supersedes and keeps the earlier
  version below it, marked superseded.
- Source documents are cited by file and section in the audited package under
  `vendor/verum_audited/`.

## Index

| ID | Subject | Status | Current version |
| --- | --- | --- | --- |
| D1 | Solver architecture and time step | DESIGN | 1.0 |
| D2 | Delivery boundary and pump operating point | SIM | 3.0 |
| D3 | Receipt boundary | SIM | 2.0 |
| D4 | Valve characteristics and stroke times | SIM | 2.0 |
| D5 | Check-valve closure | SIM | 1.0 |
| D6 | Pump start, trip and changeover excluded | DESIGN | 1.0 |
| D7 | NPSH3 relation and margin | SIM | 2.0 |
| D8 | Numerical tolerances | DESIGN | 1.0 |
| D9 | Motor, current and vibration channels not emitted | DESIGN | 1.0 |
| D10 | Validity condition for leaks | SIM | 1.0 |
| D11 | Bulk-liquid temperature stratum | SIM | 3.0 (supersedes 1.0) |
| D12 | Isolation confirmation timeout | SIM | 1.0 |
| D13 | Residual-flow threshold for failed isolation | SIM | 1.0 |
| D14 | Friction law | SIM | 1.0 |
| D15 | Fitting profiles | SIM | 1.0 |
| D16 | Alarm hysteresis | SIM | 1.0 |
| D17 | Time step and integration scheme | DESIGN | 1.0 |
| D18 | Quasi-steady validity | DESIGN (superseded by D22) | 1.0 |
| D19 | Valve motion and loss coefficient | SIM | 1.0 |
| D20 | Truth log format | DESIGN | 1.0 |
| D21 | Temperature held constant per episode | SIM | 1.0 |
| D22 | Rigid-column inertia | DESIGN | 1.0 |
| D23 | Healthy variability | SIM | 1.0 |
| D24 | Atmosphere stratum per episode | SIM | 2.0 (supersedes 1.0) |
| D25 | Validity windows | DESIGN | 1.0 |
| D26 | Protection thresholds located inside the step | DESIGN | 1.0 |
| D34 | Truth grid density | DESIGN | 1.0 |
| D35 | NPSH3 coefficient and feasible sampling band | SIM | 1.0 |
| D36 | Cap as a pressure limit at the source tap; anchor of the head | DESIGN | 2.0 (supersedes 1.0) |
| D37 | Tier of episodes with flagged windows | DESIGN | 1.0 |
| D38 | Pending sensitivity studies | DESIGN | 1.0 |
| D27 | Observation units and the atmosphere stratum | DESIGN | 1.1 (supersedes 1.0) |
| D28 | Noise standard deviations | SIM | 1.0 |
| D29 | Quantisation and clipping | SIM | 1.1 (supersedes 1.0) |
| D30 | Sample dropout | SIM | 1.0 |
| D31 | Valve contacts | SIM | 1.0 |
| D32 | Sample phase | SIM | 1.0 |
| D33 | Independent high-high detector inside the engine | DESIGN | 1.1 (supersedes 1.0) |
| D39 | Dead-leg pressure | SIM | 1.0 |
| D40 | Alarm on the level-transmitter chain | DESIGN | 1.0 |
| D41 | Campaign episode seeds | DESIGN | 1.0 |
| D42 | The sensitivity sweeps as one study | DESIGN | 1.0 |
| D43 | First-order method of characteristics | DESIGN | 1.0 |
| D44 | Boundaries of the transient engine | DESIGN | 1.0 |
| D45 | No cavitation model | DESIGN | 1.0 |
| D46 | Volatility classes | SIM | 4.0 (supersedes 3.0) |
| D47 | The transient engine does not change tiers | DESIGN | 1.0 |
| D48 | Dataset-card limitations | DESIGN | 1.0 |
| D49 | Minimum stable flow window deferred | DESIGN | 1.0 |
| D50 | Further sensitivity sweeps | DESIGN | 1.0 |
| D51 | Grid of the pumping-minimum tables | DESIGN | 1.1 (supersedes 1.0) |
| D52 | Production baseline NPSH3 coefficient | SIM | 1.0 |
| D53 | Validity-window factors | DESIGN | 3.0 (supersedes 1.2) |
| D54 | Dead-leg unvalidated window | DESIGN | 1.0 |
| D55 | Usable interval after a phase_invalid window | DESIGN | 1.0 |
| D56 | Published-experiment rungs R12 and R13 | DESIGN | 1.0 |
| D57 | Study and table scripts in a tracked directory | DESIGN | 1.0 |
| D58 | Stroke windows need flow | DESIGN | 2.0 (supersedes 1.0) |
| D59 | Dense truth rows by window kind | DESIGN | 1.0 |
| D60 | Leak | SIM | 1.0 |
| D61 | Valve restriction | SIM | 1.0 |
| D62 | Pump head degradation | SIM | 1.0 |
| D63 | Sensor faults | SIM | 1.0 |
| D64 | Misrouting | SIM | 1.0 |
| D65 | Fault onset and ramp | SIM | 1.0 |
| D66 | Rejection of faulted candidates | DESIGN | 1.0 |
| D67 | Edge-flow convention | DESIGN | 1.0 |
| D68 | Audit detectability thresholds | DESIGN | 1.0 |
| D73 | Healthy variability, profile v2 | SIM | 1.0 |
| D74 | Valve restriction modes | SIM | 1.0 |
| D75 | Misrouting (b) eligibility | SIM | 1.0 |
| D76 | Latent faults | DESIGN | 1.0 |
| D77 | Agent-side detectability audit | DESIGN | 1.0 |
| D78 | Severity classes | DESIGN | 1.0 |

## D1 - Solver architecture and time step

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** A quasi-steady engine advances the system between events. A
  custom method-of-characteristics (MOC) engine handles events and
  verification cases. The hydraulic time step is 0.923 ms. Wave speeds are
  adjusted per edge so that every edge holds a whole number of reaches; the
  largest adjustment is 0.53 %. The 2 m pump-branch edges (`E-PA2`, `E-PA3`,
  `E-PB2`, `E-PB3`) are given 2 reaches each.
- **Reason.** The audit accepts a custom 1-D MOC as a plausible method and
  allows quasi-steady balances only as development tests, not as a substitute
  for MOC under rapid events (`VERUM_INTEGRATION_README.md`, sections B and C).
  The step follows from the grid study in
  `revised/05_simulation_validation_dataset.md` section 8.2, in which the
  2 m edges limit the step and 0.923 ms gives the smallest adjustment over the
  grid searched. That section leaves acceptance of the 0.53 % adjustment to the
  hydraulic workstream (pending item 2.22); this record accepts it for
  version 1.
- **Sensitivity required.** Repeat the verification cases at the adjustment
  limit of 1.0 % (the study gives 0.927 ms) and at a finer step, and report the
  change in peak pressure and mass-ledger residual. Grid refinement is also
  governed by D8.
- **Notes.** The study fixes reaches for pipe edges only. Valves, pumps and
  tees need their own internal treatment, which the study states it does not
  address. Throughput at this step was not measured (section 8.2).

## D2 - Delivery boundary and pump operating point

### Version 3.0 (current)

- **Version:** 3.0 (2026-10-29)  **Status:** SIM  **Supersedes:** 2.0
- **Decision.** Version 2.0 stands (fixed speed, reservoir beyond
  `DISTRIBUTION_BOUNDARY`, boundary-law element dH_d = c (Q/300)^2 m between the
  node and the reservoir, `PT-203` = 2 barg + rho g dH_d). In addition, the
  coefficient c is solved separately for each fitting profile (D15) so that
  TK-102 at 7 m runs at 300 m3/h with 42 m of pump head. Each value is stored in
  `config/delivery_boundary.json` with its provenance. The solved values are
  c = 11.963444 m for `pipe_only` (11.96 m to two decimals) and
  c = 10.060889 m for `reference_fittings`. With these values the two profiles
  give practically the same operating flows (they differ in pressure
  distribution and NPSH), because a lumped K and the boundary law are both
  quadratic in the flow.
- **Reason.** The coefficient of 11.96 m was derived for straight pipe without
  fittings. With fittings the system needs less added resistance to give the
  same duty point, so one value cannot serve both profiles.
- **Contract.** The sensor and release contracts are patched
  (`config/patches/`): the `PT-203` adapter no longer calls the pressure fixed,
  the value 200000 Pa is labelled the reservoir gauge pressure, and a
  boundary-law entry points to the configuration file. The `PT-203` reference is
  unchanged.
- **Sensitivity required.** As version 2.0: vary c and the reservoir pressure;
  both sweeps are *proposals*. In addition, the fitting-profile multiplier of
  D15 changes the operating flow at fixed c; the study is in the Phase 2 report.
- **Notes.** The hydraulic model reports `PT-203` as a static pressure, that is
  total-head pressure minus the velocity pressure of `E-D2` (about 2.5 kPa at
  300 m3/h). The expression "2 barg + rho g dH_d" is the total-head (stagnation)
  value at the boundary node.

### Version 2.0 (superseded by 3.0)

- **Version:** 2.0 (2026-10-29)  **Superseded by:** 3.0  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** The pump runs at fixed speed (s = 1). The 2 barg reservoir lies
  beyond `DISTRIBUTION_BOUNDARY`. The added resistance
  dH_d = 11.96 (Q/300)^2 m, with Q in m3/h, is a boundary-law element between
  the boundary node, where `PT-203` sits, and the reservoir. It is not a new
  edge and not a new node. `PT-203` = 2 barg + rho g dH_d, in gauge pressure.
- **Reason.** Version 1.0 did not say where the resistance sits relative to the
  `PT-203` tap. Placing the reservoir beyond the boundary node keeps the
  28-edge topology unchanged and makes the node pressure flow-dependent, as the
  resistance requires. The coefficient and the pump-curve argument are those of
  version 1.0.
- **Sensitivity required.** Vary the coefficient (11.96 m) and the reservoir
  pressure (2 barg); report duty points for the three tanks at initial and
  minimum levels. Both sweeps are *proposals*; the decision log specifies none.
- **Notes.**
  - At 300 m3/h, rho g dH_d = 750 x 9.80665 x 11.96 = about 87.97 kPa, so
    `PT-203` is about 2.88 barg at 300 m3/h and varies with flow.
  - This conflicts with the configuration contract and with the prose of the
    audited package, which describe `DISTRIBUTION_BOUNDARY` as a fixed 2 barg
    Dirichlet node (`fixed_distribution_boundary_gauge_Pa` and the `PT-203`
    adapter text). The contract is not patched in this version; the patch
    belongs with the hydraulic phase that implements the boundary law.
  - The duty points computed for version 1.0 (312.6, 300.0 and 287.5 m3/h for
    TK-101, TK-102 and TK-103 at their initial levels) are unchanged.

### Version 1.0 (superseded)

- **Version:** 1.0 (2026-10-29)  **Superseded by:** 2.0  **Status:** SIM
- **Decision.** The pump runs at fixed speed (speed ratio s = 1). The
  distribution boundary is 2 barg plus a downstream resistance
  dH_d = 11.96 (Q/300)^2 m, with Q in m3/h. This places the duty point at 42 m
  and 300 m3/h for TK-102 at 7 m. It replaces the pure fixed-pressure boundary.
- **Reason.** With a pure 2 barg boundary and s = 1, the pump curve intersects
  the system beyond the 350 m3/h curve limit at the initial levels of all three
  tanks (checked with `op()` in the audited `verum_member2_verify_corrected.py`:
  the pump still has 7.4, 4.4 and 1.3 m of head margin at the limit for TK-101,
  TK-102 and TK-103). An intersection there is an extrapolation and not an
  operating point (`revised/02_hydraulic_model.md` section 3.2). The added
  resistance keeps the duty point inside the curve domain without a
  variable-speed drive or a control valve, neither of which is in the baseline.
  The coefficient equals the pump head at 300 m3/h (42 m) less the
  straight-pipe head required for TK-102 at 7 m (30.037 m, section 3.1 of the
  same document), 11.963 m.
- **Sensitivity required.** Vary the coefficient (11.96 m) and the boundary
  pressure (2 barg) and report the resulting duty points for TK-101, TK-102 and
  TK-103 at their initial and minimum levels. Specified: none; *proposed*.
- **Notes.**
  - The configuration contract fixes the distribution boundary at 200000 Pa
    gauge and excludes a baseline control valve. D2 keeps both, and adds a
    lumped resistance that is not an asset in the 28-edge topology.
  - The position of the resistance relative to the `PT-203` tap is not
    specified. The audit states that `PT-203` on a fixed-pressure node cannot
    vary with an internal restriction (`VERUM_INTEGRATION_README.md`, section
    B). If the resistance lies upstream of the tap, `PT-203` would vary with
    flow. This must be settled before implementation.
  - Because s = 1 is fixed, the duty point differs between tanks. Solving the
    audited straight-pipe system with the added resistance gives about
    312.6 m3/h (41.0 m) for TK-101 at 9 m, 300.0 m3/h (42.0 m) for TK-102 at 7 m
    and 287.5 m3/h (43.0 m) for TK-103 at 5 m. Only the TK-102 case is at
    300 m3/h.
  - `revised/02_hydraulic_model.md` section 3.2 proposes a variable-speed drive
    for regulated 300 m3/h cases. D2 does not adopt it.

## D3 - Receipt boundary

### Version 2.0 (current)

- **Version:** 2.0 (2026-10-29)  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** The receipt flow controller responds as a first-order lag with
  time constant tau = 2 s towards the 600 m3/h target. The 10 barg supply cap
  clips the flow. There is no explicit ramp.
- **Reason.** A first-order controller response replaces the unspecified
  ramp-down of version 1.0, so no ramp-time parameter is needed. When `XV-R000`
  closes, the flow falls through the controller response and the valve stroke,
  and the cap limits the pressure the source can supply.
- **Sensitivity required.** Specified: tau swept from 1 to 5 s. The cap sweep of
  version 1.0 (8 and 12 barg) is retained as a *proposal*.
- **Notes.** The 10 barg cap equals the upper end of the `PT-001` span (0 to
  10 barg). Operation in the clipped regime delivers less than 600 m3/h and must
  be flagged in the episode record.

### Version 1.0 (superseded)

- **Version:** 1.0 (2026-10-29)  **Superseded by:** 2.0  **Status:** SIM
- **Decision.** The receipt source is flow-controlled at 600 m3/h with a supply
  pressure cap of 10 barg. When `XV-R000` closes, the flow ramps down.
- **Reason.** The hydraulic workstream requires a flow-controlled source or a
  specified source pressure, never both fixed independently
  (`revised/02_hydraulic_model.md` section 1; gate G2 in section 8). The cap is
  a limit and not a second specification. It equals the upper end of the
  `PT-001` span (0 to 10 barg).
- **Sensitivity required.** Vary the cap (for example 8 and 12 barg) and the
  ramp-down time, and report the closure pressure at the `E002` tap. *Proposed.*
- **Notes.** The ramp-down time is not given and is therefore an unresolved
  parameter; code that needs it must raise `UnresolvedParameter` until a value
  is recorded. Operation in the cap-limited regime reduces the delivered flow
  below 600 m3/h and must be flagged in the episode record.

## D4 - Valve characteristics and stroke times

### Version 2.0 (current)

- **Version:** 2.0 (2026-10-29)  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** The valve flow coefficient is continuous in the opening
  fraction alpha and zero at alpha = 0. With alpha_c = 0.05:
  - for alpha <= alpha_c, Kv = Kv_max (alpha / alpha_c) 50^(alpha_c - 1);
  - for alpha > alpha_c, Kv = Kv_max 50^(alpha - 1).
  Full-open loss coefficient K = 0.1. Stroke time is 10 s for `XV-R000` and
  30 s for the other motorized valves.
- **Reason.** Version 1.0 gave Kv(0) = Kv_max / 50, which cannot isolate. The
  linear segment below alpha_c joins the equal-percentage curve at alpha_c
  (both give Kv_max 50^(alpha_c - 1)) and reaches zero at alpha = 0.
- **Sensitivity required.** Specified: stroke times 2, 10 and 30 s; full-open K
  from 0.05 to 0.2. A sweep of alpha_c (for example 0.02 to 0.1) is a
  *proposal*.
- **Notes.** `Kv_max` per valve is still unspecified and is an unresolved
  parameter. "Other motorized" is taken to mean every `XV-*` valve other than
  `XV-R000`; this should be confirmed. Contact feedback is a separate model from
  valve position (see `canonical_sensor_contract.json`).

### Version 1.0 (superseded)

- **Version:** 1.0 (2026-10-29)  **Superseded by:** 2.0  **Status:** SIM
- **Decision.** Valve flow coefficient follows Kv(a) = Kv_max * 50^(a - 1),
  where a is the opening fraction. Full-open loss coefficient is K = 0.1. Stroke
  time is 10 s for `XV-R000` and 30 s for the other motorized valves.
- **Reason.** Real Kv/Cv curves and actuation data are not available, and
  manufacturer curves must not be invented
  (`revised/02_hydraulic_model.md` section 6.1). The characteristic is a
  declared synthetic law with swept parameters.
- **Sensitivity required.** Specified: stroke times 2, 10 and 30 s; full-open K
  from 0.05 to 0.2.
- **Notes.** As written, Kv(0) = Kv_max / 50, which is not zero. Full isolation
  therefore needs an explicit shut-off rule at a = 0 that the decision does not
  state. Which valves count as "other motorized" is taken to be every `XV-*`
  valve in the topology other than `XV-R000`; this should be confirmed.
  Contact feedback is a separate model from valve position (see
  `canonical_sensor_contract.json`).

## D5 - Check-valve closure

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Check valves close over a finite time with reverse-flow
  accounting. The closure delay is swept from 0.05 to 1 s. An `ideal_instant`
  closure is retained only as a labelled benchmark.
- **Reason.** The acceptance checks require an explicit opening and closure law
  with reverse-volume accounting, and permit an ideal check valve only on
  benchmark scenarios (`revised/02_hydraulic_model.md` sections 6.1 and 11).
- **Sensitivity required.** Specified: delay 0.05 to 1 s. Report reverse
  volume and peak pressure against delay.
- **Notes.** Check-valve disc position has no instrument in the baseline and
  stays hidden.

## D6 - Pump start, trip and changeover excluded

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Pump start, trip and duty/standby changeover are excluded from
  version 1. Every episode starts with a pump running.
- **Reason.** Pump-trip diagnostics from unvalidated transients are prohibited
  by the release policy until the full solver is validated
  (`dataset_release_policy.json`, `prohibited_until_full_solver_validation`).
  Rotating inertia, torque and trip setpoints are unresolved
  (`revised/05_simulation_validation_dataset.md` section 1.4).
- **Sensitivity required.** Not applicable to a scope exclusion. The duty pump
  may be either `P-101A` or `P-101B`; results should be shown for both.
  *Proposed.*
- **Notes.** The run contacts `P-101A` and `P-101B` stay in the sensor
  contract and report a constant state in version 1.

## D7 - NPSH3 relation and margin

### Version 2.0 (current)

- **Version:** 2.0 (2026-10-29)  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** The NPSH3 relation, NPSH3 = 4 (Q/300)^2 m, and the margin ratio
  1.3 are unchanged. The 1.8 m geometry minimum is kept as a geometric limit
  (roof support, nozzle elevations) and is not a pumping guarantee. A
  pumping-minimum level is derived for each tank and temperature stratum as the
  lowest level at which available NPSH, evaluated at the solved flow, meets the
  margin. NPSH is evaluated at the solved flow of the duty point and not at
  300 m3/h.
- **Reason.** Version 1.0 screened at 300 m3/h, but with D2 the solved flow
  differs between tanks (about 312.6, 300.0 and 287.5 m3/h at the initial
  levels), and both NPSHa losses and NPSH3 depend on flow. Keeping the
  geometry minimum separate from the pumping minimum follows the audit, which
  states that 1.8 m is not an NPSH-safe level.
- **Sensitivity required.** Specified: NPSH3 coefficient 2.5, 4 and 6 m;
  temperature stratum 25, 35 and 45 C (D11). Report the derived pumping-minimum
  level for every combination. No new sweep is proposed.
- **Notes.** The pumping-minimum level is an output of the hydraulic phase. The
  Phase 2 study stores it in `config/pumping_minimum_levels.json` for each tank,
  temperature stratum, fitting profile and NPSH3 coefficient. The version 1.0 check at 300 m3/h (TK-103,
  1.8 m, 25 C: 4.83 m available against 5.2 m required) indicates that the
  pumping minimum of TK-103 exceeds 1.8 m.

### Version 1.0 (superseded)

- **Version:** 1.0 (2026-10-29)  **Superseded by:** 2.0  **Status:** SIM
- **Decision.** Required NPSH is NPSH3 = 4 (Q/300)^2 m, with Q in m3/h. The
  coefficient is swept over 2.5, 4 and 6 m. The required margin ratio is 1.3
  (available NPSH divided by NPSH3).
- **Reason.** The production gate requires an NPSH3 relation and a margin, or an
  approved alternative, and no pump-specific curve exists
  (`dataset_release_policy.json`, gate `pump_operating_range_and_NPSH3_margin`;
  `revised/02_hydraulic_model.md` section 4). This is a synthetic relation and
  does not describe any manufacturer pump.
- **Sensitivity required.** Specified: coefficient 2.5, 4 and 6 m. Report which
  tank-level and temperature states pass the margin screen under each.
- **Notes.** Using the upper-estimate NPSHa values in
  `revised/02_hydraulic_model.md` section 4, at 25 C and 300 m3/h the TK-103
  1.8 m state has NPSHa = 4.83 m against a required 1.3 * 4 = 5.2 m and would
  fail the margin screen. The TK-102 (5.59 m) and TK-101 (6.35 m) minimum-level
  states pass. These figures exclude valve and fitting losses and are
  indicative only.

## D8 - Numerical tolerances

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The mass-ledger residual must not exceed 4.2e-4 kg/s.
  Discretization differences must not exceed 50 Pa in pressure and 0.02 m3/h in
  flow. The observed convergence order must be at least 0.8 on three grids. The
  tank ledger must close at round-off scale.
- **Reason.** Gates for the numerical solver and for conservation require
  predeclared, scale-aware tolerances (`revised/02_hydraulic_model.md`
  section 8, gates G5 and G6). The documents leave the values to this record
  (`revised/05_simulation_validation_dataset.md` pending items 2.8 and 2.22).
- **Sensitivity required.** Show that conclusions do not change when each
  tolerance is tightened by a factor of two. *Proposed.*
- **Notes.** The ledger tolerance is about 7e-6 of the nominal delivery mass
  flow (300 m3/h at 750 kg/m3 is 62.5 kg/s). "Round-off scale" is not given a
  numeric value and needs one before an automated check can use it.

## D9 - Motor, current and vibration channels not emitted

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The six channels `YS-201A/B`, `IT-201A/B` and `VT-201A/B` are not
  emitted in version 1.
- **Reason.** Shaft power is not measured current, torque is not vibration
  velocity, and a speed ratio is not a speed without a reference speed. No
  verified device model exists (`VERUM_INTEGRATION_README.md`, section B).
  The omission is a profile limitation and not a set of missing samples.
- **Sensitivity required.** Not applicable. The sensor contract marks the six
  tags `withheld_missing_device_model`, and the release policy lists them under
  `withheld_until_qualified`.
- **Notes.** The withheld references in the sensor contract name `torque_Nm`
  for the vibration tags and `shaft_power_W` for the current tags, which
  contradicts the audit's own rule against that conversion. They are never
  emitted, so no data is affected, but the references need replacing when the
  device models are specified.

## D10 - Validity condition for leaks

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** A leak is valid only where the gauge pressure at the leak
  exceeds 10 kPa throughout the leak window.
- **Reason.** The leak model is a single-phase outward orifice. Reverse
  differential and flashing are outside its scope and must be reported as such
  and not as an absence of inflow (`revised/02_hydraulic_model.md` section 5).
  A margin above zero gauge keeps the model away from the reverse-differential
  boundary.
- **Sensitivity required.** Vary the threshold (for example 5 and 20 kPa) and
  report the number of candidate episodes accepted. *Proposed.*
- **Notes.** The decision does not say how an excluded candidate is recorded.
  By the release policy it is stored as a rejected candidate experiment and is
  never shown to a diagnostic agent.

## D11 - Bulk-liquid temperature stratum

- **Version:** 3.0 (2026-10-29)  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** Production bulk-liquid temperatures are 25, 35 and 40 C. 45 C is a labelled stress subset (air-temperature stress). The temperature enters the phase and NPSH screening only; hydraulic properties stay the 25 C constants.
- **Reason.** Riyadh July average high is about 43 C and the daily mean about 36.6 C. The bulk tank temperature is unsourced and is taken to follow the daily mean, which is a judgement; 40 C leaves a margin above the mean and 45 C stresses the screen.
- **Sensitivity required.** Report the screening outcome at each temperature (done per volatility class in the pumping-minimum study).
- **Notes.** Version 1.0 had 25, 35 and 45 C and is kept below. Version 2 was a draft outside this log.

## D11 - Bulk-liquid temperature stratum (superseded)

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Bulk-liquid temperature takes the values 25, 35 and 45 C. It
  enters the phase and NPSH screening only. Hydraulic properties remain the
  25 C constants.
- **Reason.** The fluid contract is a constant-property reference at 25 C, and a
  temperature sweep isolates vapor-pressure sensitivity without claiming a
  coupled seasonal assay (`fluid_contract.json`, `validity`;
  `revised/02_hydraulic_model.md` section 1.1).
- **Sensitivity required.** Specified by the stratum itself: report phase and
  NPSH screening outcomes at each of the three temperatures.
- **Notes.** The vapor-pressure reference is a generic correlation and not a
  PG95 assay. The audit reports a negative NPSHa for TK-103 at 1.8 m and 45 C,
  which the screening rejects (`revised/02_hydraulic_model.md` section 4).

## D12 - Isolation confirmation timeout

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The timeout for confirming isolation after an isolation request
  is 2 x stroke time + sensor lag. The stroke time is that of the valve being
  closed (D4); the sensor lag is the nominal lag of its confirming contact.
- **Reason.** Confirmation cannot be expected before the valve has travelled and
  its contact has reported. A factor of two on the stroke time leaves a margin
  for a slow but healthy valve, and the lag term accounts for the reporting
  delay (`revised/01_facility_tanks_topology.md` section 6.3; the contact lags
  are in section 3.5).
- **Sensitivity required.** Vary the factor (for example 1.5, 2 and 3) and the
  stroke time (D4: 2, 10 and 30 s). Both are *proposals*.
- **Notes.** With the D4 stroke times and the section 3.5 lags, the timeout is
  2 x 10 + 2.0 = 22 s for `XV-R000` and 2 x 30 + 1.5 = 61.5 s for `XV-R101`,
  `XV-R102` and `XV-R103`. The sensor lags are not in the machine-readable
  contracts and are held in `config/protection.json`. A one-hour response
  envelope is used by the headroom screen; the timeout above is a separate,
  shorter quantity.

## D13 - Residual-flow threshold for failed isolation

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Isolation is declared failed if the flow measured after the
  timeout exceeds 1.0 m3/h.
- **Reason.** The threshold is five times the standard deviation of the receipt
  flow-meter noise (0.2 m3/h, `PAR-SNS-002`), which keeps the false-failure
  probability of a healthy closed line negligible for Gaussian noise.
- **Sensitivity required.** Vary the multiple of sigma (for example 3 to 10).
  *Proposed.*
- **Notes.** The check applies to the receipt flow measurement (`FT-001`)
  after receipt isolation. Meter noise is not guaranteed to be bounded at five
  sigma (`revised/01_facility_tanks_topology.md` section 6.4 item 4).

## D14 - Friction law

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The Darcy friction factor is 64/Re for Re < 2300 and the Haaland
  expression, 1/sqrt(f) = -1.8 log10[(eps/D/3.7)^1.11 + 6.9/Re], for Re > 4000.
  Between 2300 and 4000 it is blended linearly in Re between the laminar value
  at 2300 and the Haaland value at 4000.
- **Reason.** This is the law used by the audited reference calculations
  (`revised/02_hydraulic_model.md` section 3), so the document values can be
  reproduced. The linear blend avoids a jump at the transition.
- **Sensitivity required.** None specified. The absolute roughness (4.5e-5 m)
  is a design value of the package. A roughness sweep is a *proposal*.
- **Notes.** The blend is a numerical device, not a physical model of transitional
  flow. Flow is signed: the law is evaluated with |v| and the sign of the flow.

## D15 - Fitting profiles

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Two profiles. `pipe_only`: every loss coefficient K is zero.
  `reference_fittings`: K = 0.3 per polyline bend, 0.5 at a tank outlet, 1.0 at a
  tank inlet, 0.1 per open isolation valve, 2.0 per open check valve and 1.0 per
  meter. All values are typical handbook figures selected for the simulation; they
  are unverified and are not manufacturer or as-built data.
- **Reason.** The audited package gives pipe-only results and states that the
  installed fitting schedule is not supplied (`revised/01_facility_tanks_topology.md`
  section 6.6). Two profiles keep the document values reproducible while giving a
  more resistive case.
- **Sensitivity required.** Specified: a multiplier on every K of 0.5, 1 and 2.
- **Notes.**
  - A polyline bend is an interior vertex of a route polyline at which the
    direction changes; it is assigned to the edge that contains it.
  - A loss at a valve, check valve, meter or tank is assigned to the edge that
    starts at that element (the tank inlet to the edge that ends at the tank
    nozzle), and uses that edge's diameter and velocity.
  - The full-open valve value 0.1 is the D4 full-open coefficient; partial opening
    is outside this phase.
  - The exit into the reservoir has no loss coefficient in either profile.

## D16 - Alarm hysteresis

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** A hysteresis of 0.05 m applies to the HIGH_ALARM and HIGH_HIGH
  reset conditions. HIGH_ALARM clears when the process level falls below
  12.5 - 0.05 = 12.45 m. A latched high-high trip can be reset only if the
  independent level is below 13 - 0.05 = 12.95 m (and the other reset conditions
  hold). The trip and alarm thresholds themselves are unchanged.
- **Reason.** Without a band, a level that oscillates around a threshold toggles
  the alarm on every sample. The value is a small fraction of the 0.5 m between
  the alarm and the high-high level.
- **Sensitivity required.** Vary the hysteresis (for example 0.02, 0.05 and
  0.1 m). *Proposed.*
- **Notes.** Applies to the protection configuration and tests of Phase 1.

## D17 - Time step and integration scheme

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The engine advances in steps of 1 s. Tank volumes are integrated
  with Heun's method (second-order Runge-Kutta), and the steady network is solved
  at each stage. Events truncate the step so that a step ends exactly on every
  event time. The accuracy target is a level error of at most 0.025 mm, derived
  from the discretization tolerance of D8 (0.02 m3/h acting over one hour on a
  tank area of 706.86 m2 is about 0.028 mm). A step-halving study demonstrates it.
- **Reason.** The tank volumes change slowly and the network is treated as
  quasi-steady (D18), so a low-order explicit scheme with an exact landing on event
  times is sufficient. Heun's method is second order and needs two steady solves.
- **Sensitivity required.** Step-halving at 2, 1, 0.5 and 0.25 s on the delivery
  scenario S0-A, reporting error against a high-accuracy reference and the observed
  order (specified by the task).
- **Notes.** The receipt flow state follows an exponential response that is advanced
  exactly between events; only the tank volumes use Heun's method. A level crossing
  inside a step (for example a pumping-minimum crossing) is located by Hermite
  interpolation of the volume, not by the step.

## D18 - Quasi-steady validity

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN  **Superseded by:** D22 (the factor and the rigid-column time constant are replaced by the wave-round-trip criterion; this record is kept as history)
- **Decision.** The rigid-column time constant along the active path is
  tau = (sum L_i / A_i) Q0 / (g dH0), where the sum runs over the path edges, Q0
  is the flow before the event and dH0 is the total head loss along the path at
  Q0. An event is quasi-steady-valid only if its duration is at least 10 tau (the
  factor 10 is a proposal). The ratio duration / tau is recorded. An event that
  fails is flagged `quasi_steady_invalid` in the solver diagnostics. In this
  phase a failing event is flagged and not blocked.
- **Reason.** A steady-state network ignores the inertia of the liquid column. If
  a valve moves or a flow changes in a time comparable with tau, the flows during
  the event are not those of a steady solution, and the diagnostic says so
  instead of presenting them as valid.
- **Event durations.** A valve stroke lasts its stroke time. A receipt setpoint
  change lasts four time constants of the flow controller (4 tau_c, about 98 % of
  the step). These two definitions are mine and need confirmation.
- **Path.** For a receipt event the path is the common receipt main plus the
  branch of the receiving tank. For a delivery event it is the suction branch, the
  suction header, the pump branch and the distribution main. dH0 includes the
  boundary-law drop for delivery; the pump head is not a loss.
- **Sensitivity required.** Vary the factor (for example 5, 10 and 20) and report
  which events change status. *Proposed.*
- **Notes.** Fast closures (the 10 s emergency valve) are expected to fail the
  test. They are reported, not suppressed. A transient (wave) model is needed to
  represent them.

## D19 - Valve motion and loss coefficient

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The opening alpha moves linearly in time over the stroke time of D4
  (10 s for `XV-R000`, 30 s for the other motorized valves). The loss coefficient
  is K(alpha) = K_open (Kv_max / Kv(alpha))^2, with Kv(alpha) the continuous
  equal-percentage law of D4 (linear below alpha_c = 0.05) and K_open = 0.1 at the
  local diameter. An edge is treated as closed when alpha <= 0.001.
- **Reason.** D4 fixed the flow-coefficient law; D19 expresses it as a loss
  coefficient so that the steady network can use it, and the closed threshold avoids
  an unbounded K at alpha = 0.
- **Sensitivity required.** Specified in D4: stroke times 2, 10 and 30 s and
  full-open K from 0.05 to 0.2. The closed threshold is not swept (*proposed*: 0.001
  and 0.01).
- **Notes.** At alpha = 0.001 the coefficient is about 4e5, so the edge carries
  almost no flow just before it is removed. The commanded state, the actual
  position and the physical closure are recorded separately; physical closure means
  alpha <= 0.001. Partial opening increases the loss coefficient on the edge that
  starts at the valve; the profile's open-valve K is the K_open.

## D20 - Truth log format

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The hidden truth is written as JSON Lines, gzip-compressed, one
  directory per episode. Rows are written on a 1 s grid and, for every event, as a
  pre-event and a post-event row. A hash manifest (SHA-256 of every file) closes the
  directory. Rejected episodes keep only the rejection record, the episode record and
  the manifest.
- **Reason.** Line-oriented, compressed files are simple to stream, to hash and to
  read without extra dependencies. The pre- and post-event rows follow the
  audited schema envelope (`side`).
- **Sensitivity required.** Not applicable.
- **Notes.** The gzip header carries no timestamp, so identical content gives
  identical bytes. The files are evaluator data and are never served (see
  CONTRIBUTING.md).

## D21 - Temperature held constant per episode

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The bulk-liquid temperature of an episode is one of the D11 strata and
  does not change during the episode. There is no thermal dynamics.
- **Reason.** D11 uses temperature only for the phase and NPSH screen, with hydraulic
  properties at 25 C constants. A constant stratum per episode keeps that scheme.
- **Sensitivity required.** The three strata of D11.
- **Limitation.** Real tank temperature changes with the product received, solar load
  and ambient conditions. The engine represents none of it, so the temperature
  channels carry no dynamics and the screen cannot react to a warming product.

## D22 - Rigid-column inertia

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN  **Supersedes:** D18
- **Decision.** For each single-path receipt or delivery flow the path flow Q is a
  state with
      dQ/dt = (H_drive - H_loss(Q)) / I,     I = sum L_i / (g A_i)
  along the active path. The edge head difference includes the inertial term
  (L_i / (g A_i)) dQ/dt, so the tap pressures show surge.
  - **Receipt.** H_drive = min(H_demand, H_cap), with H_demand the head the flow
    controller asks for and H_cap the head available at the 10 barg cap (head-based,
    D3) above the tank level. The controller asks for
    H_demand = H_loss(Q) + I (Q_set - Q) / tau_c with tau_c = 2 s, so that, uncapped,
    dQ/dt = (Q_set - Q) / tau_c exactly (first order, time constant tau_c). Equivalently
    dQ/dt = min[(Q_set - Q) / tau_c, (H_cap - H_loss(Q)) / I]. Under the cap, or when a
    valve closes, the flow decays by inertia.
  - **Delivery.** H_drive = pump head(Q) minus the static difference to the reservoir, the
    friction and fitting losses, and the boundary-law term (D2, D23).
  - **Closed paths.** When a valve reaches the closed threshold the path flow is set to
    zero. The momentum removed that way is a sudden stop that the model cannot resolve and
    is reported in a validity window.
  - **Branched lineups** (for example `RECEIVE_101_102`) have no single path. They are
    flagged `rigid_column_unavailable`; the receipt flow state then follows the first-order
    response and the split comes from the steady solve (explicit first-order integration).
  - **Validity.** An event is valid only if its duration is at least 10 round trips of a
    pressure wave over the path, duration >= 10 (2 L_path / a), with the screening wave
    speeds of the audited package (1089.2, 1082.8 and 1078.2 m/s for DN200, DN250 and
    DN300) combined by travel time. Otherwise it is flagged (D25). Flow that falls from 90
    to 10 percent of its value within less than that time is flagged as well.
- **Reason.** D18 judged events against a rigid-column time constant but did not model
  inertia, so the flagged events had no inertial behaviour at all. The rigid-column model
  represents the inertia of the liquid column; the wave criterion states where the
  rigid-column assumption itself fails.
- **Correction to the task text.** The demand head is evaluated with the present flow,
  H_loss(Q), not with H_loss(Q_set). With H_loss(Q_set) the uncapped response would not be
  exactly first order, because the loss difference would add to the flow change. The present
  form gives the first-order response that D3 specifies.
- **Sensitivity required.** Vary the validity factor (5, 10 and 20) and report which windows
  change status (*proposed*); step size of the substeps (*proposed*: halve the substep).
- **Notes.** Peak surge pressure of a fast closure is a wave effect and is not resolved.

## D23 - Healthy variability

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** A downstream factor f_d(t) multiplies the boundary-law coefficient c of D2.
  log f_d follows an Ornstein-Uhlenbeck process with standard deviation 0.05 and
  correlation time 1800 s, and f_d is clipped to [0.8, 1.25]. The process is drawn on the
  named seeded stream `demand` on the 1 s grid, with the exact transition
  X(k+1) = phi X(k) + sigma sqrt(1 - phi^2) xi, phi = exp(-1 s / 1800 s); between grid
  points f_d is interpolated linearly in log. The value is written to the hidden truth
  (`boundary_state`). Receipt set-points are chosen per scenario from
  {300, 400, 500, 600} m3/h, subject to the headroom screen; zero means receipt stopped.
- **Reason.** A downstream demand that never changes is not a healthy plant. The factor
  moves the delivery duty point by a few percent without adding an asset.
- **Sensitivity required.** Vary sigma (0.03 and 0.08) and the correlation time (900 and
  3600 s). *Proposed.*
- **Notes.** Only the scenarios that name the demand process use it; the others keep
  f_d = 1.

## D24 - Atmosphere stratum per episode

- **Version:** 2.0 (2026-10-29)  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** The strata are renamed: `coastal` (101325 Pa) and `inland` (94300 Pa). The episode record carries the stratum. Pumping-minimum files are per (atmosphere, volatility) pair, computed at f_d = 0.8 (D51). The two strata have equal weight; no single site is claimed.
- **Reason.** The inland value is the standard-atmosphere estimate for the Riyadh area, elevation about 600 to 625 m (about 94.0 kPa), with observed airport field pressures of about 95.3 kPa on two days; the difference is 0.18 m of NPSHa.
- **Sensitivity required.** The inland stratum is itself the sensitivity.
- **Notes.** Version 1.0 called the strata `sea_level` and `elevated`; every file, schema and test is renamed.

## D24 - Atmosphere stratum per episode (superseded)

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Each episode has an atmosphere stratum: `sea_level` (101325 Pa, baseline)
  or `elevated` (94300 Pa, a labelled robustness subset). The pumping-minimum files are
  per stratum, computed at the worst-case f_d = 0.8, for both fitting profiles and the
  NPSH3 sweep of D7. The episode record carries the stratum. SG0 still checks the phase and
  NPSH screen at every step with the solved flow.
- **Reason.** The smallest f_d gives the largest flow and therefore the largest NPSH3 and
  the smallest margin, so the level that passes at f_d = 0.8 passes at every f_d in the
  clipped range.
- **Sensitivity required.** The elevated stratum is itself the sensitivity; its elevation
  (about 600 m) is from memory and is to be confirmed by the team.
- **Notes.** The earlier files computed at f_d = 1 are kept as history.

## D25 - Validity windows

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Validity windows are hidden records with a start, an end, a reason and the
  ratio duration / (2 L_path / a). They replace the single per-row ratio of the solver
  diagnostics, they are listed in the episode record, and they are never reachable from
  `verum.api`.
- **Reason.** A window states which interval of an episode the rigid-column model does not
  represent, so that a consumer can exclude it, and keeps the reason with it.
- **Sensitivity required.** As D22.
- **Notes.** Kinds: valve stroke, receipt set-point change, flow collapse, branched lineup.

## D26 - Protection thresholds located inside the step

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** A crossing of a protection threshold (high alarm, alarm clearing, high-high)
  inside a step is located by root-finding on the cubic Hermite interpolation of the tank
  volume, and the step is truncated to end on the crossing time. The protection update at
  that time sees the level at the threshold.
- **Reason.** Detection on the 1 s grid quantises the trip time and lets the level pass the
  threshold; the trip should be seen when the level reaches it.
- **Sensitivity required.** Not applicable; the accuracy is that of the interpolation
  (below 1 ms in the shipped scenarios).
- **Notes.** The crossing time is recorded in the event.

## D34 - Truth grid density

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Hidden truth rows are written every 0.1 s inside a validity window and
  while a valve is moving (from the start of its stroke to its end), and every 1 s
  elsewhere. Rows inside a step come from the dense solution of the integrator, not from
  a new step: the step scheme and the event times are unchanged.
- **Reason.** A flow collapse of 0.2 s is invisible on a 1 s grid. The sensor chain of
  Phase 4 interpolates truth within a segment, and a 1 s interpolation across a collapse
  would be wrong by hundreds of m3/h.
- **Sensitivity required.** None; the density is an output choice (*proposed*: compare the
  integral of the flow over a collapse from 0.1 s rows with the ledger).
- **Notes.** Rows on the dense grid are interpolated states, not solver steps.

## D35 - NPSH3 coefficient and feasible sampling band

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The NPSH3 coefficient is 4 m in production episodes; 2.5 m and 6 m are
  sensitivities only. When episodes are generated in a later phase, the temperature and
  the initial level are sampled independently within the band of the atmosphere stratum in
  which the stored pumping-minimum table gives a passing level (the feasible band).
- **Reason.** One coefficient keeps the pumping-minimum table single-valued per stratum;
  independent sampling inside the feasible band avoids a correlation between temperature
  and level that would let an agent read the situation from one of them.
- **Sensitivity required.** The two other coefficients (D7 sweep).
- **Notes.** The sampler is not implemented in this phase; the decision constrains it.

## D36 - Cap as a pressure limit at the source tap; anchor of the head

- **Version:** 2.0 (2026-10-29)  **Status:** DESIGN  **Supersedes:** 1.0  **Refines:** D22
- **Decision.** The 10 barg cap is a pressure limit at the supply end of the receipt column,
  the start of `E001` (node `PIPELINE_RECEIPT_BOUNDARY`). Two taps are labelled separately:
  - the *observed* PT-001 reads the start of `E002` (sensor contract, table 6.1.1): its head is
    `H_source - loss(E001) - Lambda_up dQ/dt`, with `Lambda_up = L_E001 / (g A_DN300)`
    (30 m, 42.4 s2/m2) over `E001` only;
  - the *hidden* node value for the end of `E002` keeps `H_source - loss(E001, E002) -
    Lambda_up dQ/dt` with `Lambda_up` over `E001` and `E002` (63.6 s2/m2).
  Every other node head is anchored at the end where the drive acts as before.
- **Reason.** Version 1.0 put the PT-001 tap after `E002`; the contract puts it at the start
  of `E002`, so the observed value must not include the inertance and loss of `E002`.
- **Sensitivity required.** None.
- **Notes.** Both values are written to the hidden truth: the edge row of `E002` carries
  the start-of-`E002` pressure, the tap node row the end-of-`E002` value. Version 1.0 is kept
  below.

## D36 - Cap as a pressure limit at the source tap; anchor of the head (version 1.0, superseded)

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN  **Refines:** D22
- **Decision.** The 10 barg cap is a pressure limit at `PIPELINE_RECEIPT_BOUNDARY`, the
  tap of PT-001, which lies at the start of `E001`. The column from the tap to the tank
  and the part upstream of the tap are accounted separately: the head at a tap is anchored
  at the end where the drive acts. For the receipt path with source head `H_s` at the
  drive end: the head at PT-001 is `H_s - loss(E001, E002) - Lambda_up dQ/dt` with
  `Lambda_up = sum L/(g A)` over `E001` and `E002` only, and the head at every node
  downstream is the tank head plus the loss and inertial terms of the edges between the
  node and the tank, so that the source side and the tank side agree at every instant.
- **Reason.** The inertial term belongs to the liquid between the drive and the tap that is
  being measured, not to the whole column. With the whole column the head at the tap
  equals the supply side minus nothing, and it is anchored at the wrong end.
- **Sensitivity required.** None.
- **Notes.** The drive acts at the supply boundary beyond the meter (the pipeline). The
  rigid-column equation of D22 is unchanged.

## D37 - Tier of episodes with flagged windows

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** An episode whose record lists a flagged validity window has the dataset
  tier `restricted_benchmark`; an episode without one keeps `analytic_verification`. This
  holds until the transient (method of characteristics) engine reproduces such windows.
  `production_candidate` stays refused by the release gate while generation is disabled.
- **Reason.** A window states that the physics inside it is not represented; such data
  must not enter an unrestricted tier.
- **Sensitivity required.** None.
- **Notes.** The tier is written to the episode record only; it is not agent-visible.

## D38 - Pending sensitivity studies

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The following studies are proposed and scheduled before Phase 7: the
  wave-criterion factor of D22 at 5, 10 and 20; the standard deviation of log f_d of D23
  at 0.05, 0.1 and 0.2; the correlation time of D23 (900, 1800, 3600 s).
- **Reason.** They were required by D22 and D23 and were not run in Phase 3b.
- **Sensitivity required.** The studies themselves.
- **Notes.** Each is *proposed*.

## D27 - Observation units and the atmosphere stratum

- **Version:** 1.1 (2026-10-29)  **Status:** DESIGN  **Supersedes:** 1.0
- **Decision.** Observation values are in the engineering units of the sensor contract (m,
  m3/h, barg, C, boolean). A gauge pressure is the true absolute pressure minus the atmosphere
  of the episode stratum (D24). The truth pressure is gauge plus that atmosphere, so identical
  hydraulics give identical gauge readings in both strata; the stratum matters to a reading
  only through the hydraulics (the NPSH screen, the pumping minimum) or for a sensor referenced
  to a fixed atmosphere, of which the contract has none among the 30 emitted tags.
- **Reason.** Version 1.0 stated that the same state reads differently in the two strata for
  all transmitters; the truth is defined in gauge terms, so that is only true of a
  fixed-reference sensor.
- **Sensitivity required.** The elevated stratum is itself the check.
- **Notes.** Ranges and units are validated against the contract table copied to
  `config/sensor_specs.json`. Version 1.0 is kept below.

## D27 - Observation units and the atmosphere stratum (version 1.0, superseded)

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Observation values are in the engineering units of the sensor contract (m, m3/h, barg, C, boolean). A gauge pressure is the true absolute pressure minus the atmosphere of the episode stratum (D24), so the same state reads differently in the two strata only for sensors that measure absolute pressure and report gauge. All pressure transmitters of the contract are of that kind (the transmitter is referenced to the site atmosphere, the truth is absolute). Ranges and units are validated against the contract table.
- **Reason.** The truth stores absolute pressure; an instrument reports gauge relative to its own surroundings.
- **Sensitivity required.** The elevated stratum is itself the check.
- **Notes.** The sensor contract file holds the tag mapping; the unit, range, rate, lag and comms delay are in the instrumentation document (section 6.1.1) and are copied to `config/sensor_specs.json`.

## D28 - Noise standard deviations

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Gaussian noise with standard deviation: level 0.25 mm (half of the plus or minus 0.5 mm accuracy, k = 2), flow 0.2 m3/h, pressure 0.005 bar, temperature 0.075 C (half of the plus or minus 0.15 C accuracy read as k = 2). One stream per tag.
- **Reason.** A k = 2 accuracy is two standard deviations.
- **Sensitivity required.** *Proposed*: half and twice each value.
- **Notes.** Flow, pressure and temperature values are selections; only level and temperature follow from a stated accuracy.

## D29 - Quantisation and clipping

- **Version:** 1.1 (2026-10-29)  **Status:** SIM  **Supersedes:** 1.0
- **Decision.** The reading is quantised to span/65535 of the calibrated range and clipped at
  the range limits. A clipped value has quality `suspect` when the unclipped reading lies
  beyond the limit by more than three noise standard deviations of its class (a real
  overrange); a reading that is outside only by noise (for example a flow of zero) is
  clipped and stays `good`. A negative gauge value inside the range is valid and is not
  clipped (the range of PT-201 starts at -1 bar).
- **Reason.** Version 1.0 flagged every clipped value. A flow meter at zero flow would then
  be `suspect` in half of its samples whenever nothing flows, a pattern that would reveal
  the operating state. The three-sigma rule keeps the flag for true overrange.
- **Sensitivity required.** *Proposed*: two and four standard deviations.
- **Notes.** Version 1.0 is kept below.

## D29 - Quantisation and clipping (version 1.0, superseded)

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The reading is quantised to span/65535 of the calibrated range and clipped at the range limits; a clipped value has quality `suspect`. A negative gauge value inside the range is valid and is not clipped (the range of PT-201 starts at -1 bar).
- **Reason.** A 16-bit converter over the calibrated range.
- **Sensitivity required.** None.
- **Notes.** The range limits are those of the contract table.

## D30 - Sample dropout

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** Each scheduled sample is lost with probability 0.05 percent, the same in every episode whatever its content. A lost sample is a row with a null value, availability `missing_sample` and quality `bad`.
- **Reason.** A dropout rate that depended on the scenario would reveal the scenario.
- **Sensitivity required.** *Proposed*: 0.1 and 0.02 percent.
- **Notes.** The draw has its own stream per tag.

## D31 - Valve contacts

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The open contact is 1 when the valve opening alpha reaches 0.98 and returns to 0 when alpha falls below 0.97 (hysteresis 0.01). Only the open contact is emitted (contract). The contact change is delayed by the lag of the sensor table and the row becomes available after the comms delay. Every event-triggered tag has a row at t = 0 with its initial state. The closed contact (alpha at most 0.02) is not emitted.
- **Reason.** A limit switch is an event with a lag, not a position.
- **Sensitivity required.** *Proposed*: thresholds 0.95 and 0.99.
- **Notes.** The pump running indicators and the LSHH detectors are event tags with the same rule for the row at t = 0.

## D32 - Sample phase

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The first sample of a tag is at a phase equal to the SHA-256 digest of its name modulo its sample interval (in milliseconds); later samples follow at the interval.
- **Reason.** Tags must not all sample at the same instant, and the phase must not depend on the scenario.
- **Sensitivity required.** None.
- **Notes.** The phase is a pure function of the tag name.

## D33 - Independent high-high detector inside the engine

- **Version:** 1.1 (2026-10-29)  **Status:** DESIGN  **Supersedes:** 1.0
- **Decision.** Unchanged from version 1.0 (detector offset of 1 mm standard deviation fixed per
  episode, delay 0.2 s, own named stream, protection consumes its output, the LSHH observation is
  the same signal after the comms delay), with one recorded **deviation**: the hidden
  `protection_state` field `independent_level_m` holds the level the detector sees (the true level
  plus the episode offset), where version 1.0 and the first implementation wrote the true level
  into it. The hidden field that was called `process_level_m` is now `true_level_m` and holds the
  true level (Phase 4c).
- **Reason.** The field is named for the detector's input; writing the true level there made two
  fields carry one quantity and hid the offset from an evaluator reading the truth. The change was
  made in Phase 4c together with the requested rename, without being asked for; it is recorded
  here instead of being left as an unrecorded edit.
- **Effect.** Hidden datasets only; the schemas of the proposed hidden datasets moved to version
  0.7.0 (a breaking change for evaluators). No agent-visible schema, observation or trip time is
  affected. Tests: `independent_level_m - true_level_m` equals the offset in the trip event.
- **Sensitivity required.** *Proposed*: offset sigma 0.5 and 2 mm; delay 0.1 and 0.5 s.
- **Notes.** Version 1.0 is kept below.

## D33 - Independent high-high detector inside the engine (version 1.0, superseded)

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Each tank has an independent detector: the true level plus a fixed offset (standard deviation 1 mm, drawn once per episode from its own named stream), and an output delay of 0.2 s. It asserts when level plus offset reaches the trip level; the assertion is located by root-finding (D26) and delivered 0.2 s later. The protection logic consumes the detector output for the high-high trip; the LSHH observation is the same signal after the comms delay. The tag `truth_placeholder` is removed from the rows. The ordinary process level of the alarm is the level estimate of the control system and carries the tag `process_level`.
- **Reason.** The trip must be decided on a signal that has its own error and delay, not on the truth.
- **Sensitivity required.** *Proposed*: offset sigma 0.5 and 2 mm; delay 0.1 and 0.5 s.
- **Notes.** The process level used for the high alarm is still the true level in this phase, labelled as such.

## D39 - Dead-leg pressure

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** An isolated, liquid-full segment holds the pressure it had when it was isolated and relaxes to its connected hydrostatic or boundary pressure with a time constant of 60 s: `H(t) = H_target + (H_0 - H_target) exp(-(t - t_0)/60 s)`. A segment that is open to a tank takes that tank's head, and one open to the distribution boundary takes the reservoir head, without delay. The connected pressure of an isolated segment is the head across its closed isolation valve (first the valve at its inlet end, then other closed valves, then check valves and pumps; neighbours in sorted order); a segment with no neighbour at all takes zero gauge pressure at its elevation. No segment is undetermined.
- **Reason.** A closed pipe does not lose its pressure when the solver has no flow through it; a null would also reveal the operating state to the agent.
- **Sensitivity required.** The time constant at 10, 60 and 300 s (*proposed*).
- **Notes.** Trapped-liquid thermal expansion and compressibility are outside the model: a real isolated segment can hold a pressure unrelated to its neighbours, or rise with temperature. This is a limitation.

## D40 - Alarm on the level-transmitter chain

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** HIGH_ALARM and its clearing are decided on the level-transmitter chain of the tank (lag, noise, quantisation, dropout, comms delay) with the same per-tag streams as the observation, sampled in the engine at the transmitter's own sample times. The protection logic sees the latest sample that has arrived; nothing arrives for a dropped sample. Only the high-high trip is independent (D33).
- **Reason.** The ordinary alarm is a control-system alarm built on the level reading, not on the truth.
- **Sensitivity required.** None beyond the sensor parameters.
- **Notes.** Version 1.0 of D26 located the alarm threshold on the true level; for the alarm that is superseded by this decision, and the located crossing stays for the detector.

## D41 - Campaign episode seeds

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The seed of episode `i` of a campaign is derived from the campaign seed and the index: `SeedSequence(entropy=campaign_seed, spawn_key=(i,))`, taking the first 64-bit word of its state. The helper refuses a campaign in which two indices give one seed. The named test scenarios keep fixed seeds, each different from the others, and are not part of any campaign: their episodes carry the tier `analytic_verification` (or `restricted_benchmark` when D37 restricts them) and are never released as campaign data.
- **Reason.** Two episodes that share a seed share every random draw (noise, dropout, detector offset, demand), so their differences would not be independent evidence. In Phase 4 seven scenarios shared one seed and the pooled dropout count was a fluctuation of about three independent trials.
- **Sensitivity required.** None.
- **Notes.** The derivation is a pure function of the campaign seed and the index, so a campaign can be extended or an episode regenerated without regenerating the others.

## D42 - The sensitivity sweeps as one study

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The sweeps listed in D38 and the one required by D39 are run together as a single study before Phase 7: the wave-criterion factor of D22 at 5, 10 and 20; the standard deviation of log f_d of D23 at 0.05, 0.1 and 0.2, with its correlation time at 900, 1800 and 3600 s; the dead-leg time constant of D39 at 10, 60 and 300 s. In Phase 4c only the D39 sweep is run, on S0u-E and S0u-D, as a preview of the dependence of the observed pressures on that constant.
- **Reason.** One study with one report is easier to review than five partial ones, and the three sweeps act on different tags.
- **Sensitivity required.** The study itself.
- **Notes.** The preview does not replace the study; it was run to say which diagnostic features depend on the constant.

## D43 - First-order method of characteristics

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The transient engine (`verum.transient`) is a first-order method of characteristics on the 28 edges, with the compatibility equations C+ and C- and a friction term evaluated at the old point (`f L/(2 D A) Q|Q|`). Each edge is divided into reaches of the common time step dt = 0.923 ms, the largest that gives every edge at least one reach (the shortest edge is 2 m at 1089.2 m/s, 1.836 ms); the wave speed of each edge is adjusted to `a' = L/(N dt)` with `N = round(L/(a dt))`, the maximum adjustment being 0.53 percent. Junctions conserve mass with equal head at all pipes. Wave speeds are the screening values of the audited package (1089.2, 1082.8, 1078.2 m/s for DN200, DN250, DN300) with the restraint factor psi = 1, a screening value and not a certified pipe property.
- **Reason.** First order with a fixed grid is the simplest scheme that is exact for the frictionless case with Courant number one and has a known error order for the friction term; the adjustment is the standard way to keep every edge on the grid.
- **Sensitivity required.** Wave-speed restraint psi 0.8 and 1.0 and bulk modulus 0.8e9, 1.0e9 and 1.2e9 Pa in the extended study (D42).
- **Notes.** The time step and the adjustment are from section 4.2 of the simulation document (the minimum reach 1.836 ms and the adjusted speeds). The engine is self-built: it is verified against closed forms and other codes, which is verification and not validation.

## D44 - Boundaries of the transient engine

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Tanks and the distribution reservoir are constant-head boundaries. The receipt source is flow-controlled with the first-order response of time constant 2 s (D3) and a head cap equal to 10 barg at `PIPELINE_RECEIPT_BOUNDARY`; the pump is a quasi-steady curve between its inlet and outlet nodes with no inertia (D6); valves follow D4 and D19 with the stroke times of the configuration; a check valve closes after a finite delay (0.05, 0.3 or 1 s, default 0.3 s) and the reverse volume that passes before it closes is accounted; a closed valve is a zero-flow end.
- **Reason.** These are the boundary conditions of the rigid-column engine, so the two engines can be compared on equal terms.
- **Sensitivity required.** Check-valve delay 0.05, 0.3 and 1 s (D42).
- **Notes.** The default check-valve delay is a selection, not a manufacturer value.

## D45 - No cavitation model

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The engine has no cavitation or column-separation model. Any node at or below the vapor pressure of the episode (its stratum and volatility class) is flagged; the interval becomes a hidden `phase_invalid` window and nothing from it is usable. Pressures are never clipped.
- **Reason.** A first-order engine without a vapor model gives meaningless numbers below the vapor pressure; clipping would hide that.
- **Sensitivity required.** None.
- **Notes.** Column-separation experiments are usable only for the segments that do not reach vapor pressure.

## D46 - Volatility classes

- **Version:** 4.0 (2026-10-30)  **Status:** SIM  **Supersedes:** 3.0
- **Decision.** Three volatility classes, as in version 3.0: `EPA_GENERIC_MOTOR_GASOLINE_RVP10` (RVP 10 psi) is resolved and is the stress class; `RVP_9_0` (baseline) and `RVP_9_5` (upper bracket) are derived, provisional, evidence SIM, with the AP-42 gasoline correlation (S = 3, B in degrees Rankine, P_v (psia) = exp(A - B/T_R)). The verification gate stands as specified (constants within 0.1 percent, true vapor pressures within 2 percent, a failed gate leaves the derived classes unresolved).
- **Deviation record.** Version 3.0 named eight tabulated classes (RVP 7, 7.8, 8.3, 10, 11.5, 13, 13.5, 15). The edition fetched (June 2026 edition of the chapter, Table 7.1-2 and the worked example of Section 7.1.4) tabulates three gasoline classes, so the gate ran on the points available and not on the eight; RVP 7.8, 8.3, 11.5, 13.5 and 15 do not appear in it and were not checked. Maximum relative deviation of the correlation from the tabulated point:

  | class | tabulated point | constants A, B | true vapor pressure |
  | --- | --- | --- | --- |
  | RVP 13 | Table 7.1-2, 60 F | 2.8e-5 | 0.755 percent |
  | RVP 10 | Table 7.1-2, 60 F | 5.1e-6 | 0.274 percent |
  | RVP 7 | Table 7.1-2, 60 F | 1.4e-5 | 0.438 percent |
  | RVP 12 | worked example, 528.37 R | 1.5e-5 | 0.010 percent |
  | RVP 7 | worked example, 528.37 R | 1.4e-5 | 0.045 percent |

  All five points pass. The bracketing check requested for RVP 8.3 cannot be made, because RVP 8.3 is not tabulated. In its place a weaker check is made with the classes that are tabulated: at 25, 35, 40 and 45 C the true vapor pressures of `RVP_9_0` and `RVP_9_5` lie between those of the tabulated RVP 7 and RVP 10 constants, and `RVP_9_0` lies below `RVP_9_5`. That check is necessary and not sufficient. The derived classes stay provisional (status provisional, evidence SIM); nothing in the dataset presents them as validated.
- **Reason.** Gulf 95 RON export specifications and neighbouring specifications cap RVP at 9 to 9.5 psi. A Saudi domestic summer limit is not established. The derived classes bracket that range.
- **Sensitivity required.** The three classes are themselves the sweep (D51).
- **Notes.** Expected values to check: RVP 9 about 44 kPa at 25 C and 82 kPa at 45 C (the correlation gives 43.96 and 81.93). Version 3.0 is kept below.

## D46 - Volatility classes (version 3.0, superseded)

- **Version:** 3.0 (2026-10-29)  **Superseded by:** 4.0  **Status:** SIM
- **Decision.** Three volatility classes. `EPA_GENERIC_MOTOR_GASOLINE_RVP10` (RVP 10 psi) is resolved and is the stress class (the audited constants A = 11.724, B = 5237.3 degR). `RVP_9_0` (baseline) and `RVP_9_5` (upper bracket) are derived, provisional, evidence SIM, with the AP-42 gasoline correlation: A = 15.64 - 1.854 S^0.5 - (0.8742 - 0.3280 S^0.5) ln(RVP) and B = 8742 - 1042 S^0.5 - (1049 - 179.4 S^0.5) ln(RVP), S = 3, RVP in psi, B in degrees Rankine, P_v (psia) = exp(A - B/T_R). Verification gate, run before any derived class is used: the formula must reproduce A = 11.724 and B = 5237.3 for RVP 10 within 0.1 percent and must agree within 2 percent with the tabulated true vapor pressures of Table 7.1-2 of the EPA AP-42 chapter 7.1 for the tabulated classes (RVP 7, 7.8, 8.3, 10, 11.5, 13, 13.5, 15) at the tabulated temperatures. A derived class that fails the gate, or whose gate cannot be run, is an `UnresolvedParameter` and raises when selected; the formula is never adjusted to pass.
- **Reason.** Gulf 95 RON export specifications and neighbouring specifications cap RVP at 9 to 9.5 psi. A Saudi domestic summer limit is not established. The derived classes bracket that range.
- **Sensitivity required.** The three classes are themselves the sweep (D51).
- **Notes.** Versions 1 and 2 were drafts outside this log. Expected values to check: RVP 9 about 44 kPa at 25 C and 82 kPa at 45 C.

## D47 - The transient engine does not change tiers

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** MOC results do not change any dataset tier. The flagged validity windows of D22 and D25 stay flagged, and the tier rule of D37 is unchanged, until a later decision integrates the engine and compares its output with the episodes.
- **Reason.** The engine is a standalone library in this phase; nothing of it is in `verum.sim`.
- **Sensitivity required.** None.
- **Notes.** The integration rule is proposed in the Phase 5 report (windowed use).

## D48 - Dataset-card limitations

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** The dataset card lists, as limitations: the pump curve is synthetic; no practising engineer reviewed the design, which was checked against general engineering rules of thumb only; the receipt branch velocity of 5.2 m/s and the suction branch velocity of 2.6 m/s exceed common design guidance (an unsourced recollection) and inlet-jet and static-charge effects are not modelled; the meter loss coefficient K = 1 is probably low; there are no pump strainers, vapor handling, vent or vapor-recovery hardware; there is no pump start, trip or changeover; the Saudi domestic RVP limit is not established.
- **Reason.** A reader of the dataset must be able to see where the design departs from practice.
- **Sensitivity required.** None.
- **Notes.** Written into `docs/dataset_card.md`.

## D49 - Minimum stable flow window deferred

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Deferred to Phase 7: a hidden validity window `pump_below_minimum_stable_flow` when the pump flow falls below 30 percent of rated (90 m3/h). The 30 percent figure is an unsourced rule of thumb.
- **Reason.** The window needs the pump model of a later phase and a decision about its tier effect.
- **Sensitivity required.** Sweep 20, 30 and 40 percent when implemented.
- **Notes.** Not implemented in Phase 5.

## D50 - Further sensitivity sweeps

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
- **Decision.** Added to the study of D42: the fitting loss multiplier 0.5, 1, 2, 3; the meter loss K 0.5, 1, 2, 4; the pump curve steepness k = 8, 12, 16 m (shutoff ratio 1.19, 1.29, 1.38) with the duty point held at 300 m3/h and 42 m by recalibrating the boundary coefficient; the NPSH3 coefficient 2.5, 4, 6 m.
- **Reason.** The design values are unreviewed (D48); the study shows which results depend on them.
- **Sensitivity required.** The study itself.
- **Notes.** Run in Phase 5 as one report.

## D51 - Grid of the pumping-minimum tables

- **Version:** 1.1 (2026-10-30)  **Status:** DESIGN  **Supersedes:** 1.0
- **Decision.** The pumping-minimum tables are computed on the grid atmosphere {coastal, inland} x volatility {RVP_9_0, RVP_9_5, RVP10} x temperature {25, 35, 40, 45 C} x fitting profile {pipe_only, reference_fittings} x tank x NPSH3 {2.5, 4, 6 m}, at f_d = 0.8. One file per (atmosphere, volatility) pair. A cell in which no level of 1.8 to 12 m passes is stored as an unresolved record.
- **Reason.** The worst-case factor 0.8 gives the largest flow and the smallest NPSH margin (D24).
- **Sensitivity required.** None.
- **Notes.** Recomputed by `tools/strata_tables.py` (D57); the stored tables reproduce, level for level. Version 1.0 named untracked scripts under `local/tools/`; version 1.0 is kept below.

## D51 - Grid of the pumping-minimum tables (version 1.0, superseded)

- **Version:** 1.0 (2026-10-29)  **Superseded by:** 1.1  **Status:** DESIGN
- **Decision.** The pumping-minimum tables are computed on the grid atmosphere {coastal, inland} x volatility {RVP_9_0, RVP_9_5, RVP10} x temperature {25, 35, 40, 45 C} x fitting profile {pipe_only, reference_fittings} x tank x NPSH3 {2.5, 4, 6 m}, at f_d = 0.8. One file per (atmosphere, volatility) pair. A cell in which no level of 1.8 to 12 m passes is stored as an unresolved record.
- **Reason.** The worst-case factor 0.8 gives the largest flow and the smallest NPSH margin (D24).
- **Sensitivity required.** None.
- **Notes.** Recomputed by `local/tools/` scripts.

## D52 - Production baseline NPSH3 coefficient

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
- **Decision.** The production baseline NPSH3 coefficient is 4 m; 2.5 m and 6 m are sensitivities.
- **Reason.** One coefficient keeps the production tables single-valued (D35).
- **Sensitivity required.** 2.5 and 6 m (D50).
- **Notes.** Restates D35 for the production baseline.

## D53 - Validity-window factors

- **Version:** 3.0 (2026-10-31)  **Status:** DESIGN  **Supersedes:** 1.2  **Refines:** D22
- **Decision.** The minimum ratio of event duration to the wave round trip of the path (D22) is 50 for a valve stroke (`valve_stroke`) and 10 for a receipt set-point step (`receipt_setpoint`), a flow collapse (`flow_collapse`) and a path closure (`path_closed`), as in version 1.2 except that the stroke factor is 50 instead of 25. The set-point factor stays at 10 on the Phase 5b comparison of the inertial head (agreement within 5 percent of the dip at a duration of 8 s, ratio 22).
- **Reason.** On the valid interval (command to the first `phase_invalid` window of the transient engine, D55) the rigid minus transient error of the PT-001 peak is +13.5 percent at ratio 20, -8.6 percent at 27.7, -4.2 percent at 55 and -2.7 percent at 83; there are no data between 27.7 and 55. A factor of 50 lies just below the first ratio that reaches 5 percent and is the nearest round number that is supported by the data. It rests on one path, one valve law and a capped source, and remains provisional.
- **Sensitivity required.** The valve-stroke factor 10, 20, 25, 30, 50 and 55 in the extended study (D42, `tools/d42_study.py d53`).
- **Notes.** The configuration parameter is `wave_criterion_factor_valve_stroke`; `wave_criterion_factor` (10) is the other factor. Whether a stroke is judged at all is decided by D58. Versions 1.2, 1.1 and 1.0 are kept below.

## D53 - Validity-window factors (version 1.2, superseded)

- **Version:** 1.2 (2026-10-30)  **Superseded by:** 3.0  **Status:** DESIGN  **Supersedes:** 1.1  **Refines:** D22
- **Decision.** The ratio of event duration to the wave round trip of the path (D22) has a minimum for each kind of event: a valve stroke (`valve_stroke`) 25; a receipt set-point step (`receipt_setpoint`), a flow collapse (`flow_collapse`) and a path closure (`path_closed`) 10, the factor of D22. The set-point factor stays at 10 on the result of the Phase 5b comparison (step 1): after the correction of the post-event row, the rigid-column pressure at the start of E002 agrees with the mean of the transient-engine pressure within 5 percent of the dip `Lambda_down |dQ/dt|` at 1, 2 and 4 s after a step down, a step up and a start-up, at a duration of four controller time constants (8 s, ratio 22); a flow collapse caused by the controller (4.4 s, ratio 12) is the same physics.
- **Reason.** Version 1.1 applied the stroke factor to the flow collapse and the path closure as well. Version 1.2 does not: those windows are defined by the measured flow, not by the stroke, and in S0u-D the collapse of 4.4 s is produced by the set-point step to zero, which step 1 found valid at that duration. The basis for 25 is that of version 1.1: on the valid interval the rigid minus transient error of the PT-001 peak is -15.3 percent at ratio 5.5, -29.1 at 10, +13.5 at 20, -8.6 at 27.7, -4.2 at 55 and -2.7 at 83; only 55 reaches 5 percent, and the sign changes between 20 and 27.7. The value 25 is the owner's selection, not supported by a 5 percent criterion on these data, resting on one path, one valve law and one source; the owner may prefer a value near 55.
- **Sensitivity required.** The valve-stroke factor 10, 20, 25, 30 and 55 in the extended study (D42, `tools/d42_study.py d53`).
- **Notes.** Effect on the shipped scenarios (factor 25): S0u-D, the 10 s opening of XV-R000 on the path to TK-102 (23.5 round trips of 0.425 s), is flagged and the episode becomes `restricted_benchmark`; at 10 and 20 it is clean, at 30 and 55 it has two stroke windows. S0u-E gets a stroke window for the 10 s closure at 30 and 55. The configuration parameter is `wave_criterion_factor_valve_stroke`; `wave_criterion_factor` (10) is the other factor. The oscillation of the transient solution about the rigid-column mean (period 1.0 s in the network response) is not represented by the rigid column at any ratio. Versions 1.1 and 1.0 are kept below.

## D53 - Validity-window factors (version 1.1, superseded)

- **Version:** 1.1 (2026-10-30)  **Superseded by:** 1.2  **Status:** DESIGN  **Supersedes:** 1.0  **Refines:** D22
- **Decision.** The ratio of event duration to the wave round trip of the path (D22) has a separate minimum for each kind of window: `valve_stroke` 25, `receipt_setpoint` 10, as in version 1.0. A valve stroke, and the flow collapse and path closure that a stroke causes, is valid for the rigid column only if the stroke lasts at least 25 round trips; a receipt set-point step is valid at 10. The set-point factor stays at 10 on the result of the Phase 5b comparison (step 1): after the correction of the post-event row, the rigid-column pressure at the start of E002 agrees with the mean of the transient-engine pressure within 5 percent of the dip `Lambda_down |dQ/dt|` at 1, 2 and 4 s after a step down, a step up and a start-up, at a duration of four controller time constants (8 s, ratio 22).
- **Reason.** Comparison T2 of Phase 5 (one receipt path, one valve law, the capped source). Version 1.0 gave as basis errors of the rigid-column peak of 39 percent at ratio 10, 8.3 percent at 20 and 2.5 percent at 27.7. Those peaks ran to 0.1 s before the end of the stroke, which is after the first `phase_invalid` window of the transient engine has opened for ratios of 20 and above (D55), so they are withdrawn. On the valid interval (command to the first window) the rigid minus transient error of the PT-001 peak is -15.3 percent at ratio 5.5, -29.1 at 10, +13.5 at 20, -8.6 at 27.7, -4.2 at 55 and -2.7 at 83. Of the strokes tested only a ratio of 55 reaches 5 percent, and the sign changes between 20 and 27.7, so the error is not a simple function of the ratio. The value 25 is kept as the owner's selection: it lies between a ratio that fails clearly and one that fails by less, it is not supported by a 5 percent criterion on these data, and it rests on one path, one valve law and one source. It is provisional and is to be confirmed by the owner, who may prefer a value near 55.
- **Sensitivity required.** The valve-stroke factor 20, 25, 30 and 55 in the extended study (D42), replacing the 5, 10 and 20 of D38.
- **Notes.** The factor of the configuration (`wave_criterion_factor`, 10) is the set-point factor; the valve-stroke factor is a new parameter. The oscillation of the transient solution about the rigid-column mean (period 1.0 s in the network response) is not represented by the rigid column at any ratio of this table. Version 1.0 is kept below.

## D53 - Validity-window factors (version 1.0, superseded)

- **Version:** 1.0 (2026-10-30)  **Superseded by:** 1.1  **Status:** DESIGN  **Refines:** D22
- **Decision.** The ratio of event duration to the wave round trip of the path (D22) has a separate minimum for each kind of window: `valve_stroke` 25, `receipt_setpoint` 10. A valve stroke, and the flow collapse and path closure that a stroke causes, is valid for the rigid column only if the stroke lasts at least 25 round trips; a receipt set-point step is valid at 10. The receipt set-point factor stays at 10 on the result of the Phase 5b comparison (step 1): after the correction of the post-event row, the rigid-column pressure at the start of E002 agrees with the mean of the transient-engine pressure within 5 percent of the dip `Lambda_down |dQ/dt|` at 1, 2 and 4 s after a step down, a step up and a start-up, at a duration of four controller time constants (8 s, ratio 22).
- **Reason.** Comparison T2 of Phase 5 (one receipt path, one valve law, the capped source): at a ratio of 20 (7.2 s) the rigid-column peak is 8.3 percent from the transient peak before the closure, at 27.7 (10 s) 2.5 percent, at 10 (3.6 s) 39 percent; the data cannot separate thresholds between 20 and 27, so 25 is the round number between the failing and the passing case. It rests on one path, one valve law and one source and is provisional.
- **Sensitivity required.** The valve-stroke factor 20, 25 and 30 in the extended study (D42), replacing the 5, 10 and 20 of D38.
- **Notes.** The factor of the configuration (`wave_criterion_factor`, 10) is the set-point factor; the valve-stroke factor is a new parameter. The oscillation of the transient solution about the rigid-column mean (period 1.0 s in the network response) is not represented by the rigid column at any ratio of this table.

## D54 - Dead-leg unvalidated window

- **Version:** 1.0 (2026-10-30)  **Status:** DESIGN  **Refines:** D39, D25
- **Decision.** A hidden validity window of kind `dead_leg_unvalidated` opens for an isolated segment (D39) when the pressure it holds differs from its target (the head across its closed isolation valve to which D39 relaxes it) by more than 0.5 bar, and closes when the difference is below 0.05 bar. The window is written like the others (hidden `validity_windows` and the episode record). The tier of an episode that lists it follows D37 (`restricted_benchmark`).
- **Reason.** D39 holds an isolated segment at its last determined head and relaxes it with a selected time constant; neither the held value nor the relaxation is validated, and a large difference between the held value and the target is where the choice matters most. The two thresholds are a hysteresis so that a segment near 0.5 bar does not open and close a window at every step.
- **Sensitivity required.** The dead-leg time constant 10, 60 and 300 s (D42), and the thresholds 0.25, 0.5 and 1 bar for the opening.
- **Notes.** The thresholds are unsourced selections.

## D55 - Usable interval after a phase_invalid window

- **Version:** 1.0 (2026-10-30)  **Status:** DESIGN  **Refines:** D45
- **Decision.** When a `phase_invalid` window opens in the transient engine during a closure, everything from its start to the end of that transient is excluded from usable data. The transient ends when the heads at all points have settled to within 0.05 bar of the heads they have at the end of the run, measured after the last command. Results quoted from a run with such a window are the values before the window opened, and the rigid-column values at the same instants.
- **Reason.** The engine has no vapor model (D45); after the first node reaches the vapor pressure the numbers describe a liquid that does not exist, and the oscillation that follows is not a property of the system.
- **Sensitivity required.** None.
- **Notes.** In the comparison tables the values at the instant of closure are labelled unusable when a window opens before it.

## D56 - Published-experiment rungs R12 and R13

- **Version:** 1.0 (2026-10-30)  **Status:** DESIGN
- **Decision.** Two rungs are added to the transient verification ladder from the water-hammer experiments of Jensen et al. 2018 (Fluids 3(3) 64): R12 compares the engine with experiments 1 to 3 (single phase, no cavitation expected) and R13 with the first pressure peak of experiments 5 and 6, up to the first `phase_invalid` window. The experimental parameters are kept in a test-data file with their provenance. The closure exponent of the valve law is a value fitted by the authors, not a measurement, and the file says so. The test-only valve follows the authors' law `tau_v = 1 - (t/tc)^m` and `Q = Q0 tau_v sqrt(H/H0)`; the wave speed is set directly and friction is quasi-steady Darcy-Weisbach. The tolerances are fixed in the test docstring before the run: against the paper's quasi-steady model, maximum 1 percent, third peak 2 percent, tenth peak 3 percent, frequency 1 percent; against measurement, first peak 3.5 percent for experiments 1 to 3 and 5 percent for R13; later peaks and frequency are reported and not tested, with the overestimate of quasi-steady friction stated as a known limitation. A tolerance that is missed is reported and investigated and is not widened.
- **Reason.** Until now the engine was checked against closed forms and other codes only; this is its first comparison with measurement, and the first quantity at risk is the pressure rise at the valve.
- **Sensitivity required.** None.
- **Notes.** A comparison with experiments is validation of the numerical method for those pipes, not of the facility model.

## D57 - Study and table scripts in a tracked directory

- **Version:** 1.0 (2026-10-30)  **Status:** DESIGN
- **Decision.** The scripts that compute the studies and tables the documents quote (the D42 study, the pumping-minimum and stratum tables, the transient scenarios T1 to T4, the experiment comparisons) live in `tools/`, which is tracked. Each has a module docstring that says what it computes and which decision it serves. Scripts that need the full audited package or an isolated environment stay in `local/checks/`. Results and reports stay in `local/`.
- **Reason.** A table in a document that cannot be regenerated from tracked files cannot be checked.
- **Sensitivity required.** None.
- **Notes.** D51 and the documents that named `local/tools/` now name `tools/`.

## D58 - Stroke windows need flow

- **Version:** 2.0 (2026-10-31)  **Status:** DESIGN  **Supersedes:** 1.0  **Refines:** D53
- **Decision.** A valve stroke can open a `valve_stroke` window only if the flow through the valve is at least 10 percent of the design flow of its path (600 m3/h for the receipt path, the receipt flow of the configuration; 300 m3/h for the delivery path, the duty flow of the pump). The flow is read at the start of an opening stroke, and at the instant the opening of a closing stroke has fallen to 0.2 (the stopped flow, and with it the surge, is decided there). A stroke below that flow is judged valid and is counted as an evaluated event. The window of a closing stroke, if there is one, still starts at the start of the stroke and is written at that time of the record.
- **Reason.** The pressure surge of a closure scales with the flow that is stopped, and a valve whose opening is above 0.2 stops little of it. A closure that starts together with a set-point step to zero (S0u-D at 600 s) starts at the full flow, but the controller removes the flow within about 4.4 s, before the valve has closed; version 1.0 flagged it for a surge that cannot occur.
- **Sensitivity required.** The fraction 5, 10 and 20 percent (`tools/d42_study.py d58`).
- **Notes.** The opening of 0.2 and the 10 percent are unsourced selections. The rule changes the tier of S0u-D from restricted_benchmark to analytic_verification and leaves S0u-E restricted. Version 1.0 is kept below.

## D58 - Stroke windows need flow (version 1.0, superseded)

- **Version:** 1.0 (2026-10-31)  **Superseded by:** 2.0  **Status:** DESIGN  **Refines:** D53
- **Decision.** A valve stroke can open a `valve_stroke` window only if the flow through the valve at the start of the stroke is at least 10 percent of the design flow of its path (600 m3/h for the receipt path, the receipt flow of the configuration; 300 m3/h for the delivery path, the duty flow of the pump). A stroke below that flow is judged valid and is counted as an evaluated event.
- **Reason.** The pressure surge of a closure scales with the flow that is stopped; a stroke that starts with almost no flow cannot produce the transient the window warns about.
- **Sensitivity required.** The fraction 5, 10 and 20 percent (`tools/d42_study.py d58`).
- **Notes.** The rule uses the flow at the start of the stroke. A closure that starts together with a set-point step to zero (S0u-D at 600 s) starts at the full flow, although the controller removes the flow within about 4.4 s, before the valve has closed; the rule as written flags it. The 10 percent is an unsourced selection.

## D59 - Dense truth rows by window kind

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN  **Refines:** D34
- **Decision.** The 0.1 s truth rows of D34 are written while a valve moves and inside a window of kind `valve_stroke`, `flow_collapse` or `receipt_setpoint`. They are not written inside `dead_leg_unvalidated`, `branched_lineup` or `path_closed` windows.
- **Reason.** The dead-leg window lasts hundreds of seconds and the quantity in it relaxes slowly; dense rows there only enlarge the truth file (S0u-E grew by 49 percent in Phase 5b).
- **Sensitivity required.** None.
- **Notes.** A window of a transient kind that overlaps a slow one keeps its dense rows.

## D60 - Leak

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D10
- **Decision.** A pipe leak is an orifice to the atmosphere, `Q = Cd A sqrt(2 p_gauge / rho)`, with `Cd = 0.62`, `p_gauge = rho g (H - z)` at the leak point (total head, velocity head neglected), the area `A` log-uniform between 2e-6 and 1e-3 m2, and the position uniform along the edge excluding the end 5 percent (fraction 0.05 to 0.95). It is valid only while the gauge pressure at the leak is above 10 kPa (D10); otherwise the candidate is rejected (D66). The spilled mass leaves the network once and is added to the spill line of the mass ledger. There is no flashing.
- **Reason.** A sharp-edged orifice is the simplest outward single-phase leak law and has a closed form that tests can check by hand. The log-uniform area spans about 2.7 decades, from a weep to a large hole.
- **Sensitivity required.** `Cd` 0.5, 0.62 and 0.8 in the audit (D68); the pressure threshold 5, 10 and 20 kPa (D10).
- **Notes.** How the leak enters the steady network, the rigid-column engine and the ledger is in `docs/fault_models.md`; the area range and `Cd` are unsourced selections.

## D61 - Valve restriction

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D19, D31
- **Decision.** A restricted valve has an actual opening ceiling `alpha_stuck`, uniform in `[0.15, 0.9]`, reached as the severity rises, `alpha = min(alpha_motion, 1 - s (1 - alpha_stuck))`. The command and the stroke are unchanged. The loss is the law of D19 at the actual opening, and the open contact follows D31, so an opening below 0.98 reads not open. A contact that stays open while the valve is restricted is a compound fault and is not part of the single-fault audit.
- **Reason.** A stuck or fouled valve that moves only part of its travel is the common restriction; keeping the command separate from the actual opening is what makes the fault observable only through the process.
- **Sensitivity required.** None in this phase (the audit covers the range).
- **Notes.** The range is an unsourced selection.

## D62 - Pump head degradation

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D2
- **Decision.** The head curve of the running pump is multiplied by `head_scale`, uniform in `[0.70, 0.98]` at severity one and interpolated linearly with the severity, for the whole curve (the shutoff head and the coefficient `k`). The speed is fixed and the efficiency is unchanged.
- **Reason.** A worn impeller lowers the head at all flows by about the same fraction; scaling both terms keeps the curve shape.
- **Sensitivity required.** None in this phase.
- **Notes.** The shaft power at a given flow is computed from the scaled head with the unchanged efficiency.

## D63 - Sensor faults

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D27 to D32
- **Decision.** Sensor faults act on the continuous tags only (LT, FT, PT, TT), in the sensor chain after sampling and before noise and quantisation. Bias: `+ b` of span, `b` in `±[0.2, 5]` percent. Drift: `+ d (t - t_on)` of span per hour, `d` in `±[0.2, 5]` percent per hour. Stuck-at: the reading is frozen at the value of the first sample at or after the onset. Truth and every other tag are unchanged.
- **Reason.** Bias, drift and a frozen reading are the usual analogue transmitter faults; the span makes the sizes comparable between tags.
- **Sensitivity required.** None in this phase.
- **Notes.** All three variants use the audited fault type `SENSOR_DRIFT` and differ in `mechanism`.

## D64 - Misrouting

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D4, D31
- **Decision.** Two variants on the tank inlet and outlet valves and the pump-branch valves. (a) The valve is commanded closed but is physically open (the opening rises to 1 as the severity rises). (b) The valve is commanded open but is stuck at an opening of at most 0.02 (the ceiling falls to a value log-uniform in `[0.005, 0.02]`). The commanded state, the actual opening and the contact state stay separate records.
- **Reason.** These are the two ways a lineup differs from what the operator believes it to be.
- **Sensitivity required.** None in this phase.
- **Notes.** The states that follow (two suction branches open, a receipt into two tanks) are handled by the engine's branched scheme and its gates and are not suppressed.

## D65 - Fault onset and ramp

- **Version:** 1.0 (2026-10-31)  **Status:** SIM
- **Decision.** The onset is uniform in `[600, T - 1800]` s. A hydraulic fault ramps linearly over 30, 300 or 1200 s; there are no steps. A sensor fault may step. Faults persist to the end of the episode; there is no recovery in version 1.
- **Reason.** A ramp avoids a step that a rigid-column model of D22 cannot represent; the last 1800 s leave time for the fault to show.
- **Sensitivity required.** The ramp time in the audit.
- **Notes.** The three ramp times are selections.

## D66 - Rejection of faulted candidates

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN  **Refines:** D20
- **Decision.** A candidate episode that violates any gate (pump domain, phase screen, pumping minimum, mass ledger, solver convergence, the leak pressure condition) is written as `simulation_rejected` and is never labelled as a fault. The leak pressure condition and a leak on an edge without a determined pressure are gate `SGF`.
- **Reason.** A fault whose consequence the model cannot represent would put a label on a physically invalid record.
- **Sensitivity required.** None.
- **Notes.** The rejection record is never agent-visible.

## D67 - Edge-flow convention

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN  **Refines:** D27
- **Decision.** The `flow_m3s` of an edge row is the flow at its downstream end, so that FT-001 and FT-201 read at their meter nodes. A leak is a separate sink recorded in the edge row as `leak_flow_m3s`; the flow at the upstream end is the written flow plus the leak flow.
- **Reason.** The meters sit at the ends of the edges they are attached to; without a leak the two ends are equal and the convention changes nothing.
- **Sensitivity required.** None.
- **Notes.** The field `leak_flow_m3s` is present in an edge row only when it is not zero.

## D68 - Audit detectability thresholds

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN
- **Decision.** A change of a tag is detectable above two thresholds, each three times a standard deviation: the noise standard deviation of the tag (D28), and the standard deviation of the healthy variability of the tag measured over 20 seeds with the demand process on. The change is that of the noise-free sampled series averaged over 60 s.
- **Reason.** The first threshold is what a single reading can resolve; the second is what the healthy process itself does. A fault below both has no observable consequence.
- **Sensitivity required.** `Cd` 0.5, 0.62 and 0.8 for the leak thresholds.
- **Notes.** The audit reports, and does not choose, the severity ranges.

## D73 - Healthy variability, profile v2

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D30
- **Decision.** A scenario file names a `variability_profile`: `off`, `v1` or `v2`. `off` and `v1` reproduce the existing files bit for bit. Profile `v2` adds two changes on named streams. (a) The delivery-demand factor f_d follows piecewise constant regimes: each value is log-uniform in [0.6, 8], each dwell is uniform in [600, 1800] s, the change between regimes is a linear ramp of 60 s, and the existing Ornstein-Uhlenbeck process (sigma 0.05, correlation time 1800 s) is applied on top. A regime outside the gates (pump domain Q/s at most 350 m3/h, minimum stable flow 90 m3/h of D49, phase and NPSH screen, pumping minimum) is redrawn and each redraw is recorded. If any state at f_d = 0.6 exceeds Q/s = 350 m3/h minus a margin of 5 m3/h, the lower bound is raised to the smallest value that keeps the margin, and the raised bound is recorded in the configuration. (b) The receipt set-point follows an OU process with sigma 2 percent of the set-point, correlation time 600 s, clipped to plus and minus 6 percent, subject to the headroom screen at 1.06 times the set-point. The hidden `boundary_state` records the regime value and the receipt set-point.
- **Reason.** Under profile v1 the healthy tags vary only by a slow OU process; the audit thresholds of D68 and D77 are three standard deviations of the healthy variability, and a baseline that is too quiet would make faults look more detectable than they are.
- **Sensitivity required.** Healthy standard deviation per tag under v1 and v2 over 20 seeds; the pumping-minimum tables at the worst-case f_d of v2 for all strata, both fitting profiles and NPSH3 2.5, 4 and 6 m.
- **Notes.** The regime and receipt streams are separate from every existing stream (D30), so that the existing streams are not displaced. The bounds 0.6 and 8, the dwell times and the 60 s ramp are unsourced selections.

## D74 - Valve restriction modes

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D61, D31
- **Decision.** A valve restriction has two modes, drawn with equal probability. In `position_visible` the actual opening is the stuck opening alpha_stuck and the contact reads not open (D31 reads the contact from the actual opening). In `obstruction` the loss coefficient follows alpha_stuck while the closed-limit contact still reads open, as it would for a valve whose stem is open and whose disc or seat is blocked. The mode is recorded in the hidden `fault_truth` as `fault_mode`.
- **Reason.** The two physical cases differ in what the agent can see, and the audit must cover both.
- **Sensitivity required.** The audit of D77 for both modes.
- **Notes.** The 50 percent split is a selection.

## D75 - Misrouting (b) eligibility

- **Version:** 1.0 (2026-10-31)  **Status:** SIM  **Refines:** D64
- **Decision.** Misrouting (b), an open valve reported closed or a closed valve reported open to the agent while the actual state differs, is eligible only on a valve of a parallel branch, for example in the lineup RECEIVE_101_102. It is not eligible on a valve in series with the whole flow, where the physical state is fixed by the flow. Misrouting (a) is unchanged.
- **Reason.** On a serial valve the actual state is decided by the flow and a mismatch is not a separate fault.
- **Sensitivity required.** None.
- **Notes.** An ineligible draw is rejected with the gate and the reason.

## D76 - Latent faults

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN
- **Decision.** A fault placed on an asset that is inactive in the active lineup (a stopped pump, a closed valve on a path that carries no flow) is labelled `latent` in the hidden `fault_truth` field `activity`; an active asset is labelled `active`. The validator returns `active` or `latent`. In a later campaign latent faults are at most 5 percent of fault episodes and are excluded from detection metrics.
- **Reason.** A fault with no possible consequence on the telemetry must not be scored as a missed detection.
- **Sensitivity required.** None.
- **Notes.** The campaign generator is not part of this phase; the cap is recorded for it.

## D77 - Agent-side detectability audit

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN  **Refines:** D68
- **Decision.** The audit computes residual features from the observation stream and design data only: mass balance, pump consistency, delivery law, FT-201 against design flow, receipt law, a one-step-ahead persistence forecast per continuous tag, and the discrete features valve contacts and pump run status. The design model is perturbed over five draws (pump head plus and minus 3 percent, fitting K multiplier in [0.5, 2], boundary coefficient multiplier in [0.8, 1.25]). The threshold of a feature is three times its standard deviation over 20 healthy seeds and five draws under profile v2. For each (fault, asset, severity) the margin of a feature is the maximum signal over the threshold, and the time to first exceed is counted in 60 s windows.
- **Reason.** The audit of Phase 6a used the twin; an agent has only the observations and design data, and a design that is wrong by the nuisance amounts must not raise an alarm.
- **Sensitivity required.** The nuisance ranges above and the 20 seeds.
- **Notes.** The nuisance ranges are unsourced selections.

## D78 - Severity classes

- **Version:** 1.0 (2026-10-31)  **Status:** DESIGN  **Refines:** D68
- **Decision.** For an episode the margin m is the maximum over features of signal over threshold (D77). The class is `invisible` for m below 1, `marginal` for m from 1 to below 3 and `clear` for m from 3. A later sampler allocates equally across the three classes and draws log-uniformly within a class. The boundaries per (fault type, asset class) are stored in `config/severity_classes.json`.
- **Reason.** Sampling log-uniformly over the whole range puts most episodes in one class; the classes make the share of hard and impossible cases explicit.
- **Sensitivity required.** The share of episodes per class under the old and the class-balanced sampling.
- **Notes.** No severity range is changed to improve the shares.

## Episode profile

Episodes use the `reference_fittings` profile (D15). The `pipe_only` profile exists to
reproduce the audited reference figures and is not used for episodes.

## Open proposals pending team confirmation

These are Phase 1 choices that the audited documents do not state. They are
implemented, but they are proposals and need confirmation by the team.

| ID | Proposal | Where |
| --- | --- | --- |
| P1 | Lineup transitions other than the two documented chains: all-closed states reach each other; an active mode is entered from, and left to, a hold state only; the receipt hold serves modes that open `XV-R000`; the changeover hold serves modes with a running pump and keeps the source tank. | `verum.lineups.transitions` |
| P2 | A high-high isolation request closes both `XV-R000` and the inlet valve of the tripped tank; the confirmation timeout is the larger of the two valve timeouts. | `verum.protection.config` |
| P3 | A latched trip is reset only by an authorised event from operations or protection, with the independent signal valid and below the trip level minus the hysteresis of D16. | `verum.protection.machine` |
| P4 | The factor 10 of D22 and the event-duration definitions (stroke time; four controller time constants). | `verum.sim.validity` |
| P5 | The operations controller closes `XV-R000` and the tank inlet valve in response to a protection request (reactive command with a configured delay). | `verum.ops` |
