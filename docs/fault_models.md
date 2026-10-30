# Fault models

This document describes the single-fault injection of `verum.faults` and the audit of what each
fault changes in the emitted tags. It was written before the code; the decisions it adopts are D60
to D68 in `docs/design_decisions.md`. Everything in it is a simulation selection. No fault law, range
or threshold is a measurement, a manufacturer value or a field result, and nothing here has been
validated against a real terminal.

Scope of this version: one fault per episode, five fault types, no recovery, no multi-fault episodes,
no campaign generator, no vapor-related faults (flashing, column separation), no agents and no use
of the transient engine inside an episode.

## Fault types

| type (`fault_type` of the audited schema) | asset | physical parameter modified | decision |
| --- | --- | --- | --- |
| `PIPE_LEAK` | an edge | leak area A at a position along the edge | D60 |
| `VALVE_RESTRICTION` | a motorized valve | actual opening ceiling, command unchanged | D61 |
| `PUMP_HEAD_DEGRADATION` | a pump | head scale of the whole curve | D62 |
| `SENSOR_DRIFT` (variants bias, drift, stuck-at) | a continuous tag | additive error of the reading | D63 |
| `VALVE_MISROUTING` (variants a and b) | a valve | actual opening against the commanded state | D64 |

The audited schema `fault_truth` has no separate type for sensor bias or stuck-at; all three sensor
variants use `SENSOR_DRIFT` and the field `mechanism` names the variant.

## Severity trajectory and timing (D65)

Every fault has an onset time `t_on`, uniform in `[600, T - 1800]` s for an episode of length `T`, and
a severity trajectory `s(t)` in `[0, 1]`, piecewise linear in seconds since onset with the last value
held (the form of the audited schema). A hydraulic fault ramps from 0 to 1 over 30, 300 or 1200 s
(the knots are `(0, 0)` and `(ramp, 1)`); there are no steps. A sensor fault may step: the knot is
`(0, 1)`. Faults persist to the end of the episode. Each physical parameter is a linear function of
the severity, `p(s) = p0 + s (p1 - p0)` with `p1` the value at severity one, which the record
stores as `fault_value_at_severity_one`. The leak area is the exception in the sense that it is
`s A1` (baseline 0), which is the same linear form.

## Leak (D60)

**Law.** A leak at a node of the pipe at distance fraction `x` along an edge discharges to the
atmosphere through a sharp-edged orifice:

    Q_L = Cd A sqrt(2 p / rho),    p = rho g (H - z_L),    Cd = 0.62

with `H` the total head of the leak node, `z_L` the elevation of the leak point (linear between the
end elevations of the edge) and `A = s(t) A1`. The velocity head is neglected, so `p` is the gauge
pressure of the node computed from the total head; for the receipt branches (DN200, up to 5.2 m/s)
this overstates the static pressure by up to 1.4 m of head (10 kPa), for the DN300 mains by 0.3 m
(2 kPa). `A1` is log-uniform between 2e-6 and 1e-3 m2 and `x` uniform in `[0.05, 0.95]`. The audit
varies `Cd` between 0.5 and 0.8.

**Validity (D10).** The law is single-phase, outward flow. The leak is valid only while `p > 10 kPa`
at the leak point and while the edge carries a determined (live) pressure. Otherwise the candidate
episode is rejected (gate `SGF`, record `simulation_rejected`), never labelled as a fault (D66).
There is no flashing and no reverse flow.

**(a) Steady network.** The edge is split at the leak into two pipe edges of lengths `x L` and
`(1 - x) L`; the local loss coefficient of the edge is shared in proportion to the lengths (a
limit: a fitting at one end of the edge is spread along it). The leak node is joined to a fixed-head
atmosphere node at head `z_L` by an element with the flow law above in terms of `H - z_L`. The Newton
solve is unchanged, with the new unknown node. The flow written in the edge row is the flow at the
downstream end of the edge (D67); the flow at the upstream end is that plus `Q_L`; the leak flow is
written as `leak_flow_m3s` in the edge row. End pressures use the flow of the end.

**(b) Rigid-column path engine.** The state of a column is the flow at the controlled end: for the
receipt path the source flow `Q_r`; for the delivery path the flow through the pump `Q_d`. Mass
conservation fixes the flow in every edge of the path from the state and the leak flows: for the
receipt path the flow after a leak is `Q_r - Q_L`; for the delivery path the flow upstream of a
suction-side leak is `Q_d + Q_L`, the flow downstream of a discharge-side leak is `Q_d - Q_L`, and the
boundary flow is `Q_d` less the discharge leaks. The friction and local losses of each edge, and the
boundary law, use the flow of that edge. The inertance `Lambda = sum L/(g A)` and the single
`dQ/dt` of D22 are kept: the inertial head of a section is `Lambda_section dQ/dt` where the true rate
of an edge differs by `dQ_L/dt`. The leak flows used inside a step are the values of the last accepted
steady solve (frozen over a step of at most 1 s), and the post-step steady solve uses the imposed
boundary flows implied by them.

*Approximation error.* The inertial head is wrong by at most `Lambda_section |dQ_L/dt|`. For the
largest leak (A = 1e-3 m2, 10 barg, Q_L about 0.032 m3/s) ramped over 30 s and a section of
`Lambda` = 311 s2/m2 this is 0.33 m (2.4 kPa) during the ramp and zero after it; for a ramp of 300 s
it is 0.03 m. The freezing of `Q_L` over a step changes the flow of an edge by `|dQ_L/dt| dt`, below
0.1 percent of `Q_L` per step for ramps of 30 s or more. The test compares the rigid-column result for a
leak ramped over 300 s with the transient engine (leak sink as in rung R7).

**(c) Mass ledger.** The spilled volume of a step is `Q_L h` for the frozen `Q_L` (trapezoid
of the two solves in the branched scheme). The tank volumes receive the flows implied by the
state (`C_r = integral of (Q_r - Q_L,r)`, tank outflow `Q_d + Q_L,s`), the boundary received
mass is `integral Q_r`, the delivered mass is `integral (Q_d - Q_L,d)` and the spill is added once
to the spill line of the network row (`cumulative_spill_kg`). The residual is
`received - delivered - spill - change of tank inventory`. The pipe inventory is constant (the pipes
stay full), so a leak does not change the inventory of the pipes.

*Choice.* Two simpler alternatives were considered and rejected: carrying the inertia on the
source flow only (the flow into the leak edge) and treating the leak as an extra tank inflow. The
first loses mass conservation in the tanks; the second ignores that the leak changes the losses
downstream. The chosen option conserves mass exactly in the engine's own accounting and keeps the
D22 structure.

## Valve restriction (D61)

The actual opening is limited by a ceiling that falls from 1 to `alpha_stuck` as the severity rises,
`alpha_ceiling = 1 - s (1 - alpha_stuck)`, with `alpha_stuck` uniform in `[0.15, 0.9]`:
`alpha = min(alpha_motion, alpha_ceiling)`. The command and the stroke are unchanged. A restricted
valve that is commanded closed is closed. The loss is the D19 law at the actual opening
(`K(alpha) = K_open (Kv_max/Kv(alpha))^2`) and the valve contact is derived from the actual
opening by D31, so a valve with `alpha < 0.98` reads not open. A contact that stays open while the
valve is restricted would be a compound fault and is not part of this phase.

## Pump head degradation (D62)

The head curve of the running pump is multiplied by `head_scale(s) = 1 - s (1 - h1)`,
`h1` uniform in `[0.70, 0.98]`: `H(Q) = head_scale (H0 - k (Q/Q_ref)^2)`. The speed is fixed
and the efficiency, NPSH3 and the pump domain are unchanged. A lower head lowers the delivery flow; a
low flow is not a gate failure, a flow above the pump domain is.

## Sensor faults (D63)

On the continuous tags only (LT, FT, PT and TT; 14 of the 30 emitted tags are continuous, the
event tags are not faulted). Let `span = range_hi - range_lo` of the tag. The reading before noise,
quantisation and clipping is changed by

- **bias:** `+ b span`, `b` uniform in `±[0.002, 0.05]` (sign random);
- **drift:** `+ d span (t - t_on) / 3600`, `d` uniform in `±[0.002, 0.05]` per hour;
- **stuck-at:** the reading is the noise-free sampled value of the first sample at or after the onset
  and does not change afterwards.

Truth, the other tags, the random draws of the chain (noise and dropout use one draw per scheduled
sample whatever the outcome) and the sample times are unchanged. A bias can push a reading into the
clipping range, which sets the quality flag by the existing rule.

## Misrouting (D64)

Eligible valves: the tank inlet valves `XV-R101..103`, the tank outlet valves `XV-S101..103` and the
pump-branch valves `XV-PAI`, `XV-PAO`, `XV-PBI`, `XV-PBO`. The commanded state, the actual opening
and the contact state stay separate records (the valve row carries `commanded_open` and
`position_frac`; the contact is derived from the opening).

- **(a) commanded closed, physically open:** the opening floor rises with the severity,
  `alpha = max(alpha_motion, s)`. The valve is commanded closed and ends fully open.
- **(b) commanded open, stuck at `alpha <= 0.02`:** the ceiling falls to `alpha_stuck`, log-uniform in
  `[0.005, 0.02]`; the mechanism is the restriction of D61 with a closed-like range.

The states that result (two suction branches open, a receipt into two tanks) are not suppressed.
The engine's quasi-steady branched scheme and its windows apply, and the gates decide.

## Eligibility and rejection (D66)

Checked before the run, as a validator of the specification record: the asset exists and has the type
the fault needs; the severity parameter lies in its range; the onset lies in `[600, T - 1800]`; the
ramp is one of 30, 300, 1200 s (hydraulic faults); at most one fault per asset and one fault in the
episode; for a leak, `x` in `[0.05, 0.95]`. Checked while running: every gate of the engine (pump
domain, phase and NPSH screen, pumping minimum, mass ledger, solver convergence) and the leak
pressure condition. A candidate that fails any of them is written as `simulation_rejected` with
the gate; the fault is not labelled and no data are kept.

## Edge-flow convention (D67)

The `flow_m3s` of an edge row is the flow at its downstream end, so that FT-001 (end of E001) and FT-201
(end of E-D1) read at their meter nodes. Without a leak the two ends carry the same flow and the
convention changes nothing.

## Hidden records

`fault_truth` rows follow the audited schema (`schemas/fault_truth.schema.json`, not modified): fault
type, instance id, asset, location (a leak's edge and fraction), onset, mechanism, the severity
trajectory, the physical parameter with baseline and severity-one values, hidden. The episode record
lists the instance ids. The specification record is validated by `schemas/fault_spec.schema.json`.
Nothing about faults is reachable from `verum.api`; `verum.sensors` knows only a hook interface
(a callable acting on the reading), not the faults package.

## Observability audit (D68)

The audit asks what each single fault changes in the emitted tags, not whether an agent could detect it.
Detectability thresholds: three times the noise standard deviation of the tag, and three times the
standard deviation of the healthy variability of the tag measured over 20 seeds with the demand
process on. A change is judged on the noise-free sampled series averaged over 60 s. The grid, the
tools and the results are in the audit section at the end of this document.
