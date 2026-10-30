# Fault models

This document describes the single-fault injection of `verum.faults` and the audit of what each fault changes in the emitted tags. It was written before the code; the decisions it adopts are D60 to D68 in `docs/design_decisions.md`. Everything in it is a simulation selection.

No fault law, range or threshold is a measurement, a manufacturer value or a field result, and nothing here has been validated against a real terminal.

Scope of this version: one fault per episode, five fault types, no recovery, no multi-fault episodes, no campaign generator, no vapor-related faults (flashing, column separation), no agents and no use of the transient engine inside an episode.

## Fault types

| type (`fault_type` of the audited schema) | asset | physical parameter modified | decision |
| --- | --- | --- | --- |
| `PIPE_LEAK` | an edge | leak area A at a position along the edge | D60 |
| `VALVE_RESTRICTION` | a motorized valve | actual opening ceiling, command unchanged | D61 |
| `PUMP_HEAD_DEGRADATION` | a pump | head scale of the whole curve | D62 |
| `SENSOR_DRIFT` (variants bias, drift, stuck-at) | a continuous tag | additive error of the reading | D63 |
| `VALVE_MISROUTING` (variants a and b) | a valve | actual opening against the commanded state | D64 |

The audited schema `fault_truth` has no separate type for sensor bias or stuck-at; all three sensor variants use `SENSOR_DRIFT` and the field `mechanism` names the variant.

## Severity trajectory and timing (D65)

Every fault has an onset time `t_on`, uniform in `[600, T - 1800]` s for an episode of length `T`, and a severity trajectory `s(t)` in `[0, 1]`, piecewise linear in seconds since onset with the last value held (the form of the audited schema). A hydraulic fault ramps from 0 to 1 over 30, 300 or 1200 s (the knots are `(0, 0)` and `(ramp, 1)`); there are no steps. A sensor fault may step: the knot is `(0, 1)`.

Faults persist to the end of the episode. Each physical parameter is a linear function of the severity, `p(s) = p0 + s (p1 - p0)` with `p1` the value at severity one, which the record stores as `fault_value_at_severity_one`. The leak area is the exception in the sense that it is `s A1` (baseline 0), which is the same linear form.

## Leak (D60)

**Law.** A leak at a node of the pipe at distance fraction `x` along an edge discharges to the atmosphere through a sharp-edged orifice:

    Q_L = Cd A sqrt(2 p / rho),    p = rho g (H - z_L),    Cd = 0.62

with `H` the total head of the leak node, `z_L` the elevation of the leak point (linear between the end elevations of the edge) and `A = s(t) A1`. The velocity head is neglected, so `p` is the gauge pressure of the node computed from the total head; for the receipt branches (DN200, up to 5.2 m/s) this overstates the static pressure by up to 1.4 m of head (10 kPa), for the DN300 mains by 0.3 m (2 kPa).

`A1` is log-uniform between 2e-6 and 1e-3 m2 and `x` uniform in `[0.05, 0.95]`. The audit varies `Cd` between 0.5 and 0.8.

**Validity (D10).** The law is single-phase, outward flow. The leak is valid only while `p > 10 kPa` at the leak point and while the edge carries a determined (live) pressure. Otherwise the candidate episode is rejected (gate `SGF`, record `simulation_rejected`), never labelled as a fault (D66). There is no flashing and no reverse flow.

**(a) Steady network.** The edge is split at the leak into two pipe edges of lengths `x L` and `(1 - x) L`; the local loss coefficient of the edge is shared in proportion to the lengths (a limit: a fitting at one end of the edge is spread along it). The leak node is joined to a fixed-head atmosphere node at head `z_L` by an element with the flow law above in terms of `H - z_L`.

The Newton solve is unchanged, with the new unknown node. The flow written in the edge row is the flow at the downstream end of the edge (D67); the flow at the upstream end is that plus `Q_L`; the leak flow is written as `leak_flow_m3s` in the edge row. End pressures use the flow of the end.

**(b) Rigid-column path engine.** The state of a column is the flow at the controlled end: for the receipt path the source flow `Q_r`; for the delivery path the flow through the pump `Q_d`.

Mass conservation fixes the flow in every edge of the path from the state and the leak flows: for the receipt path the flow after a leak is `Q_r - Q_L`; for the delivery path the flow upstream of a suction-side leak is `Q_d + Q_L`, the flow downstream of a discharge-side leak is `Q_d - Q_L`, and the boundary flow is `Q_d` less the discharge leaks.

The friction and local losses of each edge, and the boundary law, use the flow of that edge. The inertance `Lambda = sum L/(g A)` and the single `dQ/dt` of D22 are kept: the inertial head of a section is `Lambda_section dQ/dt` where the true rate of an edge differs by `dQ_L/dt`.

The leak flows used inside a step are the values of the last accepted steady solve (frozen over a step of at most 1 s), and the post-step steady solve uses the imposed boundary flows implied by them.

*Approximation error.* The inertial head is wrong by at most `Lambda_section |dQ_L/dt|`. For the largest leak (A = 1e-3 m2, 10 barg, Q_L about 0.032 m3/s) ramped over 30 s and a section of `Lambda` = 311 s2/m2 this is 0.33 m (2.4 kPa) during the ramp and zero after it; for a ramp of 300 s it is 0.03 m.

The freezing of `Q_L` over a step changes the flow of an edge by `|dQ_L/dt| dt`, below 0.1 percent of `Q_L` per step for ramps of 30 s or more. The test compares the rigid-column result for a leak ramped over 300 s with the transient engine (leak sink as in rung R7).

**(c) Mass ledger.** The spilled volume of a step is `Q_L h` for the frozen `Q_L` (trapezoid of the two solves in the branched scheme).

The tank volumes receive the flows implied by the state (`C_r = integral of (Q_r - Q_L,r)`, tank outflow `Q_d + Q_L,s`), the boundary received mass is `integral Q_r`, the delivered mass is `integral (Q_d - Q_L,d)` and the spill is added once to the spill line of the network row (`cumulative_spill_kg`). The residual is `received - delivered - spill - change of tank inventory`.

The pipe inventory is constant (the pipes stay full), so a leak does not change the inventory of the pipes.

*Choice.* Two simpler alternatives were considered and rejected: carrying the inertia on the source flow only (the flow into the leak edge) and treating the leak as an extra tank inflow. The first loses mass conservation in the tanks; the second ignores that the leak changes the losses downstream. The chosen option conserves mass exactly in the engine's own accounting and keeps the D22 structure.

## Valve restriction (D61)

The actual opening is limited by a ceiling that falls from 1 to `alpha_stuck` as the severity rises, `alpha_ceiling = 1 - s (1 - alpha_stuck)`, with `alpha_stuck` uniform in `[0.15, 0.9]`: `alpha = min(alpha_motion, alpha_ceiling)`. The command and the stroke are unchanged. A restricted valve that is commanded closed is closed.

The loss is the D19 law at the actual opening (`K(alpha) = K_open (Kv_max/Kv(alpha))^2`) and the valve contact is derived from the actual opening by D31, so a valve with `alpha < 0.98` reads not open. A contact that stays open while the valve is restricted is the second mode of decision D74, below.

Two modes (D74), named in the specification (`fault_mode`; a restriction without it is refused, no mode is assumed):

- **`position_visible`:** the actual opening is the ceiling and the open contact follows it, as above.
- **`obstruction`:** the loss follows the ceiling (the same D19 law at `alpha_stuck`) and the flow and pressures are those of the other mode, but the stem is at the commanded position, so the open contact still reads open (D31 applied to the stem position). The valve-state truth row carries the stem position as `contact_position_frac` next to `position_frac`, which sets the loss.

The two modes differ only in the contact tag; a test checks the same flow in both (reference path with the extra loss `K(alpha_stuck) - K(1)`, evaluated at the tank level of the row) and the release of the contact at 301.8 s in one and not in the other. The split between modes in a later campaign is a sampler choice (50 percent each, D74) and is not implemented here.

## Pump head degradation (D62)

The head curve of the running pump is multiplied by `head_scale(s) = 1 - s (1 - h1)`, `h1` uniform in `[0.70, 0.98]`: `H(Q) = head_scale (H0 - k (Q/Q_ref)^2)`. The speed is fixed and the efficiency, NPSH3 and the pump domain are unchanged. A lower head lowers the delivery flow; a low flow is not a gate failure, a flow above the pump domain is.

## Sensor faults (D63)

On the continuous tags only (LT, FT, PT and TT; 14 of the 30 emitted tags are continuous, the event tags are not faulted). Let `span = range_hi - range_lo` of the tag. The reading before noise, quantisation and clipping is changed by

- **bias:** `+ b span`, `b` uniform in `±[0.002, 0.05]` (sign random);
- **drift:** `+ d span (t - t_on) / 3600`, `d` uniform in `±[0.002, 0.05]` per hour;
- **stuck-at:** the reading is the noise-free sampled value of the first sample at or after the onset and does not change afterwards.

Truth, the other tags, the random draws of the chain (noise and dropout use one draw per scheduled sample whatever the outcome) and the sample times are unchanged. A bias can push a reading into the clipping range, which sets the quality flag by the existing rule.

## Misrouting (D64)

Eligible valves: the tank inlet valves `XV-R101..103`, the tank outlet valves `XV-S101..103` and the pump-branch valves `XV-PAI`, `XV-PAO`, `XV-PBI`, `XV-PBO`. The commanded state, the actual opening and the contact state stay separate records (the valve row carries `commanded_open` and `position_frac`; the contact is derived from the opening).

- **(a) commanded closed, physically open:** the opening floor rises with the severity, `alpha = max(alpha_motion, s)`. The valve is commanded closed and ends fully open.
- **(b) commanded open, stuck at `alpha <= 0.02`:**
  - the ceiling falls to `alpha_stuck`, log-uniform in `[0.005, 0.02]`; the mechanism is the restriction of D61 with a closed-like range.
  - Eligible only on a valve of a parallel branch (D75): a tank inlet valve while another inlet is open (for example `XV-R101` and `XV-R102` in `RECEIVE_101_102`) or a tank outlet valve while another outlet is open.
  - On a valve in series with the whole flow (`XV-R101` in `RECEIVE_101`, `XV-S101` and the pump-branch valves in `DELIVER_101_A`) the state is fixed by the flow and the candidate is refused before the run.
  - The pump branches are never open together in the static lineups, so a pump-branch valve is not eligible. Misrouting (a) is unchanged.

The states that result (two suction branches open, a receipt into two tanks) are not suppressed. The engine's quasi-steady branched scheme and its windows apply, and the gates decide.

## Representable range

`tools/representable_range.py` applies each fault type to each eligible asset in a lineup in which the asset acts, at the least and the most severe end of its range (onset 600 s, ramp 30 s, 1800 s observed, 25 C, coastal, `RVP_9_0`, reference fittings, reference levels 9, 7 and 5 m), and finds by bisection the largest severity that passes every gate of the engine.

The full tables are in `local/results/representable_range.md`; the summary is the following. A candidate beyond the limit is written as `simulation_rejected` with its gate and is never labelled healthy (D66).

| fault type | range tried | largest passing severity | rejected beyond, and the gate |
| --- | --- | --- | --- |
| leak (area) | 2e-6 to 1e-3 m2 | 1e-3 m2 on every edge that carries a determined pressure in the lineup | on an edge that does not (for example the pump B branch while pump A delivers, the receipt edges of a delivery) every severity is rejected by SGF `leak_edge`; no leak is ever labelled on an idle edge |
| restriction, outlet or pump suction valve (closure fraction) | 0.10 to 0.85 | 0.7533 for `XV-S101`, `XV-PAI` and `XV-PBI`, 0.7196 for `XV-S102`, 0.6662 for `XV-S103` | SG0 `phase_validity_status` (the suction loss takes the NPSH margin below the screen) |
| restriction, pump discharge or receipt inlet valve | 0.10 to 0.85 | 0.85 for `XV-PAO`, `XV-PBO`, `XV-R101`, `XV-R102`, `XV-R103` | none in the range |
| pump head loss fraction | 0.02 to 0.30 | 0.30 for `P-101A` and `P-101B` | none in the range |
| misrouting (a), forced open | magnitude 1 | passes for `XV-PBI`, `XV-R101`, `XV-R102`, `XV-R103`, `XV-S101`, `XV-S102`, `XV-S103` in the lineups tried | `XV-PBO` forced open in `DELIVER_101_A`: SG2 `steady_solve` (no steady state); rejected |
| misrouting (b), stuck opening | 0.02 down to 0.005 | 0.005 for `XV-R101` and `XV-R102` in `RECEIVE_101_102` | none; every other valve is not eligible (D75) |
| sensor bias, drift, stuck-at | 0.002 to 0.05 of span | the whole range | no gate applies; the fault acts only in the sensor chain |

Consequence: a severe restriction of a valve on the suction side of the duty pump (more than 0.67 to 0.75 closed, according to the tank) is not representable, because the rigid-column model with the NPSH screen of D7 rejects the run; such a fault is outside the dataset and not a weak signal. The limits depend on the level, the temperature and the stratum of the run (the NPSH margin), and are those of the conditions listed; the bisection assumes that a severity that passes implies that every smaller one passes, and the end points of the 106 cases agree with it.

## Latent faults (D76)

A fault on an asset that is inactive in the lineup in force from its onset is labelled `latent` in the episode record (`fault_activity`); an active one is `active`. The label is computed from the lineup states from the onset to the end of the episode (the state at the onset and one per later timed lineup or set-point command; `verum.faults.activity`):

| fault | active if |
| --- | --- |
| leak, sensor fault | always |
| pump head fault | the pump runs |
| restriction, `position_visible` | the valve is open (its contact changes) |
| restriction, `obstruction` | the valve is open and carries flow (a receipt set-point above zero for an inlet valve, a running pump for an outlet or pump-branch valve) |
| misrouting (a), forced open | the valve is not already open |
| misrouting (b), stuck nearly closed | the valve is open |

A latent fault changes no emitted number: the observation and hydraulic-state files of the faulted episode equal those of the healthy episode (a test runs a head fault on the stopped pump B while pump A delivers). In a later campaign latent faults are at most 5 percent of the fault episodes and are excluded from the detection metrics; a campaign generator is not part of this phase.

A command triggered by an event (a protection request) is not applied in the label, which can turn a latent label into active but never the reverse.

## Eligibility and rejection (D66)

Checked before the run, as a validator of the specification record: the asset exists and has the type the fault needs; the severity parameter lies in its range; the onset lies in `[600, T - 1800]`; the ramp is one of 30, 300, 1200 s (hydraulic faults); at most one fault per asset and one fault in the episode; a restriction names its mode (D74); misrouting (b) is on a parallel branch of the lineup at the onset (D75); for a leak, `x` in `[0.05, 0.95]`.

Checked while running: every gate of the engine (pump domain, phase and NPSH screen, pumping minimum, mass ledger, solver convergence) and the leak pressure condition. A candidate that fails any of them is written as `simulation_rejected` with the gate; the fault is not labelled and no data are kept.

## Edge-flow convention (D67)

The `flow_m3s` of an edge row is the flow at its downstream end, so that FT-001 (end of E001) and FT-201 (end of E-D1) read at their meter nodes. Without a leak the two ends carry the same flow and the convention changes nothing.

## Hidden records

`fault_truth` rows follow the audited schema (`schemas/fault_truth.schema.json`, not modified): fault type, instance id, asset, location (a leak's edge and fraction), onset, mechanism, the severity trajectory, the physical parameter with baseline and severity-one values, hidden. The episode record lists the instance ids.

The vendored schema has no field for the restriction mode or the activity label, so the `mechanism` of a restriction row is `restriction_position_visible` or `restriction_obstruction`, and the episode record lists `fault_modes` and `fault_activity` in the order of the instance ids (only when a fault is injected). The specification record is validated by `schemas/fault_spec.schema.json`.

Nothing about faults is reachable from `verum.api`; `verum.sensors` knows only a hook interface (a callable acting on the reading), not the faults package.

## Implementation

- `verum.faults` (hidden side): `FaultSpec` records validated by `schemas/fault_spec.schema.json` (backend-proposed, closed), the eligibility validator (`check`, `violations`), `FaultSet` (the injector the engine calls) and the hidden `fault_truth` rows (`fault_truth.jsonl.gz` in the episode directory, empty for a healthy episode; the episode record lists `fault_instance_ids`).
- The engine takes a `FaultInjection` (leaks, valve opening modifiers, pump head scale, step boundaries at the knots of a ramp). A ramp ends a step where it changes slope, so the state at a knot is exact. `Valve.alpha` is the commanded motion changed by the modifier; the actuator continues from its own position, so a restriction does not change what a later command does.
- The sensor chain knows only a hook, `SensorHook(tag, t, value) -> value`, called after sampling and before noise for every scheduled sample (also a dropped one). With `clean` set the chain returns the noise-free sampled series, which the audit uses.
- Gates: a leak on an edge without a determined pressure or with a gauge pressure at or below 10 kPa stops the run with gate `SGF`; every other gate is unchanged. A rejected candidate keeps `simulation_rejected.json` only, and its record lists no fault.
- The leak adds `leak_flow_m3s` to the edge row when it is positive and fills the spill line of the network ledger row; the transient engine accepts a sink that grows linearly (`leak_ramp`) and evaluates it implicitly, which an explicit sink did not allow at larger coefficients.

## Limits

- A leak in the rigid-column engine is a sink evaluated from the last accepted solve (frozen over a step of at most 1 s); a leak that grows faster than a 30 s ramp, or a leak at the end of an edge, is outside the verified range. Its position within the edge is a share of length and of the local loss coefficient. The velocity head is neglected in its pressure.
- A leak in the transient engine sits at a junction, not inside an edge; the rigid-column leak of the comparison test is 5.25 m from that junction.
- Misrouting can create lineups the operator model does not expect (two suction branches, a receipt into two tanks). They are handled by the branched scheme, which is a validity window, or by a gate. A stuck-almost-closed valve on the duty path is outside the eligible set since D75 (it was rejected by gate SG0 or SG2 in the first audit, and is now refused before the run).
- A leak on an idle branch that is connected to live fluid cannot be represented: the steady network does not solve dead-end edges, so such a candidate is rejected at every severity and is never labelled (D82).
- The visible restriction and misrouting have a single class (clear) in the audit grid and cannot be balanced across classes (D82).
- A stuck-at has no consequence on a tag whose true signal is constant over the episode.
- Single faults only: the signatures of two simultaneous faults are not studied, a recovery is not modelled, and the sensor faults act on the 14 continuous tags only.
- No fault law, range or threshold is validated; the audit says what the model produces, not what a real terminal would show.

## Observability audit (D68): results

The runs are made by `tools/fault_audit.py` and tabulated by `tools/fault_audit_report.py` (full tables in `local/results/fault_audit.md`, not committed).

Grid: 8 log-spaced severities across the range of each fault, scenarios S0-A, S0-C and S0-B as applicable, three assets or locations per type (two pumps), onset 900 s, 1800 s observed, 300 s ramp, coastal, 25 C, reference fittings, the healthy twin of the same seed; 240 fault runs, 63 healthy runs (20 seeds with the demand process on per scenario and the twins) and 153 sensor-fault cases applied to the twins' truth.

The severity coordinate is the area of a leak, the closure fraction `1 - alpha_stuck` of a restriction, the head loss fraction `1 - head_scale` of a pump, the fraction of span (per hour for a drift) of a sensor fault and the stuck opening of a misrouted valve.

The two detectability thresholds are those of D68; where the demand process does not touch a tag its healthy variability is numerically zero and only the noise limits detection.

| fault | severity coordinate | smallest above 3 sigma of the noise | smallest above the healthy variability as well | first detection at the largest severity (s) | rejected by a gate | no consequence |
| --- | --- | --- | --- | --- | --- | --- |
| leak | area m2 | 2.87e-05 to 6.97e-05 (9 of 9 assets) | 6.97e-05 to 0.000412 (9 of 9 assets) | 30 to 250 | 0 of 72 runs | 0 of 9 assets |
| restriction | closure fraction | 0.136 to 0.25 (7 of 9 assets) | 0.136 to 0.626 (7 of 9 assets) | 70 to 130 | 4 of 72 runs | 2 of 9 assets |
| pump | head loss fraction | 0.02 to 0.02 (2 of 4 assets) | 0.0434 to 0.0434 (2 of 4 assets) | 30 to 30 | 0 of 32 runs | 2 of 4 assets |
| bias | fraction of span | 0.002 to 0.002 (9 of 9 assets) | 0.002 to 0.0199 (9 of 9 assets) | 10 to 10 | 0 of 72 runs | 0 of 9 assets |
| drift | fraction of span per hour | 0.002 to 0.00317 (9 of 9 assets) | 0.002 to 0.0316 (9 of 9 assets) | 20 to 140 | 0 of 72 runs | 0 of 9 assets |
| stuck | - | 7 of 9 assets | 5 of 9 assets | 30 to 1160 | 0 of 9 runs | 2 of 9 assets |
| misroute_a | - | 6 of 8 assets | 6 of 8 assets | 20 to 50 | 1 of 8 runs | 1 of 8 assets |
| misroute_b | stuck opening | 0.005 to 0.005 (2 of 7 assets) | 0.005 to 0.005 (2 of 7 assets) | 70 to 70 | 40 of 56 runs | 5 of 7 assets |

Reading the table:

- **Smallest detectable severity.**
  - "Smallest above 3 sigma of the noise" is the smallest of the eight severities for which some tag leaves the noise band in the 60 s mean; "as well" requires also the healthy variability of D68.
  - For the pump, the bias and the drift the smallest severity of the range (2 percent head loss, 0.2 percent of span) is already detectable, so the lower end of those ranges is not an observability limit; the ranges were not changed.
  - A leak is detectable from 2.9e-5 m2 (delivery side, about 1.9 m3/h at 3.3 bar, seen by the flow meter and the tank level) or 7.0e-5 m2 (suction side and receipt side, the tank level only); above the healthy variability of the delivery process it needs 4.1e-4 m2.
  - At a discharge coefficient of 0.5 or 0.8 the same flow needs an area of 0.62/Cd times that (3.6e-5 and 2.2e-5 m2 for the delivery-side leak): the leak depends on Cd times A only, and a test checks the identity.
- **Tags that carry the signal.**
  - A leak on the delivery side: FT-201, the level of the delivering tank, PT-202A and PT-203 (177, 69, 43 and 33 noise sigmas at the largest area).
  - A suction-side leak: only the tank level (the pump flow hardly changes). A receipt-side leak: the tank level and PT-001.
  - A restriction or a pump fault: FT-201, the tank level, PT-202A and PT-203, and a restriction on a valve with a limit switch also its contact, which changes at every closure fraction of the range (the contact releases below 0.97) and is the earliest indicator.
  - A sensor fault: its own tag only. A forced-open valve: the levels of the two tanks it connects and its contact.
- **No observable consequence** (no tag above either threshold and no event change): a restriction of a closed receipt valve (XV-R102, XV-R103 in S0-B), a head degradation of the stopped pump P-101B, a stuck-at on a tag that does not change (PT-202A in S0-A, FT-001 in S0-B), and a forced-open pump-B outlet valve in S0-C (rejected by the solver gate). These are faults of the model with no trace.
- **Rejected by a gate.** Severity 8 (closure fraction 0.85) of a restriction of the duty suction or pump inlet valve (the NPSH margin of the pump, SG0), and every severity of a valve stuck almost closed on the duty path (SG0 or SG2). They are not observations.
- **Confusable signatures** (cosine above 0.95 between the mean change over the last 300 s of two runs, in noise sigmas): a restriction of the pump inlet valve and a pump head degradation (0.999, S0-A and S0-C; the valve contact of the restriction separates them); leaks at different places of the same hydraulic zone (E-D1 and E-PA3, 0.993; E002, E003 and E-R101a on the receipt side, 0.997 to 1.0); a leak on the receipt side and a stuck level transmitter (0.98 to 0.99); a restriction of the receipt inlet valve and a bias or drift of PT-001 (1.0, both move PT-001 only); a bias, a drift and a stuck-at of the same tag (1.0 in the end change; they differ in time); two misrouted receipt or suction valves in S0-C (0.994). Leak against flow-meter bias or drift is not confusable in this measure (cosine between -0.03 and 0.0), because the leak also moves the tank level and the pressures; valve restriction against pump degradation is.
- **First detection.** At the largest severity the earliest tag leaves the noise band 30 to 250 s after the onset for a leak, 70 to 130 s for a restriction, 30 s for a pump fault and 10 s for a bias.

## Agent-side detectability audit (D77 to D82)

The twin audit above compares a faulted run with its healthy twin. An agent has no twin: it has the observed tags and the design model. This audit asks what an agent could see.

**Method.** Each run is reduced to residual features over windows of 60, 300 and 900 s ending on a 60 s grid (D80): mass balance (flow in minus flow out minus the least-squares slope of the summed tank volume), pump consistency, delivery law, delivery flow and receipt pressure against the design model, and a trend of each tag. The design model is perturbed over five draws (pump head, fitting loss, boundary coefficient). The threshold of a feature is the 99th percentile, over healthy runs and draws, of the largest deviation from the healthy mean over all windows (D79). The margin of a cell is the largest deviation over all windows divided by the threshold, best over the three window lengths and worst over the draws. A change of a valve contact or a pump status is a margin of 3. The held margin (three consecutive windows) is a second column and sets the time to detect (D81). Classes: invisible below 1, marginal from 1 to below 3, clear from 3.

**Calibration.** 200 healthy runs per lineup and profile fix the thresholds, with 3 to 5 percent median error of the percentile (a bootstrap over runs; 15 to 17 percent for the worst feature). 100 other healthy runs per lineup and profile give the false-alarm rates.

| quantity | v1 | v2 |
| --- | --- | --- |
| mean false-alarm rate per feature | 1.1 to 1.5 percent | 1.1 to 1.4 percent |
| features above 2 percent | 13 to 21 percent | 9 to 19 percent |
| healthy runs with an alarm on any feature | 39 to 49 percent | 35 to 41 percent |
| factor on all thresholds for 1 percent on any feature | 1.28 to 1.35 | 1.28 |
| any feature after that factor | 1 to 3 percent | 1 to 2 percent |

The target of 1 percent holds for each feature. A cell takes the largest margin over about 50 features and three window lengths, so a margin of 1 is exceeded by about 40 percent of healthy runs (166 of 400 under v1, 148 of 400 under v2); a margin of 3 by none. The tables give the counts at the thresholds of D79 and at the thresholds scaled by the factor above, which restore 1 percent on any feature. Cells that equal a healthy run (latent faults) are excluded from the counts.

**Noise floor of the mass-balance rate** (m3/h, standard deviation over healthy windows). The hand value is the level noise of 0.25 mm on three tanks of 706.86 m2: 18.4, 1.64 and 0.316 for 60, 300 and 900 s.

| profile | 60 s | 300 s | 900 s |
| --- | --- | --- | --- |
| v1 | 19.7 to 19.8 | 1.71 to 1.72 | 0.33 to 0.37 |
| v2 | 19.5 to 19.8 | 1.90 to 2.62 | 1.40 to 3.71 |

Under v1 the measured values are 4 to 16 percent above the hand estimate (the flow meter noise and the position of a reading inside its 10 s block). Under v2 the longer windows are dominated by changes of flow inside the window: the slope of the volume weights the middle of the window and the mean of the flow weights it evenly, so a regime ramp leaves a residual. The spread has heavy tails (900 s on lineup A: 3.71 by standard deviation, 1.37 by median absolute deviation).

**Detection** (active cells with a margin of at least 1, and in brackets at least 3, of the cells of the fault):

| fault | twin | three-sigma held margin, v1 / v2 | calibrated, v1 | calibrated, v2 | calibrated and scaled, v2 |
| --- | --- | --- | --- | --- | --- |
| leak | 40/72 | 16/72 / 13/72 | 54/72 (33) | 40/72 (10) | 19/72 (9) |
| restriction, `position_visible` | 52/52 | 52/52 / 54/54 | 52/52 (52) | 54/54 (54) | 54/54 (54) |
| restriction, `obstruction` | not run | 25/52 / 14/54 | 36/52 (26) | 19/54 (9) | 14/54 (9) |
| pump head loss | 16/16 | 12/16 / 11/16 | 15/16 (10) | 12/16 (8) | 12/16 (8) |
| sensor bias | 72/72 | 9/72 / 7/72 | 70/72 (62) | 60/72 (35) | 48/72 (34) |
| sensor drift | 67/72 | 37/72 / 23/72 | 62/72 (53) | 52/72 (23) | 31/72 (20) |
| sensor stuck-at | 7/9 | 3/9 / 6/9 | 8/9 (5) | 8/9 (7) | 7/9 (4) |
| misrouting (a) | 7/7 | 7/7 / 7/7 | 7/7 (7) | 7/7 (7) | 7/7 (7) |
| misrouting (b), parallel branch | not comparable | 16/16 / 16/16 | 16/16 (16) | 16/16 (16) | 16/16 (16) |

Cells that change a contact (the visible restriction, misrouting) are clear by the contact. Under v2 leaks, bias, drift, the obstruction mode and pump faults are less detectable than under v1, because the regimes raise the variability of the residuals that depend on the downstream factor; a stuck-at is as detectable or more, because the regimes move the true quantity away from the frozen reading.

**Classes** (profile v2; share of the active cells of the grid, which is log-uniform in severity; the scaled columns use the scaled thresholds):

| fault | invisible | marginal | clear | scaled: invisible | marginal | clear |
| --- | --- | --- | --- | --- | --- | --- |
| leak | 0.44 | 0.42 | 0.14 | 0.74 | 0.14 | 0.12 |
| restriction, `obstruction` | 0.65 | 0.19 | 0.17 | 0.74 | 0.09 | 0.17 |
| pump head loss | 0.25 | 0.25 | 0.50 | 0.25 | 0.25 | 0.50 |
| sensor bias | 0.17 | 0.35 | 0.49 | 0.33 | 0.19 | 0.47 |
| sensor drift | 0.28 | 0.40 | 0.32 | 0.57 | 0.15 | 0.28 |
| sensor stuck-at | 0.11 | 0.11 | 0.78 | 0.22 | 0.33 | 0.44 |
| restriction, `position_visible` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 |
| misrouting (a), (b) | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 |

Class-balanced sampling gives a third of each class that a fault type populates. The visible restriction and misrouting populate only the clear class and cannot be balanced (D82). Profile v1 has more clear cells (leak 0.25, 0.29, 0.46; obstruction 0.31, 0.19, 0.50).

**Smallest detectable severity** (profile v2; median over the assets of the class that reach a margin of 1, with their number; severity as in the audit grid). Left: thresholds of D79. Right: scaled thresholds.

| fault | asset class | 60 s | 300 s | 900 s | scaled: 60 s | 300 s | 900 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| leak (m2) | discharge | 2.0e-4 | 1.2e-4 | 9.3e-5 | 2.9e-4 | 1.9e-4 | 2.0e-4 |
| leak (m2) | pump branch | 2.0e-4 | 1.2e-4 | 9.1e-5 | 2.8e-4 | 1.9e-4 | 1.9e-4 |
| leak (m2) | receipt | 2e-6 (3/3) | 7.8e-5 | 2.9e-5 | none | 1.2e-4 | 9.0e-5 |
| leak (m2) | suction | 9.0e-4 (1/2) | 3.5e-4 | 2.4e-4 | none | 5.0e-4 | 5.0e-4 |
| pump (head loss) | pump | 0.031 | 0.036 | 0.032 | 0.037 | 0.043 | 0.044 |
| restriction `obstruction` (closure) | tank inlet | 0.18 | 0.21 | 0.19 | 0.30 | 0.25 | 0.26 |
| restriction `obstruction` (closure) | tank outlet | 0.49 (1/2) | 0.56 | 0.49 | 0.61 (1/2) | 0.61 (1/2) | 0.52 (1/2) |
| restriction `obstruction` (closure) | pump branch | 0.47 (2/3) | 0.50 (2/3) | 0.47 (2/3) | 0.50 (2/3) | 0.53 (2/3) | 0.51 (2/3) |
| bias (fraction of span) | flow | 0.002 | 0.020 | 0.020 | 0.036 (1/3) | 0.028 | 0.029 |
| bias (fraction of span) | level | 0.002 | 0.002 | 0.002 | 0.002 | 0.002 | 0.002 |
| bias (fraction of span) | pressure | 0.0080 | 0.0058 | 0.0052 | 0.039 | 0.0075 | 0.0077 |

Where a value is the smallest in the range (2e-6 m2, 0.002) the margin already reaches 1 at the least severe point; for a flow meter and a receipt leak at 60 s that is the false-alarm floor, not detection, and the scaled columns show no detection there. On the discharge side a 900 s window halves the smallest detectable leak against a 60 s window (thresholds of D79).

**Time to detect** (profile v2; seconds after the onset at the end of three consecutive windows above the threshold; median over the detected cells, and the number at the most severe cells in the text below):

| fault | 60 s | 300 s | 900 s |
| --- | --- | --- | --- |
| leak | 360 | 420 | 900 |
| restriction, `obstruction` | 300 | 360 | 450 |
| pump head loss | 270 | 390 | 570 |
| sensor bias | 180 | 180 | 300 |
| sensor drift | 180 | 180 | 360 |
| sensor stuck-at | 390 | 300 | 600 |
| misrouting (a) | 180 | 240 | 296 |
| restriction, `position_visible` | 37 | 37 | 37 |
| misrouting (b) | 11 | 11 | 11 |

At the most severe cells a leak is found after 300 s at 60 s, 360 s at 300 s and 540 s at 900 s. A longer window finds smaller faults and finds them later.

**Confusable pairs** (cosine above 0.95 of the normalised signature, cells with a margin of at least 1, profile v2). A restriction in mode `obstruction` and a pump head degradation are confusable in 12 cell pairs, and no contact separates them: an obstruction leaves the contact open and a pump fault has none. A restriction in mode `position_visible` against a pump degradation (13 pairs), against a leak (36), against the obstruction mode (80) and against misrouting (a) (19) is separated by the contact. A leak against an obstruction (36 pairs), a bias (230), a drift (148) or a stuck-at (22), and a bias against a drift (207), are not separated by any contact. Leak against pump degradation does not appear.

**What changed against the three-sigma held-margin method (D77 version 1), and why.**

- Detection rose for leaks, bias and drift. Longer windows and a regression slope lower the noise floor of the mass balance from 19.7 to 0.33 m3/h under v1 (table above), so a bias of a level or pressure transmitter is seen at 0.002 and 0.005 of span (900 s) where the held margin saw 9 of 72 bias cells. Under v2 the floor stays at 1.4 to 3.7 m3/h at 900 s because of regime ramps, and the 900 s threshold of the mass balance is 14 m3/h against 1.2 m3/h under v1.
- The threshold is a percentile of the largest deviation, not three standard deviations pooled over windows, so it no longer depends on the number of windows.
- The single-window margin has a false-alarm floor that the held margin hid. At a margin of 1 about 40 percent of healthy runs alarm. The counts at a margin of 1 therefore overstate detection, and the scaled columns and the margin of 3 are the safer reading.
- A leak is smallest detectable at 8e-5 to 2.2e-4 m2 (best length; 1.9e-4 to 4.9e-4 m2 with the scaled thresholds), against 3.3e-4 to 8.8e-4 m2 with the held margin.
- The confusable pairs lost leak against pump degradation and gained leak against obstruction, because the features and windows differ.
- Time to detect is now a function of the window length, 180 s to 900 s for the faults that are seen.

**Limits.** The nuisance ranges, the window lengths and the number of healthy runs are selections. The design model is the plant model itself, so an agent with a worse model sees less. A leak on an idle branch connected to live fluid cannot be represented, because the steady network does not solve dead-end edges (D82). The visible restriction and misrouting populate only the clear class (D82). The classes describe this model and these features, not a real terminal.
