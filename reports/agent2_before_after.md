# Agent 2 before and after: the same 181 validation and train windows through the full runner

The full runner, with `verify_bundle` and the final report, was run twice on the same sample: once with the random forest in Agent 2 (the state of this branch before Agent 2 was changed) and once with the topology residual detector. Nothing else differs between the two runs: the other seven agents, the runner, the contracts and the sample are the same. Labels were read from the sample for grouping only; no agent saw them. The test split was not opened in either run.

The sample is the one used for the earlier end-to-end baseline: 169 validation windows (87 faulty, 82 fault-free) and 12 train windows (6 and 6), drawn by a seeded stratified sampler. It is not a random sample of windows, so the rates below are rates within each class of this sample and are not the rates of the full validation split. The comparison table is written by `tools/agents/compare_agent2_runs.py` from the two output folders.

The Agent 5 in both runs is the one on this branch. The change on the branch `baseline-fixes` (events that name no tag or asset count as neither support nor conflict) is not merged here. It would matter only for the old Agent 2, whose model event names no tag; every residual event of the new Agent 2 names tags.

## (a) Pipeline health

| measure | old Agent 2 | new Agent 2 |
|---|---|---|
| windows run | 181 | 181 |
| crashes | 0 | 0 |
| verify_bundle ok | 181 | 181 |
| final report built | 181 | 181 |
| runner issues | 0 | 0 |
| seconds per window | 2.04 | 2.0 |
| test-split files touched | 0 | 0 |

| role | old status counts | new status counts |
|---|---|---|
| anomaly_detection | complete 181 | complete 181 |
| diagnostic_reasoning | degraded 181 | degraded 181 |
| inspection_planning | degraded 181 | degraded 181 |
| evidence_verification_decision | degraded 181 | degraded 181 |

Final assessment state, old: more_evidence_required 181. New: more_evidence_required 181.

## (b) Agent 2 events

Old Agent 2:

| windows | any model event | tagless model event | quality event | status |
|---|---|---|---|---|
| validation, fault-free | 77/82 = 0.939 (0.865 to 0.974) | 77/82 = 0.939 (0.865 to 0.974) | 68/82 = 0.829 (0.734 to 0.895) | complete 82 |
| validation, faulty | 86/87 = 0.989 (0.938 to 0.998) | 86/87 = 0.989 (0.938 to 0.998) | 67/87 = 0.770 (0.671 to 0.846) | complete 87 |
| train_sanity, fault-free | 3/6 = 0.500 (0.188 to 0.812) | 3/6 = 0.500 (0.188 to 0.812) | 5/6 = 0.833 (0.436 to 0.970) | complete 6 |
| train_sanity, faulty | 6/6 = 1.000 (0.610 to 1.000) | 6/6 = 1.000 (0.610 to 1.000) | 3/6 = 0.500 (0.188 to 0.812) | complete 6 |

New Agent 2:

| windows | any model event | tagless model event | quality event | status |
|---|---|---|---|---|
| validation, fault-free | 15/82 = 0.183 (0.114 to 0.280) | 0/82 = 0.000 (0.000 to 0.045) | 68/82 = 0.829 (0.734 to 0.895) | complete 82 |
| validation, faulty | 66/87 = 0.759 (0.659 to 0.836) | 0/87 = 0.000 (0.000 to 0.042) | 67/87 = 0.770 (0.671 to 0.846) | complete 87 |
| train_sanity, fault-free | 0/6 = 0.000 (0.000 to 0.390) | 0/6 = 0.000 (0.000 to 0.390) | 5/6 = 0.833 (0.436 to 0.970) | complete 6 |
| train_sanity, faulty | 4/6 = 0.667 (0.300 to 0.903) | 0/6 = 0.000 (0.000 to 0.390) | 3/6 = 0.500 (0.188 to 0.812) | complete 6 |

New Agent 2: window score above the pinned threshold, and residual events by key.

| windows | n | window score exceeded | residual events |
|---|---|---|---|
| validation, fault-free | 82 | 13/82 = 0.159 (0.095 to 0.253) | R1 5, R2 11, R3 12, R4 1 |
| validation, faulty | 87 | 64/87 = 0.736 (0.634 to 0.817) | R1 35, R2 42, R3 29, R4 2 |
| train_sanity, fault-free | 6 | 0/6 = 0.000 (0.000 to 0.390) | R1 0, R2 0, R3 0, R4 0 |
| train_sanity, faulty | 6 | 2/6 = 0.333 (0.097 to 0.700) | R1 0, R2 2, R3 3, R4 1 |

## (c) What Agent 5 does with the events

| comparison | windows |
|---|---|
| windows with an Agent 5 report in both runs | 181 |
| identical hypothesis identifiers, same order | 181 |
| same hypotheses (mechanism and asset), any order | 181 |
| same hypotheses in the same ranked order | 181 |

Hypotheses that cite the Agent 2 report, old Agent 2:

| windows | hypotheses | support | conflict | neither |
|---|---|---|---|---|
| validation, fault-free | 9 | 0 | 9 | 0 |
| validation, faulty | 77 | 9 | 68 | 0 |
| train_sanity, fault-free | 0 | 0 | 0 | 0 |
| train_sanity, faulty | 6 | 2 | 4 | 0 |

New Agent 2:

| windows | hypotheses | support | conflict | neither |
|---|---|---|---|---|
| validation, fault-free | 9 | 1 | 6 | 2 |
| validation, faulty | 77 | 24 | 49 | 4 |
| train_sanity, fault-free | 0 | 0 | 0 | 0 |
| train_sanity, faulty | 6 | 5 | 0 | 1 |

Faulty windows only, by whether the hypothesis matches an injected fault, old:

| hypothesis | hypotheses | support | conflict | neither |
|---|---|---|---|---|
| matches an injected fault | 33 | 9 | 24 | 0 |
| does not match | 50 | 2 | 48 | 0 |

New:

| hypothesis | hypotheses | support | conflict | neither |
|---|---|---|---|---|
| matches an injected fault | 33 | 25 | 5 | 3 |
| does not match | 50 | 4 | 44 | 2 |

By the events Agent 2 sent and its coverage, old:

| events | coverage | hypotheses | support | conflict | neither |
|---|---|---|---|---|---|
| quality events | assessed | 1 | 0 | 1 | 0 |
| tagless model event | assessed | 25 | 0 | 25 | 0 |
| tagless model event + quality events | assessed | 66 | 11 | 55 | 0 |

New:

| events | coverage | hypotheses | support | conflict | neither |
|---|---|---|---|---|---|
| no events | assessed | 7 | 0 | 0 | 7 |
| quality events | assessed | 19 | 3 | 16 | 0 |
| tagged residual events | assessed | 18 | 8 | 10 | 0 |
| tagged residual events + quality events | assessed | 48 | 19 | 29 | 0 |

## Reading

- **Pipeline health is unchanged.** 181 of 181 windows pass `verify_bundle` and build a final report in both runs, with no crash and no runner issue. Agent 2 returns `complete` for all 181 windows in both runs, because every residual that applies to a window could be computed; the degraded and insufficient-evidence paths are exercised by the unit tests and not by this sample. Agent 5, Agent 6 and Agent 8 return the same statuses, and every final assessment is `more_evidence_required` in both runs.
- **The event rate changes from almost everything to a minority of fault-free windows.** The forest raised its model event in 0.939 of fault-free and 0.989 of faulty validation windows. The new Agent 2 raises a residual event in 0.183 of fault-free and 0.759 of faulty validation windows, and its window score is above the pinned threshold in 0.159 and 0.736. The fault-free exceedance here is above the 0.080 measured on the whole validation split at the same threshold because the sample is stratified, not random. Quality events are unchanged: they come from the same rules and appear in most windows of both classes.
- **Agent 5 forms the same hypotheses.** In all 181 windows the hypothesis identifiers, mechanisms, assets and ranked order are identical. Agent 2 changes only whether its report is cited as support or conflict.
- **Agent 5 does treat a tagged event that does not overlap a hypothesis as a conflict.** The rule is in `_check_anomaly_and_forecast` of its rules module: if the tags or assets of the Agent 2 events overlap those of the hypothesis, the Agent 2 report is cited as support; otherwise, if there are any events and the coverage is `assessed`, it is cited as conflict. The rule does not look at the kind of event, so a quality event (a missing reading or a bad-quality flag on some tag) counts the same as a residual event. The only ways to avoid a conflict from non-overlapping events are coverage `partial`, which the new Agent 2 returns when a residual is unknown, and sending no events.
- **How often.** With the new Agent 2, 92 hypotheses cite its report: 30 as support, 55 as conflict, 7 as neither (the 7 are in windows with no event at all). Of the 66 hypotheses in windows where Agent 2 sent tagged residual events, 27 cite support and 39 cite conflict. Of the 19 hypotheses in windows with quality events only, 3 cite support and 16 cite conflict. With the forest, 11 cited support and 81 conflict, because its single event names no tag.
- **The conflicts now separate correct from incorrect hypotheses.** In faulty windows, the 33 hypotheses that match an injected fault cite support 25 times and conflict 5 times; the 50 that do not match cite support 4 times and conflict 44 times. With the forest the matching hypotheses cited conflict in 24 of 33. This is a count on a small stratified sample and says nothing about how Agent 5 should weigh the evidence.
- **The remaining cost of the rule.** 5 of 33 matching hypotheses still cite conflict (a residual event that names tags the hypothesis does not use), and 16 conflicts come from quality events alone. Agent 5 was not changed.
