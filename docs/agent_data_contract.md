# Eight-role reference-model data contract

The architecture is the eight logical agents in the master project context, version 1.3 dated 28 October 2026. Its SHA-256 is `21fd59d1c0bafab09daf5dfab1df7dc68aa6a58d5cd4e8a07d88f740b8b8176d`. Five team members do not imply five agents. The export creates datasets and reference fixtures; it implements and trains no agents.

| Role | Available data task | Unsupported target |
|---|---|---|
| Predictive Health | Forecast the next 300 s of reported continuous measurements from prior available readings | Validated equipment health score or remaining useful life |
| Anomaly Detection | Observed data-quality events and separately masked reduced-model injection targets | Treating an invisible or unaudited fault as healthy |
| Topology & Dependency | Retrieve declared direct connections with the public graph supplied | Hidden actual valve position or confirmed active flow route |
| Historical & Asset Intelligence | Retrieve declared asset facts and explicitly absent maintenance history | Invented past maintenance or failures |
| Diagnostic Reasoning | Masked single/multiple injection components in the reduced hydraulic simulator | Field-confirmed causes or unqualified mechanical diagnoses |
| Inspection Planning | Retrieve actual catalog costs, durations, prerequisites and limitations | An invented optimal action or realised information-gain score |
| Inspection Quality & Documentation | Observed record quality and retrospective inspection metadata checks | Acceptance of legacy out-of-horizon measurements as equipment evidence |
| Evidence Verification & Decision | Check timing and usability of supplied evidence proposals | Automatic maintenance/control decisions or a confirmed equipment condition |

## Inputs and labels

Shared snapshots use only records whose availability time is at or before their cutoff. The 300 s windows are closed on the right and open on the left. Last missing readings stay missing; earlier measurements have a distinct value, quality and age. Numerical summaries describe reported values, including explicitly counted non-good-quality samples; they are not corrected physical truth. Boolean contacts retain their last reported state without continuous-signal statistics. Ages at least as old as the lookback are right-censored at the lookback with an explicit lower-bound flag; a contact unchanged since startup cannot encode the absolute episode clock through its age. Episode identifiers, absolute episode clocks, hidden truth, future measurements and supervision masks do not enter model inputs. Every role receives only its own target through the loader.

All labels reside outside the input object. Diagnostic targets describe injected simulator components, not proof that every window independently reveals those components. A clear source-audit class is necessary but not sufficient evidence of real-world identifiability. Active marginal, invisible, unaudited, latent or unassessed injections mask the supervised diagnosis loss. Restricted source episodes, overlapping emitted-tag validity windows and insufficient post-onset context also mask it. A masked target is null, never a healthy negative. The context delay uses the existing 900 s audit convention after the injection ramp, as a conservative reference-model design choice, not a physical detection guarantee.

Forecast targets contain future reported means, observation counts and missing/non-good counts, never future hidden state. Final windows and invalid/restricted forecast intervals are masked. Training must honour each target's `supervised_loss_mask`; null values must not be converted to zero, healthy equipment or an empty fault list. Quality targets remain usable where physical diagnosis targets are masked. No scaler, threshold or imputation policy is fitted on validation/test data by the exporter.

## Splits and repeated records

Completed campaign episodes keep their existing train, validation and test membership. All snapshots of one episode stay together. Inspection children inherit their parent's split, so variants of the same hydraulic trace cannot cross splits. The four incomplete source slots remain gaps in the source manifest; the exporter does not fabricate replacements. The original campaign is fault-enriched and has fixed onset ranges and one-hour episodes; it does not estimate industrial fault prevalence, long-term degradation or deployment performance.

Static reference fixtures for roles 3, 4 and 6 are deduplicated by query within each view. Their public facts can occur in more than one split because the declared plant knowledge is available at inference. They are retrieval/contract fixtures, not independent tests of learned factual recall or novel-equipment generalisation. Do not inflate a training sample count by repeating them for every time window, or score them as independent evidence of diagnostic performance.

## Inspection and mechanical scope

The legacy mechanical extension retains its original archive. Its 3420 performed results are outside their one-hour process coverage and its measurement models are unqualified. Only metadata quality checks are exported from those results; numerical findings and normal/critical condition categories are withheld. Cancellations remain unperformed. The two coupled roof references supply four challenge-only record checks; two contain supported raw manual-level measurements, with condition acceptance still unknown. Challenge references are not training-class balance or validation of industrial roof damage.

Roof, fitting and cascade labels from uncoupled overlays must not supervise physical diagnosis from duplicate hydraulic readings. Native coupled roof constraints remain a bounded reference demonstration; unselected support strength, failure propagation, vent capacity and damaged-emission parameters remain unresolved. Routine EPA vapour estimates are averages under the documented intact/reference assumptions, not instantaneous VOC sensor observations. None of these limitations can be resolved by assigning convenient numbers or converting an unavailable inspection into a normal result.

## Portable layout and use

Build with `python tools/dataset_release.py build --source data/campaign --output data/verum_reference_v1 --workers 3`, then verify with `python tools/dataset_release.py verify data/verum_reference_v1`. Each observation file is copied byte-for-byte, with both compressed-byte and decompressed-content hashes recorded. Source scenarios, labels, fault truth and validity intervals are retained under the evaluator directory for audit, never served as inputs. Shared references and examples are hashed; an incomplete export has a build sentinel and cannot be loaded.

Use `iter_role_examples(root, role_key, split)` or the command's `materialize` subcommand to obtain input/target pairs. Keep validation for model selection and open test targets only for final evaluation. The raw evaluator directory is not an inference or retrieval source. Inspection metadata banks carry their own inherited splits and separate challenge membership. Each pair identifies its use as reference-model supervision or a public-reference fixture.

The export is a bounded reference dataset handoff. It does not alter `assert_training_ready`, manufacture engineering approval or enable production generation. A full industrial training claim still requires the hardware evidence and physical validation described in the hardware resolution document.

## Coupled roof and process-covered inspection references

`roof_reference_v1` selects one healthy source parent per available split and withdrawing-tank cell, using declared modes and a stable identifier ordering. Where a pure-delivery parent exists it takes priority. Cases receiving into the same tank, lineup changes and nonanalytic source episodes are excluded by prospective design. It records every floating-control/held-boundary attempt without replacing rejected cases or selecting only successful inspections. The original source split and parent group are retained for both members of each pair.

The manual-level inspection uses the existing 1800 s request convention and the catalog's worst-case approval, scheduling, task and result delays. The derived process horizon is 7320 s. Each measurement is generated from the actual simulated state during that covered interval. The existing approval emulator can reject the request or a work condition can cancel it; those outcomes remain records. Supported raw measurement does not mean known equipment condition or field-calibrated measurement accuracy.

The held boundary is imposed at initialisation, with a pressure-equalized gas reference and the existing team-selected geometry/mass proxy. It is a left-censored prescribed constraint, not a later observed roof failure. No rupture, secondary failure, damaged-emission or material-strength target is introduced. These reference runs broaden numerical/inspection coverage but do not close the missing vent, structural, fitting or calibration evidence. The output contains actual coupled observations; it does not copy a control's hydraulic trace into a different mechanical label.

```bash
python tools/roof_reference.py --source data/campaign --output data/roof_reference_v1 --workers 3
python tools/dataset_release.py build --source data/campaign --output data/verum_reference_v1 --workers 3
```

The public reference includes the existing tank/roof parameter records and pipe dimensions, routes and source locators. These are declared design specifications, not measured current state. Asset retrieval returns explicit null specifications for assets without such supplied details; it does not manufacture pump curves, maintenance history or hardware ratings.
