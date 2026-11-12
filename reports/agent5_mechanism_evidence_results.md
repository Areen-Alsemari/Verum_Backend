# Agent 5 compares the Agent 2 report by mechanism: before and after

Agent 5 used to cite the Agent 2 report as support or conflict by tag overlap between the hypothesis and the events (`reports/agent5_agent2_evidence.md`). It now reads the window assessment of the report instead: a state for each of the four residuals and whether the window was complete. The change is confined to Agent 5. Hypothesis ids, components and scores are untouched: they are identical in all 181 windows (92 hypotheses) before and after. Only the support and conflict lists, the unresolved questions and the anomaly check change.

## 1. The rule

- Each hypothesis belongs to a family with a fixed set of expected residuals, written from the topology and fixed in `mechanism.py` before any scoring (section 4c of the evidence report). The validation figure is the share of validation windows with that fault in which the expected residual exceeded.

| family | expected residual | reliable | validation figure |
|---|---|---|---|
| pump head loss | R2 | yes | 72 of 72 |
| restriction at a pump inlet valve | R2 | yes | 44 of 50 |
| restriction at a pump outlet valve | R3 | yes | 58 of 67 |
| restriction at a receipt-side valve | R4 | no | 0 of 4 |
| restriction at a tank-outlet valve | none | no | - |
| leak between the two meters | R1 | no | 43 of 54 |
| leak on E001 or E-D2 | none | no | - |
| flow-meter sensor fault (FT-001, FT-201) | R1 | no | drift 23 of 31 on FT-001, stuck 15 of 15 on FT-201 |
| level-sensor drift or stuck | R1 | no | 19 of 19 and 13 of 13 |
| level-sensor bias | none | no | - |
| valve misrouting | none | no | - |

- Support: an expected residual is exceeded.
- Conflict: every expected residual is within normal, the window assessment is complete, and the family is reliable. Only the three pump families are.
- Everything else is unknown, with no support, no conflict and an unresolved question: an expected residual is unknown, the family has no expected residual, the hypothesis maps to no family (no asset, several components, a pressure transmitter), or the report has no usable window assessment. In an unreliable family the question says that the absence of the residual is weak evidence.
- Quality events and tag-less events never support or conflict. A quality event that names a tag the hypothesis relies on adds a data-quality caveat and keeps silence from becoming a conflict.
- The anomaly check in `upstream_checks` follows the citations (fail on any conflict, pass on any support) and is unknown without a usable window assessment.

## 2. Before and after on the same 181 windows

The sample is the one of `reports/agent2_before_after.md`: 169 validation windows and 12 train windows, one run per window with the full runner. Before is the branch without this change (Agent 5 as merged from `dev`, with the tag-overlap rule); after is this branch. `verify_bundle` passes in 181 of 181 windows before and after, a final report is built in 181 of 181, and the test split was not opened.

Citation of the Agent 2 report, by match with an injected fault:

| hypotheses | n | support before | support after | conflict before | conflict after | neither before | neither after |
|---|---|---|---|---|---|---|---|
| matches an injected fault | 33 | 25 | 16 | 5 | 2 | 3 | 15 |
| does not match | 50 | 4 | 1 | 44 | 0 | 2 | 49 |
| fault-free window | 9 | 1 | 0 | 6 | 0 | 2 | 9 |

Stop rule: matching hypotheses cite 2 conflicts after against 5 before, and non-matching hypotheses cite 1 support after against 4 before. Neither condition for stopping holds. This is not an improvement overall, because the change trades sensitivity for specificity:

- Support on matching hypotheses falls from 25 to 16 of 33, and conflict on non-matching hypotheses falls from 44 to 0 of 50. The tag-overlap conflict was noisy (it also fell on 5 matching hypotheses) but it separated the two groups; the new conflict channel is almost silent.
- Both conflicts that remain are on matching hypotheses: restrictions at pump valves in windows where the expected residual stayed within normal (the 12 to 13 percent of validation windows in which it does). On this sample the new rule gives no correct conflict.
- Matching hypotheses by family after: pump 9 of 9 supported; restriction 7 supported, 2 in conflict and 8 neither of 17; sensor fault 0 of 1; misrouting 0 of 6, which have no expected residual by design. Non-matching: 1 support (a pump hypothesis for the pump that was not faulted, since R2 does not say which pump), the rest neither.
- Unresolved questions added: 55 for hypotheses that map to no family, 11 for families with no expected residual, 7 for silence of an unreliable family, and 7 data-quality caveats.

Anomaly check of Agent 5 (`upstream_checks`): pass in 181 windows before; after, unknown in 162, pass in 17 and fail in 2.

Agent 8, from the diagnosis report it receives:

| | before | after |
|---|---|---|
| conflict entries | 61 | 14 |
| of which cite the Agent 2 report | 55 | 4 |
| windows with at least one conflict entry | 52 | 9 |
| decision state | more_evidence_required in 181 | more_evidence_required in 181 |

The four entries that cite the Agent 2 report are the 2 conflicts on matching hypotheses and the 2 failed anomaly checks. The responses of Agents 1, 3, 4, 6 and 7 are identical in all 181 windows; Agent 5 differs in 178 windows and Agent 8 in 50, because of the lists above.

## 3. What this check is

This is a development check on validation windows and 12 train windows, not an independent test. The expectation sets were written from the topology and fixed before any scoring. The choice of which families are reliable used the validation recall of the evidence report, so the sample that is scored here is the sample that informed that choice. The sample is stratified, not random, and the cells are small.

## 4. Differences from the request and tests

- The level-sensor bias family has no expected residual (a constant offset has no slope, section 4c), where the request listed bias with drift and stuck. Pressure-transmitter sensor faults are not mapped, because the request listed flow meters and level sensors only.
- Four earlier Agent 5 tests encoded the replaced tag-overlap rule (support from an event naming the asset, conflict from an event naming other tags, tag-based quality events, and the pump support in the upstream rules test). They were rewritten to state the new behaviour, not deleted: the same scenarios now give neither support nor conflict, or support through the window assessment. The test for a tag-less event is unchanged.
- The new tests are in `test_diagnostic_reasoning_mechanism.py` (29 cases). A mutation check on a scratch copy applied 13 changes, among them flipping support and conflict, dropping the reliable-family condition, treating unknown as within normal, reading quality events, ignoring the complete flag and accepting wrong residual identifiers; all 13 were caught by the tests.
- Persistence and `recent_anomaly_assessments` are not used, and Agent 8 is unchanged.
