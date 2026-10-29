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
- Log version 4 (2026-10-29). Records are version 1.0 unless stated. A record
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
| D11 | Bulk-liquid temperature stratum | SIM | 1.0 |
| D12 | Isolation confirmation timeout | SIM | 1.0 |
| D13 | Residual-flow threshold for failed isolation | SIM | 1.0 |
| D14 | Friction law | SIM | 1.0 |
| D15 | Fitting profiles | SIM | 1.0 |
| D16 | Alarm hysteresis | SIM | 1.0 |
| D17 | Time step and integration scheme | DESIGN | 1.0 |
| D18 | Quasi-steady validity | DESIGN | 1.0 |
| D19 | Valve motion and loss coefficient | SIM | 1.0 |
| D20 | Truth log format | DESIGN | 1.0 |
| D21 | Temperature held constant per episode | SIM | 1.0 |

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

- **Version:** 1.0 (2026-10-29)  **Status:** DESIGN
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
| P4 | The factor 10 of D18 and the event-duration definitions (stroke time; four controller time constants). | `verum.sim.validity` |
| P5 | The operations controller closes `XV-R000` and the tank inlet valve in response to a protection request (reactive command with a configured delay). | `verum.ops` |
