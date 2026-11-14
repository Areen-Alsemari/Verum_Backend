# Agent 8 review precedence: rule E4, pre-registration and results

This report is started before any run. Section 1 is the pre-registration and is not changed after the evaluation; the results are added below it in later sections, and any departure from section 1 is listed there as a deviation.

## 1. Pre-registration

### 1.1 The rule to implement

Rule E4 of `reports/agent8_precedence_design.md`, with its two guards and a third.

Alerts, checked first and in this order. The first that holds names the main reason, and every alert that holds is named in the summary:

1. reliable-family conflict: the outcome of the check `anomaly_report` in the `upstream_checks` of the diagnosis report is `fail`;
2. failed record check: a conflict entry that does not come from the diagnosis report (a failed precondition in the plan, a failed check or contradiction in the quality report, or proposals that share original evidence roots);
3. persistent alarm: `input.persistence.alarming` is true;
4. supported hypothesis with persistence not known to be false: the outcome of the check `anomaly_report` is `pass` and `input.persistence.alarming` is not false (null and an absent field count as not known to be false).

With an alert the decision is `review_required`, before the missing-evidence condition. Without an alert the existing logic applies unchanged (missing reports, no proposal or an unusable proposal give `more_evidence_required`; then the existing conflict rule; then `inconclusive`; then `assessment_available`).

The mapping from Agent 5 is written as named constants: the check identifier `anomaly_report`, the outcome `pass` for "supported" and the outcome `fail` for "reliable-family conflict". A test runs the Agent 5 rules and pins both outcomes to these constants.

Guards:

1. `assessment_available` is returned only when the diagnosis has candidates and every proposal is usable and there is at least one proposal. A property test over the combinations of inputs pins it.
2. A `review_required` caused by an alert keeps a `collect_evidence` next step while evidence is missing (a missing report, no proposal or an unusable proposal), and its summary names the alert reason in plain words about measured flows and pressures, with no location and no fault claim beyond what Agent 5 states.
3. No state, summary, next step, issue or limitation uses wording that implies approval, confirmation of equipment condition or an automatic action. The three fixed flags are unchanged. A test scans the text of every branch.

No new contract field is used. `persistence` and `diagnosis_report.upstream_checks` are existing fields.

### 1.2 Evaluation

- Data: the full validation split, every window with a valid label (3,980 windows, 3,484 fault-free, 496 faulty), through the runner with the installed agents, including the Agent 8 of this change. The windows of each episode are run in chronological order as one run with the `AssessmentLog`, so that persistence is known from the third window. A window without a valid label is not in the split; its position counts as a window with no assessment in the log. The 181-window sample is run the same way (`run_runner_sample.py --chain`); its episodes are partial.
- Definitions: a fault-free window has no injected change; a fault-free episode has no faulty window; a faulty episode has at least one. A review window is one whose decision is `review_required`.
- Rules compared: A (the current agent, which returns `more_evidence_required` for every window that has no proposal), B (only alert 1, then the existing logic), and E4. A and B are computed from the stored inputs of Agent 8; E4 is the decision the new agent returned, and the simulated E4 must agree with it in every window.
- Reported: decision counts; the share of review windows among faulty and among fault-free windows; per fault type (pump, restriction, leak, sensor fault, misrouting, several components); at episode level, faulty episodes with any review window, fault-free episodes with any review window, and the time from the first faulty window to the first review window at or after it (median and quartiles, and the number never flagged), with reviews before the first faulty window of a faulty episode counted separately; 95% Wilson intervals for the shares, which ignore the correlation between windows of one episode and are therefore too narrow; they are not used for the decision.

### 1.3 Adoption rule

E4 is adopted only if both hold on the full validation split:

- review windows are at most 5% of the fault-free windows, and
- fault-free episodes with any review window are at most 10% of the fault-free episodes.

Otherwise the agent falls back to rule B, E4 is reported as not adopted, and the results below say so.

### 1.4 What this evaluation is

The rules were chosen after the 181-window sample had been seen, and the sample is part of the full validation split, so the two are not independent. The full-split numbers are the check, but they are validation data too: the thresholds of Agent 2 and the choice of reliable families used validation windows. The test split is not opened; the audit hook of the detector experiments raises on any open outside the train and validation files, and its summary of rejected opens must be empty.

## 2. Results

Implementation: `src/verum/agents/evidence_verification_decision/alerts.py` and the precedence in `agent.py`. The tests are in `tests/agents/evidence_verification_decision/test_review_precedence.py` (16 tests). The evaluation script is `tools/agents/evaluate_agent8_review.py`. The audit hook recorded no rejected open in any run.

### 2.1 Full validation split

windows 3980, faulty 496, fault-free 3484, episodes 673. simulated E4 equals the returned decision in 3980 of 3980 windows; windows with no proposal 3980; persistence in the requests {'None': 1495, 'False': 2127, 'True': 358}. Windows are run in order within each episode; persistence is known in 2,485 of the 3,980 windows. No window has an evidence proposal, so rule A returns `more_evidence_required` for all of them.

Decisions by rule, with the share of review windows:

| rule | windows | n | more_evidence_required | review_required | inconclusive | assessment_available | review share (95%) |
|---|---|---|---|---|---|---|---|
| A | all | 3980 | 3980 | 0 | 0 | 0 | 0/3980 = 0.000 (0.000 to 0.001) |
| A | faulty | 496 | 496 | 0 | 0 | 0 | 0/496 = 0.000 (0.000 to 0.008) |
| A | fault-free | 3484 | 3484 | 0 | 0 | 0 | 0/3484 = 0.000 (0.000 to 0.001) |
| B | all | 3980 | 3971 | 9 | 0 | 0 | 9/3980 = 0.002 (0.001 to 0.004) |
| B | faulty | 496 | 487 | 9 | 0 | 0 | 9/496 = 0.018 (0.010 to 0.034) |
| B | fault-free | 3484 | 3484 | 0 | 0 | 0 | 0/3484 = 0.000 (0.000 to 0.001) |
| E4 | all | 3980 | 3575 | 405 | 0 | 0 | 405/3980 = 0.102 (0.093 to 0.112) |
| E4 | faulty | 496 | 166 | 330 | 0 | 0 | 330/496 = 0.665 (0.623 to 0.705) |
| E4 | fault-free | 3484 | 3409 | 75 | 0 | 0 | 75/3484 = 0.022 (0.017 to 0.027) |

Review share per fault type (rule A never flags):

| fault type | windows | rule B review | rule E4 review |
|---|---|---|---|
| leak | 57 | 0/57 = 0.000 (0.000 to 0.063) | 34/57 = 0.596 (0.467 to 0.714) |
| misrouting | 15 | 0/15 = 0.000 (0.000 to 0.204) | 2/15 = 0.133 (0.037 to 0.379) |
| pump | 72 | 0/72 = 0.000 (0.000 to 0.051) | 67/72 = 0.931 (0.848 to 0.970) |
| restriction | 156 | 9/156 = 0.058 (0.031 to 0.106) | 108/156 = 0.692 (0.616 to 0.759) |
| sensor fault | 152 | 0/152 = 0.000 (0.000 to 0.025) | 83/152 = 0.546 (0.467 to 0.623) |
| several components | 44 | 0/44 = 0.000 (0.000 to 0.080) | 36/44 = 0.818 (0.680 to 0.905) |

Episode level. Time is counted from the cutoff of the first window with an injected change to the cutoff of the first review window at or after it, in seconds:

| rule | faulty episodes with a review | faulty episodes reviewed before onset | fault-free episodes with a review | time to first review, quartile 1 (s) | median (s) | quartile 3 (s) | faulty episodes never reviewed |
|---|---|---|---|---|---|---|---|
| A | 0/120 = 0.000 (0.000 to 0.031) | 0 | 0/553 = 0.000 (0.000 to 0.007) | - | - | - | 120 |
| B | 6/120 = 0.050 (0.023 to 0.105) | 0 | 0/553 = 0.000 (0.000 to 0.007) | 0 | 0 | 600 | 114 |
| E4 | 93/120 = 0.775 (0.692 to 0.841) | 3 | 42/553 = 0.076 (0.057 to 0.101) | 0 | 300 | 300 | 27 |

Rule E4 by the first alert that holds:

| windows | reliable-family conflict | failed record check | persistent alarm | supported hypothesis | none |
|---|---|---|---|---|---|
| faulty | 9 | 0 | 281 | 40 | 166 |
| fault-free | 0 | 0 | 75 | 0 | 3409 |

### 2.2 The 181-window sample (chained)

windows 181, faulty 93, fault-free 88, episodes 100. simulated E4 equals the returned decision in 181 of 181 windows; windows with no proposal 181; persistence in the requests {'None': 124, 'False': 37, 'True': 20}. All 181 windows pass `verify_bundle` and build a final report. The episodes of the sample are partial, so the episode counts describe the windows that were sampled.

| rule | windows | n | more_evidence_required | review_required | inconclusive | assessment_available | review share (95%) |
|---|---|---|---|---|---|---|---|
| A | all | 181 | 181 | 0 | 0 | 0 | 0/181 = 0.000 (0.000 to 0.021) |
| A | faulty | 93 | 93 | 0 | 0 | 0 | 0/93 = 0.000 (0.000 to 0.040) |
| A | fault-free | 88 | 88 | 0 | 0 | 0 | 0/88 = 0.000 (0.000 to 0.042) |
| B | all | 181 | 179 | 2 | 0 | 0 | 2/181 = 0.011 (0.003 to 0.039) |
| B | faulty | 93 | 91 | 2 | 0 | 0 | 2/93 = 0.022 (0.006 to 0.075) |
| B | fault-free | 88 | 88 | 0 | 0 | 0 | 0/88 = 0.000 (0.000 to 0.042) |
| E4 | all | 181 | 144 | 37 | 0 | 0 | 37/181 = 0.204 (0.152 to 0.269) |
| E4 | faulty | 93 | 57 | 36 | 0 | 0 | 36/93 = 0.387 (0.294 to 0.489) |
| E4 | fault-free | 88 | 87 | 1 | 0 | 0 | 1/88 = 0.011 (0.002 to 0.062) |

| fault type | windows | rule B review | rule E4 review |
|---|---|---|---|
| leak | 12 | 0/12 = 0.000 (0.000 to 0.243) | 3/12 = 0.250 (0.089 to 0.532) |
| misrouting | 7 | 0/7 = 0.000 (0.000 to 0.354) | 0/7 = 0.000 (0.000 to 0.354) |
| pump | 13 | 0/13 = 0.000 (0.000 to 0.228) | 13/13 = 1.000 (0.772 to 1.000) |
| restriction | 15 | 2/15 = 0.133 (0.037 to 0.379) | 6/15 = 0.400 (0.198 to 0.643) |
| sensor fault | 38 | 0/38 = 0.000 (0.000 to 0.092) | 10/38 = 0.263 (0.150 to 0.420) |
| several components | 8 | 0/8 = 0.000 (0.000 to 0.324) | 4/8 = 0.500 (0.215 to 0.785) |

| rule | faulty episodes with a review | faulty episodes reviewed before onset | fault-free episodes with a review | time to first review, quartile 1 (s) | median (s) | quartile 3 (s) | faulty episodes never reviewed |
|---|---|---|---|---|---|---|---|
| A | 0/61 = 0.000 (0.000 to 0.059) | 0 | 0/39 = 0.000 (0.000 to 0.090) | - | - | - | 61 |
| B | 2/61 = 0.033 (0.009 to 0.112) | 0 | 0/39 = 0.000 (0.000 to 0.090) | 0 | 0 | 0 | 59 |
| E4 | 23/61 = 0.377 (0.266 to 0.503) | 1 | 0/39 = 0.000 (0.000 to 0.090) | 0 | 0 | 0 | 38 |

| windows | reliable-family conflict | failed record check | persistent alarm | supported hypothesis | none |
|---|---|---|---|---|---|
| faulty | 2 | 0 | 19 | 15 | 57 |
| fault-free | 0 | 0 | 1 | 0 | 87 |

### 2.3 Adoption outcome

- Review windows among the 3,484 fault-free windows: 75, which is 0.0215 (limit 0.05).
- Fault-free episodes with any review window: 42 of 553, which is 0.0759 (limit 0.10).
- **E4 is adopted.** Both conditions hold on the full validation split. The margin on the episode condition is thin: the 95% interval of 0.0759 over 553 episodes reaches 0.101, and the interval was not part of the rule.
- E4 returns 405 review windows in 3,980: 330 of 496 faulty windows (0.665) and 75 of 3,484 fault-free windows (0.022). At episode level it flags 93 of 120 faulty episodes (0.775) and 42 of 553 fault-free episodes (0.076); 27 faulty episodes are never flagged. Rule B flags 9 faulty windows and 6 faulty episodes, and no fault-free window.

### 2.4 What drives the result

- Every one of the 75 fault-free review windows, and all 42 fault-free episodes, come from the persistent-alarm alert. No fault-free window of the split has a supported hypothesis (the anomaly check never passes) and none has a conflict. The false-alarm rate of E4 is therefore the false-alarm rate of the persistence rule, 0.076 of fault-free episodes, which is the validation figure that Agent 2 states against its 5% target.
- The persistent alarm is also most of the sensitivity: it is the first alert in 281 of the 330 faulty review windows. The supported-hypothesis alert is the first in 40 and the reliable-family conflict in 9.
- Three faulty episodes are reviewed before the first window with an injected change.
- By fault type, review is highest for pump faults (0.93) and several components (0.82), and lowest for misrouting (0.13), for which no residual is expected.
- The first review comes at the first faulty window or one window later in at least half of the reviewed faulty episodes (median 300 s, quartiles 0 and 300 s). The alert on a supported hypothesis needs only one window; the persistent alarm needs three.

### 2.5 Tests and mutation check

The 16 new tests cover every alert, their order, each guard, absent, unknown and known-false persistence, the older behaviour when none of the new inputs is present, determinism, the pinning of the Agent 5 mapping, the wording scan, and the unchanged contract lists. A mutation check on a scratch copy applied 14 changes (reordering the alerts, treating unknown or malformed persistence as false, letting a known false silence a conflict, dropping guard 1, dropping each part of guard 2, dropping the supported mapping, changing the conflict mapping, approval and confirmation wording, requiring a diagnosis for every alert, authorising an action, and reading a failed record check from the diagnosis); all 14 were caught.

No older test was rewritten. One change was made to the implementation to keep them passing: a conflict entry with no `check_id` is not treated as a failed record check, because older tests pass minimal conflict entries.

### 2.6 What this evidence is

The rules were chosen after the 181-window sample had been seen, and the sample is part of the full validation split; the two are not independent. The full-split numbers are the check, and they are validation data too: the thresholds of Agent 2 and the choice of reliable families used validation windows. The test split was not opened. The table of the first alert and the analysis in section 2.4 were added after the first results were seen; they do not change the adoption decision.
