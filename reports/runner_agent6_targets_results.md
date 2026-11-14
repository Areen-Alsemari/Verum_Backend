# Runner: Agent 6 gets only the assets that Agent 5 implicates

Erratum: the count of 30 meaningful windows in this report includes 5 train windows; over the validation split alone it is 25, as in the compressed workflow results report.

This report is started before any run. Section 1 is the pre-registration and is not changed after the evaluation; results are added below it in later sections, and any departure from section 1 is listed there as a deviation.

## 1. Pre-registration

### 1.1 Data rule

No file under `data/` is opened by hand, and the evaluation runs under the audit hook of the detector experiments (`tools/detector/guard.py`), which raises on any open of the release folder that is not a train or validation role view, the examples of those splits, the public reference, or the manifest. The summary of rejected opens must be empty. To learn the format of a file, the code that writes it is read. The only data the evaluation reads are the role-view records of the 181-window sample through `tools/agents/run_runner_sample.py`, as in the earlier reports.

### 1.2 The targets

Today the runner passes every asset of the reference (49) to Agent 6 as a target (`src/verum/agents/runner/prepare.py:91`, `builders.py:105-124`). The change:

- The targets are **all the catalogue assets that the hypotheses of Agent 5 implicate**, in the rank order of the hypotheses and without repeats. An asset is implicated when a hypothesis component names it as `asset_id`, or names it as `tag_id` when that tag is itself an asset of the reference (the pressure transmitters).
- All, not only the first-ranked, because the design document (`reports/runner_followup_design.md`, section 6) recommends passing the implicated assets, and because passing only the first would hide candidates that Agent 5 has proposed. The cost is stated: Agent 6 establishes a precondition only when the request has exactly one target (`inspection_planning/preconditions.py:100`), so in a window with two implicated assets every option stays `unknown` whatever the checks say. Agent 6 is not changed. In the earlier simulation 36 windows had one implicated asset and 2 had two.
- A tag that is not an asset is not mapped to an asset. In particular a level transmitter is not mapped to its tank, because the reference declares no such link and the runner does not carry domain knowledge that the reference lacks. The design document's count of 38 windows included that mapping, so the count here may be smaller; the difference is reported.
- If the caller supplies `query_asset_ids`, they are used as given for Agent 6 as before (older call pattern). The assets passed to Agents 3 and 4 are not changed.
- If no asset is implicated, Agent 6 gets an empty target list. The runner records the fact in a note, `NO_IMPLICATED_ASSETS`, and Agent 6 returns `insufficient_evidence` with `NO_COMPATIBLE_INSPECTION_OPTIONS`.

### 1.3 The constraint checks

The runner derives a constraint check only when the precondition can be read honestly from the observation window of the same request, and never derives anything else:

- **ACT-INSP-06, "Tank out of receipt mode", outcome `pass`**, when every declared edge that enters the tank's receipt nozzle comes from a valve whose contact tag is in the window and reads closed. The valve and the tank are linked by the declared connections of the reference. The evidence is the window's feature summary. In every other case no check is derived.
- **Nothing for the pump precondition** ("running under load for at least 20 min"): the window covers 300 s, so a pass cannot be established; it is not derived.
- **Nothing for the tank level, pipe pressure or valve flow preconditions**: they need a link between a tag and an asset that the reference does not declare.
- **Nothing for the permit-like preconditions**: they need an approved request, which stays caller-supplied. The runner does not supply one.
- **No `fail` is derived.** A failed precondition of a plan is read by Agent 8 as a conflict and gives its failed-record-check alert, which would turn a statement about feasibility (a stopped pump, an open receipt valve) into a review alert. The number of such cases that were not derived is recorded in a note.
- Checks supplied by the caller come first; a derived check is added only when the caller has none with the same identifier.

Nothing that is a label reaches an agent request: the builder reads the Agent 5 report, the reference and the window summary only. A test scans the Agent 6 request for forbidden keys.

### 1.4 Evaluation and what is expected

- The 181-window sample, run with `tools/agents/run_runner_sample.py --chain` under the audit hook, compared with the earlier run of the same sample on the previous code of the runner (the branch `runner-followup-design`, which differs from this one only in this change).
- Reported: Agent 6 options per window and statuses before and after, the number of windows with `insufficient_evidence`, `verify_bundle` on all 181 windows, whether the requests and responses of Agents 1, 3, 4, 5 and 7 are identical, whether the Agent 8 decisions changed, and, for the 30 windows that the design document names as meaningful, what Agent 6 now returns.
- Expected before the run: at most 38 windows with one or two targets; 143 or more with none; options per window 0 to 2 against 55; no change in Agents 1, 3, 4, 5 and 7; no change in the Agent 8 decision states, because no `fail` is derived; the derived ACT-INSP-06 check only in windows where the implicated asset is a tank (probably none).
- Success criteria: `verify_bundle` passes in 181 of 181 windows; Agents 1, 3, 4, 5 and 7 requests and responses are identical; the audit hook records no rejected open.

## 2. Results

Section 1 is unchanged. The evaluation ran the 181-window sample (169 validation, 12 train) with `tools/agents/run_runner_sample.py --chain` under the audit hook. The hook summary: allowed opens only in the examples (2416), knowledge (2), role views (4) and the manifest (2); the list of rejected opens is empty; no test-split file was touched. The earlier run of the same sample on the previous code of the runner is the baseline. The tables below come from `tools/agents/compare_agent6_targets.py`, which reads the stored bundles of the two runs only.

### 2.1 Agent 6 before and after

In the baseline every window gave 55 options (49 targets paired with the actions of matching kind), all `unknown`, and the report status was `degraded` in all windows. Now:

| measure | before | after |
|---|---|---|
| report status | degraded 181 | insufficient_evidence 143, degraded 38 |
| windows with insufficient_evidence | 0 | 143 |
| options per window | 55 in all 181 | 0 in 143, 1 in 36, 2 in 2 |
| options in all windows | 9955 | 40 |
| options by feasibility | unknown 9955 | unknown 40 |
| windows with a target list | 181 (49 targets) | 38 (36 with one target, 2 with two) |

The runner notes about Agent 6 after the change: `NO_IMPLICATED_ASSETS` in 143 windows (the same 143 that return `insufficient_evidence`), `NO_BUDGET` and `NO_CONSTRAINT_CHECKS` in 181. `WINDOW_CHECKS_DERIVED` and `PRECONDITION_FAILURES_NOT_DERIVED` appear in no window.

The 38 windows hold 36 faulty and 2 fault-free windows. The targets are valves (XV-PBI 8, XV-R101 7, XV-S102 2, XV-S103 2, XV-PAI 2, XV-PAO 1, XV-PBO 1, XV-R103 1), pumps (P-101A 5, P-101B 4), pressure transmitters (PT-202A 2, PT-202B 2) and pipes (E-PB3, E001, E003, 1 each). No tank is implicated in any window, so the one derivation that the runner can make (the receipt precondition of ACT-INSP-06) was never reached in the sample; it is exercised by the unit tests only. The number of windows with targets, 38, equals the design document's figure, so the decision not to map a level transmitter to its tank made no difference on this sample. The actions in the 40 options are ACT-INSP-02 (24), ACT-INSP-03 (9), ACT-INSP-07 (4) and ACT-INSP-04 (3).

### 2.2 The other roles

| role | requests identical | responses identical |
|---|---|---|
| Agent 1 predictive_health | 181 of 181 | 181 of 181 |
| Agent 2 anomaly_detection | 181 of 181 | 181 of 181 |
| Agent 3 topology_dependency | 181 of 181 | 181 of 181 |
| Agent 4 historical_asset_intelligence | 181 of 181 | 181 of 181 |
| Agent 5 diagnostic_reasoning | 181 of 181 | 181 of 181 |
| Agent 7 inspection_quality_documentation | 181 of 181 | 181 of 181 |
| Agent 8 evidence_verification_decision | 181 of 181 | 181 of 181 |
| Agent 6 inspection_planning | 0 of 181 | 0 of 181 |

The comparison sets aside the embedded Agent 6 report and its evidence row in the requests that carry it (Agents 7 and 8). Agent 8 decision states are the same in all 181 windows (`more_evidence_required` 144, `review_required` 37) and the conflict entries are the same (14 before, 14 after). That is the expected outcome of deriving no failed check. `verify_bundle` passes in 181 of 181 windows before and after.

### 2.3 The 30 meaningful windows of the design document

These are the faulty single-component windows whose injected fault sits on an asset the catalogue can inspect and which Agent 5 names first. Before, each had 55 unknown options. Now:

| injected mechanism | targets | options now | feasibility | options addressing a hypothesis | windows |
|---|---|---|---|---|---|
| misroute_a | 1 | 1 | unknown | 1 | 6 |
| pump | 1 | 1 | unknown | 1 | 9 |
| restriction_obstruction | 1 | 1 | unknown | 1 | 2 |
| restriction_position_visible | 1 | 1 | unknown | 1 | 11 |
| restriction_position_visible | 2 | 2 | unknown | 2 | 1 |
| stuck | 1 | 1 | unknown | 1 | 1 |

In 29 of the 30 the plan holds one option and in one window two (31 options in all), and every option addresses a hypothesis; before, each window held 55 options with the same feasibility. None is `eligible_for_human_review`: the preconditions of the actions in these windows (pump run time, valve flow, pressure, permits) are not readable from a 300 s window or need a caller-supplied approval, so each option stays `unknown`, which is the intended outcome. The remaining 8 windows with targets are faulty windows outside the 30 or fault-free windows.

### 2.4 Against the expectations of section 1

All expectations held: at most 38 windows with targets (38), 143 or more with none (143), options per window 0 to 2 (against 55), no change in Agents 1, 3, 4, 5 and 7, no change in the Agent 8 decision states, and no derived ACT-INSP-06 check in the sample. The success criteria are met: `verify_bundle` 181 of 181, requests and responses of Agents 1, 3, 4, 5 and 7 identical, no rejected open.

### 2.5 Limits

- The derived-check path has no occurrence in the sample, so its effect on Agent 6 and Agent 8 is shown only by synthetic tests, not by data.
- With two implicated assets (2 windows) Agent 6 cannot establish any precondition, whatever the window shows; this follows from its rule and is accepted.
- No option became eligible, so the follow-up chain beyond Agent 6 is not exercised here.
- The baseline is the previous runner on the same sample; the comparison does not measure whether the narrower options are more useful to an operator.

## 3. Changes outside the new module

- `tests/agents/runner/test_runner_topology_query.py`: an older test asserted that the Agent 6 request equals the explicit-all request; with the new targets that no longer holds, so Agent 6 was removed from the roles it compares and the test now asserts an empty default target list for placeholders and all ids for the explicit-all call. No assertion about another role was weakened.
- `tests/agents/fixtures/chained/inspection_planning.request.json` was regenerated with the fixture script; only this file changed (`target_asset_ids` is now empty in the placeholder run).
- A test for the state of an on-off contact found an error in an early version of the reading rule (a value of 0.5 was read as closed); the rule now accepts only a boolean or exactly 0 or 1.
- `tools/agents/run_runner_sample.py` now installs the audit hook and prints its summary.
