# Agent 5: candidates from the Agent 2 residual pattern (design note and pre-registration)

Read-only survey made on the branch `agent5-candidates`, which starts from `integration`, before any code change or evaluation. The question is whether Agent 5 can propose a hypothesis in faulty windows where its classifier proposes none, using only the expected-residual table that already exists in the Agent 5 package and the Agent 2 window assessment.

## 1. The problem

- On the 496 faulty windows of the validation split, the classifier of Agent 5 proposes no hypothesis in 141 (`reports/agent5_evidence_ranking_results.md`, section 5). In the 181-window sample, a hypothesis names a catalogue asset in 38 windows (`reports/runner_agent6_targets_results.md`).
- A re-ranking of existing hypotheses cannot help in a window with no hypothesis. The odds update failed for that reason: the bottleneck is coverage, not ranking.

## 2. What the inputs already say

- `mechanism.py` holds a table of fault families and, for each, the residuals of the Agent 2 assessment that the layout says should move. The sets were written from the topology (an extra loss between two measured points moves the residual that spans them), not fitted. The validation counts in its comments and the `reliable` flag were read from labels; this design uses neither.
- The Agent 2 window assessment gives a state for each residual R1 to R4 (`exceeded`, `within_normal`, `unknown`), the window score, the window threshold (3.03) and the flag `exceeded` (score above the window threshold), and the persistence rule (2 of the last 3 windows above 1.74). A residual is exceeded when it is above its own threshold (0.72 to 1.86), so a residual can be exceeded in a window that is not.
- Agent 2 writes one event per exceeded residual, naming the tags that residual reads. R2 and R3 read the tags of the pump that runs (for pump A: FT-201, PT-202A, PT-201 or PT-203, and the run state P-101A).
- The runner applies the persistence rule over the windows of one run and gives Agent 5 the result in `input.persistence.alarming`: true, false, or null when unsettled (fewer than 3 windows held, or a window that does not settle it).
- The contract lets a component have a null `asset_id` and a null `tag_id`, and lets a hypothesis have a null `score`. The classifier already emits mechanism-only hypotheses with both null. So the contract can express a hypothesis without a catalogue asset; there is no reason to stop. It cannot express a family whose mechanism is open (the mechanism is one value of a fixed list), which section 4 handles.

## 3. The inverse mapping

Taken from the expected sets of `mechanism.py`. A family is a candidate when every residual in its expected set is exceeded. Families with an empty expected set (tank-outlet restriction, leak outside the mass balance, level-sensor bias, valve misrouting) are never candidates.

| exceeded residual | candidate families (with their full expected set) |
|---|---|
| R1 mass balance | leak between the two meters (R1); flow-meter sensor fault (R1); level-sensor drift or stuck (R1) |
| R2 pump head | pump head loss (R2); restriction at a pump inlet valve (R2); suction-header transmitter PT-201 (R2); discharge transmitter of the running pump (R2, R3), only when R3 is also exceeded |
| R3 discharge loss | restriction at a pump outlet valve (R3); discharge-header transmitter PT-203 (R3); discharge transmitter of the running pump (R2, R3), only when R2 is also exceeded |
| R4 receipt line | restriction at a receipt-side valve (R4); receipt-line transmitter PT-001 (R4) |

The discharge transmitter families are per pump (PT-202A, PT-202B). Only the one whose tag the Agent 2 event of R2 or R3 names is a candidate, since the residual of the other pump was not computed.

## 4. When a candidate is emitted, and what it states

Emitted only when all of these hold:

1. The classifier and the rule candidates produced no hypothesis for the window. Existing hypotheses, their ids, scores and citations are never changed.
2. The anomaly report is present, not failed, and has a usable window assessment (`usable_assessment` of `mechanism.py`).
3. The window result is alarming: the assessment flag `exceeded` is true.
4. Persistence applies: when `input.persistence.alarming` is false, nothing is emitted. When it is null or the field is absent, persistence is unknown; following the rule of Agent 8 that unknown is never taken as false, the candidate is emitted and says that persistence is unknown.
5. At least one residual is exceeded and at least one family matches.

Each candidate states:

- **Family**: in its first unresolved question, by the family name of `mechanism.py`, with the supporting residuals (the exceeded residuals of its expected set) and the statement that it was raised from the residual pattern, not by the classifier.
- **Mechanism**: one value of the contract list stands for the family, fixed here: `pump` for pump head loss, `restriction_position_visible` for the three valve families, `leak` for the leak family, `drift` for the sensor families. A question says the residuals cannot tell a visible-position restriction from an obstruction, or bias, drift and stuck apart (drift and stuck for the level family), so the mechanism names the family only.
- **Asset or tag only when the evidence names one**: the pump head loss candidate names the pump whose run-state tag the R2 event lists (`asset_id`). A pressure-transmitter family is the family of one tag, and that tag is listed by the event of its residual, so it is named as `tag_id` (as `asset_id` too, as the classifier does for transmitters). The valve, leak, flow-meter and level families stay family-level, with null asset and tag: the evidence names a pump, not its inlet or outlet valve, and names both flow meters and all three level transmitters. If the event cannot be found, the pump and transmitter candidates are family-level too.
- **Score**: null. There is no classifier score, and the residual z values are not comparable with decision scores.
- **Support**: the observation evidence ids, as for every hypothesis, and the anomaly report, because the supporting residuals are exceeded. Other upstream comparisons (forecast, topology, asset, inspection) are made by the existing rules unchanged. The mechanism rule's "no family" question is not added to a candidate, because the candidate's family is stated.
- **Order**: families covering more exceeded residuals first, then the order of the table in `mechanism.py` (pump head loss, inlet valve, outlet valve, receipt valve, leak, flow meter, level sensor, then the transmitters PT-001, PT-201, PT-202A, PT-202B, PT-203). This order is a fixed convention, not evidence; `ranking_basis` says `residual_pattern_fixed_order` when the list holds only candidates.
- **Identifier**: `HYP-A2-<rank>-<family>-<asset or tag or family-level>`, disjoint from the classifier identifiers (`HYP-<rank>-...`).

With no anomaly report, no usable window assessment, or the flag `exceeded` false, the output is identical to the previous Agent 5.

## 5. Pre-registration (written before any evaluation)

Everything below is fixed now. The evaluation is run once; any change after a result is seen is reported as a deviation. Nothing is tuned on validation.

### 5.1 Data

- Only the validation split, and the 12 train windows of the 181-window sample in section 5.5. The test split is never opened. Every run installs the audit hook of the detector experiments (`tools/detector/guard.py`); its list of rejected opens must be empty. Nothing is fitted, so no train window is needed.
- The 3,980 validation windows with a valid label (496 faulty, 3,484 fault-free). Each episode is run through the runner in window order as one run with one assessment log, as in the chained 181-window runs (eligible windows only, a skipped position padded with an empty entry), with the installed agents for roles 1 to 4 and 7 and placeholders after the diagnosis. The Agent 5 request of each window is stored; the variants of Agent 5 are run on the stored requests.

### 5.2 Measures

- Faulty: at least one injected component. Coarse family of a mechanism: pump; restriction (both restriction mechanisms); leak; sensor fault (bias, drift, stuck); misrouting.
- Coverage: share of faulty windows with at least one hypothesis.
- Family top-1 over all 496 faulty windows: the first hypothesis has the coarse family of an injected component; a window with no hypothesis counts as wrong. Top-3 and the exact (mechanism and asset) measures are reported, not used by the rule.
- Fault-free windows: hypotheses with a score at or above 0.9 (a null score is not at or above 0.9), and, reported without gating, the number of fault-free windows that gain a candidate.
- 95% percentile intervals from 1,000 bootstrap resamples of whole episodes, seed 20261108, paired for differences.

### 5.3 Variants and controls

- previous: the Agent 5 of `integration`, run from a separate checkout of that commit on the same stored requests.
- new: this change.
- absent: this change on requests whose anomaly report has its window assessment removed. It must equal previous in all 3,980 windows (status, issues, result). A mismatch is a defect, reported and fixed before any adopt decision.
- shuffle: this change on requests whose anomaly result (window assessment and events) and persistence statement come from another window, five seeded permutations over the whole split (seeds 20261108 to 20261112).

### 5.4 Stop rule

Adopt only if all of these hold on the 3,980 windows; otherwise the code is removed and this report and the results are kept.

- (a) Coverage of faulty windows rises (new above previous).
- (b) Family top-1 over all 496 faulty windows improves, with the 95% paired bootstrap interval of new minus previous excluding zero (lower bound above zero).
- (c) Fault-free hypotheses with a score at or above 0.9 do not increase. Candidates carry no score, so (c) holds by construction; the fault-free windows that gain a candidate are the real cost and are reported.
- (d) Added here, stricter than (a) to (c): the family top-1 gain of new over previous exceeds the largest gain of the five shuffles, so that a gain is not explained by a fixed guess fired at random.

### 5.5 The 181-window sample

After the decision, the 181-window sample is run with `tools/agents/run_runner_sample.py --chain` on the code that is kept and on the code of `integration`, and the number of windows whose Agent 5, Agent 6 and Agent 8 reports change is reported, with the movement of the Agent 6 report statuses.
