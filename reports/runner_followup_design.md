# Follow-up round: what the runner, Agents 6 to 8 and the data allow

Read-only design document. Nothing in the agents, the runner or the contract was changed. The additions are this document and `tools/agents/simulate_followup_targets.py`, which calls Agent 6 on changed copies of stored requests and counts windows. The branch `runner-followup-design` starts from `agent8-review-precedence`. File references are to that tree.

Data touched: the stored bundles of a runner run over the 181-window sample (run with `tools/agents/run_runner_sample.py --chain`), configuration and schema files, directory listings of the release and of the campaign evaluator folder, and the code. No data file was read for content. One slip is recorded in section 7.

## 1. How the Agent 6 request is built today, and what Agent 6 returns

### 1.1 The request

- **Targets: 49.** `src/verum/agents/runner/prepare.py:91` sets `query_assets` to the caller's `query_asset_ids` or, when there are none, to every asset of the reference. The reference lists 49 assets: 28 pipe edges, 11 isolation valves, 5 pressure transmitters, 3 tanks, 2 pumps. `builders.py:105-124` passes that list as `target_asset_ids`. The runner never narrows it, not even to what Agent 5 implicates.
- **Catalogue: 7 actions.** `prepare.py:89` copies the reference catalogue (`ACT-INSP-01` to `07`, each for one asset kind: tank, isolation valve, pump, pipe, tank, tank, pressure transmitter).
- **Constraints: none.** `constraint_checks` is empty unless the snapshot carries some (`builders.py:109-111`, note `NO_CONSTRAINT_CHECKS`). **Budget: null.** Both limits are null (`builders.py:112-114`, note `NO_BUDGET`). **Workflow requests: none** (`builders.py:123`).

### 1.2 What Agent 6 returns and why every option is unknown

`src/verum/agents/inspection_planning/agent.py:105-146` pairs every catalogue action with every target of the right kind: 3 + 11 + 2 + 28 + 3 + 3 + 5 = **55 options per window**. Each option's feasibility comes from `preconditions.py:88-149`. A precondition passes only when a constraint check matches the action and asset, its evidence is of the right kind, and, for permit-like wording, an approved workflow request exists. There are three separate reasons that all 55 options are `unknown`:

1. **No constraint check is supplied** (section 1.1), so no precondition can be established.
2. **The target list is ambiguous.** `preconditions.py:100` sets `target_is_unambiguous` only when `target_asset_ids == [target_asset]`. With 49 targets, no precondition of any option can be established even if checks were supplied.
3. **Five of the seven actions need a permit-like precondition** (`PERMIT_TERMS`, `preconditions.py:15`: "permit", "approval", "access"; ACT-INSP-01, 02, 04, 05, 07). Those need an approved workflow request that names the action and the asset (`preconditions.py:48-85`), which exists only after someone has chosen and requested the inspection. ACT-INSP-03 (pump under load) and ACT-INSP-06 (tank out of receipt) have no permit precondition.

`recommended_option_id` is the constant null (`agent.py:173`); `expected_information_gain_bits` is null; the report is `degraded` with the issue `INSPECTION_PRECONDITIONS_UNKNOWN` (`agent.py:146-165`). Agent 8 ignores all of it (`reports/agent8_precedence_design.md`), and the final report lists all 55 options with feasibility `unknown` (`inspection_quality_documentation/report.py:172-207`).

Agent 6 today, on the 181 windows:

| measure | value |
|---|---|
| report status | {'degraded': 181} |
| options per window (6 is 6 or more) | {6: 181} |
| options by feasibility | {'unknown': 9955} |
| options that address a hypothesis | 40 |
| issue codes | {'INSPECTION_PRECONDITIONS_UNKNOWN': 181} |

### 1.3 What the request would look like with only the implicated assets

The target list would be the catalogue assets named by the components of the Agent 5 hypotheses (a pipe edge for a leak, a valve for a restriction or a misrouting, a pump, a pressure transmitter, and the tank for a level transmitter, whose dip sounding is the check of its reading; flow meters have no catalogue action). Simulated on the 181 windows, by calling Agent 6 on the stored request with only `target_asset_ids` replaced:

Targets implicated by Agent 5:

| targets per window (3 is 3 or more) | windows |
|---|---|
| 0 | 143 |
| 1 | 36 |
| 2 | 2 |

Agent 6 on all implicated assets:

| measure | value |
|---|---|
| report status | {'insufficient_evidence': 143, 'degraded': 38} |
| options per window (6 is 6 or more) | {0: 143, 1: 36, 2: 2} |
| options by feasibility | {'unknown': 40} |
| options that address a hypothesis | 40 |
| issue codes | {'NO_COMPATIBLE_INSPECTION_OPTIONS': 143, 'INSPECTION_PRECONDITIONS_UNKNOWN': 38} |

Agent 6 on the first implicated asset only (one unambiguous target):

| measure | value |
|---|---|
| report status | {'insufficient_evidence': 143, 'degraded': 38} |
| options per window (6 is 6 or more) | {0: 143, 1: 38} |
| options by feasibility | {'unknown': 38} |
| options that address a hypothesis | 38 |
| issue codes | {'NO_COMPATIBLE_INSPECTION_OPTIONS': 143, 'INSPECTION_PRECONDITIONS_UNKNOWN': 38} |

Reading of these results:

- Agent 5 names a catalogue asset in only **38 of 181 windows** (36 with one asset, 2 with two). In the other 143 the hypotheses carry no asset (a generic "leak" or "bias") or there is no hypothesis. Agent 6 then has nothing to plan and returns `insufficient_evidence` with `NO_COMPATIBLE_INSPECTION_OPTIONS` (`agent.py:139-143`, `184-201`). That is honest, but the follow-up has no target.
- In the 38 windows Agent 6 returns 1 or 2 options instead of 55, each addressing a hypothesis (40 of 40 options, against 40 of 9,955 today). Every option is still `unknown`: there are no constraint checks and no approved request.
- With one target the ambiguity reason disappears. The remaining reasons are removable only by the caller: constraint checks derived from the observation window for the preconditions that the window can show (flow or pressure at the target, pump running, tank level, tank out of receipt), and, for the permit-like preconditions, an approved request after the human has chosen. An option can therefore reach `eligible_for_human_review` only for ACT-INSP-03 and ACT-INSP-06 before the choice, and for the others only after the request is approved.

## 2. What Agents 7 and 8 need to leave their degraded states

### 2.1 Today

Agent 7 is `degraded` with `NO_INSPECTION_RESULTS` and empty `record_checks` (`inspection_quality_documentation/agent.py:79-80`). Agent 8 receives no proposal and returns `more_evidence_required` or, since the review precedence, `review_required` with a step to collect evidence. The runner supplies inspection data only when the snapshot carries it (`builders.py:127-154`, `snapshot.py:11-33`).

### 2.2 The fields

| item | fields | who is supposed to produce it | provenance in the contract |
|---|---|---|---|
| inspection request (`schemas/inspection_request.schema.json`) | `request_id` (`REQ-INSP-nnnnn`), `t_requested_sim_s`, `action_id`, `target_asset`, `justification` (at least two `competing_hypotheses`, `agent_reported_information_gain_bits`, `estimated_cost_usd`), `human_approval` (`status` PENDING, APPROVED or REJECTED; `approver_id`, `work_permit_number`, `rejection_reason`) | the caller on behalf of a human; the approval comes from the approval emulator or a real approver (`inspection/service.py:63-88`) | evidence kind `inspection_request`, source `inspection_request:<id>`, provenance `simulated_workflow`; its hash must match the row (`agent_interfaces.py:30-38, 194-207`) |
| inspection result (`schemas/inspection_result.schema.json`, wrapped as `workflow_status: performed`) | `result_id` (`RES-INSP-nnnnn`), `request_id`, `action_id`, `evidence_status` (valid, missing, contradictory, low_confidence), `performed_at_t_sim_s`, `technician_id`, `tool_serial`, `calibration_valid_until`, `findings` (`outcome_category`, `primary_metric` with name, value, unit, `uncertainty_k2`, and `secondary_observations`), `validation_status` (PASSED_QA, FLAGGED_INCONSISTENT, RETEST_REQUIRED) | the inspection service through the gateway (`inspection/service.py:98-135`); in a real deployment a technician's record | evidence kind `inspection_result`, source `inspection_result:<id>`, provenance `simulated_inspection`; `performed_at_t_sim_s` may not be later than the cutoff; content hash bound to its row (`agent_interfaces.py:184-191`) |
| process coverage | `coverage_id`, `target_asset`, `start_s`, `end_s`, `evidence_ids` | the caller, from the recorded process | must not extend beyond the cutoff (`agent_interfaces.py:192-196`); its evidence must be registered |
| constraint check (input of Agent 6) | `check_id` starting with `<action>-<asset>-`, `description` equal to the catalogue precondition, `outcome` pass, fail or unknown, `evidence_ids` | the caller | evidence of kind observation window, representation or inspection result; a permit-like precondition needs an inspection request instead (`preconditions.py:11-45`) |
| record check (Agent 7 output) | per result: `result_id`, `checks` (13 named checks: request link, chronology, human approval, performed status, evidence availability, calibration validity, required fields, measurement unit, uncertainty, process coverage, validation status, source provenance, source quality), `measurement_usable`, `scope_supported`, fixed `equipment_condition_confirmed: false`, `evidence_ids` | Agent 7 (`inspection_quality_documentation/agent.py:164-560`) | derived report; roots are the original evidence |
| evidence proposal (Agent 8 input) | `proposal_id`, `source_ref` (prefix observations, features, reference, inspection_request, inspection_result, history or report), `claimed_available_at_s`, `claimed_evidence_ids` | the caller or an adapter that proposes which registered items should count; there is no producer in the runner today | the claimed ids must be registered, available by the cutoff and from the named source (`evidence.py`); quality and scope come only from an Agent 7 record that matches the claimed ids (`agent.py:75-105`) |

### 2.3 What makes a result usable

Agent 7 sets `measurement_usable` true only if every check passes. Three of the checks depend on the result's own content and not on the loop:

- `evidence_availability` and `source_quality` pass only when `evidence_status` is `valid` (agent.py:369-380, 531-560); `low_confidence`, `missing` and `contradictory` fail;
- `validation_status` must be `PASSED_QA`; `calibration_validity` needs `calibration_valid_until` on or after the date of the cutoff;
- `process_coverage` needs a supplied coverage row for the target that contains `performed_at_t_sim_s`.

Agent 8 then needs a proposal whose claimed ids match such a record, with `measurement_usable` and `scope_supported` both true, before `usable` can be true (`agent.py:75-105`, `evidence.py`). Only then is `assessment_available` reachable. Agent 5 reads the quality report only as "some record is usable" (support for every hypothesis) or "some record is not usable" (conflict for every hypothesis) (`diagnostic_reasoning/rules.py:504-515`); it does not read the content of a finding.

### 2.4 The qualification gate

The inspection models are qualified only in part. `UNQUALIFIED_ACTIONS` (`inspection/catalog.py:23`) holds ACT-INSP-01, 03, 04 and 06; in the default mode they return no measurement, with `evidence_status: missing` and the text "The measurement is unavailable" (`inspection/models.py:287-304`). The three modelled actions return a measured value but with `evidence_status: low_confidence` and the outcome category `TEST_INCONCLUSIVE`, because equipment acceptance tolerances are unavailable (valve check, `models.py:125-154`; dip, `207-232`; calibration, `253-284`). So **in the default mode no inspection result is `valid`, and Agent 7 can never set `measurement_usable` true**. The pump vibration and acoustic leak models exist (`models.py:157-205`) and give `valid` results, but only with `allow_extrapolated_research=True`, which the documentation calls not qualified inspection evidence (`docs/inspection_model.md`, section "How an outcome is produced"). The data contract lists the acceptance of legacy out-of-horizon measurements as equipment evidence as unsupported (`docs/agent_data_contract.md:13`).

Consequence: with the stock models the second pass can move Agent 7 from "no results" to "results present and judged unusable", and Agent 8 can name that, but no run reaches `assessment_available` unless the research mode is used and labelled.

## 3. What the data offers for simulating an inspection

### 3.1 Files

- **Inspection truth** (`schemas/inspection_truth.schema.json`, version 0.7.0, one file per episode: `inspection_truth.jsonl.gz`). Each row has `t_sim_s`, `side` (a grid row or the two sides of a discontinuity), `tanks` (level, temperature, volume for each tank), `edges` (flow and pressures for each of the 28 edges), `valves` (commanded state, position fraction, contact), `pumps` (run state, speed ratio, head scale), `leaks` (fault instance, edge, fraction along the edge, flow), `faults` (instance, type, asset, severity, parameter and value), `tags` (true value and fault offset of each of 14 tags) and the constant `hidden: true`. It holds the true state **per asset and per time**, not a per-check answer; `inspection/truth.py` interpolates it and holds the last state after the last row.
- **Fault truth, labels, scenario, validity windows** (`fault_truth.jsonl.gz`, `labels.json`, `scenario.json`, `validity_windows.jsonl.gz`) in the same episode folder. `scenario.json` carries the seed that the inspection service uses for its random streams (`truth.py:47-60`).
- **The release does not contain the inspection truth.** The evaluator folder of the release (`data/reference_release_v2/verum_reference_v2/evaluator/source_episodes/<episode>/`) holds only fault truth, labels, scenario and validity windows. The inspection truth is in the campaign evaluator folder (`data/campaign/evaluator/episodes/<episode>/`), which has 3,000 episodes: the 756 validation episodes and 1,660 train episodes of the release are all there, and the other 584 include the test episodes. One loader would have to read it only for the validation episodes it is given. The audit hook of the detector experiments (`tools/detector/guard.py`) classifies only paths inside the release folder and lets every other path through, so it does not protect the campaign folder; a new guard for it would be needed.
- **Release inspection records** (`inspection_records/source_00/inspection_quality.jsonl`, built by `training/inspection_records.py`): 12 records of one action (manual dip, ACT-INSP-05) on healthy roof-reference parents, with numerical findings withheld, a 7,320 s process horizon, and targets about record completeness (`docs/agent_data_contract.md:44-50`). They carry no fault and no asset-level truth and are of no use for a fault follow-up.
- **The inspection service** (`inspection/service.py`) turns an episode's truth into agent-visible requests, results and history; `InspectionService(evaluator_directory)` is already used to generate the release records (`training/reference.py:123`).

### 3.2 Splits and tests

The campaign evaluator folder is not split; the split is the episode's membership in the release role views. The tests are: `tests/regression/test_inspection_truth.py` (D156: the truth rows against the full hydraulic state of short episodes, one healthy and one for each fault subtype, and digests); `test_inspection.py` (catalogue, models, preconditions, workflow, validator, history and gateway on hand-written truth); `test_inspection_episodes.py` (each action on real short episodes with one known fault, expected outcomes worked out by hand); `test_inspection_horizon.py` (findings need recorded process coverage at the time of the measurement); `test_inspection_work_conditions.py` (cancellation during work without disclosing future changes).

### 3.3 Evaluator side only, never a label for an agent

- the inspection truth rows, `fault_truth`, `labels.json`, `scenario.json` (the seed), `observation_audit` and `validity_windows`;
- `Record.outcome.true` (the true quantity behind every measured value, for example the true leak flow, the detection probability, the true station, the head-loss fraction), returned by `InspectionService.record()` (`service.py:90`); only the views of `results()` and `requests()` and the gateway allowlist (`api/gateway.py:81`) are agent-visible;
- the rejection reason of the approval emulator, which is computed from the truth at the decision time (`workflow.py:59-66`, `preconditions.py:74-80`): reason codes such as `LEVEL_BELOW_1_8_M` or `PUMP_NOT_UNDER_LOAD_20_MIN` are visible to the agent by design and reveal part of the true state;
- the scenario label of any simulated follow-up (confirming, refuting, inconclusive, noisy);
- the episode identifier and file names, which `FORBIDDEN` keys in `agent_interfaces.py:19-26` keep out of messages.

## 4. A proposal for a follow-up round

### 4.1 The horizon problem comes first

An inspection takes an approval delay of 300 to 1,800 s, a scheduling delay of 0 to 900 s, the action duration (45 to 120 min) and 120 s for the result (`config/inspection_catalog.json`, section `workflow`; `workflow.py:49-80`). The default workflow refuses a measurement that would be performed after the recorded process (`INSUFFICIENT_SIMULATED_HORIZON`, `workflow.py:63-64`). The recorded episodes end at 3,600 s and the windows have cutoffs of 300 to 3,600 s. The request validator requires the result to be performed no later than the cutoff of the request that carries it (`agent_interfaces.py:184`), and the runner requires a new observation summary for a later cutoff for a new revision (`snapshot.py:35-64`). Even with the shortest delays, a 45-minute action requested at 300 s is visible at 3,120 s, and no action of 60 minutes or more fits at all. Counted on the sample with best-case delays:

Latest cutoff in the sample 3600 s; process horizon 3600 s; windows per position {1: 13, 2: 13, 3: 12, 4: 10, 5: 7, 6: 5, 7: 10, 8: 14, 9: 20, 10: 29, 11: 28, 12: 20}.
| action | duration (min) | windows that fit | of which faulty |
|---|---|---|---|
| ACT-INSP-01 | 90.0 | 0 | 0 |
| ACT-INSP-02 | 45.0 | 13 | 0 |
| ACT-INSP-03 | 60.0 | 0 | 0 |
| ACT-INSP-04 | 120.0 | 0 | 0 |
| ACT-INSP-05 | 45.0 | 13 | 0 |
| ACT-INSP-06 | 60.0 | 0 | 0 |
| ACT-INSP-07 | 45.0 | 13 | 0 |

**No faulty window of the sample leaves room for an inspection and a later pass inside the recorded process.** The 13 windows that fit are the first windows of their episodes, before any fault. The follow-up therefore cannot be built from the recorded episodes with a realistic workflow. Three ways around it:

- **S1, extended companion episodes.** Re-run the simulator for selected validation episodes with the same scenario and seed and a longer duration, so that the process, the observations and the inspection truth continue past 3,600 s. Faults persist to the end of an episode (`docs/fault_models.md:25`), and `truth.py` already holds the last state beyond the last row. The first 3,600 s must reproduce the stored observations; that is a test to write before relying on it. This is the only way to keep the realistic delays, the process coverage and a true second observation window. It needs new data and a generator run outside the release.
- **S2, held state (research mode).** `allow_extrapolated_research=True` holds the last state after the horizon. The results are labelled by the code as not qualified evidence, and the second pass would have no new observations (reusing the last summary is what the revision guard exists to prevent). Not recommended except to exercise code.
- **S3, compressed workflow.** The caller treats the inspection as performed at once, at the cutoff of the first pass, against the true state of that cutoff, and the second pass uses the next real window (300 s later). The delays of the catalogue are not respected, so this tests the plumbing and the behaviour of Agents 5 to 8 and the report, not a realistic workflow. The result and the request must say so, and Agent 7's chronology and coverage checks do not detect it (they test order and coverage only).

I recommend **S3 for a first round, to test the plumbing at no data cost, and S1 for any claim about a realistic follow-up**.

### 4.2 The round

The runner stays a function of one snapshot; the caller holds the state, as with the `AssessmentLog`. The state is: the current `Snapshot`, the `AssessmentLog`, the list of requests, results and coverage rows so far, the evaluator-side service and the scenario manifest.

1. **First pass.** Run the runner on the window as today. It returns Agent 5 hypotheses, Agent 6 options (narrowed as in section 1.3, which needs a change in the caller or in the builder, not in the contract), the Agent 7 report with no results, and the Agent 8 decision.
2. **Choice.** A fixed policy of the caller stands in for the human: take the first hypothesis that names a catalogue asset; choose the action by mechanism (leak: ACT-INSP-04 on the pipe edge; restriction or misrouting: ACT-INSP-02 on the valve; pump head loss: ACT-INSP-03 on the pump; pressure-transmitter fault: ACT-INSP-07; level-transmitter fault: ACT-INSP-05 on the tank); one action per round; no use of any label. If no hypothesis names an asset, there is no follow-up and the window stays where it is.
3. **Request and approval.** The caller builds an `inspection_request` whose `justification` lists at least two competing hypotheses from Agent 5, the cost from the catalogue and the information gain from Agent 6 (null becomes 0.0). The approval emulator decides; its 5% non-safety rejection and its rejection for failed work conditions are kept, because a rejected request is a scenario in its own right. The request id comes from a counter of the caller, never from an outcome.
4. **Simulated result.** The result is generated from the inspection truth by the existing models (section 4.3), through the service and its gateway allowlist, and registered with the provenance `simulated_inspection`. The scenario label is written only to the evaluator-side manifest.
5. **Second pass.** `next_revision` makes a new snapshot with the result, the request and a process-coverage row (a row for the target asset that covers the performed time and cites registered observation evidence), plus constraint checks derived from the observation window for the preconditions it can show, and the approved request for the permit-like ones. The caller also builds one evidence proposal for the result (`inspection_result:<id>`, its availability time, its registered evidence ids). The `AssessmentLog` continues. Agents 5 to 8 run again.
6. **Final report.** The maintenance report shows the hypotheses (still unconfirmed), the options (now one or two with a feasibility other than `unknown`), the performed inspection and its record checks, the Agent 8 decision and its missing-information and limitation lines. It has no field for the content of the finding beyond what Agent 7 and Agent 5 pass on; it must not state a condition.

### 4.3 Scenarios, generated from the truth and labelled

Each scenario is a draw of the existing outcome model on the true state at the performed time, with the service's random stream for the request. In the default mode (the qualified one) the outcomes are:

| scenario | how it is generated | what the agents will see |
|---|---|---|
| confirming | the target is the faulty asset; valve check (restriction) reports a measured pressure drop and stem travel consistent with a partly closed valve; calibration reports the true offset of the transmitter; dip reports the tank level | numbers in line with the hypothesis, but `evidence_status: low_confidence` and category `TEST_INCONCLUSIVE`; Agent 7 judges the record unusable. A `valid` confirmation exists only in research mode (acoustic detection of a leak, pump vibration) |
| refuting | the target is a healthy asset (a wrong hypothesis); the same models on the healthy state | numbers consistent with a healthy asset, with the same `low_confidence` marking |
| inconclusive | acoustic survey of a leak below the detection limit (probability 1 / (1 + (0.9 / q)^2), `models.py:178-205`); any action in the unqualified set (`measurement_available`, status `missing`); a rejected or cancelled request | `TEST_INCONCLUSIVE`, status `missing` or `low_confidence`, or no result |
| noisy or wrong | the measurement noise of the model (standard deviation U / 2) enlarged by a stated factor; or `validation_status` set to `FLAGGED_INCONSISTENT` or `RETEST_REQUIRED`; or `evidence_status: contradictory`; or `calibration_valid_until` before the assessment date; or a result generated from the truth of another asset | Agent 7's validation, calibration or source-quality checks fail and the record is unusable |

None of the scenario names enters a message. The manifest, which stays on the evaluator side, records for each round the episode, the window, the scenario, the true fault, the seed and the choice made.

### 4.4 Contract changes

None are needed. `inspection_results`, `inspection_requests`, `process_coverage`, `constraint_checks`, `evidence_proposals`, `workflow_requests` and `result_evidence_ids` are existing inputs, and the evidence kinds and the provenance label `simulated_inspection` already exist. What is needed is code outside the contract: a builder or caller step that narrows the targets, a caller step that derives constraint checks from the observation window, a caller-side adapter that builds requests, proposals and coverage rows, a loader for the inspection truth restricted to validation episodes, and an evaluator-side manifest. One open item may need a contract change: nothing in an agent response says that the result is simulated or that the workflow was compressed except the provenance label of the evidence row. If the final report must state it, the cheapest carrier without a schema change is a line in `findings.secondary_observations` of the result (free text); whether the report prints it has to be checked.

### 4.5 Risks of leaking labels into the agents

1. **Choosing the target from the label.** The target must come from the first-pass outputs only. A test that the choice is a function of the stored first-pass bundle alone would pin it.
2. **Rejection reasons** are computed from the true state at the decision time and are visible. They are part of the existing workflow, but they should be recorded in the manifest and not tuned.
3. **`Record.outcome.true`** and `service.record()` are evaluator-side. The adapter must use only `results()` and `requests()` views.
4. **The random stream** depends on the seed and the request id. If a caller could choose request ids after seeing outcomes, it could choose favourable draws. The id must come from a counter.
5. **Scenario naming in free text**: no note, justification or secondary observation may carry the scenario or the fault.
6. **Split leakage.** The campaign folder holds the test episodes' inspection truth next to the others. The loader must be given the validation episode ids and must refuse anything else; the audit hook has to be extended to that folder.
7. **Tuning on the follow-up.** Changing Agents 5 to 8 after seeing second-pass outcomes on the same validation windows would turn the follow-up into training data. The rules of a round should be fixed before it runs.
8. **Identifiers.** Episode ids and file names must not enter requests (`FORBIDDEN` keys).

## 5. Which of the 181 windows would give a meaningful follow-up

A follow-up is meaningful when the fault sits on an asset that the catalogue can inspect and Agent 5 names that asset, so that the choice is made from first-pass output. The 93 faulty windows of the sample:

Faulty windows by follow-up class:

| class | windows |
|---|---|
| fault asset has no catalog action | 5 |
| inspectable, Agent 5 names it first | 30 |
| inspectable, Agent 5 names no catalog asset | 48 |
| inspectable, Agent 5 names other assets only | 2 |
| several injected components | 8 |

The same by injected mechanism:

| class | mechanism | windows |
|---|---|---|
| fault asset has no catalog action | drift | 3 |
| fault asset has no catalog action | stuck | 2 |
| inspectable, Agent 5 names it first | misroute_a | 6 |
| inspectable, Agent 5 names it first | pump | 9 |
| inspectable, Agent 5 names it first | restriction_obstruction | 2 |
| inspectable, Agent 5 names it first | restriction_position_visible | 12 |
| inspectable, Agent 5 names it first | stuck | 1 |
| inspectable, Agent 5 names no catalog asset | bias | 14 |
| inspectable, Agent 5 names no catalog asset | drift | 9 |
| inspectable, Agent 5 names no catalog asset | leak | 12 |
| inspectable, Agent 5 names no catalog asset | misroute_a | 1 |
| inspectable, Agent 5 names no catalog asset | pump | 2 |
| inspectable, Agent 5 names no catalog asset | restriction_position_visible | 1 |
| inspectable, Agent 5 names no catalog asset | stuck | 9 |
| inspectable, Agent 5 names other assets only | pump | 2 |
| several injected components | several | 8 |

The windows whose fault Agent 5 names first, by the action that would inspect them and what the default inspection model returns:

| action | outcome of the default inspection model | windows |
|---|---|---|
| ACT-INSP-02 | measured, low confidence | 20 |
| ACT-INSP-03 | unavailable | 9 |
| ACT-INSP-07 | measured, low confidence | 1 |

- **30 windows** are meaningful: the fault is on an inspectable asset and Agent 5 names it first (9 pump, 14 restriction, 6 misrouting, 1 pressure-transmitter fault). 2 more name only other assets, so the inspection would be aimed at the wrong place.
- **48 windows cannot be followed up from first-pass output** although the fault is inspectable: 12 leaks, 14 biases, 9 drifts and 9 stuck readings, a pump and a restriction among the rest. Agent 5 gives no asset for them, so the choice would need the label or a sweep of 28 pipe edges at 350 USD each.
- **5 windows** (drift or stuck of a flow meter) have no catalogue action: flow meters are not catalogue assets. **8 windows** have several injected components.
- Of the 30, **21 have a modelled action** in the default mode (valve check 20, transmitter calibration 1), whose results are `low_confidence`; **9 pump windows** have an action whose model is unqualified, so the result would say that the measurement is unavailable.
- **0 of the 93 faulty windows** leave room for the inspection and a second pass inside the recorded process (section 4.1). Meaningful windows exist only under S1 or S3.
- Among the 88 fault-free windows, 2 have a hypothesis that names a catalogue asset, so the narrowed Agent 6 would offer an option there and the round would send an inspection to a healthy asset (a refuting case by construction); the other 86 would have nothing to inspect.

## 6. Recommendation

1. **Do not start with a full second-pass loop.** Two findings limit what it can show before any code is written: the recorded episodes are too short for a realistic inspection workflow (zero faulty windows have room), and in the default mode no inspection result is `valid`, so Agents 7 and 8 cannot leave their degraded states whatever the scenario.
2. **Do the runner-side narrowing first (no new data).** Pass the implicated assets (not all 49) to Agent 6, derive the observation-based constraint checks, and let the caller supply the approved request after the choice. Expected effect on the sample: 38 windows get 1 or 2 options with a real addressed hypothesis instead of 55 unknown ones, and the report stops listing 55 options. This changes the final report and nothing in the contract.
3. **Then run S3 on the 30 meaningful windows as a plumbing and behaviour test**, labelled as a compressed workflow, in the default mode, with the four scenarios of section 4.3, and read what Agents 5 to 8 and the report do. Expect Agent 7 to mark every default-mode record unusable and Agent 8 to stay in review or more-evidence states; that is the correct reading of the current qualification, and it should be the stated result of the test.
4. **Decide the qualification question before any claim.** To reach `assessment_available` through a follow-up, an inspection model must produce `valid` evidence, which means qualifying a model (the pump vibration or the acoustic survey or tolerances for the valve, dip and calibration checks) or running the research mode with an explicit, visible label. That is a project decision, not a runner change.
5. **Use S1 (extended companion episodes) only for a realistic workflow study**, after checking that the first 3,600 s of an extended run reproduce the stored observations, and only for validation episodes.
6. Contract changes: none are needed for steps 2 and 3. The one open question is how the report states that a result is simulated and that the workflow was compressed.

## 7. Data read and one slip

The design needed no data content. The files used are code, schemas, configuration, the stored bundles of the earlier sample run, and directory listings (names only) of the release evaluator folder, one validation episode folder and the campaign evaluator folder. The slip: while looking for the format of the release's inspection records I printed the first 1,500 bytes of `inspection_records/source_00/inspection_quality.jsonl`. That file mixes splits and its first record is a **test-split** row. I saw the first record in full and the start of the second (field names and values of manual-dip exercises). Nothing from it was used here, and the structure of the file is described above from the code that writes it (`training/inspection_records.py`) and from the documentation. It is reported so that it can be judged: no test-split label of a window used in any evaluation was seen, but a test-split file was opened, outside the audit hook.
