# Agent 8: how its decision precedence works today and which rules would use the evidence

Read-only design document. Nothing in the agents, the runner or the contract was changed; the only additions are this document and the script `tools/agents/simulate_agent8_precedence.py`. The branch `agent8-precedence-design` is `contract-window-assessment` merged with `agent5-evidence-ranking` (the merge was clean). File references are to that tree. The test split was not opened.

## 1. The current decision logic

### 1.1 States and what each says

The contract allows four decision states (`contracts/agents/v1/evidence_verification_decision.schema.json:67-72`). All four are produced by `src/verum/agents/evidence_verification_decision/agent.py`:

| state | built at | summary text | next step |
|---|---|---|---|
| `more_evidence_required` | agent.py:243-254 | "Required evidence or verification remains unavailable." | `collect_evidence`: "Obtain and verify missing or unresolved evidence before making an assessment." |
| `review_required` | agent.py:257-270 | "Evidence conflicts or shared provenance require human review." | `review_records`: "Review conflicting records and overlapping evidence roots without treating them as independent support." It cites the evidence ids of every conflict. |
| `inconclusive` | agent.py:273-284 | "No supported diagnostic candidate assessment is available." | `human_review`: "Review the inconclusive diagnostic assessment." |
| `assessment_available` | agent.py:287-300 | "Supported diagnostic candidates are available for human review; equipment condition is not confirmed." | `human_review`: "Review the supported diagnostic candidates and evidence before any operational decision." |

Around every state (agent.py:349-382, 399-432): the summary gets " Evidence IDs: ..." appended when evidence checks exist (367-369); `human_decision_required` is true, `automatic_action_authorized` and `equipment_condition_confirmed` are false (378-380); `hypothesis_report_ids` holds the diagnosis report id only when the diagnosis says `candidates_available` (359-365); the response limitations say that the assessment is advisory (426-430). The next-step kind `continue_observation` is allowed by the schema (line 192) and is never used.

Response status (agent.py:411-422): `complete` for `assessment_available` only; `degraded` for the other three, with one issue whose code is `EVIDENCE_DECISION_` followed by the state in capitals and whose message is the summary. A failure anywhere returns status `error` with a null result and the code `EVIDENCE_DECISION_ERROR` (agent.py:465-527). The contract validator adds one rule on top (`src/verum/contracts/agent_interfaces.py:355-391`): `assessment_available` needs a diagnosis with `candidates_available` and every evidence proposal usable. It places no condition on `review_required`.

### 1.2 The order in which inputs are checked

`_process_decision` (agent.py:435-462) and `_decision` (agent.py:303-324):

1. One admission check per supplied evidence proposal (agent.py:327-346, `evidence.py`): a proposal is usable only if time, provenance, quality and scope are all positively established; unknown is not a pass (evidence.py:3-4).
2. Conflict entries are collected (agent.py:443-444): hypotheses of the diagnosis that have any `conflict_evidence_ids` (112-120); upstream checks of the diagnosis whose outcome is `fail` (122-130); failed preconditions of every inspection option of Agent 6 (134-148); failed checks and contradictory conclusions for one result in Agent 7 (151-194); proposals sharing original evidence roots (216-240).
3. Missing reports: the diagnosis, plan or quality report is null or has a null result (agent.py:446-448).
4. Precedence, in this order (agent.py:310-324):
   1. `more_evidence_required` if any report is missing, **or there is no evidence proposal at all**, or any proposal is not usable;
   2. `review_required` if there is any conflict entry;
   3. `inconclusive` if the diagnosis is null, has no result, is not `candidates_available`, or has no hypothesis;
   4. `assessment_available` otherwise.

### 1.3 What it reads and what it ignores

| source | read | ignored |
|---|---|---|
| Agent 5 diagnosis | each hypothesis's `hypothesis_id` and `conflict_evidence_ids` (112-120); each upstream check with outcome `fail`: `check_id`, `description`, `evidence_ids` (122-130); `assessment` and whether there are hypotheses (316-321); `report_id` (359-365) | the score, the components, `support_evidence_ids`, `unresolved_questions`, upstream checks that pass or are unknown, `ranking_basis`, the report status and issues |
| Agent 6 plan | the `precondition_checks` of each option with outcome `fail` (134-148) | `feasibility`, `recommended_option_id`, cost, duration, `addresses_hypothesis_ids`, the report status |
| Agent 7 quality | the `checks` of each record with outcome `fail` and contradictions between records (176-194); `measurement_usable` and `scope_supported` of records that match a proposal's claimed evidence (75-105) | `observed_quality`, `retest_result_ids`, the report status and issues |
| Persistence | nothing | `persistence` and `recent_anomaly_assessments`: the schema accepts them and the runner supplies them, but no line of the agent refers to them |

### 1.4 Why a conflict cannot become `review_required` today

The line that decides it is agent.py:310: `not checks`. The agent only builds evidence checks for the proposals in `input.evidence_proposals`, and the runner passes only the proposals the snapshot carries (`src/verum/agents/runner/builders.py:143-154`, with the note `NO_EVIDENCE_PROPOSALS`). In a normal run there are none, so the first rule fires on every window and the conflict rule at line 313 is never reached. In the sample below, 181 of 181 windows have no proposal. Even with proposals, every one must be positively usable, which needs a quality record from Agent 7 that matches it; with no inspection results Agent 7 has none, so the proposal would be unknown, which blocks too. The module docstring (agent.py:3-6) states the precedence as intended: missing evidence outranks conflict.

## 2. What Agent 8 receives on the 181-window sample

The sample is the one of the earlier reports (169 validation windows and 12 train windows, 93 faulty and 88 fault-free), run through the full runner on this branch with `python tools/agents/run_runner_sample.py --out <folder>`. In that run every window is a case of its own, so the `AssessmentLog` is not threaded and persistence is unknown in all 181 windows. The chained variant (`--chain`) runs the windows of each episode in time order as one run, with a skipped position counted as a window without an assessment; there persistence is known for 57 windows. The tables come from `python tools/agents/simulate_agent8_precedence.py --run <folder> --chain <folder>`.

Agent 8 today, windows run one by one:

| measure | value |
|---|---|
| decision states returned | {'more_evidence_required': 181} |
| windows with no evidence proposal | 181 |
| windows with a missing report | 0 |
| windows with a conflict entry | 9 |
| conflict entries by source | {'diagnosis:hypothesis': 9, 'diagnosis:anomaly_report': 2, 'diagnosis:forecast_report': 3} |
| persistence alarming in the request | {'None': 181} |
| rule A reproduces the returned decision | 181 of 181 |
| anomaly check fail equals a hypothesis citing the anomaly report as conflict | 181 of 181 |
| anomaly check pass equals a hypothesis citing a signal report as support | 150 of 181 |

Hypotheses of Agent 5, by what they cite. "Support" means the hypothesis cites the anomaly report or the forecast report as support, "conflict" that it cites any report as conflict:

| windows | hypotheses | support | conflict | both | neither |
|---|---|---|---|---|---|
| faulty | 83 | 51 | 5 | 4 | 23 |
| fault-free | 9 | 6 | 0 | 0 | 3 |

Agent 6 (inspection planning). There are 55 options per window (one per catalogue action and target asset). Every option has feasibility `unknown` because no constraint checks or budget are supplied (`src/verum/agents/inspection_planning/agent.py:109-146`, `src/verum/agents/runner/builders.py:112`), and `recommended_option_id` is the constant null (agent.py:173):

| measure | value |
|---|---|
| report status | {'degraded': 181} |
| options per window (5 means 5 or more) | {5: 181} |
| options by feasibility | {'unknown': 9955} |
| windows with a recommended option | 0 |

Agent 7 (inspection quality). With no inspection result supplied, the report is `degraded` with the issue `NO_INSPECTION_RESULTS` (`src/verum/agents/inspection_quality_documentation/agent.py:79-80`), has no record checks, and lists the observed quality of the 30 tags:

| measure | value |
|---|---|
| report status | {'degraded': 181} |
| record checks per window (-1 no result) | {0: 181} |
| observed-quality entries per window (-1 no result) | {30: 181} |

Persistence, chained variant (Agent 8 today):

| measure | value |
|---|---|
| decision states returned | {'more_evidence_required': 181} |
| windows with no evidence proposal | 181 |
| windows with a missing report | 0 |
| windows with a conflict entry | 9 |
| conflict entries by source | {'diagnosis:hypothesis': 9, 'diagnosis:anomaly_report': 2, 'diagnosis:forecast_report': 3} |
| persistence alarming in the request | {'None': 124, 'False': 37, 'True': 20} |
| rule A reproduces the returned decision | 181 of 181 |
| anomaly check fail equals a hypothesis citing the anomaly report as conflict | 181 of 181 |
| anomaly check pass equals a hypothesis citing a signal report as support | 150 of 181 |

Persistence and support by label of the window in the chained variant ("supported" means the anomaly check of the diagnosis passes, that is a hypothesis is supported by the Agent 2 window assessment through the mechanism rule):

| windows | persistence and support | count |
|---|---|---|
| fault-free | alarming False, supported False | 32 |
| fault-free | alarming None, supported False | 55 |
| fault-free | alarming True, supported False | 1 |
| faulty | alarming False, supported False | 5 |
| faulty | alarming None, supported False | 54 |
| faulty | alarming None, supported True | 15 |
| faulty | alarming True, supported False | 14 |
| faulty | alarming True, supported True | 5 |

Of 93 faulty windows, 19 have a persistent alarm; a supported hypothesis exists in 5 of those and in 15 more with persistence unknown. Of the 88 fault-free windows 1 has a persistent alarm and none has a supported hypothesis.

## 3. Candidate precedence rules, simulated

Each rule is a pure function of values read from the stored Agent 8 request and the stored reports; rule A is the current agent and reproduces its returned decision in 181 of 181 windows. All rules map to the four existing states. None returns anything but `more_evidence_required`, `review_required`, `inconclusive` or `assessment_available`, none changes the three fixed flags, and none authorises an action or confirms a condition. Definitions of what a rule reads, all visible to Agent 8 in its request:

- **reliable-family conflict**: the anomaly check of the diagnosis has outcome `fail`. Agent 5 sets it only when a hypothesis of a pump family (pump head loss, pump inlet or outlet valve) has its expected residual within normal in a complete window (`src/verum/agents/diagnostic_reasoning/mechanism.py:42-44, 156-192`, `rules.py:375-392`). It equals "a hypothesis cites the anomaly report as conflict" in 181 of 181 windows.
- **supported hypothesis**: the anomaly check has outcome `pass`, that is a hypothesis has an exceeded expected residual.
- **alarming**: `input.persistence.alarming` is true; false means known not alarming; null means unknown.
- **failed record check**: any conflict entry that does not come from the diagnosis (an Agent 6 precondition fail, an Agent 7 failed check or contradiction, shared evidence roots). There is none in the sample.
- **obtainable**: some Agent 6 option has feasibility `eligible_for_human_review`. There is none in the sample.

Rules:

- **A** current.
- **B** a reliable-family conflict gives `review_required` before missing evidence; otherwise A.
- **C** persistence alarming true and a supported hypothesis give `review_required` before missing evidence; otherwise A.
- **D** if A would say `more_evidence_required`: stay there when Agent 6 has an obtainable option, otherwise `review_required` when a supported hypothesis exists; otherwise A.
- **D\*** D with "supported" widened to any signal report, the anomaly report or the forecast (to show what forecast support adds).
- **E1** A without the `not checks` condition: no proposal means nothing to verify.
- **E2** `review_required` for a reliable-family conflict, a failed record check, or rule C; otherwise A.
- **E3** `review_required` for a reliable-family conflict, a failed record check, or a supported hypothesis unless persistence is known to be false; otherwise A.
- **E4** E3, and also `review_required` whenever persistence alarms, with or without a supported hypothesis.

Windows run one by one (persistence unknown). The last two columns are the share of faulty and of fault-free windows that the rule would flag `review_required`:

| rule | description | more_evidence_required | review_required | inconclusive | assessment_available | faulty flagged review | fault-free flagged review |
|---|---|---|---|---|---|---|---|
| A | current | 181 | 0 | 0 | 0 | 0 of 93 | 0 of 88 |
| B | reliable-family conflict first | 179 | 2 | 0 | 0 | 2 of 93 | 0 of 88 |
| C | persistent supported alarm first | 181 | 0 | 0 | 0 | 0 of 93 | 0 of 88 |
| D | obtainable evidence stays, else review if supported | 161 | 20 | 0 | 0 | 20 of 93 | 0 of 88 |
| D* | D, support from the anomaly report or the forecast | 130 | 51 | 0 | 0 | 45 of 93 | 6 of 88 |
| E1 | A without the empty-proposal condition | 0 | 9 | 107 | 65 | 9 of 93 | 0 of 88 |
| E2 | B or C or failed record check first | 179 | 2 | 0 | 0 | 2 of 93 | 0 of 88 |
| E3 | conflict, or supported unless persistence is false | 159 | 22 | 0 | 0 | 22 of 93 | 0 of 88 |
| E4 | E3, and review whenever persistence alarms | 159 | 22 | 0 | 0 | 22 of 93 | 0 of 88 |

All decision states by group, windows run one by one:

| rule | windows | more_evidence_required | review_required | inconclusive | assessment_available |
|---|---|---|---|---|---|
| A | faulty | 93 | 0 | 0 | 0 |
| A | fault-free | 88 | 0 | 0 | 0 |
| B | faulty | 91 | 2 | 0 | 0 |
| B | fault-free | 88 | 0 | 0 | 0 |
| C | faulty | 93 | 0 | 0 | 0 |
| C | fault-free | 88 | 0 | 0 | 0 |
| D | faulty | 73 | 20 | 0 | 0 |
| D | fault-free | 88 | 0 | 0 | 0 |
| D* | faulty | 48 | 45 | 0 | 0 |
| D* | fault-free | 82 | 6 | 0 | 0 |
| E1 | faulty | 0 | 9 | 28 | 56 |
| E1 | fault-free | 0 | 0 | 79 | 9 |
| E2 | faulty | 91 | 2 | 0 | 0 |
| E2 | fault-free | 88 | 0 | 0 | 0 |
| E3 | faulty | 71 | 22 | 0 | 0 |
| E3 | fault-free | 88 | 0 | 0 | 0 |
| E4 | faulty | 71 | 22 | 0 | 0 |
| E4 | fault-free | 88 | 0 | 0 | 0 |

Chained variant, all 181 windows:

| rule | description | more_evidence_required | review_required | inconclusive | assessment_available | faulty flagged review | fault-free flagged review |
|---|---|---|---|---|---|---|---|
| A | current | 181 | 0 | 0 | 0 | 0 of 93 | 0 of 88 |
| B | reliable-family conflict first | 179 | 2 | 0 | 0 | 2 of 93 | 0 of 88 |
| C | persistent supported alarm first | 176 | 5 | 0 | 0 | 5 of 93 | 0 of 88 |
| D | obtainable evidence stays, else review if supported | 161 | 20 | 0 | 0 | 20 of 93 | 0 of 88 |
| D* | D, support from the anomaly report or the forecast | 130 | 51 | 0 | 0 | 45 of 93 | 6 of 88 |
| E1 | A without the empty-proposal condition | 0 | 9 | 107 | 65 | 9 of 93 | 0 of 88 |
| E2 | B or C or failed record check first | 174 | 7 | 0 | 0 | 7 of 93 | 0 of 88 |
| E3 | conflict, or supported unless persistence is false | 159 | 22 | 0 | 0 | 22 of 93 | 0 of 88 |
| E4 | E3, and review whenever persistence alarms | 144 | 37 | 0 | 0 | 36 of 93 | 1 of 88 |

Chained variant, only the 57 windows where persistence is known (24 faulty, 33 fault-free):

| rule | description | more_evidence_required | review_required | inconclusive | assessment_available | faulty flagged review | fault-free flagged review |
|---|---|---|---|---|---|---|---|
| A | current | 57 | 0 | 0 | 0 | 0 of 24 | 0 of 33 |
| B | reliable-family conflict first | 57 | 0 | 0 | 0 | 0 of 24 | 0 of 33 |
| C | persistent supported alarm first | 52 | 5 | 0 | 0 | 5 of 24 | 0 of 33 |
| D | obtainable evidence stays, else review if supported | 52 | 5 | 0 | 0 | 5 of 24 | 0 of 33 |
| D* | D, support from the anomaly report or the forecast | 44 | 13 | 0 | 0 | 10 of 24 | 3 of 33 |
| E1 | A without the empty-proposal condition | 0 | 4 | 38 | 15 | 4 of 24 | 0 of 33 |
| E2 | B or C or failed record check first | 52 | 5 | 0 | 0 | 5 of 24 | 0 of 33 |
| E3 | conflict, or supported unless persistence is false | 52 | 5 | 0 | 0 | 5 of 24 | 0 of 33 |
| E4 | E3, and review whenever persistence alarms | 37 | 20 | 0 | 0 | 19 of 24 | 1 of 33 |

How to read these. The sample is stratified, with 51% faulty windows, so the shares of flagged faulty windows are sensitivities within this sample and the shares of flagged fault-free windows are false-alarm rates within it. A count of 0 of 88 fault-free windows does not exclude a rate of up to 3.4% (rule of three). The fault-free windows are 82 validation windows and 6 train windows. The count for D\* shows that support from the forecast alone adds 6 flagged fault-free windows.

## 4. What each rule means for an operator, what can go wrong, what it needs

In every rule the response status stays `degraded` and carries an issue named after the state, as today; `review_required` and `more_evidence_required` are told apart by the summary, the next step and the issue code. The `review_required` text today speaks only of conflicts and shared provenance, so a rule that flags for another reason needs its own summary and next-step text (free text, no new field). None of the rules needs a new contract field: the state, the next-step kinds, `upstream_checks` of the diagnosis and the optional `persistence` input already exist.

| rule | operator sees | could go wrong | contract |
|---|---|---|---|
| A | `more_evidence_required` in all 181 windows, with one generic step, whatever the signals say. The 9 windows with a conflict entry and the 20 with a persistent alarm look like the rest. | Agent 8 gives no triage: the information of Agents 2 and 5 never reaches the operator through the decision state. | none |
| B | `review_required` in the 2 windows where a pump-family hypothesis is contradicted by a quiet residual, with the conflicting evidence ids. | Those windows are faulty ones in which the expected residual stayed quiet, so the "conflict" is a miss by the residual. Review is still reasonable, but the text must say what the contradiction is. Sensitivity is 2 of 93. | reads `upstream_checks` of the diagnosis: exists |
| C | `review_required` only where persistence alarms and a hypothesis is supported: 5 of 93 faulty windows, none fault-free. | Almost silent: persistence is known only in the chained variant, and a supported hypothesis is rare. Depends on a threshold whose validation episode alarm rate is 7.6% against a 5% target. | reads `persistence`: exists (optional) |
| D | `review_required` whenever a hypothesis is supported (20 of 93 faulty, 0 of 88 fault-free), because Agent 6 never marks an option obtainable. | The "obtainable" test is dead today: all 9,955 options are `unknown`. D then reduces to "supported hypothesis means review". Once Agent 6 does mark options eligible, supported windows with an obtainable inspection would go back to `more_evidence_required`, which hides the signal again. | reads feasibility of Agent 6: exists |
| D\* | as D, with forecast support: 45 of 93 faulty, 6 of 88 fault-free. | Forecast support is heuristic and unvalidated (see the module text of `rules.py`), and it raises the false alarms. Not recommended. | exists |
| E1 | `assessment_available` in 65 windows, `inconclusive` in 107, `review_required` in 9, never `more_evidence_required`. | Removing only the empty-proposal condition tells the operator "supported diagnostic candidates are available" for 9 fault-free windows and calls 65 windows assessed while Agent 6 has no feasible option and Agent 7 has no inspection result. It also tells 28 faulty windows "inconclusive". The condition protects the approval-like state from vacuous evidence. Not acceptable alone. | none |
| E2 | B or C or a failed record check: 7 of 93 faulty (chained), 0 of 88 fault-free. | Conservative to the point of little use; the failed-record-check branch is untested on real windows. | exists |
| E3 | `review_required` for a conflict or a supported hypothesis unless persistence is known false: 22 of 93 faulty, 0 of 88 fault-free, with or without persistence. | A supported hypothesis in one window can come from a residual that exceeds in 4 to 10% of fault-free windows; the sample has no such case but 88 windows cannot show a rate under 3.4%. Persistence false suppresses a window only if one exists. | exists |
| E4 | E3 and every persistent alarm: 36 of 93 faulty (39%), 1 of 88 fault-free (1.1%) in the chained variant; 22 and 0 where persistence is unknown. Of the 24 faulty and 33 fault-free windows with persistence known: 19 and 1. | The extra 14 faulty windows are persistent alarms with no supported hypothesis, so the operator is asked to review something Agent 5 cannot name; the text must say so. The false-alarm side rests on one window. | exists |

## 5. Recommendation

**Adopt E4, with two guards, and do not adopt E1.**

The finding that matters is in section 1.4, not in the rules: Agent 8 cannot leave `more_evidence_required` in the runtime path because "no evidence proposal" counts as "evidence missing". Missing evidence then masks every signal, including the 20 windows with a persistent alarm and the 20 with a supported hypothesis. The rule should be asymmetric: a gap in evidence may block states that say something is available (`assessment_available`), but it should not suppress an alert (`review_required`).

E4 does that. In order: (1) the alert conditions come first and give `review_required`: a reliable-family conflict, a failed record check, a persistent alarm, or a supported hypothesis with persistence not known false; (2) otherwise missing reports or a supplied but unusable proposal give `more_evidence_required`, as in A; (3) otherwise A, which for a window with no alert and no proposal stays `more_evidence_required`. This gives, on the sample, 22 of 93 faulty windows flagged and 0 of 88 fault-free without persistence, and 36 of 93 and 1 of 88 with persistence.

Guards:

1. `assessment_available` stays unreachable unless the proposals are usable (keep the `not checks` condition for that state only). The contract validator already requires it (`src/verum/contracts/agent_interfaces.py:386-391`) and E1 shows what happens otherwise.
2. A `review_required` caused by an alert must keep the evidence gap visible: the next steps include `review_records` or `human_review` for the alert **and** `collect_evidence` while a report or proposal is missing, and the summary names the reason (conflict, persistent alarm, supported hypothesis) instead of the conflict-only sentence of today.

Before adoption the false-alarm side needs a larger measurement than 88 windows: the full validation split has 3,484 fault-free windows, the harness that stores the Agent 5 request of each window exists in the history of the branch `agent5-evidence-ranking` (commit `6537e5f`), and the decision of E4 can be computed from the stored request. The persistent-alarm part depends on a threshold whose validation alarm rate is 7.6% of fault-free episodes against the 5% it was set for, so its false alarms will be higher than the 1 of 88 seen here.

### Tests that would pin it

Each with an "Independent:" docstring and a small synthetic request:

1. No proposal, no alert: `more_evidence_required` (unchanged from A).
2. No proposal and the anomaly check `fail`: `review_required`, not `more_evidence_required`.
3. No proposal and `persistence.alarming` true: `review_required`, with and without a supported hypothesis.
4. No proposal, anomaly check `pass`, persistence null: `review_required`; persistence false: not `review_required`; persistence false does not suppress a conflict or a failed record check.
5. Unknown is never false: a null `alarming` never suppresses a supported hypothesis; a missing `persistence` key (older requests) gives the same answer as null.
6. `assessment_available` is returned only when diagnosis candidates exist and every proposal is usable, over all combinations of the inputs (a property test).
7. The three fixed flags and `advisory_only` hold for every branch; the response validates with `validate_response`.
8. The evidence gap stays visible: with a missing report the `review_required` result still lists a `collect_evidence` step; the summary names the reason for each trigger.
9. A failed record check outranks every other trigger; a missing diagnosis report with an alarming persistence is handled (alert still shown, no crash).
10. Determinism, and parity with the current agent: an input with no alert gives the state that rule A gives.
11. A mutation check in a scratch copy: swap the order of the alert and missing-evidence branches, treat null persistence as false, drop the `not checks` guard for `assessment_available`, let a quality-only event trigger review, read the forecast as support, and change a fixed flag; each must be caught.
12. A contract test that the decision-state enum and the next-step kinds are unchanged.

## 6. Limits of this analysis

- Nothing was implemented; the rules are simulated on stored requests.
- The sample is a stratified development sample of 181 windows (51% faulty). The rates are not rates of the full validation split, and the chained variant gives persistence for 57 windows only, because the sampled windows of an episode are not consecutive.
- The "supported" and "reliable conflict" signals are the outputs of the mechanism rule of Agent 5, which was itself checked only on this kind of sample; this document does not validate them.
- The persistence rule, its threshold and its limits are in the Agent 2 limitation text and in `reports/contract_window_assessment_results.md`.
