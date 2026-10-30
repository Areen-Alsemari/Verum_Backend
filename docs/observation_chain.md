# Observation chain and read-only gateway

This document describes `verum.sensors`, which turns the hidden truth of an episode into the observations an agent may see, and `verum.api`, the library that serves them. It describes a model of a synthetic terminal: the noise levels, delays and rates are selections, and nothing here has been validated against an installed instrument. The decisions are D27 to D33 in `docs/design_decisions.md`.

## Separation

`verum.sensors` is separate from `verum.truth`. One module, `verum.sensors.adapter`, reads the episode directory and is the only importer of truth types (a static test enforces it); the chain itself (`chain.py`) works on arrays. `verum.api` imports no truth, engine, hydraulics, ledger or protection module and reads only `observations.jsonl.gz`.

## What is observed

Only the 30 tags with status `emit` in the sensor contract have a specification (`config/sensor_specs.json`, from table 6.1.1 of the instrumentation document, and `config/sensors.json`). The six withheld tags (`YS-201A/B`, `VT-201A/B`, `IT-201A/B`) have none and produce no row.

Every truth quantity a tag reads is determined: a segment that carries no flow has a pressure (decision D39, below), so a null row is always a random dropout and the null rate is the same in every episode.

### Dead-leg pressure (D39)

A segment that the steady solve leaves without flow takes the head of the tank or the reservoir it is open to; an isolated, liquid-full segment holds the head it had when it was isolated and relaxes to the head across its closed isolation valve with a time constant of 60 s.

A standby pump branch therefore reads the head of the suction tee, and PT-001 after a receipt closure decays from its last value toward the hydrostatic head of the receiving tank. Trapped-liquid thermal and compressibility effects are not modelled.

### The two PT-001 values (D36 version 2)

The observed PT-001 reads the start of `E002` (sensor contract): the source head less the loss of `E001` and `Lambda_E001 dQ/dt`, with `Lambda_E001 = 42.4 s2/m2`. The hidden tap value for the end of `E002` keeps `E001` and `E002` (63.6 s2/m2) and is labelled `end_of_E002_lambda_E001_E002` in the node row.

## The chain, in order

1. **Mapping and units.**
   - The true quantity named by `measured_variable_ref`, converted to the observation unit before anything else: m3/s to m3/h, absolute pressure to gauge with the atmosphere of the episode stratum (101325 or 94300 Pa), K to C.
   - The truth pressure is absolute (gauge plus the stratum atmosphere) and every emitted transmitter reports gauge against the episode atmosphere, so the same hydraulics read the same in both strata.
   - A sensor referenced to a fixed atmosphere would read 0.07025 bar lower in the inland stratum; none of the 30 emitted tags is of that kind.
2. **Transport delay.** None unless given.
3. **First-order lag** with the time constant of the table. The discretisation is exact for a piecewise-linear input and the state is carried; at an event (a pre-event and a post-event row at one instant) the input jumps and the state is continuous. The chain never interpolates across an event; a sample at an event time reads the post-event input.
4. **Sampling** at the rate of the table, with the phase of the tag (the SHA-256 of its name modulo its interval, decision D32), either instantaneous or, for `TT-101..103`, the mean of the lagged signal over the trailing 30 s.
5. **Bias and drift** hooks, zero for now.
6. **Noise**, Gaussian per sample: level 0.25 mm, flow 0.2 m3/h, pressure 0.005 bar, temperature 0.075 C. One random stream per tag and per purpose (`sensor/<tag>/noise`, `sensor/<tag>/dropout`), so adding a tag changes no other tag's draws.
7. **Quantisation and clipping.** The reading is rounded to span/65535 and clipped to the calibrated range; it is flagged `suspect` when it lies beyond the range by more than three noise standard deviations (a real overrange, decision D29 version 1.1). A negative gauge value inside the range is valid.
8. **Dropout.** Each sample is lost with probability 0.05 percent, the same in every episode. A lost sample is a row with a null value, `missing_sample` and quality `bad`.

Each row carries `t_sim_s`, `t_available_s` (the sample time plus the comms delay of the table), `timestamp_utc` (a fixed synthetic start, `config/sensors.json`), the unit, the quality flag and the availability status, and validates against the closed `observation.schema.json`.

The hidden `observation_audit` row carries `t_source_s` and `max_truth_time_used_s`; the schema is closed, so the list of active validity windows is not a field of it (the window records are joined by time from the hidden `validity_windows` dataset).

## Event tags

Valve contacts, pump running indicators and the high-high detectors are rows at t = 0 and at each change. The valve open contact asserts when the opening reaches 0.98 and releases below 0.97 (decision D31); the row follows after the lag of the table and becomes available after the comms delay. Only the open contact is emitted.

## The independent detector (decision D33)

The high-high trip of the protection logic is decided on a detector inside the engine: the true level plus a fixed offset (standard deviation 1 mm, one draw per episode from the stream `detector/<tank>`), located by root-finding and delivered after 0.2 s. The LSHH observation is that signal after the comms delay.

HIGH_ALARM and its clearing use the level-transmitter chain itself (decision D40): the engine samples the same lag, noise, quantisation and dropout draws as the observation chain and the protection logic sees a sample when it has arrived, so the alarm time equals the `t_available_s` of the first `LT` observation at or above the alarm level.

In the S0u-E episode the offset moves the trip by 0.085 s against the former truth-based trip, and the alarm moves from 848.23 s (true crossing) to 852.54 s.

## The gateway

`verum.api.Gateway(episode_directory).query(T)` returns, as a dictionary, the episode's opaque identifier, `T`, the observations with `t_available_s <= T`, the assets (tanks, pumps, isolation valves) and the inspection catalog.

Every observation is validated against the closed observation schema and every asset against a closed schema; the payload then passes an allowlist that rejects keys outside the interface and strings that name a scenario, a validity window, a dataset tier or a truth dataset. The inspection catalog is empty: no catalog exists in the audited package or the configuration, and none has been invented.

## Joining windows to observations

The audited audit schema is closed. `verum.evaluation.attach_window_ids` (evaluation side, not in `verum.api`) attaches the identifiers of the validity windows that contain the sample time to copies of the observation rows. The joined rows are evaluator data.

## Limitations

- Truth between rows is linear; outside valve strokes and validity windows the truth rows are 1 s apart (decision D34), so fast changes there are not resolved.
- Dead-leg pressures follow a selected relaxation (D39); they are not a model of trapped liquid.
- Noise is white and Gaussian; there is no bias, drift, stuck value or spike.
- Nothing in this document has been validated against measured data.
