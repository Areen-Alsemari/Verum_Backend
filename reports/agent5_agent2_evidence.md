# Agent 5 and the topology residual events of Agent 2: what the citations show

Read-only analysis of the full runner on the 181 windows of `reports/agent2_before_after.md`, with the topology residual Agent 2 and the Agent 5 of this branch. Nothing was changed: not Agent 5, not Agent 2, not the runner. The test split was not opened.

## 1. Scope and definitions

The sample is the one produced by `tools/agents/run_runner_sample.py`: 169 validation windows (87 faulty, 82 fault-free) and 12 train windows (6 and 6), drawn by a seeded stratified sampler. It is not a random sample, so every count below describes this sample. Part 4c is the exception: it uses every validation window with a supervised label (3,484 fault-free and 496 faulty) and the residual code of Agent 2 itself, with no Agent 5 involved. The tables of parts 4a and 4b were computed from the stored bundles of the run; the tables are regenerated with `python tools/agents/agent5_agent2_evidence.py --run <run folder> --out <file>` on a run made with the tag-overlap citation rule that this report describes (the per-event part and the consistency line are defined for that rule). Labels were read for grouping only. No agent saw them.

All 181 windows have Agent 2 status `complete` and coverage `assessed`. Agent 5 produced 92 hypotheses over the sample, and they are the same hypotheses, in the same order, as with the earlier Agent 2.

How Agent 5 uses the Agent 2 report (`_check_anomaly_and_forecast` in the diagnostic reasoning rules):

1. The tags of a hypothesis are the tag of its component, if any, plus the primary tags that Agent 5 keeps for its asset. Its assets are the asset of each component.
2. The report is cited as support when the hypothesis assets or tags overlap the assets or tags of any Agent 2 event, quality events included.
3. Otherwise the report is cited as conflict if it holds at least one event and its coverage is `assessed`. The kind of event is not read.
4. Otherwise it is not cited.

The rule is exclusive, so a report is never cited as both. The column "both" below is zero by construction and is shown because it was asked for. The rule was recomputed from the events and the hypotheses of each window and agrees with the citations in all 92 cases.

A hypothesis "matches an injected fault" when the mechanism and asset of its first component equal a mechanism and asset of an injected component. For a window with several injected components the pairs are the combinations of its mechanisms and assets. Fault-free windows have nothing to match, so their hypotheses are shown on their own row.

Residual events in the sample: R1 40, R2 55, R3 44, R4 4, in 85 of the 181 windows.

## 2. Part 4a: support, conflict, both, neither

| hypotheses | n | support | conflict | both | neither |
|---|---|---|---|---|---|
| matches an injected fault | 33 | 25 (0.76) | 5 (0.15) | 0 (0.00) | 3 (0.09) |
| does not match | 50 | 4 (0.08) | 44 (0.88) | 0 (0.00) | 2 (0.04) |
| fault-free window (no injected fault) | 9 | 1 (0.11) | 6 (0.67) | 0 (0.00) | 2 (0.22) |

By what Agent 2 sent in the window:

| hypotheses | Agent 2 events in the window | n | support | conflict | neither |
|---|---|---|---|---|---|
| matches | residual events | 23 | 22 | 1 | 0 |
| matches | quality events only | 7 | 3 | 4 | 0 |
| matches | no events | 3 | 0 | 0 | 3 |
| does not match | residual events | 41 | 4 | 37 | 0 |
| does not match | quality events only | 7 | 0 | 7 | 0 |
| does not match | no events | 2 | 0 | 0 | 2 |
| fault-free window | residual events | 2 | 1 | 1 | 0 |
| fault-free window | quality events only | 5 | 0 | 5 | 0 |
| fault-free window | no events | 2 | 0 | 0 | 2 |

Observations:

- Hypotheses that match an injected fault cite support in 25 of 33 cases and conflict in 5. Hypotheses that do not match cite conflict in 44 of 50 and support in 4. The citation therefore separates the two groups, with the large exception that follows.
- The eight matching hypotheses without support are: three in windows where Agent 2 sent no event (restriction at XV-R101, XV-S102 and XV-PAI); four in windows where it sent only quality events on unrelated tags (a restriction at XV-PBI, an obstruction and a restriction at XV-R101, and a restriction at XV-S103); and one restriction at XV-R101 in a window whose only residual event was R3, which reads the discharge-side tags. In the quality-only windows the conflict comes from a missing-reading or quality event, not from a residual. Four of the seven matching hypotheses in quality-only windows are in conflict for that reason.
- Among hypotheses that do not match, all seven in quality-only windows cite conflict. In the fault-free windows six of the nine hypotheses cite conflict, five of them in windows whose only events are quality events.
- 53 of the 92 hypotheses name nothing that Agent 5 can compare: 52 have no asset and no tag, and one is a leak at E-PB3, an edge with no primary tags. Agent 2 events never carry an asset, so such a hypothesis cannot be supported by any Agent 2 report. It cites conflict whenever the report holds an event. None of the 33 matching hypotheses is of this kind.

## 3. Part 4b: support and conflict per residual event

An Agent 5 citation refers to the report as a whole. To attribute it to a residual, each hypothesis was paired with each residual event of its window and the pair was classified:

- support from this event: the hypothesis tags overlap the tags of this event (the rule of Agent 5 applied to this event alone);
- support from another event: the report is cited as support, but through another event of the window, possibly a quality event;
- conflict: the report is cited as conflict. This happens only when no event of the report overlaps, so the conflict is shared by every event of the window and is not caused by one residual;
- neither: the report is not cited.

A hypothesis in a window with two residual events appears in two rows. Families follow the mechanism of the first component: pump, restriction (position visible or obstruction), leak, sensor fault (bias, drift, stuck) and misrouting. Counts are pairs, with the share of the row in parentheses.

All hypotheses:

| residual event | hypothesis family | pairs | support from this event | support from another event | conflict | neither |
|---|---|---|---|---|---|---|
| R1 | restriction | 7 | 3 (0.43) | 1 (0.14) | 3 (0.43) | 0 (0.00) |
| R1 | leak | 1 | 0 (0.00) | 0 (0.00) | 1 (1.00) | 0 (0.00) |
| R1 | sensor fault | 20 | 0 (0.00) | 0 (0.00) | 20 (1.00) | 0 (0.00) |
| R2 | pump | 10 | 9 (0.90) | 0 (0.00) | 1 (0.10) | 0 (0.00) |
| R2 | restriction | 6 | 2 (0.33) | 2 (0.33) | 2 (0.33) | 0 (0.00) |
| R2 | leak | 3 | 0 (0.00) | 0 (0.00) | 3 (1.00) | 0 (0.00) |
| R2 | sensor fault | 23 | 3 (0.13) | 0 (0.00) | 20 (0.87) | 0 (0.00) |
| R2 | misrouting | 3 | 3 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| R3 | pump | 2 | 1 (0.50) | 0 (0.00) | 1 (0.50) | 0 (0.00) |
| R3 | restriction | 8 | 4 (0.50) | 2 (0.25) | 2 (0.25) | 0 (0.00) |
| R3 | sensor fault | 13 | 1 (0.08) | 0 (0.00) | 12 (0.92) | 0 (0.00) |
| R3 | misrouting | 1 | 0 (0.00) | 1 (1.00) | 0 (0.00) | 0 (0.00) |
| R4 | restriction | 4 | 3 (0.75) | 0 (0.00) | 1 (0.25) | 0 (0.00) |
| R4 | leak | 2 | 2 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |

Hypotheses that match an injected fault:

| residual event | hypothesis family | pairs | support from this event | support from another event | conflict | neither |
|---|---|---|---|---|---|---|
| R1 | restriction | 3 | 2 (0.67) | 1 (0.33) | 0 (0.00) | 0 (0.00) |
| R2 | pump | 9 | 9 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| R2 | restriction | 3 | 2 (0.67) | 1 (0.33) | 0 (0.00) | 0 (0.00) |
| R2 | sensor fault | 1 | 1 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| R2 | misrouting | 3 | 3 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| R3 | pump | 1 | 1 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| R3 | restriction | 6 | 4 (0.67) | 1 (0.17) | 1 (0.17) | 0 (0.00) |
| R3 | sensor fault | 1 | 1 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |
| R3 | misrouting | 1 | 0 (0.00) | 1 (1.00) | 0 (0.00) | 0 (0.00) |
| R4 | restriction | 3 | 3 (1.00) | 0 (0.00) | 0 (0.00) | 0 (0.00) |

How wide the tag overlap is, taken from the tag registry of Agent 5 and the tags each residual reads (R1: FT-001, FT-201 and the three level transmitters; R2: FT-201, PT-201, the discharge transmitter and the run state of the running pump; R3: FT-201, PT-203, the same discharge transmitter and run state; R4: FT-001 and PT-001). Of the 49 assets and tags that Agent 5 knows, the number whose tags overlap an event of each residual: R1 19, R2 13, R3 12, R4 8. Twenty-three of the 49, the pipe edges other than E001 to E003, E-D1 and E-D2, have no primary tags and overlap none.

Observations:

- R2 events support pump hypotheses in 9 of 10 pairs, all nine from matching hypotheses. The tenth is a non-matching pump hypothesis in conflict.
- R1 events give no support to sensor-fault hypotheses (0 of 20) and none to the single leak hypothesis. R1 supports restriction hypotheses in 3 of 7 pairs, through shared tags (the primary tags of the receipt and tank-outlet valves include FT-001, FT-201 or a level transmitter), not through a physical link between a mass imbalance and a restriction.
- R2 supports all three misrouting pairs, all of them matching. The valve XV-PBI keeps PT-201 and PT-202B among its primary tags, which R2 reads. Part 4c shows that misrouting is not expected to move any residual, so this support comes from the tag lists.
- R4 events, four in all, support restriction in 3 of 4 pairs and leak in 2 of 2.
- Because a residual event carries every tag the residual reads, a hypothesis that shares any one of them is supported. FT-201 is read by R1, R2 and R3, so every asset whose primary tags include FT-201 (both pumps, the tank-outlet valves, the pump valves, E-D1) is supported by any of the three. The support is a statement about tag overlap, not about which residual moved.

## 4. Part 4c: which residuals physics says should fire

### 4.1 Expectations from the topology

The sets below were written from the single-line layout (receipt meter FT-001, receipt line with PT-001, tank branches, suction header with PT-201, two pump branches with discharge transmitters PT-202A and PT-202B, discharge header with PT-203, delivery meter FT-201) and from the definitions of the four residuals, before any window was scored. They agree with the signature matrix of `reports/detector_v3_c3_characterisation.md` where that matrix is distinct (pump head loss on R2, drift on R1). A loss that lies upstream of PT-201 shifts the pressures downstream of it together, so none of the four pressure differences sees it. A loss between two measured points changes the residual that spans them. The tag-to-location mapping is unverified (see the characterisation report), and the sets rest on the order of transmitters along the line.

| Fault | Expected to move | Reason |
|---|---|---|
| Pump head loss, pump running | R2 | The pressure rise across the pump falls at the delivery flow. The drop to the header (R3) is unchanged to first order. |
| Restriction at a receipt-side valve (XV-R000, XV-R101 to XV-R103) | R4 | The loss lies between the receipt header and the tank, upstream of PT-001. |
| Restriction at a tank-outlet valve (XV-S101 to XV-S103) | none | The loss lies upstream of PT-201 and shifts all later pressures together. |
| Restriction at a pump inlet valve (XV-PAI, XV-PBI), pump running | R2 | The valve lies between the suction header and the pump discharge transmitter. |
| Restriction at a pump outlet valve (XV-PAO, XV-PBO), pump running | R3 | The valve lies between the pump discharge transmitter and the discharge header. |
| Leak between the two meters | R1 | The receipt flow minus the delivery flow no longer equals the change of inventory. A pressure effect may follow, but the mass balance is the direct one. |
| Leak on E001 or E-D2 | none | These edges lie outside the interval between the two meters. |
| Misrouting (valve forced open) | none | A valve forced open on a branch that was closed adds a parallel or dead path whose flows are measured by the same meters. The change shows on the valve contact, which Agent 2 does not read. |
| Sensor fault on FT-001 | R1 and R4 | The receipt flow enters the mass balance and the receipt line fit. |
| Sensor fault on FT-201 | R1, R2 and R3 | The delivery flow enters all three. |
| Sensor fault on PT-001, PT-201, PT-203 | R4, R2, R3 respectively | Each transmitter enters one residual. |
| Sensor fault on PT-202A or PT-202B, that pump running | R2 and R3 | The discharge transmitter enters both. |
| Level transmitter: drift or stuck | R1 | The mass balance uses the slope of the level. |
| Level transmitter: bias | none | A constant offset has no slope. |

Windows with several injected components (44 in validation) have no single expectation and are left out. The first run grouped all pressure transmitters and both flow transmitters in one row each; the grouping was corrected to one row per tag without changing any expected set.

A fault on an asset that is not active in the lineup changes nothing the residuals can see. The activity label is kept in files that were not opened here. Two cases are handled from the window itself: for a fault on a pump branch or a pump discharge transmitter, the window counts only if that pump is running (the number in the column "fault active"). A fault on an idle tank branch cannot be separated, so such windows count as misses where they occur. The expected-computable column counts windows where every residual of the expected set could be computed.

### 4.2 Fault-free reference

Fault-free validation windows, each residual against its own threshold, and the share of windows in which any residual exceeds:

| fault-free validation windows | exceed | computable | rate (95% interval) |
|---|---|---|---|
| R1 | 143 | 3484 | 143/3484 = 0.041 (0.035 to 0.048) |
| R2 | 314 | 3136 | 314/3136 = 0.100 (0.090 to 0.111) |
| R3 | 322 | 3136 | 322/3136 = 0.103 (0.093 to 0.114) |
| R4 | 50 | 3484 | 50/3484 = 0.014 (0.011 to 0.019) |
| any residual | 557 | 3484 | 557/3484 = 0.160 (0.148 to 0.172) |

### 4.3 Whether the expectation holds

Validation windows with a single injected component. "At least one expected exceeds" and "all expected exceed" refer to the expected set; "a residual outside the expected set exceeds" counts windows where some other residual does, with the same rate on fault-free windows for comparison (restricted to windows where the expected residuals could be computed). For rows with no expected residual the outside column is the rate of any residual.

| family | subgroup | expected | windows | fault active | expected computable | at least one expected exceeds | all expected exceed | a residual outside the expected set exceeds | same, fault-free windows |
|---|---|---|---|---|---|---|---|---|---|
| pump | pump head loss | R2 | 72 | 72 | 72 | 72/72 = 1.000 (0.949 to 1.000) | same | 8/72 = 0.111 (0.057 to 0.204) | 373/3136 = 0.119 (0.108 to 0.131) |
| restriction | restriction, pump inlet valve | R2 | 50 | 50 | 50 | 44/50 = 0.880 (0.762 to 0.944) | same | 7/50 = 0.140 (0.070 to 0.262) | 373/3136 = 0.119 (0.108 to 0.131) |
| restriction | restriction, pump outlet valve | R3 | 67 | 67 | 67 | 58/67 = 0.866 (0.764 to 0.928) | same | 9/67 = 0.134 (0.072 to 0.236) | 352/3136 = 0.112 (0.102 to 0.124) |
| restriction | restriction, receipt-side valve | R4 | 4 | 4 | 4 | 0/4 = 0.000 (0.000 to 0.490) | same | 1/4 = 0.250 (0.046 to 0.699) | 509/3484 = 0.146 (0.135 to 0.158) |
| restriction | restriction, tank-outlet valve | none | 35 | 35 | 35 | n/a | n/a | 8/35 = 0.229 (0.121 to 0.390) | 557/3484 = 0.160 (0.148 to 0.172) |
| leak | leak between the two meters | R1 | 54 | 54 | 54 | 43/54 = 0.796 (0.671 to 0.882) | same | 29/54 = 0.537 (0.406 to 0.663) | 500/3484 = 0.144 (0.132 to 0.156) |
| leak | leak outside the mass balance | none | 3 | 3 | 3 | n/a | n/a | 0/3 = 0.000 (0.000 to 0.562) | 557/3484 = 0.160 (0.148 to 0.172) |
| sensor fault | sensor bias, PT-001 | R4 | 6 | 6 | 6 | 1/6 = 0.167 (0.030 to 0.564) | same | 0/6 = 0.000 (0.000 to 0.390) | 509/3484 = 0.146 (0.135 to 0.158) |
| sensor fault | sensor bias, PT-201 | R2 | 6 | 6 | 6 | 6/6 = 1.000 (0.610 to 1.000) | same | 1/6 = 0.167 (0.030 to 0.564) | 373/3136 = 0.119 (0.108 to 0.131) |
| sensor fault | sensor bias, PT-202A | R2, R3 | 17 | 12 | 12 | 12/12 = 1.000 (0.757 to 1.000) | 12/12 = 1.000 (0.757 to 1.000) | 0/12 = 0.000 (0.000 to 0.243) | 119/3136 = 0.038 (0.032 to 0.045) |
| sensor fault | sensor bias, PT-202B | R2, R3 | 11 | 4 | 4 | 4/4 = 1.000 (0.510 to 1.000) | 4/4 = 1.000 (0.510 to 1.000) | 0/4 = 0.000 (0.000 to 0.490) | 119/3136 = 0.038 (0.032 to 0.045) |
| sensor fault | sensor bias, PT-203 | R3 | 9 | 9 | 9 | 9/9 = 1.000 (0.701 to 1.000) | same | 1/9 = 0.111 (0.020 to 0.435) | 352/3136 = 0.112 (0.102 to 0.124) |
| sensor fault | sensor bias, level transmitter | none | 20 | 20 | 20 | n/a | n/a | 3/20 = 0.150 (0.052 to 0.360) | 557/3484 = 0.160 (0.148 to 0.172) |
| sensor fault | sensor drift, FT-001 | R1, R4 | 31 | 31 | 31 | 23/31 = 0.742 (0.568 to 0.863) | 0/31 = 0.000 (0.000 to 0.110) | 2/31 = 0.065 (0.018 to 0.207) | 450/3484 = 0.129 (0.118 to 0.141) |
| sensor fault | sensor drift, level transmitter | R1 | 19 | 19 | 19 | 19/19 = 1.000 (0.832 to 1.000) | same | 2/19 = 0.105 (0.029 to 0.314) | 500/3484 = 0.144 (0.132 to 0.156) |
| sensor fault | sensor stuck, FT-201 | R1, R2, R3 | 15 | 15 | 15 | 15/15 = 1.000 (0.796 to 1.000) | 12/15 = 0.800 (0.548 to 0.930) | 0/15 = 0.000 (0.000 to 0.204) | 7/3136 = 0.002 (0.001 to 0.005) |
| sensor fault | sensor stuck, PT-202A | R2, R3 | 5 | 5 | 5 | 5/5 = 1.000 (0.566 to 1.000) | 5/5 = 1.000 (0.566 to 1.000) | 0/5 = 0.000 (0.000 to 0.434) | 119/3136 = 0.038 (0.032 to 0.045) |
| sensor fault | sensor stuck, level transmitter | R1 | 13 | 13 | 13 | 13/13 = 1.000 (0.772 to 1.000) | same | 3/13 = 0.231 (0.082 to 0.503) | 500/3484 = 0.144 (0.132 to 0.156) |
| misrouting | misrouting (valve forced open) | none | 15 | 15 | 15 | n/a | n/a | 4/15 = 0.267 (0.109 to 0.520) | 557/3484 = 0.160 (0.148 to 0.172) |

Rate of each residual in the same windows:

| family | subgroup | expected | windows | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|---|---|
| pump | pump head loss | R2 | 72 | 2/72 = 0.028 (0.008 to 0.096) | 72/72 = 1.000 (0.949 to 1.000) | 8/72 = 0.111 (0.057 to 0.204) | 0/72 = 0.000 (0.000 to 0.051) |
| restriction | restriction, pump inlet valve | R2 | 50 | 2/50 = 0.040 (0.011 to 0.135) | 44/50 = 0.880 (0.762 to 0.944) | 7/50 = 0.140 (0.070 to 0.262) | 0/50 = 0.000 (0.000 to 0.071) |
| restriction | restriction, pump outlet valve | R3 | 67 | 2/67 = 0.030 (0.008 to 0.102) | 9/67 = 0.134 (0.072 to 0.236) | 58/67 = 0.866 (0.764 to 0.928) | 0/67 = 0.000 (0.000 to 0.054) |
| restriction | restriction, receipt-side valve | R4 | 4 | 0/4 = 0.000 (0.000 to 0.490) | 0/4 = 0.000 (0.000 to 0.490) | 1/4 = 0.250 (0.046 to 0.699) | 0/4 = 0.000 (0.000 to 0.490) |
| restriction | restriction, tank-outlet valve | none | 35 | 2/35 = 0.057 (0.016 to 0.186) | 5/35 = 0.143 (0.063 to 0.294) | 6/35 = 0.171 (0.081 to 0.327) | 0/35 = 0.000 (0.000 to 0.099) |
| leak | leak between the two meters | R1 | 54 | 43/54 = 0.796 (0.671 to 0.882) | 27/49 = 0.551 (0.413 to 0.681) | 18/49 = 0.367 (0.247 to 0.507) | 0/54 = 0.000 (0.000 to 0.066) |
| leak | leak outside the mass balance | none | 3 | 0/3 = 0.000 (0.000 to 0.562) | 0/0 | 0/0 | 0/3 = 0.000 (0.000 to 0.562) |
| sensor fault | sensor bias, PT-001 | R4 | 6 | 0/6 = 0.000 (0.000 to 0.390) | 0/1 = 0.000 (0.000 to 0.793) | 0/1 = 0.000 (0.000 to 0.793) | 1/6 = 0.167 (0.030 to 0.564) |
| sensor fault | sensor bias, PT-201 | R2 | 6 | 0/6 = 0.000 (0.000 to 0.390) | 6/6 = 1.000 (0.610 to 1.000) | 1/6 = 0.167 (0.030 to 0.564) | 0/6 = 0.000 (0.000 to 0.390) |
| sensor fault | sensor bias, PT-202A | R2, R3 | 12 | 0/12 = 0.000 (0.000 to 0.243) | 12/12 = 1.000 (0.757 to 1.000) | 12/12 = 1.000 (0.757 to 1.000) | 0/12 = 0.000 (0.000 to 0.243) |
| sensor fault | sensor bias, PT-202B | R2, R3 | 4 | 0/4 = 0.000 (0.000 to 0.490) | 4/4 = 1.000 (0.510 to 1.000) | 4/4 = 1.000 (0.510 to 1.000) | 0/4 = 0.000 (0.000 to 0.490) |
| sensor fault | sensor bias, PT-203 | R3 | 9 | 0/9 = 0.000 (0.000 to 0.299) | 1/9 = 0.111 (0.020 to 0.435) | 9/9 = 1.000 (0.701 to 1.000) | 0/9 = 0.000 (0.000 to 0.299) |
| sensor fault | sensor bias, level transmitter | none | 20 | 2/20 = 0.100 (0.028 to 0.301) | 3/20 = 0.150 (0.052 to 0.360) | 3/20 = 0.150 (0.052 to 0.360) | 0/20 = 0.000 (0.000 to 0.161) |
| sensor fault | sensor drift, FT-001 | R1, R4 | 31 | 23/31 = 0.742 (0.568 to 0.863) | 1/27 = 0.037 (0.007 to 0.183) | 1/27 = 0.037 (0.007 to 0.183) | 0/31 = 0.000 (0.000 to 0.110) |
| sensor fault | sensor drift, level transmitter | R1 | 19 | 19/19 = 1.000 (0.832 to 1.000) | 2/15 = 0.133 (0.037 to 0.379) | 1/15 = 0.067 (0.012 to 0.298) | 0/19 = 0.000 (0.000 to 0.168) |
| sensor fault | sensor stuck, FT-201 | R1, R2, R3 | 15 | 12/15 = 0.800 (0.548 to 0.930) | 15/15 = 1.000 (0.796 to 1.000) | 15/15 = 1.000 (0.796 to 1.000) | 0/15 = 0.000 (0.000 to 0.204) |
| sensor fault | sensor stuck, PT-202A | R2, R3 | 5 | 0/5 = 0.000 (0.000 to 0.434) | 5/5 = 1.000 (0.566 to 1.000) | 5/5 = 1.000 (0.566 to 1.000) | 0/5 = 0.000 (0.000 to 0.434) |
| sensor fault | sensor stuck, level transmitter | R1 | 13 | 13/13 = 1.000 (0.772 to 1.000) | 3/13 = 0.231 (0.082 to 0.503) | 2/13 = 0.154 (0.043 to 0.422) | 0/13 = 0.000 (0.000 to 0.228) |
| misrouting | misrouting (valve forced open) | none | 15 | 0/15 = 0.000 (0.000 to 0.204) | 4/15 = 0.267 (0.109 to 0.520) | 1/15 = 0.067 (0.012 to 0.298) | 0/15 = 0.000 (0.000 to 0.204) |

Observations:

- The expectation holds where the fault sits between two measured points of the pump branch: pump head loss 72 of 72 for R2, pump inlet valve 44 of 50 for R2, pump outlet valve 58 of 67 for R3. Residuals outside the expected one stay near the fault-free rates (R3 in pump head loss 0.111 against 0.103; R2 in outlet-valve restriction 0.134 against 0.100).
- Sensor faults on pressure transmitters on the pump branch behave as expected (PT-201 6 of 6, PT-202A 12 of 12, PT-202B 4 of 4, PT-203 9 of 9), as do level-transmitter drift and stuck on R1 (19 of 19 and 13 of 13) and a stuck delivery meter (15 of 15 for at least one, 12 of 15 for all three). A bias on PT-001 reaches R4 in 1 of 6 windows.
- A drift on FT-001 reaches R1 in 23 of 31 windows and R4 in none, so "all expected" is 0 of 31: the receipt line fit does not see it.
- A leak between the meters exceeds R1 in 43 of 54 windows (0.80). R2 also exceeds in 0.55 of the windows where it is computable and R3 in 0.37, against 0.10 fault-free; the leak moves pressures as well, so R2 and R3 are not free of leaks, and a residual outside the expected set is not evidence against the leak.
- Restriction at a receipt-side valve is the weak case: R4 exceeds in 0 of 4 windows. The count is small.
- Where no residual is expected, the rate of any residual is close to the fault-free rate: tank-outlet valve restriction 8 of 35 (0.23, interval 0.12 to 0.39) against 0.16; level-transmitter bias 3 of 20 (0.15); misrouting 4 of 15 (0.27, interval 0.11 to 0.52), all four through R2. All three intervals include the fault-free rate, so these samples do not separate them from it.

## 5. Reading the numbers

- The 181 windows are a stratified sample. The shares in parts 4a and 4b are shares of 92 hypotheses and of small cell counts, several below ten, and carry no interval. Part 4c uses the full validation split and gives 95% Wilson intervals over windows; windows of one episode are correlated, so these intervals are narrower than an interval over episodes would be.
- The hypotheses of Agent 5 (identifiers, assets and order) were identical with the earlier Agent 2 in all 181 windows, so a change between Agent 2 versions shows in how the report is cited, not in which hypotheses are proposed.
- The comparison with the physical expectation uses the mapping of transmitters to locations that the declared reference does not verify. A different location of PT-202 or PT-201 would change the sets for pump valves and pressure transmitters.
- The citation rule of Agent 5 reads tags and assets, not residuals, and an event of any kind with no overlap counts as conflict in an assessed report. The findings in 4a (quality-only windows) and 4b (shared tags, edges without tags, hypotheses without an asset) follow from that rule and from the tag registry, and none was tuned or changed here.
