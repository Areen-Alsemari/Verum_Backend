# Quasi-steady dynamic engine

This document describes the engine in `verum.sim` that advances the terminal in time
over the steady network of `verum.hydraulics`, the operations controller in `verum.ops`
and the hidden truth store in `verum.truth`. It describes a model of a synthetic
terminal: nothing here has been validated against a physical installation, and the
engine has no wave dynamics. The decisions behind it are D17 to D21 in
`docs/design_decisions.md`.

## State

- Tank liquid volumes `V_i` (m3); the level follows from the calibrated inverse of
  `verum.tanks`. Density is the 25 C constant (decision D21: the temperature of an
  episode is one of the D11 strata and does not change).
- Valve actuators (11 isolation valves): commanded state, actual opening `alpha` and
  physical closure. The three are separate records.
- The receipt flow state `q` and its set-point `q_set`.
- The running pump (fixed speed, one pump; no start, trip or changeover, decision D6).
- One protection state machine per tank, and the operations controller with its lineup
  state machine.
- The cumulative boundary volumes of the mass ledger.

Pipes are full and incompressible, so pipe inventory is constant and is not a state.

## Equations

**Tank volumes** (decision D17). For a step of length `h` from `t` to `t + h`, with `f(V, t)`
the net inflow of each tank from a steady network solve:

    f1 = f(V(t), t)                       (state solve at t)
    V* = V(t) + h f1                      (predictor)
    f2 = f(V*, t + h)                     (second stage)
    V(t + h) = V(t) + (h/2) (f1 + f2)     (Heun)

The solve at the start of the next step is the state solve at the new time, so each step
costs two steady solves, warm-started from the previous heads.

**Receipt flow** (decision D3). `dq/dt = (q_set - q) / tau` with `tau = 2 s`, advanced
exactly between events: `q(t + h) = q_set + (q(t) - q_set) exp(-h / tau)`. The imposed
flow is capped inside the steady solve at a head-based source pressure of 10 barg; a
capped flow is solved, not clipped afterwards.

**Valves** (decisions D4 and D19). The opening moves linearly at `1 / stroke` per second
(10 s for `XV-R000`, 30 s for the other motorized valves). The loss coefficient is
`K(alpha) = K_open (Kv_max / Kv(alpha))^2` with `K_open = 0.1`, where `Kv / Kv_max =
50^(alpha - 1)` for `alpha > 0.05` and `(alpha / 0.05) 50^(0.05 - 1)` below. The valve is
treated as closed when `alpha <= 0.001`, which removes its edges from the network. A
partly open valve adds `K(alpha) - K_open` to the edge that starts at the valve.

**Mass ledger.** `residual = rho [received - delivered - (sum V - sum V0)]`, where
`received` and `delivered` are the boundary volumes (receipt meter edge `E001`, delivery
edge `E-D2`) integrated with the same stage flows as the tank volumes. The tolerance is the
decision D8 rate times elapsed time (4.2e-4 kg/s) plus the recursive-summation bound
`(n - 1) 2^-53 sum |x|` over the terms used.

## Step scheme and event ordering

The step is at most 1 s and ends on the next grid point, the next event or the end of the
run, whichever comes first, so every event time is the end of a step. Events are held in a
queue ordered by `(time, rank, sequence)`. At one instant the order is:

1. commands (rank 0), including reactive commands created by a protection event of the
   same instant;
2. the protection update, with the signals at that instant;
3. valve changes (rank 2): the end of a stroke and the crossing of the closed threshold;
4. the solver step that follows.

Events are the commands from the operations controller, the end of a valve stroke, and a
valve crossing the closed threshold. A valve position is a function of time between
orders, so the positions used by both stages are exact.

## The operations controller

`verum.ops` is the only issuer of valve and receipt commands. It executes the schedule of a
scenario file: timed commands, and reactive commands that answer a protection event after a
delay (proposal P5 in the design record). A lineup command is resolved through the lineup
state machine, so a receipt switch must pass the hold state; it may not start or stop a
pump. The protection logic only requests isolation. Commands and valve orders can be
created only inside `verum.ops` (a module token, checked by a static test).

## Protection signals

The protection machines receive the true tank level, the true closure of the valves and the
true receipt flow. These rows carry `signal_source = "truth_placeholder"`. A test fails if
any module outside `verum.sim` mentions that tag or imports its definition, so a later
sensor module cannot consume it by accident.

## Quasi-steady validity (decision D18)

For each event the engine computes the rigid-column time constant of the affected path,

    tau = (sum L_i / A_i) Q0 / (g dH0)

with `Q0` the larger of the present flow, the set-point and the design flow of the path
(or the reference flow if the pump is dead-headed), and `dH0` the friction and local loss
along the path at `Q0` with the valves fully open (plus the boundary-law drop for a delivery
path). The duration of a valve event is its travel time; that of a receipt set-point change
is four controller time constants. An event is quasi-steady-valid if its duration is at
least 10 tau (the factor is a proposal). The ratio duration / tau is written to the solver
diagnostics when the event starts, and every diagnostic row inside the window carries
`quasi_steady_invalid`. A failing event is flagged and not blocked. All receipt events and
the emergency closure fail the test in the shipped scenarios.

## Gates

The gates run at every step and not only at the start.

- **SG0.** The pumping-minimum level of the delivering tank for the episode temperature,
  profile and NPSH3 coefficient is read from configuration. A level below it, at the start
  or later, rejects the episode; the crossing time inside a step is found by Hermite
  interpolation of the volume. A combination that never passes is rejected at the start. The
  phase and NPSH screen must be `OK` at every step while the pump runs. A solved pump flow
  outside its curve rejects the episode.
- **SG1.** The mass ledger must close within its tolerance after every step.
- **SG2.** A steady solve that does not converge rejects the episode.
- **SG3.** For scenarios marked healthy, all levels stay between 1.8 and 12 m and every
  protection machine stays NORMAL.

A rejected episode is written as a record naming the gate, the time and the parameter. The
truth files of the run are removed. Nothing is truncated or clipped silently.

## Truth store (decision D20)

Each episode has a directory with four gzip JSON Lines datasets (`hydraulic_state`,
`solver_diagnostics`, `mass_ledger`, `events`), `episode.json`, `provenance.json` (git
commit) and a SHA-256 manifest. Rows are written on a 1 s grid, and for every event as a
pre-event and a post-event row. The datasets are described by six backend-proposed schemas
(`schemas/`, version 0.5.0) that await review by the schema owner. They are evaluator data
and are never served.

## Checkpoint and restart

A checkpoint is a deep copy of the engine state (the immutable last solve is shared). An
engine built from a checkpoint continues exactly as the original; the tests compare the
rows after the checkpoint for equality as floating-point numbers on the same platform.

## Limitations

- No wave propagation, no column separation, no valve slam, no pump start or trip, no
  check-valve closure dynamics. Fast events are only flagged.
- Pipes are incompressible and full; line pack and compressibility are not represented.
- Temperature is constant in an episode, with no thermal dynamics (decision D21), so the
  phase screen cannot react to a warming product.
- Protection acts on true signals; instrument lags, noise and failures are absent.
- The emergency closure acts on a receipt that is flow-controlled with a pressure cap; the
  flow collapses in the last 3 percent of the stroke, within about 0.3 s, which the 1 s
  grid and the quasi-steady model cannot resolve.
- The stored pumping-minimum levels are sea-level values; the site-pressure table is a
  sensitivity only.
- Healthy episodes make no random draw; the named random streams exist for later phases.
- Nothing in this document has been validated against measured data.
