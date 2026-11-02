# Normal-operation vapour estimates

These methods produce evaluator-only mass estimates. They do not produce VOC observations, subtract another hydraulic mass sink, predict damaged materials or qualify the dataset for physical training. The immutable vendor handoff supplies representative facility choices; EPA supplies applicable normal-operation methods. Neither determines unspecified installed hardware.

## Routine window

`verum.vapour.window.estimate_window` joins the sourced standing components and withdrawal calculation for a constant-condition window. Timestamps must have an explicit UTC offset, recorded levels must cover the entire window and match the declared maximum recording interval, and all samples must remain floating and within the M1 normal operating envelope. The caller must explicitly declare a freely moving roof; level alone does not prove a jammed roof is floating normally. The inherited minimum 30-day and 365-day scaling conventions remain DESIGN choices rather than exact calendar-month definitions.

The input requires a named product/property profile, explicit source-bearing vapour properties and density, shell condition, seam construction/basis and actual seam length where needed. The mechanical-shoe rim register contains the reviewed EPA Table 7.1-8 average-fitting variants; the M1 adapter requires explicit average-fit selection and secondary attachment. Tight-fitting factors and a primary-only system cannot silently replace the selected secondary seal.

Each of the four M1 fitting groups needs a complete count and explicit classification/basis. Uncontrolled wells require exposed area excluding obstructions, well height and affirmative uncontrolled status. The adapter checks the source's height domain and cannot apply that correlation to a controlled opening. Six specified suspension penetrations cannot be assigned the no-opening hanger factor. Missing or incompatible classifications raise instead of producing an incomplete total.

Withdrawal follows cumulative recorded decreases, separately from gross simultaneous discharge. Sparse or incomplete level records do not reconstruct unrecorded cycles; the output retains that limitation and unresolved uncertainty. Constant vapour properties are explicit inputs, not inferred from bulk temperature, a generic fuel name or a previous hourly episode. The result binds the entire input, factor files and geometry. The command adds the current source revision and base configuration hash.

The level input explicitly declares piecewise-linear interpolation between knots. Bounds apply to that prescribed trajectory, not to unrecorded field excursions. This is a declared numerical representation rather than proof that a sparsely observed operating tank followed those intermediate levels.

## Normally supported liquid-heel landing

`verum.vapour.landing.heel_landing_episode` implements the normal IFRT liquid-heel method using explicit geometry, available liquid, vapour properties and daily expansion. The idle term is capped by available heel mass. Refilling is separated into prior-stock arrival and incoming-generated vapours; change of service uses each stock's own properties. Prior stock already exhausted by idle losses is not counted again on refilling. Without completed refilling, filling and whole-episode totals remain unknown rather than assumed zero.

`landing_daily_expansion` computes the normal landing form of Equation 1-5 from explicit average temperature, temperature span, vapour pressure span and atmospheric pressure. Its zero breather-setting range follows the source's landing convention, not a simulation of actual blocked or restricted vents. Weather, thermal and fluid-property inputs are not fabricated. The API also accepts a separately sourced expansion factor in 1/day.

This implementation covers full and partial liquid heels, normal maintained supported roofs and free venting. Drain-dry idle clingage, forced tank cleaning, closed-vent operation, structural hang-up, blocked-vent pressure and damaged-material rates need separate applicable models and evidence. The presence of this normal landing calculator must not be used to estimate an abnormal held-roof event. Routine periods must exclude landed periods; overlapping totals must not be summed.

## Command

```bash
.venv/bin/python tools/vapour_estimate.py --input local/reviewed_vapour_inputs.json --output local/vapour_estimate.json
```

The input `estimate_type` is `routine_window` or `liquid_heel_landing`. Routine inputs follow the complete-window contract above. Landing inputs place source-bearing numeric records under `parameters` and explicitly state `heel`, `normal_supported_landing`, `freely_vented`, `maintained` and `refill_completed`. A refilled landing requires incoming-stock properties even if the service is unchanged, so the method never silently invents the incoming mixture. Output files are created once; an unresolved input stops before writing an estimate.

## Source locators and verification

[EPA AP-42 Chapter 7.1, June 2026](https://www.epa.gov/system/files/documents/2026-08/c7s1_2026.pdf): normal scope and cadence in sections 7.1.1.1 and 7.1.3.8.1; rim systems in Table 7.1-8; fitting and seam terms in Equations 2-13 through 2-18; withdrawal in Equations 2-19/20; liquid-heel landing in section 7.1.3.3 and Table 7.1-17; caps and change of service in Equations 3-4, 3-16 and the text following 3-18; daily expansion/saturation in Equations 1-5 and 1-23. The earlier official [2018 chapter](https://www.epa.gov/sites/default/files/2020-11/documents/ap42_chapter_7_section_7-1_revisions.pdf) and [2025 chapter](https://www.epa.gov/system/files/documents/2025-09/c7s1_2025.pdf) provide legible equation transcriptions; the current applicability and factor rows are checked against the 2026 chapter. Do not mix the older hatch value or example rounding into the current registry.

The published normal IFRT example checks the underlying routine components. Separate tests use independent ideal-gas arithmetic and source formula substitutions for landing, heel depletion, partial-day duration and change of service. Complete-window tests use explicitly synthetic fitting choices and do not select missing Verum hardware. Software agreement establishes implementation consistency, not the actual emission uncertainty of this representative plant.
