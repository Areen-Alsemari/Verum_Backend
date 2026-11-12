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
