# Training qualification

The current campaign is a controlled synthetic experiment, not a sample of terminal operating history. Its hourly windows, 80% faulted episode fraction and middle-window fault placement are experimental choices. They cannot supply a real fault prior, expected warning time or operational detection rate. Changing those values to guessed industrial frequencies would not validate the data.

## Physical scope

The delivery and receipt episode engine has reduced path dynamics. The standalone method-of-characteristics engine has separate verification, but is not the episode producer. Transient physical training remains subject to the existing full-network release gates. Restricted branched episodes cannot be promoted by counting successful runs.

The archived mechanical extension copies each healthy parent's hydraulic observations. Its roof displacement proxy therefore does not represent a physically coupled roof failure. Its synthetic gap, seating, inspection and secondary tear rules are provisional. EPA routine tank-loss coefficients do not validate damaged-tank loss rates, instantaneous VOC or the selected cascade threshold. The vendor research explicitly leaves these mechanisms and measurement performance unqualified.

Archived inspections extend a held final process state beyond the hydraulic horizon. Default scheduling refuses uncovered measurements and checks work-start, recorded work-period and completion conditions. Cancellation is exposed at its occurrence, not at earlier approval. Unsupported roof, fitting, vibration and acoustic models return missing/inconclusive evidence. Explicit research replay does not qualify archived findings. Sampling-resolution limits and omitted personnel/access conditions prevent treating these checks as a certified permit system.

The one-sided `RoofHangup` input models a rigid roof held at its initial floating elevation during withdrawal. Liquid displacement feeds back into head and transmitters. The native producer now writes coupled signals, canonical roof truth, complete scenario inputs and censored initial-condition metadata. Cases remain restricted: no tilt, rupture or automatic seal tear is inferred. Pressure-load assessment accepts explicit absolute gas pressures above and below the deck but does not compute vent flow or pressure. The deck mass remains the vendor design proxy and support strength remains unresolved. See `docs/roof_vapour_basis.md`.

## Sampling and timing

New restricted extension runs select a target using a named seeded stream before observing its level trajectory. Parents are not screened for realised motion. Every requested cascade trial is retained; absence of a child is an outcome, rather than a reason to delete the parent. These changes remove future-conditioned experimental selection. They do not turn the remaining synthetic damage law into a validated mechanism. Archived cases are preserved, not relabelled.

An explicit `observation_window` profile admits initial, early and late faults in the core episode producer. A pre-existing physical fault is represented as a step at the first observation and receives evaluator-only left-censor metadata: the historical failure time is unknown. A ramp at time zero still describes observed progression, not an invented historical onset. Finite positive ramps can extend beyond the observation horizon. No occurrence distribution is implied. The legacy profile and its identifiers remain unchanged; new-profile identities bind the profile and fault specifications.

## Truth and qualification

`verum.training.load_episode_truth` reads both hydraulic and mechanical canonical truth files and rejects inconsistent duplicate identifiers or disagreement with stored fault labels. An empty hydraulic compatibility file does not make a mechanical fault healthy. No diagnostic agent or trainer is implemented.

`verum.training.assert_training_ready` refuses a dataset with unresolved qualification. Evidence binds the manifest, source revision, configuration and referenced artifact hashes. Reviews must cover the physical model, operating envelope, fault mechanisms, sensor chain, observability supervision and split/shortcut audit, as well as every existing physical release gate. Independent engineering references and design validation are permitted; private field records are not the only admissible evidence. Hashes establish which evidence was reviewed, not whether its engineering conclusions are correct. Neither self-declared pass flags nor software tests replace that review.

The 574 unaudited core visibility classes remain unknown supervision, rather than assigned detection difficulty. Fault identity truth is retained. Completing those classes requires the documented observation audit with thresholds fitted from healthy training records; validation and test records cannot fit the rule. A complete emissions model also needs matched equipment terms, withdrawal/landing treatment for the intended window, valid fluid properties and explicit uncertainty. A physical cascade needs a separately justified child failure criterion, rather than a normal pressure or level response labelled as new damage.
