# Transient engine

This document describes `verum.transient`, a first-order method-of-characteristics (MOC) engine
for the 28 edges of the terminal. It is a standalone library: it does not touch `verum.sim`, the
truth store or the gateway, nothing calls it, and it changes no dataset tier (decision D47). It
is self-built. It is verified against closed forms, against the rigid-column engine in the
limit in which the two should agree, and against two other codes on water cases; that is
verification, not validation. No measured data were available (see the section on checks).
The decisions behind it are D43 to D47 in `docs/design_decisions.md`.

## Equations

Along an edge, with piezometric head `H` and flow `Q` (m3/s, positive in the edge direction),

    C+ :  H_P = C_p - B Q_P,    C_p = H_A + B Q_A - R_A Q_A |Q_A|
    C- :  H_P = C_m + B Q_P,    C_m = H_B - B Q_B + R_B Q_B |Q_B|

with `B = a / (g A)` and `R = (f dx / D + K dx / L) / (2 g A^2)`. The friction term is evaluated
at the old point (first order). `f` is the Darcy factor of the steady package (decision D14: 64/Re
below Re 2300, Haaland above 4000, a linear blend between); a test compares the two
implementations. `K` is the local loss coefficient of the edge under the fitting profile, spread
evenly over the reaches. Elevation enters through piezometric heads, so no slope term appears.

Interior points use the two characteristics directly. At an end point of an edge the engine
works with the flow `Qn` that leaves the pipe into the node, `H = C_e - B_e Qn` for an end
reached by C+ and `H = C_e + B_e Qn` for an end reached by C-, and the total head
`D_e = C_e + v^2 / 2g` with the velocity of the old point (a lagged velocity-head correction).

**Junctions** conserve mass and equal total head: the node head is
`(sum g_e D_e - demand) / sum g_e` with `g_e = 1 / B_e`, and `Qn = g_e (D_e - H_node)`. This is
the ideal junction of the textbook; minor losses at tees are carried by the edge `K` values.

**Series elements** (valve, pump, check valve) sit between two pipe ends and satisfy

    B_s Q + K2 Q |Q| = W + S,    B_s = B_1 + B_2,  W = D_1 - D_2,

with `S` the shutoff head of a running pump. The positive root is computed in the rationalised
form `2 |rhs| / (B_s + sqrt(B_s^2 + 4 K2 |rhs|))`, which stays exact when `K2` tends to zero (the
textbook form returned zero flow for `K2` of order 1e-16; found by the grid refinement study).

## Grid and wave-speed adjustment

One common time step `dt = 0.923 ms` (half of the 1.836 ms that a 2 m edge at 1089.2 m/s needs, so
that every edge has at least two reaches, and small enough to keep the adjustment below 0.53
percent). Each edge is divided into `N = round(L / (a dt))` reaches and
its wave speed is adjusted to `a' = L / (N dt)`, so that the Courant number is one on every edge.
The largest adjustment is 0.53 percent. The screening speeds are 1089.2, 1082.8 and 1078.2 m/s
for DN200, DN250 and DN300 (restraint factor psi = 1, a screening value and not a certified pipe
property). Another psi or bulk modulus scales them with the thin-wall relation
`a = sqrt((K / rho) / (1 + (K / K0) psi c))`, `c` fixed by the screening speed at `K0 = 1e9` Pa.
The grid has 1011 points.

## Boundaries (decision D44)

- Tanks and the distribution reservoir are constant-head boundaries; the reservoir follows the
  boundary law `H_res + c f_d (Q / 300 m3/h)^2`.
- The receipt source is flow-controlled: each step the commanded flow moves from the actual flow
  towards the set-point with time constant 2 s, and a head cap equal to 10 barg at
  `PIPELINE_RECEIPT_BOUNDARY` limits it.
- A valve is a series element with the extra loss `(K(alpha) - K_open) / (2 g A^2)` of the steady
  package's law, on the area of the edge that leaves it; alpha moves linearly with the stroke time
  (decisions D4 and D19) and the valve is closed (zero flow) at alpha of 0.001 or less.
- The pump is a quasi-steady curve between its inlet and outlet nodes with no inertia (D6):
  `H = H0 - k (Q / Qref)^2` while running. A stopped pump is a resistance without shutoff head
  (a modelling choice: the curve with `H0 = 0`, so it passes flow in either direction).
- A check valve passes forward flow. A reverse flow that persists for the delay (0.05, 0.3 or
  1 s, default 0.3 s, a selection) closes it; it reopens when the flow turns forward. The
  reverse volume that passes before the closing step is accounted.
- Initial state: the steady solution of `verum.hydraulics` for the lineup, levels and receipt
  flow, with dead legs filled consistently (segments of closed edges at the head of their open
  neighbour). Held for 5 s the maximum drift is below 1e-11 m for the reference lineups.

## No cavitation model (decision D45)

A step in which any point has an absolute pressure at or below the vapor pressure of the episode
(stratum and volatility class) opens a `phase_invalid` window. Nothing from the interval is
usable. Pressures are never clipped. After the first such window the numbers describe a
liquid that cannot exist.

## Mass ledger

`inflow - outflow - leak - storage` with the elastic storage of the pipes
`sum A dx g / a^2 (H - H_0)`. The residual does not accumulate; it stays within two steps of the
largest end flow (test R7).

## Verification ladder

Every test states whether its expected value is independent of the code.

| rung | content | expected value | result |
| --- | --- | --- | --- |
| R1 | Joukowsky: reservoir, pipe, instantaneous valve closure, frictionless; rise `a' v0 / g`, arrival times L/a and 2L/a | closed form, independent | passes to 1e-6 m |
| R2 | square wave of period 4L/a, sign and size of the reflections | closed form, independent | passes |
| R3 | prescribed linear flow reduction: triangle wave between 0 and Michaud's `2 L v0 / (g Tc)` with period 4L/a | closed form, independent | passes |
| R4 | steady Darcy-Weisbach profile held; oscillation decay against `exp(-f v0 t / 2D)` | closed form, independent | passes (15 percent on the decay ratio) |
| R5 | three grids (200, 400, 800 reaches), friction plus finite closure | Richardson | observed order 0.99 for the head and 0.84 for the flow (required 0.8); Richardson error of the finest grid 1.4 Pa and 0.0004 m3/h (budget 50 Pa, 0.02 m3/h) |
| R6 | tee, equal and unequal pipes: junction head and flows of the Riemann problem, mass at every step | closed form, independent | passes (velocity-head tolerance) |
| R7 | mass ledger through a closure and with a leak sink | bound from the scheme | passes |
| R8 | slow limit: 600 s receipt closure and 600 s pump-outlet closure against the rigid-column engine | tolerance derived in the test, slow marker | passes; flows within 0.07 percent, pressures within 0.03 bar |
| R9 | steady equivalence at every edge end for four reference lineups | shares the boundary definitions with the steady package | passes to 1e-6 m and 1e-9 m3/s |
| R10 | check valve: reverse flow blocked after the delay, reverse volume against the probed flow, delay sweep | independent integral | passes |
| R11 | determinism; checkpoint restart bit identical | equality | passes |
| R12 | experiments 1 to 3 of Jensen et al. 2018 (single phase), head at a test-only valve | published quasi-steady model and measurement | passes, except the frequency of experiment 2 against the paper |
| R13 | experiments 5 and 6, first peak up to the first `phase_invalid` window | measurement | passes |

Further tests: the Darcy factor equals the steady package's over the Reynolds range; the valve law
scale `(K - K_open) / (2 g A^2)` (found wrong by a factor A during R8 and corrected); the series
root near zero; the windowed run equals the continuous run on T1; the package imports neither the
truth store, the gateway nor the rigid-column engine.

Two deviations from the plan. The Allievi chain was not coded: for a prescribed linear flow
reduction Michaud's value is exact (R3), and for a real valve law the comparison with the
rigid-column engine (R8 and T2) carries more information than a second approximate formula. And
R8's second case is a closure of the pump outlet valve, because the shipped model has no delivery
set-point (the delivery flow follows the pump curve and the downstream law).

Defects found by the ladder and corrected: a friction switch that left smooth-pipe friction on; the
valve loss using `1 / (2 g A)` instead of `1 / (2 g A^2)`; the cancellation in the series root; the
reverse volume counting the flow of the step that closes the check valve.

## Checks against other codes (local, not part of the test suite)

- **TSNet 0.3.1** (water, reservoir, 500 m of pipe, valve, a = 1000 m/s, v0 = 1.112 m/s, closure in one
  step of 0.05 s): the head rise is 113.46 m in TSNet and 113.38 m in the engine (Joukowsky
  113.38 m); the collapse when the reflection returns is at 1.25 s in both (the engine 1.2525 s);
  the plateau of TSNet tilts by 1.3 m over 1 s because it has steady friction and the engine case
  has none, which is 0.8 percent of the rise. TSNet needed numpy 1.26.4 and WNTR 1.3.2, and it
  fails on a pipe connected to a reservoir at one end and an operating valve at the other (an index
  missing in its boundary branch), so the case has a short pipe upstream of the valve pipe.
- **EPANET through WNTR 1.3.2**: steady heads and flows for five reference lineups. EPANET neglects
  the velocity head, so the steady solution is compared as an energy head. Largest head difference
  0.02 to 0.06 m (tolerance 3 percent of the head change plus 0.02 m; Swamee-Jain against Haaland
  differ by about 1 percent), flow differences 0.2 percent in the two delivery cases.
- **Published experiments (R12, R13, Phase 5b).** Jensen et al. 2018 (Fluids 3(3) 64): the full text
  could not be retrieved (HTTP 403 from the publisher), so the parameters and the published results
  were taken as given in the task statement and are not verified against the paper; Kodura 2016 was not
  used. The closure exponent m of the valve law is a value the authors fitted. The test-only valve
  follows their laws (equations 27 and 28); the pipe has 24 reaches, Courant number one, and Haaland
  friction in place of Colebrook. Head at the valve, engine against the paper's quasi-steady model:
  maximum -0.12, -0.62 and -0.09 percent (experiments 1 to 3), third peak -0.12, -0.61, -0.09, tenth
  peak -0.08, -0.50, -0.07; frequency -0.05, -1.72 and +0.01 percent. Against measurement the maximum
  is +0.08, -2.39 and +2.19 percent; the third and tenth peaks are above the measured ones (+4 to +5 and
  +17 to +24 percent in experiments 1 and 3, +1 and +7 in experiment 2), which is the known
  overestimate of quasi-steady friction, and the frequency is 1 to 5 percent high. First peak of
  experiments 5 and 6, before the first phase window (0.066 s): 62.31 and 209.66 m against the
  measured 62.13 and 210.69 m (+0.3 and -0.5 percent). One tolerance is missed: the frequency of
  experiment 2 (1 percent) differs by 1.7 percent from the paper; the engine equals the closed form
  a / (4 L) to 0.1 percent in all three, so the difference is in the published figure or in a stated
  parameter. The paper's own code was not run: Octave is not installed. This is a check of the
  numerical method for these pipes with single-phase flow, not validation of the facility model.

## Comparison with the rigid-column engine (T1 to T4)

Full tables are in the Phase 5 and 5b reports. Numbers are quoted for the valid interval only (decision
D55): from the command to the start of the first `phase_invalid` window of the transient engine, with
the rigid-column value over the same interval. Values at the instant of closure are unusable, because
a window has opened before it (it opens at 97 to 98 percent of the stroke in every case below).

ESD isolation (XV-R000 over 10 s, XV-R101 over 30 s, 600 m3/h, cap 10 barg, ratio of stroke to wave
round trip 27.7), first window at 19.77 s:

| location | transient peak, valid interval (barg) | rigid-column peak, same interval (barg) | rigid minus transient |
| --- | --- | --- | --- |
| start of E002 (PT-001) | 11.50 | 10.08 | -12.4 % |
| end of E002 (hidden tap) | 11.69 | 10.10 | -13.6 % |
| receipt header | 1.48 | 1.50 | +1.1 % |

The earlier columns "at closure" (14.4 barg at PT-001, 15.9 at the tap in the transient engine, 12.3
and 13.5 in the rigid column) are unusable: they lie after the window opened. The tabulated rigid values
13.46 and 15.19 barg of the ESD table belong to alpha = 0.001 and are in the same case.

Receipt valve strokes with the cap, PT-001 peak up to the first window, rigid minus transient: 2 s
(ratio 5.5) -15.3 %, 3.6 s (10) -29.1 %, 7.2 s (20) +13.5 %, 10 s (27.7) -8.6 %, 20 s (55) -4.2 %, 30 s
(83) -2.7 %. The sign changes with the ratio, so the error is not a simple function of it. The values
quoted in Phase 5 (+8.5, +39.2, -8.3, +2.5, +0.4, -1.3 %) were peaks up to 0.1 s before the end of the
stroke, which lies after the window has opened at ratios of 20 and above, and are withdrawn. Only a
ratio of 55 reaches 5 percent in the valid interval.

Where the first vapor-pressure point is (Phase 5b, step 3): in all four cases (the isolation and the
strokes of 7.2, 10 and 30 s) it is the first point of E003, that is the downstream face of XV-R000 (0 m
from the valve), a single point at the first step, at an opening of 0.023 to 0.026 and 0.425 to 0.436
bar absolute against 0.4396 bar. The rarefaction behind the closing valve, not the compression ahead of
it, reaches the vapor pressure first.

What neither engine can represent in an ESD closure: the last 2 to 3 percent of the stroke of XV-R000,
where the flow stops, the downstream face of the valve reaches the vapor pressure, a vapor cavity forms
and collapses and the head at the valve is set by that collapse. The transient engine has no vapor model
and the rigid column has no wave, so the maximum pressure of the event and its timing are not
represented by either.

- Slow limit (R8, 600 s strokes): the transient engine reproduces the steady package at the
  opening of each instant to 0.0001 bar; the rigid column agrees with it apart from the filling
  of the tank, which the transient engine (constant-head tanks) does not represent (1.74 Pa/s
  at 600 m3/h).
- A pump-branch valve stroke of 30 and 10 s: agreement before the rigid engine rejects the run.
- A receipt set-point step 600 to 300 m3/h: the flow agrees. The pressure at the start of E002
  oscillates in the transient engine (minimum -0.40 barg, mainly at 1.0 s and 0.41 s) about the
  rigid-column value; the mean over a window of 2.0 s agrees with the rigid column to within 5
  percent of the dip magnitude `Lambda_down |dQ/dt|` at 1, 2 and 4 s after the step, for the step
  down, the step up and the start-up (Phase 5b, step 1). The statement of Phase 5 that the rigid
  column has no inertial dip was wrong: the dip is present, and the earlier comparison set the
  transient peak-to-peak oscillation against the 1 s rows of the rigid column and took the dip row
  at 1 s for the final steady value. What was missing was the post-event row at the command
  instant, which repeated the pre-event pressures (see `docs/path_dynamics_engine.md`).
- A pump stop opens a `phase_invalid` window 0.37 s after the stop for every check-valve delay.

## Throughput and windowed use

One simulated minute of the full network (1011 points, 65005 steps) takes 14.7 s of wall clock on
one core, 4400 steps per second, deterministic float64 and single-threaded (an Apple silicon
laptop, numpy). A 60 s event window therefore costs about 15 s, a 600 s run 2.5 minutes and one
simulated hour about 15 minutes. The profile of the step loop: 71 percent in the Darcy factor
(logarithms of the Haaland formula), the rest is array overhead. The one-hour projection is
acceptable for windowed use, so Numba was not used and no speed-up is claimed.

**Proposed rule (not implemented).** The engine would run inside an episode only for a window in
which the rigid-column engine already flags a validity window of kind `valve_stroke`,
`receipt_setpoint`, `flow_collapse` or `path_closed`, or for any event whose ratio of duration to
wave round trip is below 30 (the finding above; the factor 10 of D22 is a proposal). The window
starts about 2 s before the first command, from the steady state of the rigid-column engine at
that instant (levels, lineup, receipt flow and valve openings), and ends when the heads at all
points have settled to 0.05 bar or at the end of the first `phase_invalid` window, whichever is
earlier; nothing after a `phase_invalid` window is usable. The transient result would be written
as a separate hidden dataset with the window identifier, and would not feed back into the
rigid-column state. A test shows that a window started 2 s before the command reproduces the
continuous run started 20 s earlier to 1e-6 m (0.007 Pa) up to the first `phase_invalid` window.
Integration requires a later decision that also revises D37 and D47.

## Limitations

First order in space and time (observed order about 1); no unsteady friction; no cavitation or
column separation; no pump inertia, start or trip curve; ideal junctions; wave speeds are screening
values with a restraint factor, not pipe data; the pump curve and the check-valve delay are
selections. The sensitivity of the main results to these selections is in the study of D42.

## Use

    from verum.transient import TransientEngine, TransientSpec
    from verum.transient.driver import Probe, ValveEvent

    spec = TransientSpec(lineup=lineup, tank_levels_m=levels, receipt_flow_m3h=600.0,
                         receipt_setpoint_m3h=600.0,
                         valve_events=(ValveEvent("XV-R000", 10.0, 0.0, 10.0),))
    engine = TransientEngine(model, spec)
    series = engine.run(40.0, [Probe("pt001", "E002", 0.0)])
    engine.phase.windows   # intervals that are not usable (decision D45)

`get_state` and `set_state` checkpoint and restore a run bit for bit.
