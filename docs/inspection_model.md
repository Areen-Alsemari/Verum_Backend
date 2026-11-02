# Inspection model

Default catalog views mark unqualified roof/fitting, vibration and acoustic outputs unmodelled with unknown uncertainty, matching their missing/inconclusive results. Catalog and query views use the attached service's capability view. Explicit historical research retains its original catalog, without asserting field qualification. Available valve, level and calibration readings remain distinct from unsupported equipment-acceptance decisions. See D129.

This document describes the inspection actions that an agent can ask for, how a request is approved and performed, how an outcome is produced from the true state of the episode, and what the model does not claim. The decisions behind it are D100 to D109 in `docs/design_decisions.md`.

## What an agent can do

An agent can read the catalog of seven actions, submit a request for one action on one asset, read the state of its requests, read the results that are available, and read the history of the assets. It cannot dispatch anyone. Every request goes to an approval emulator that stands for the plant operator, and the emulator is the only actor in the workflow.

All of this goes through the gateway (`verum.api.Gateway`) when an inspection service is attached to it. The gateway returns only rows that pass the closed schemas of the interface, and every function takes the time of the agent: nothing that has not happened by that time is returned.

## The catalog

The catalog is in `config/inspection_catalog.json` and comes from section 6.3 of the instrumentation document. The agent sees the name, the kind of asset it applies to, the preconditions, the cost, the duration and the outputs with their expanded uncertainty U (coverage factor 2).

| Action | Asset | Cost (USD) | Duration (min) | Main output and U |
| --- | --- | --- | --- | --- |
| `ACT-INSP-01` rim seal and deck survey | tank | 280 | 90 | maximum rim gap, 1.0 mm |
| `ACT-INSP-02` valve travel and pressure drop | isolation valve | 90 | 45 | pressure drop, 0.01 bar; stem travel, 2 percent |
| `ACT-INSP-03` pump vibration | pump | 140 | 60 | overall velocity, 0.1 mm/s |
| `ACT-INSP-04` acoustic leak survey | pipe edge | 350 | 120 | leak found or not found |
| `ACT-INSP-05` manual dip | tank | 110 | 45 | level, 1.5 mm |
| `ACT-INSP-06` vent and fitting check | tank | 160 | 60 | seating of the fittings |
| `ACT-INSP-07` pressure loop calibration | pressure transmitter | 120 | 45 | calibration error, 0.025 percent of span |

A value that the source document does not state is left unresolved and the agent sees it as missing. These are the spectral peak ratios, the water bottom cut, the cracking pressure and the localisation error of the leak survey.

## The workflow

A request names the action, the asset, the competing hypotheses, the information gain that the agent expects and its estimated cost. The gateway refuses a request for an unknown asset, for an action that does not apply to the kind of asset, for a gain above the base-2 logarithm of the number of distinct hypotheses, for a time in the future, for an identifier that was used, and for a request that sets its own approval.

The emulator decides after a delay that is uniform from 5 to 30 minutes. It rejects a request for a non-safety reason with probability 5 percent, and it rejects a request whose precondition fails in the true state at the time of the decision. A rejection carries a plain reason code.

An approved request is scheduled after a delay that is uniform from 0 to 15 minutes, takes the duration of its action, and the result is available 2 minutes after the action is performed. Before that time the agent sees the request as requested or approved and nothing else. All delays and draws come from named random streams of the episode seed, keyed by the request, so a request has the same timeline whatever the other requests are.

## How an outcome is produced

The model reads the true state of the episode at the performed time from the evaluator file of true quantities, and the measured value is that true value plus a Gaussian error with standard deviation U divided by 2. Numbers are interpolated between the rows of the file. Across an event, where the file has a row just before and a row just after, the value is that of the side on which the time falls.

An action often needs more than the 3600 s episode, because it takes 45 to 120 minutes after an approval delay. The default workflow refuses a planned measurement beyond recorded process coverage with `INSUFFICIENT_SIMULATED_HORIZON`; declaring a longer scenario duration without supplying additional process states is insufficient. Result delivery may occur later than the process horizon if the measurement itself is covered. Replaying archived research requires explicit `allow_extrapolated_research=True`, which preserves the historical held-state emulation but is not qualified inspection evidence.

- The valve check reports the pressure drop across the valve body, from the loss coefficient of the valve law at the actual opening and the flow, and the measured stem travel. It also states the commanded state and whether the open contact reads open, so a valve that is commanded open but is only partly open, with a contact that still reads open, can be told from one whose contact follows it.
- The pump check reports an overall vibration velocity that rises with the head loss of the pump by a declared law. No other vibration physics is modelled.
- The acoustic survey finds a leak of the target edge with probability 1 / (1 + (q50 / q)^2), where q is the leak flow at the performed time and q50 is 0.9 m3/h. If it finds the leak it gives a position along the edge with a normal error of 5 m.
- The dip reports the true level of the tank in mm. The agent compares it with the level that the radar gauge reports, which finds a bias, a drift or a stuck sensor.
- The calibration reports the difference between the true pressure at the transmitter and the value it reports, in percent of span, which finds a bias, a drift or a stuck sensor.
- The rim survey and the fitting check depend on the state of the rim seal and the fittings, which comes from the vapour track. Until that track is merged they return an intact result and say so in the result.

## Categories

A result has one of four categories: `NORMAL_INTACT`, `MINOR_DEGRADATION`, `CRITICAL_DEFECT` and `TEST_INCONCLUSIVE`. The thresholds are stored in the catalog file with their source. Only a few come from the document. A valve drop at or below 0.05 bar is normal, and a pump velocity at or above 7.1 mm/s is critical. The others are selections that are marked as such. A dip or a calibration is normal if it agrees with the reported value within three standard deviations of the difference, and otherwise inconclusive, because there is no threshold of severity. An acoustic survey that finds a leak is critical, and one that finds nothing is inconclusive, because a small leak can stay below the detection limit.

## History

Each asset has a synthetic history of prior inspections, calibrations and work orders, generated from the episode seed. It does not depend on the faults of the episode: a faulted and a healthy episode with the same seed have the same history. A record holds a date, an action or a work type and an outcome, and no measured value. A result that becomes available during the episode adds a record at that time.

## Limits

The probabilities of detection, the vibration law, the localisation error and the thresholds are selections of a simulation. They are not field performance and are not validated against inspection data. The detection limit of 15 L/min is an assumption of the source document that it states as unvalidated.

Default execution checks process preconditions at approval, work start, every recorded state during work and completion. A failed condition cancels the result at that recorded time, even if the process recovers before completion. Earlier approval and result views do not reveal a future cancellation. Archived research replay retains approval-only behaviour. These are simulation-cadence checks, not certified continuous monitoring or a complete personnel/atmospheric permit model.


## Mechanical extension

An episode with a versioned mechanical sidecar supplies rim gaps and fitting seating state to the existing inspection workflow. A rim inspection reports a noisy gap and a roof-position anomaly when present; a fitting check reports the selected synthetic seating-defect code. Both retain low-confidence evidence and plain model-limit notes. Episodes without the sidecar keep the earlier placeholder behaviour for reproducibility.

The mechanical extension is a restricted synthetic model (D121). It does not model roof forces or change hydraulic observations. The associated 30-day constant-condition vapour reference is evaluator-only, carries unresolved uncertainty and is not a complete tank loss or an observation.

Historical mechanical, vibration and acoustic outcome laws require explicit legacy research use. Default unsupported actions produce `TEST_INCONCLUSIVE` with missing evidence. The metric `measurement_available = 0` is an availability indicator, not a zero physical reading or proof of intact equipment. New coupled-roof cases require actual process coverage even when research extrapolation is requested.
