# Verum supported project scope

Verum is an eight-role advisory system for selected hydraulic and sensor faults in a representative simulated gasoline terminal. The data supports development and bounded evaluation; passing software tests is not field qualification. No agent implementation or model training is part of the data pipeline.

## Included capabilities

| Logical agent | Supported data and evaluation task |
| --- | --- |
| Predictive Health | Forecast reported signals and describe observed trends; preserve missing readings and quality flags. |
| Anomaly Detection | Detect observed quality events and evaluate eligible hydraulic/sensor reference injections under explicit loss masks. |
| Topology & Dependency | Retrieve declared connectivity and asset dependencies; retain ambiguity between command, contact and actual position. |
| Historical & Asset Intelligence | Retrieve source-bearing design specifications and available simulated records; state explicitly when history is absent. |
| Diagnostic Reasoning | Compare supported hydraulic/sensor hypotheses, including simultaneous independent injections; retain alternatives and unknowns. |
| Inspection Planning | Retrieve applicable actions, prerequisites, cost, duration and measurement limitations; compare feasible options without fabricated optimal-action labels. |
| Inspection Quality & Documentation | Check record completeness, units, workflow ordering, process coverage and uncertainty metadata. |
| Evidence Verification & Decision | Check availability time, provenance, conflicts and evidence sufficiency for human review. |

The supervised mechanisms are pipe leaks, position-visible and obstruction restrictions, pump head degradation, sensor bias/drift/stuck readings and eligible misrouting-(a) cases. Sparse mechanisms have limited evaluation coverage; misrouting-(b) physical diagnosis is excluded. Multiple independently injected faults and their simulated interactions are included, without claiming one fault caused another.

Normal-operation vapour estimates remain supported calculations under their explicit input and time-window assumptions. Coupled floating/held-roof runs remain bounded initial-constraint reference experiments, with process-covered manual measurements. Neither is a structural-failure training label or an instantaneous VOC measurement.

## Excluded capabilities

- Roof rupture, support failure, material tearing and hardware-specific structural failure prediction.
- Damaged-seal or damaged-fitting emissions, or inferred emission increases from an arbitrary severity multiplier.
- Mechanical fault-to-fault cascades without a supported component failure criterion and load path.
- Remaining useful life, field-qualified equipment acceptance and automatic process/maintenance control.
- Detection of uncoupled mechanical overlays from unchanged hydraulic observations.
- Physical inspection measurements outside process coverage, with invalid timing, incomplete metrics or incompatible units.

The scope contract is versioned in `config/extensions/project_scope_v1.json`. A clear visibility label cannot override this contract. Excluded targets are unknown and masked rather than healthy negatives. The original research archives remain available for audit but are not automatic training inputs. Changing scope does not silently certify or repair those archives.

## Acceptance of a supported release

Every model input must remain causal, every target must be separate, every parent-related case must retain one split, and missing or unsupported evidence must not become an equipment-condition conclusion. The release and all 24 role/split files must pass integrity checks. Physical qualification and production gates stay separate and closed. Metrics must state the evaluated mechanism, visibility class, operating conditions and sample coverage; static public-reference fixtures are not independent diagnostic tests.
