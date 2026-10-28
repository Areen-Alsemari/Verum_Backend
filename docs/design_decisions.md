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
- All records are version 1.0, dated 2026-10-29.
- Source documents are cited by file and section in the audited package under
  `vendor/verum_audited/`.

## Index

| ID | Subject | Status |
| --- | --- | --- |
| D1 | Solver architecture and time step | DESIGN |
| D2 | Delivery boundary and pump operating point | SIM |
| D3 | Receipt boundary | SIM |
| D4 | Valve characteristics and stroke times | SIM |
| D5 | Check-valve closure | SIM |
| D6 | Pump start, trip and changeover excluded | DESIGN |
| D7 | NPSH3 relation and margin | SIM |
| D8 | Numerical tolerances | DESIGN |
| D9 | Motor, current and vibration channels not emitted | DESIGN |
| D10 | Validity condition for leaks | SIM |
| D11 | Bulk-liquid temperature stratum | SIM |

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

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
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

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
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

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
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

- **Version:** 1.0 (2026-10-29)  **Status:** SIM
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
