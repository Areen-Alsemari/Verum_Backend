# Path-dynamics engine

This document describes the engine in `verum.sim` that advances the terminal in time,
the steady network of `verum.hydraulics` it calls, the operations controller in `verum.ops`
and the hidden truth store in `verum.truth`. It describes a model of a synthetic terminal:
nothing here has been validated against a physical installation. The decisions behind it
are D17 to D26 in `docs/design_decisions.md`; D22 replaces the quasi-steady validity
factor of D18. The engine no longer treats the receipt and delivery flows as steady: each
single path is a rigid column with inertia.

## State

- Tank liquid volumes `V_i` (m3); the level follows from the calibrated inverse of
  `verum.tanks`. Density is the 25 C constant (decision D21).
- Valve actuators (11 isolation valves): commanded state, actual opening `alpha` and
  physical closure, three separate records.
- The receipt flow `Q_r` and the delivery flow `Q_d` (m3/s), and the receipt set-point.
- The running pump (fixed speed, one pump; no start, trip or changeover, decision D6).
- One protection state machine per tank, and the operations controller.
- The cumulative boundary volumes of the mass ledger, validity windows and the recorded
  protection crossings.
- The downstream factor `f_d` and the atmosphere stratum are not states: `f_d` is a
  function of time drawn once from the seed, the stratum is fixed by the scenario.

Pipes are full and incompressible, so pipe inventory is constant and is not a state.

## Equations

**Rigid column** (decision D22). For a single receipt or delivery path,

    I dQ/dt = H_drive - H_loss(Q),        I = sum L_i / (g A_i)

along the active path. `H_loss` is the friction and local loss with partly closed valves,
computed by `verum.sim.path` with the same friction law, fitting coefficients and valve law
as the steady solver.

- *Receipt.* `H_drive = min(H_demand, H_cap)` with `H_demand = H_loss(Q) + I (Q_set - Q)/tau_c`,
  `tau_c = 2 s` and `H_cap` the source head at the 10 barg cap. Hence
  `dQ/dt = min[(Q_set - Q)/tau_c, (H_cap - H_source(Q))/I]`: uncapped the response is
  first order with `tau_c`; under the cap, or when a valve closes, the flow decays by
  inertia.
- *Delivery.* `H_drive` is the tank head plus the pump head at `Q`, minus the reservoir
  head and the boundary-law term `c f_d (Q/300 m3/h)^2`; a check valve keeps the flow from
  reversing.
- *Closed path.* When a valve reaches the closed threshold (`alpha <= 0.001`) the path
  flow is set to zero. The momentum removed is a sudden stop that the model cannot resolve;
  it is reported in a validity window.

**Integration.** The flows and the volumes that have passed (`C_r`, `C_d`) form one system
integrated by Radau IIA (implicit, order 5, tolerances in `config/sim.json`) over each step.
The system is stiff when a valve nearly closes (the loss slope is large), and the implicit
method is stable for the relaxation time of about 1.4 s of the delivery column and for the
sub-second time scale of a capped, closing receipt. The tank volumes and the ledger fluxes
are the same numbers (`C_r`, `C_d`), so the ledger closes by construction up to round-off.

**Steady solve at the imposed flows.** After the integration the network is solved with the
flows imposed (`SteadyInputs.imposed_delivery_flow_m3h`, receipt flow imposed, the cap
switched off because the dynamics apply it). The node heads then receive the inertial
offsets: along the flow the head drop over edge `i` is `loss_i + (L_i/(g A_i)) dQ/dt`. A
receipt path is anchored at its tank (offset `+Lambda_down dQ/dt`), a delivery path at its
tank with a quasi-steady pump rise (offset `-Lambda_up dQ/dt`). Tap pressures therefore
show surge, and the NPSH screen sees the reduced suction head of an accelerating delivery.

A receipt set-point step changes `dQ/dt` at once while the flow is continuous, so the offsets,
and the pressures with them, jump at the command. The pair of rows written at that instant
therefore carries the rate after the command in the post-event row: at the step from 600 to
300 m3/h the head at the start of E002 falls by `Lambda_down x 150/3600 = 12.99 m` (95.5 kPa)
between the pre-event and the post-event row. Before this was added the post-event row repeated
the pre-event pressures and the first dip appeared only in the next row.

**Branched lineups.** When two receipt branches or two suction branches are open there is no
single column. The step then uses the earlier scheme: Heun's method on the tank volumes
with two steady solves, the receipt flow first order and exact, the cap applied in the
solve. The interval is a validity window (`rigid_column_unavailable`).

**Valves** (decisions D4 and D19). The opening moves linearly at `1 / stroke` per second
(10 s for `XV-R000`, 30 s for the other motorized valves). `K(alpha) = K_open (Kv_max/Kv)^2`
with `K_open = 0.1`, `Kv/Kv_max = 50^(alpha - 1)` for `alpha > 0.05` and
`(alpha/0.05) 50^(0.05 - 1)` below. A partly open valve adds `K(alpha) - K_open` to the edge
that starts at the valve.

**Mass ledger.** `residual = rho [received - delivered - (sum V - sum V0)]` with the tolerance
of decision D8 (4.2e-4 kg/s times elapsed time) plus the recursive-summation bound.

## Healthy variability and strata (decisions D23 and D24)

The downstream factor `f_d(t)` multiplies the boundary-law coefficient. `log f_d` is a
stationary Ornstein-Uhlenbeck process (standard deviation 0.05, correlation time 1800 s) on
the 1 s grid with the exact transition, drawn from the named stream `demand`, linear in the
logarithm between grid points and clipped to [0.8, 1.25]. Only a scenario with
`demand_process` true uses it; otherwise `f_d` is exactly 1. The value is written to the
hidden `boundary_state` dataset. Receipt set-points are chosen from 0, 300, 400, 500 and
600 m3/h.

Each episode has an atmosphere stratum, `coastal` (101325 Pa) or `inland` (94300 Pa,
an estimate for a site near 600 m, elevation from memory and to be confirmed), and a
volatility class, `RVP_9_0` (baseline), `RVP_9_5` or `RVP10` (stress), decisions D11, D24
and D46. The pumping-minimum tables are stored per (stratum, volatility class) pair, for both
fitting profiles, the four temperatures and the NPSH3 sweep, computed at the worst-case
`f_d = 0.8` (the largest flow and the smallest margin), decision D51. The derived classes are
used only if the verification gate against the tabulated true vapor pressures passes.

## Step scheme and event ordering

The step is at most 1 s and ends on the next grid point, the next event, a protection
threshold crossing, or the end of the run. Events are held in a queue ordered by
`(time, rank, sequence)`. At one instant the order is: commands (rank 0), the protection
update, valve changes (rank 2), then the solver step.

**Protection crossings** (decision D26). After a step, the interpolated level of each tank
(the dense solution of the integrator, or a cubic Hermite interpolation in a branched step)
is tested against the thresholds that apply in the present protection state. A crossing is
located by root-finding, the step is repeated to end on the crossing time, and the protection
update at that instant sees the level at the threshold. The located time is recorded in the
event and in the episode record; it is not quantised to the grid.

## The operations controller

`verum.ops` is the only issuer of valve and receipt commands. It executes the schedule of a
scenario file: timed commands, and reactive commands that answer a protection event after a
delay (proposal P5). A lineup command is resolved through the lineup state machine, so a
receipt switch must pass the hold state; it may not start or stop a pump. The protection
logic only requests isolation. Commands and valve orders can be created only inside
`verum.ops` (a module token, checked by a static test).

## Protection signals

The alarm and its clearing use the level-transmitter chain of the tank (decision D40): lag,
noise, quantisation, dropout and comms delay with the draws of the observation chain; the
protection logic sees the latest sample that has arrived. The high-high trip is decided on an independent detector inside the engine (decision D33): the
true level plus a fixed offset (standard deviation 1 mm, one draw per episode from the
named stream `detector/<tank>`), located by root-finding, delivered to the protection logic
after 0.2 s. A static test fails if any call hands anything but the detector function's
output to the protection logic as the independent level. The LSHH observation is this same
signal after the comms delay.

## Dead legs (decision D39)

Segments without flow have a pressure: a segment open to a tank or the distribution boundary takes
its head; an isolated segment holds its head and relaxes to the head across its closed valve with
60 s (`verum.sim.deadleg`). Every edge of the network therefore has end pressures at every row.

## Validity windows (decisions D22, D25, D53 and D54)

The rigid-column model is valid for an event only if the event lasts at least a factor times the
pressure-wave round trip of its path, `duration >= factor * 2 sum(L_i/a_i)`, with the screening
wave speeds of the audited package (1089.2, 1082.8 and 1078.2 m/s for DN200, DN250 and DN300).
The factor is 50 for a valve stroke and 10 for a receipt set-point step, a flow collapse and a
path closure (D53; both are proposals, the first rests on one path, one valve law and one
source). A stroke is judged only if the flow through the valve is at least 10 percent of the
design flow of its path (D58 version 2): the flow at the start of an opening stroke, and the flow
at the instant the opening of a closing stroke has fallen to 0.2. A window is the interval in which the model does not represent the physics:

- `duration_below_wave_criterion`: a valve stroke or a set-point change (four controller time
  constants) shorter than the criterion;
- `flow_collapse_within_wave_criterion`: the flow of a closing path falls from 90 to 10
  percent in less than the criterion; `path_closed_with_flow`: the path closes before the
  flow has fallen to 10 percent;
- `rigid_column_unavailable`: a branched lineup;
- `dead_leg_held_pressure_unvalidated` (kind `dead_leg_unvalidated`): an isolated segment holds a
  pressure more than 0.5 bar from its target; the window closes below 0.05 bar (D54).

Each window has a start, an end, a reason and the ratio duration / round trip (null for a
branched lineup and for a dead-leg window). Windows are hidden records: the `validity_windows`
dataset, the `active_validity_window_ids` of the solver diagnostics, and the episode record.
They are never reachable from `verum.api`. In the shipped scenarios: S0u-E has the 10 s closure
of `XV-R000` (27.7 round trips of 0.361 s against 50), the flow collapse under the cap (about
0.19 s, 0.5 round trips) and a dead-leg window of 329 s for the source side of the closed valve;
S0u-D has none: the 10 s closure of `XV-R000` at 600 s is judged when its opening has fallen to
0.2, by which time the receipt flow is below 60 m3/h, and its 10 s opening at 1200 s starts at
zero flow and is not judged. The other scenarios have none. The 0.1 s truth rows are written inside windows of
kind `valve_stroke`, `flow_collapse` and `receipt_setpoint`, not inside the dead-leg window (D59).

## Gates

The gates run at every step and not only at the start.

- **SG0.** The pumping-minimum level of the delivering tank for the episode temperature,
  profile and NPSH3 coefficient is read from configuration. A level below it, at the start
  or later, rejects the episode; the crossing time inside a step is found by Hermite
  interpolation of the volume. The table is the one of the episode's stratum, computed at
  `f_d = 0.8`; the table of the episode's stratum and volatility class. A combination that never
  passes is rejected at the start. The
  phase and NPSH screen must be `OK` at every step while the pump runs. A solved pump flow
  outside its curve rejects the episode.
- **SG1.** The mass ledger must close within its tolerance after every step.
- **SG2.** A steady solve that does not converge rejects the episode.
- **SG3.** For scenarios marked healthy, all levels stay between 1.8 and 12 m and every
  protection machine stays NORMAL.

A rejected episode is written as a record naming the gate, the time and the parameter. The
truth files of the run are removed. Nothing is truncated or clipped silently.

## Truth store (decision D20)

Each episode has a directory named by the opaque episode id (no scenario identifier appears
in any directory or file name) with six gzip JSON Lines datasets (`hydraulic_state`,
`solver_diagnostics`, `mass_ledger`, `events`, `boundary_state`, `validity_windows`),
`episode.json` (which carries the stratum, the validity windows and the protection
crossings), `provenance.json` (git commit) and a SHA-256 manifest. Rows are written on a
1 s grid, and for every event as a pre-event and a post-event row. The datasets are
described by eight backend-proposed schemas (`schemas/`, version 0.7.0) that await review
by the schema owner. They are evaluator data and are never served.

## Checkpoint and restart

A checkpoint is a deep copy of the engine state (the immutable last solve is shared). An
engine built from a checkpoint continues exactly as the original; the tests compare the
rows after the checkpoint for equality as floating-point numbers on the same platform.

## Limitations and what the model cannot resolve

- **Sub-second waves.** There is no wave propagation, column separation or valve slam.
  The rigid column responds instantly to a head change along the path; pressure waves with
  round trips of 0.36 s (receipt) to 0.7 s (delivery) are not represented. Events shorter
  than ten round trips are only flagged.
- **Peak surge pressure.** The reported surge is the inertial head of a rigid column,
  `(L/(g A)) dQ/dt`. The peak pressure of a fast closure (Joukowsky-type) is a wave effect
  and is not resolved; the stop of the flow at the closed threshold (about 40 m3/h in
  the S0u-E closure) is an unresolved sudden stop. Under the cap the source head is the
  cap by construction, so the model cannot report a pressure above it.
- Pipes are incompressible and full; line pack and compressibility are not represented.
- There is no pump start or trip and no check-valve closure dynamics. The standalone
  transient engine of `docs/transient_engine.md` has both, but is not called by this engine.
- Temperature is constant in an episode (decision D21).
- Protection acts on true signals; instrument lags, noise and failures are absent.
- A branched lineup falls back to the quasi-steady scheme and is flagged.
- The pumping-minimum tables, the strata and the derived volatility classes are provisional
  selections; the inland stratum rests on an elevation from memory.
- The rigid-column model under-predicts the peak head of a valve closure unless the stroke lasts
  about thirty wave round trips; see `docs/transient_engine.md`. The inertial head of the
  downstream column after a receipt set-point step is represented; the elastic oscillation about
  it (period 1.0 s in the network response) is not.
- Tests of the lumped path against the steady solver share formulas with the
  implementation and are not independent validation of the hydraulics.
- Nothing in this document has been validated against measured data.
