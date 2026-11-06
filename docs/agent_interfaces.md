# Verum Agent Development Guide

## Start here

This is the build plan for our eight Verum agents. Each agent has a defined job, input, output, implementation method and test plan below. An agent is a software component; it does not automatically need an LLM or its own trained model. We will train numerical models where our data supports them and use explicit checks and lookups for the other jobs.

The interfaces and example messages are supplied. The agents, training programs, connected runner and frontend still need to be built. The model families below are candidates to compare, not claims that a winning model has already been trained. No new simulation data is required for this plan.

| Agent | Main implementation | Owner |
| --- | --- | --- |
| 1 Predictive Health | Learned forecasting model | Member 1 |
| 2 Anomaly Detection | Learned physical detector plus data-quality rules | Member 2 |
| 3 Topology and Dependency | Graph queries, no learned model required | Member 3 |
| 4 Historical and Asset Intelligence | Source-backed retrieval, no learned model required | Member 3 |
| 5 Diagnostic Reasoning | Learned fault classifier plus evidence comparisons | Member 4 |
| 6 Inspection Planning | Catalogue filtering and requirement checks | Member 5 |
| 7 Inspection Quality and Documentation | Record checks and structured report assembly | Member 5 |
| 8 Evidence Verification and Decision | Evidence checks and assessment rules | Member 4 |

Member 3 also owns the common data adapter and runner. Everyone starts with the supplied example messages; nobody needs to wait for another member to finish training. Member numbers are assignments for us to allocate to names, not existing usernames.

Read the shared data rules next, then your agent pages. Everyone reads the report workflow and completion checklist. The JSON schemas are the exact field reference; the guide explains what to build inside them.

## Shared data and model rules

### Where the data is

Use data/reference_release_v2/verum_reference_v2/ as the working release. Paths below are relative to that folder. The full ZIP already contains the readings and prepared examples; do not generate replacement simulations.

| Data | What to use it for |
| --- | --- |
| observations/ | The 87,529,784 individual hydraulic readings, including timing, units and quality flags. Use these for sequence inputs or investigations. |
| role_views/ROLE/train.jsonl.gz | Prepared inputs and targets for that role. Substitute its exact role key from its page. |
| role_views/ROLE/validation.jsonl.gz and test.jsonl.gz | Select models and settings on validation; report final results on untouched test data. |
| examples/ and release_manifest.json | Match each snapshot and existing target to its source episode and prediction time. |
| knowledge/public_reference.json and inspection_records/ | Declared assets, reference facts and available simulated inspection records. |

The 180,339 role records include different views of the same snapshots, reference queries and record checks. They are not 180,339 independent faults. The 87 million readings provide the underlying detail; they are not individually labelled examples and must not all be placed in training. The 3,000 hydraulic episodes are already split into 1,660 train, 756 validation and 584 test episodes. Keep those splits, including parent groups of paired roof references.

### Prepare model inputs correctly

For summary models, use only the role record's input.observations. Extract channels in a saved, stable tag and feature order. Preserve missing and quality indicators. Fit scaling and imputation on training data only; a training-fitted statistical replacement is an input-processing choice, not a claim that a missing measurement was observed. Keep missing targets masked.

For sequence models, read release_manifest.json to locate the episode's observations and shared examples. For each example, use its recorded source_cutoff_s and only readings whose t_available_s is in the preceding 300 seconds and no later than that cutoff. Preserve measurement time separately from availability time. Pad batches with an explicit padding mask; do not treat padding as measured zero. Reuse the example's existing target and split. Read episodes incrementally instead of loading 87 million rows into memory. A sequence loader still needs to be implemented.

Never put target, use, supervision masks, hidden truth, episode identifiers, source file names or absolute simulation clocks into learned features. Those fields may select eligible examples or track provenance outside the model. Do not shuffle windows into new train/test splits. Multiple reports derived from one reading are correlated evidence, not separate confirmations.

### Compare models and record the result

For Agents 1, 2 and 5, compare a reference baseline, a simple learned model and one stronger tabular model using validation results and runtime. Try a sequence network only for a demonstrated gap.

Record model, features, eligible counts, settings, named seed stream, validation metrics, runtime and selection reason. Use named seeded streams, not a global seed. Freeze preprocessing, thresholds and model before final test evaluation. Simulator performance does not establish industrial accuracy.

## Agent 1 Predictive Health

Role key: predictive_health. Owner: Member 1. This agent forecasts what the instruments will report, so the system can show a near-term trend. It does not estimate remaining equipment life.

| Part | Exact build requirement |
| --- | --- |
| Input | input.observations, target_tag_ids and forecast_horizon_s equal to 300. Observations use the agreed summary or sequence wrapper. |
| Training data | role_views/predictive_health/. Use target.future_measurements for each channel only when target.supervised_loss_mask is true and a usable target exists. |
| Learned model | Regression: map the preceding five-minute observations to each requested channel's reported mean over the next five minutes. |
| Output | result.forecasts containing tag_id, unit, quantity, horizon_s, value, interval, evidence_ids and limitations. Keep health_score and remaining_useful_life null. |

### Build and compare

1. Build a persistence baseline: predict the next window mean using that channel's current available window mean. If it is unavailable, return an unavailable forecast; do not invent a value. Compare models on the same eligible targets and report coverage separately.

2. Train Ridge regression on the prepared summary features. Fit preprocessing using train only. Train a separate regressor per target channel so different target availability can be handled correctly.

3. Compare with RandomForestRegressor or HistGradientBoostingRegressor using the same allowed features and eligible targets. Keep one trained output per sensor, or use a multi-output wrapper only when its training rows have all required targets. Never fill missing labels to make a rectangular target matrix.

4. If temporal patterns remain a clear weakness, compare a GRU or LSTM using existing raw windows. These are learned sequence models, not LLMs. This requires the sequence loader, padding masks and the same evaluation targets; do not change the task to obtain better scores.

### Test and deliver

Report MAE and RMSE for each sensor with its unit, eligible target count and prediction coverage, alongside persistence. MAE is average absolute error; RMSE puts more weight on large errors. Do not average metres, pressure and temperature errors into one unexplained number. Compare operating/fault groups through evaluation metadata outside the model.

Return an uncertainty interval only if it has been calibrated and its coverage tested using held-out validation data; otherwise interval is null. Do not label an arbitrary band as 95 percent confidence. Deliver the model, preprocessing, feature/tag order, comparison table and run adapter.

The supported output is a five-minute interval mean. The supplied targets do not support an hour-ahead claim, a failure timestamp or guaranteed advance warning of an independently injected fault.

## Agent 2 Anomaly Detection

Role key: anomaly_detection. Owner: Member 2. This agent distinguishes problems in the readings from patterns associated with supported injected physical changes. An anomaly means something needs attention, not that a specific fault is proven.

| Part | Exact build requirement |
| --- | --- |
| Input | input.observations and optional forecast_report from Agent 1. It must also work when forecast_report is null. |
| Training data | role_views/anomaly_detection/. Quality counts are in target.data_quality. Physical labels and their eligibility mask are under target.reference_supervision. |
| Learned model | Binary physical-reference classifier using observations. Quality checks are explicit rules, not a learned model copying visible counts. |
| Output | result.events with event_id, tag_ids, asset_ids, category, score, method_id, evidence_ids and limitations; also coverage and no_event_means_healthy false. |

### Build and compare

1. Implement deterministic quality events for missing readings and non-good quality flags. Preserve what the source flag actually means. These checks can be tested against data_quality, but recovering visible missing counts is not evidence of physical fault detection skill.

2. For physical detection, make a binary label from the eligible reference_supervision record's injected_change_present. Apply its nested supervised_loss_mask. A masked or unknown label must not become a healthy negative.

3. Evaluate an always-negative reference baseline to expose class imbalance. Train LogisticRegression with training-fitted preprocessing, then compare RandomForestClassifier or HistGradientBoostingClassifier. The baseline is an evaluation reference, not permission to declare quiet equipment healthy.

4. Select the operating threshold on validation. If exploring an unsupervised alternative, IsolationForest must be fitted on eligible healthy training records only and evaluated against the same physical labels. Try a sequence autoencoder only if this comparison establishes a useful reason; its reconstruction score is not automatically a calibrated probability.

### Test and deliver

Report precision, recall, PR-AUC and the confusion matrix for eligible physical labels, including positive/negative counts. Precision asks how many alarms are correct; recall asks how many supported changes are detected. Also report false alarms and missed detections by episode and mechanism. Separate reading-quality results from physical results.

Start the physical model with observation inputs only. If a forecast is present at runtime, compare it through a separately labelled rule or method. Do not train on Agent 1's ideal future targets as though they were its predictions. A learned forecast-residual detector would require realistic held-out upstream predictions and its own evaluation; it is not supplied by this dataset.

The event categories are missing_reading, non_good_quality, reported_signal_departure and supported_physical_reference. Use null for an unsupported score; expose a calibrated_probability only after calibration. Deliver model/preprocessing, threshold selection, metrics and missing-forecast tests.

## Agent 3 Topology and Dependency

Role key: topology_dependency. Owner: Member 3. This agent answers which assets are declared connected and which paths may matter to an investigation. It supplies structural context to diagnosis.

| Part | Exact build requirement |
| --- | --- |
| Input | query_asset_ids, direction, declared_connections, reference_evidence_ids and optional observations. Each declared connection has edge_id, from_node and to_node. |
| Reference data | role_views/topology_dependency/ and the public reference graph. There are 49 reference queries per split, not a large independent graph-learning dataset. |
| Learned model | None required. Use deterministic graph queries. |
| Output | direct_connections, reachable_nodes, routing_assessment, actual_routing_confirmed false and evidence_ids. |

### Build in this order

1. Load only the declared graph supplied to the agent. Build forward and reverse adjacency maps while preserving original edge and node identifiers. Return a useful missing-asset result for an unknown identifier.

2. Implement direct-neighbour lookup as the baseline. Add breadth-first or depth-first traversal for upstream, downstream or both directions. Keep a visited set so a loop cannot cause an endless traversal. Sort output deterministically.

3. Return source-linked connections and reachable nodes. If reported equipment states are used to discuss a possible route, identify their quality and uncertainty. A command or reference drawing does not prove the current physical valve position.

4. Do not add a GNN or LLM just to call this an agent. A learned graph model would need an independently evaluated task that the exact graph queries cannot already answer.

### Test and deliver

Test a single edge, a multi-edge path, reversed direction, a disconnected asset, unknown identifiers, duplicate edges and a graph loop. Every returned edge must exist in the supplied graph; every reachable node must have a valid path in the requested direction.

Compare exact sets of edges and nodes against the supplied fixtures and hand-checked small graphs. Keep structural correctness separate from actual routing confirmation. Return declared_only when only the declared layout is known; use ambiguous or unknown when appropriate.

Deliver the graph loader/query functions, the agent adapter and query tests. No trained model file is expected. Member 3 also supplies the shared runner, but Agent 3 itself should remain a small independently testable component.

## Agent 4 Historical and Asset Intelligence

Role key: historical_asset_intelligence. Owner: Member 3. This agent finds supplied asset facts and records and returns their sources. It does not create a maintenance history from engineering assumptions.

| Part | Exact build requirement |
| --- | --- |
| Input | query_asset_ids, assets, declared_facts, history and reference_evidence_ids. Facts include their field_path, value, unit, source_locator, parameter_status and evidence_ids. |
| Reference data | role_views/historical_asset_intelligence/, public_reference.json and genuinely available history records. There are 49 reference queries per split. |
| Learned model | None required for the supplied structured asset catalogue. Use indexed retrieval. |
| Output | asset_records, facts, history, history_status, missing_asset_ids and evidence_ids. |

### Build in this order

1. Index records by asset_id. Retrieve exact matching asset records and source-bearing facts. Preserve units, pressure basis, parameter status and source text. An unresolved value remains unresolved.

2. Filter to the requested assets and fields. Do not return facts for a similarly named asset as an exact match. Return missing_asset_ids for absent records.

3. Return only history actually supplied and available at the analysis time. Use no_verified_past_maintenance_supplied when appropriate. Simulator records must remain labelled as simulated; they are not industrial service records.

4. Start with exact lookup. Add keyword or TF-IDF retrieval only if the team introduces a real unstructured reference corpus and can test source retrieval. Embeddings or an LLM are optional future retrieval tools, not a requirement for these structured files. Do not fine-tune on repeated copies of the same 49 queries.

### Test and deliver

Test known and unknown assets, two similar identifiers, missing history, unresolved parameters, absent units and future-dated records. Check exact asset matching, source preservation, missing-information handling and whether every returned fact occurs in the provided input.

Do not convert a design selection into a measured operating state or a field-qualified rating. Roof reference facts can describe the selected configuration; they cannot supply missing roof strength, damaged-emission factors or an unsupported structural diagnosis.

Deliver the retrieval index/loader, field filtering, provenance tests and adapter. No trained model file or external API key is required.

## Agent 5 Diagnostic Reasoning

Role key: diagnostic_reasoning. Owner: Member 4. This agent proposes supported explanations for observations, then compares them with available evidence. A candidate explanation remains a hypothesis until evidence supports it.

| Part | Exact build requirement |
| --- | --- |
| Input | observations and optional forecast_report, anomaly_report, topology_report, asset_report and inspection_quality_report. |
| Training data | role_views/diagnostic_reasoning/. Use target.injected_change_present and injected_components only where target.supervised_loss_mask is true. |
| Learned model | Observation-based classification of supported injected changes. Multi-label classification allows more than one component instead of forcing one mutually exclusive fault. |
| Output | hypotheses with components, score, support_evidence_ids, conflict_evidence_ids and unresolved_questions; also assessment, upstream_checks, ranking_basis and field_diagnosis_qualified false. |

### Build and compare

1. Build labels from the eligible training components only. Supported names are leak, restriction_position_visible, restriction_obstruction, pump, bias, drift, stuck and misroute_a. Inspect actual class support before fitting. Do not add roof failure, vapour damage or a mechanical cascade label.

2. Establish constant-label evaluation baselines. Train a simple observation model: LogisticRegression for change presence and one-versus-rest LogisticRegression for supported component labels. Compare a multi-output RandomForestClassifier or one binary HistGradientBoostingClassifier per supported label.

3. Handle labels with no positive training cases explicitly as unsupported learned outputs; do not invent examples or claim their detection is learned. If predicting asset/tag locations, train and evaluate that as a separate target with its own support counts. A mechanism prediction alone does not justify filling an asset identifier.

4. Keep comparison with other agents outside the learned model. Check graph membership, matching source facts, usable inspection results and conflicting observations through named rules. Populate the five upstream_checks entries even when the corresponding report is missing; missing means unknown. Do not multiply correlated model scores or invent confidence bonuses for agreement.

### Test and deliver

Report per-label support, precision/recall/F1, micro and macro F1, and exact-set accuracy. Evaluate change detection and localisation separately. If there are too few examples for a claim, state that limit. Empty components can be a training negative; an empty runtime hypothesis list is not independent proof of healthy equipment.

The hydraulic training subset has 9,832 eligible diagnostic windows, including 1,253 positive windows; overlapping windows are not independent failures. Keep the existing split. Test observation-only operation before connecting reports, then test missing/conflicting reports and stale analysis contexts.

Deliver classifier/preprocessing, label mapping, supported-class list, thresholds, metrics, rule comparisons and adapter. No learned stacking on ideal upstream labels is included in this plan.

## Agent 6 Inspection Planning

Role key: inspection_planning. Owner: Member 5. This agent proposes available inspections that could help investigate a candidate, while showing feasibility and limits. It does not approve, dispatch or perform work.

| Part | Exact build requirement |
| --- | --- |
| Input | diagnosis_report, catalog, catalog_evidence_ids, observations, constraint_checks, budget, target_asset_ids, assets and workflow_requests. Optional reports stay null when absent. |
| Reference data | role_views/inspection_planning/ and the seven catalogue actions. These are action fixtures, not expert-labelled optimal decisions. |
| Learned model | None required. Use catalogue filtering and explicit requirement checks. |
| Output | options with action_id, target_asset, addressed hypotheses, feasibility, checks, cost, duration, information-gain fields, limitations and evidence_ids; also selection_policy_id, recommended_option_id and dispatch_authorized false. |

### Build in this order

1. Retrieve actions that support the requested asset kind and target. Copy their exact documented costs, durations, outputs and requirements. Do not infer that an unmodelled output is available.

2. Evaluate each requirement as satisfied, failed or unknown from available evidence. A missing pressure measurement cannot satisfy a pressure requirement. Use the catalogue's documented limits; do not introduce typical operating thresholds.

3. Apply explicitly supplied budget and duration limits. Record why an option is blocked or unknown. Among eligible options, a documented cost/time ordering is a baseline selection policy, not a claim of optimal diagnostic value. Keep recommended_option_id null when no justified recommendation exists.

4. Preserve null expected_information_gain_bits and information_gain_method_id when there is no supported estimate. The current data does not supply an optimal policy or outcome likelihoods for learning information gain. Reinforcement learning or an LLM planner would not resolve that missing evidence.

### Test and deliver

Test all seven catalogue actions, wrong asset kinds, unknown requirements, failed requirements, insufficient budget, repeated requests and unavailable diagnosis. Check every returned action/target/cost/duration against the provided catalogue and show selection reasons.

The existing inspection submission API requires a numerical information-gain estimate and at least two competing hypotheses. A proposal with unknown information gain must report this submission blocker. Do not insert zero or invent a second hypothesis to get past the API. The advisory proposal can still be displayed for human review.

Deliver the catalogue adapter, requirement evaluator, selection policy, blocked/unknown tests and agent adapter. No trained policy file is expected.

## Agent 7 Inspection Quality and Documentation

Role key: inspection_quality_documentation. Owner: Member 5. This agent has two separate jobs: check inspection evidence, and prepare a structured maintenance assessment report. The report describes available findings and proposed work; it is not a claim that maintenance has been completed.

| Part | Exact build requirement |
| --- | --- |
| Quality input | inspection_results, result_evidence_ids, catalog, catalog_evidence_ids, process_coverage, observations and inspection_requests. Only performed and available results may be consumed. |
| Quality output | record_checks with measurement_usable, scope_supported and equipment_condition_confirmed false; observed_quality and retest_result_ids. |
| Report input | After Agent 8 finishes, use validated same-analysis reports, their evidence registry and Agent 8's assessment. This is a separate build_report operation, not a new input field silently added to run. |
| Report output | Structured JSON matching contracts/reports/maintenance_report.schema.json. The frontend renders this JSON as a report and exports PDF. |
| Learned model | No quality classifier or report fine-tuning is needed. Start with explicit checks and templates. Optional Cohere wording uses a pretrained LLM. |

### Build in this order

1. Implement record checks for request/result linkage, performed status, availability, required fields, supported units, uncertainties, process coverage and source quality. An incomplete result may require retesting; it does not confirm equipment condition. Preserve distinctions between usable, unusable and unknown.

2. Test quality checks against role_views/inspection_quality_documentation/. Distinguish ordinary observation-quality records from inspection-record examples using the stored use field. There are only 12 covered inspection records across all splits, so this is not enough to justify a learned inspection-condition model.

3. Implement a separate report assembler after Agent 8's assessment. Copy source facts, proposed hypotheses, inspection options, caveats and next steps into the report fields. Cite the source report and evidence for each item. Start with deterministic wording templates so it works offline.

4. If the team wants more natural wording, add Cohere only for the optional narrative field. Keep identifiers, measurements, units, findings, recommendations and assessment fields under application control. Reject unsupported wording and fall back to the template on errors. The next reporting pages specify this boundary.

### Test and deliver

Test non-performed results, unavailable results, missing fields, unsupported measurements, missing evidence, explicit unknowns and retest needs. For reports, test exact copying of values/units, correct analysis revision, valid JSON, missing-agent sections and source citations. No report may present a proposed inspection as already performed.

Deliver the quality checker, report assembly function, templates, report contract validation and adapter. If Cohere is added, also deliver its server-side wrapper, prompt/version record, fallback tests and configuration instructions. There is no report-writing training corpus or completed maintenance-report ground truth in this release.

## Agent 8 Evidence Verification and Decision

Role key: evidence_verification_decision. Owner: Member 4. This agent checks whether the available evidence supports an assessment and what still needs human review. It supplies the decision section used in Agent 7's report.

| Part | Exact build requirement |
| --- | --- |
| Input | diagnosis_report, inspection_plan_report, inspection_quality_report and evidence_proposals. Each proposal includes its source reference, claimed availability and evidence identifiers. |
| Evaluation data | role_views/evidence_verification_decision/ and connected report fixtures. Check use because record subtypes differ. |
| Learned model | None required. Implement explicit evidence-admission and assessment rules. No LLM makes the final decision. |
| Output | decision_state, summary, hypothesis_report_ids, evidence_checks, conflicts, next_steps, human_decision_required true, automatic_action_authorized false and equipment_condition_confirmed false. |

### Build in this order

1. Check each proposed item against the available evidence registry: identity/checksum, actual availability by the analysis cutoff, quality and supported scope. Proposal metadata may name a future item, but its future contents are not available evidence.

2. Record time_admissible, provenance_verified, quality_acceptable and scope_supported separately. A failed required check makes an item unusable; unknown required checks keep usability unknown. A valid hash establishes identity, not physical truth.

3. Check that all consumed agent reports belong to the same case, analysis, revision, cutoff and reference snapshot. Trace derived evidence to its original roots. Do not count Agent 1 and Agent 2 reading the same sensor as independent physical confirmation.

4. Implement a documented decision table: missing required evidence leads to more_evidence_required; unresolved conflicts needing judgement lead to review_required; no useful supported assessment leads to inconclusive; a completed supported assessment may be assessment_available. Define precedence for overlapping cases and test it. Human review remains required for every state.

### Test and deliver

Test future/unregistered evidence, changed checksums, low-quality and out-of-scope items, conflicting diagnoses, missing inspection results and repeated evidence roots. Compare each individual admission flag with the fixture target where that target is supplied. Include hand-written cases for combinations absent from the release.

An evidence item's usability is not a diagnosis, and completing checks does not establish healthy equipment. The summary must preserve unresolved hypotheses and avoid instructions that operate plant equipment automatically.

Deliver the verification rules, decision table, traceable assessment, tests and adapter. Agent 8 does not produce PDF or call a text model. Its validated response is passed to Agent 7's separate report assembler.

## Report JSON and frontend responsibilities

### How the report is produced

The normal analysis runs Agents 1, 2, 3 and 4; Agent 7 checks any available inspection evidence; Agent 5 proposes diagnoses; Agent 6 proposes inspections; Agent 8 verifies the combined evidence. Agent 7 then runs build_report on those completed messages. This final formatting step does not feed another diagnosis pass or create a ninth agent. A newly available inspection starts a new analysis revision.

The runner owner prepares one validated report bundle and passes it to the documentation owner. It contains the current context, available validated agent responses and evidence registry. The documentation owner must reject mixed-analysis messages and verify the hashes and evidence links before assembly. The separate report schema defines the output shape; it does not by itself prove that every written claim is true.

| JSON field | What the backend supplies and the frontend shows |
| --- | --- |
| report_version, report_id, context | Report identity, case, analysis revision and time. Preserve the existing context fields. |
| report_type, title, review_status | A maintenance assessment, clearly awaiting human review. |
| source_reports | Identifiers, agent role keys and canonical content hashes of the actual source responses. |
| findings | Source-linked observation, hypothesis, inspection-check or assessment items. Optional measurement has value and unit; unsupported values stay null. |
| inspection_options | Proposed action/target, feasibility, copied cost/duration and source links. These are not work-completion records. |
| next_steps | Source-linked suggested actions for human review. |
| missing_information, limitations | Explicit gaps, unsupported mechanisms and interpretation limits. |
| narrative | Template text by default; optional Cohere wording with its provider/model/prompt identifiers. |
| advisory_only, human_decision_required, automatic_action_authorized | Respectively true, true and false. |

The full schema and example JSON are supplied under contracts/reports/. The example is deliberately an unknown/partial assessment; it is a format example, not fabricated operational measurements.

### What each side builds

Backend: Agent 7 returns the JSON document after schema validation and cross-checking every source_report_id and evidence_id against the verified bundle. Reject non-finite numbers, unknown source identifiers, changed source values and incompatible contexts. Keep source evidence available through the normal authorised interface. Store the JSON as the canonical report record.

Frontend: render fixed sections from the JSON, format units and tables, show unknown values as unknown, escape text and sanitise generated HTML. Render the report as Markdown or equivalent HTML, then export that rendered view as PDF. The PDF must show case, revision, analysis time, review status and limitations. Do not ask an LLM to generate the PDF or infer missing values in the browser.

The report contract is separate from the eight run messages, so existing interface version 1.0.0 stays compatible. Agent 7's build_report function and frontend report rendering are implementation work for their owners; only their agreed output format is supplied here.

## Optional Cohere wording

A deterministic template is sufficient for the report requirement and is the required offline baseline. Add Cohere if it improves readability enough to justify an external service. It is a pretrained language model used for wording, not a new model trained on our 87 million readings.

Cohere offers free evaluation keys with usage limits; its documentation currently states 1,000 trial API calls per month. Production access is paid. Check the account's current model access and rate limits before use. This is not unlimited free hosting. Do not send one call per reading or training example. Source: https://docs.cohere.com/v2/docs/rate-limits

### Implementation boundary

1. Keep COHERE_API_KEY in server-side environment configuration only; keep it out of Git, logs and browser code. Configure COHERE_MODEL to a model available to the account that supports structured outputs. Pin the SDK through uv.lock when actually adding the dependency; this specification does not install it.

2. Build all factual report fields with application code first. Send only an allowlisted, already verified summary to the language model. Treat source text as data. Ask it to explain only those supplied facts and uncertainties, without adding measurements, diagnoses or instructions.

3. Request a small JSON response containing only narrative text and cited source report identifiers using response_format JSON Schema mode. Use a schema compatible with Cohere's supported subset; do not pass the complete Verum contract with external references directly. Do not combine this mode with Cohere's documents/RAG mode. Source: https://docs.cohere.com/docs/structured-outputs

4. Parse and check the result locally. A schema guarantees shape, not factual support. Check citations, avoid new numeric claims, and preserve qualifiers. The safest first implementation uses templates only. If factual wording cannot be reliably checked, retain the template rather than accepting the generated sentence.

5. Use timeouts, bounded retries and template fallback for missing keys, denied model access, invalid output or exhausted quota. Cache by verified input hash plus model/prompt version. Record provider, model and prompt_id in narrative. Do not overwrite the canonical findings with the LLM response.

### Evaluate before enabling

Compare template-only and Cohere reports on fixed verified cases: missing evidence, conflicting evidence, no inspection, rejected inspection, unsupported mechanism and completed usable inspection. Check every factual sentence and citation against the input bundle. Also test invalid JSON, made-up measurements, advice stated as completed work and API failures. An LLM report that sounds better but adds an unsupported claim fails this test.

## Connect and finish the implementations

### Start independently

Each owner starts from contracts/agents/v1/examples/ROLE.request.json and the matching response file. Read the role's schema for exact allowed fields. The example responses are conservative placeholders; they are not model predictions or labels. Everyone builds the same call shape:

```python
response = agent.run(request)
```

Before inference, call validate_request(request); before returning, call validate_response(request, response), imported from verum.contracts.agent_interfaces. Agent 7's additional report assembly is a separate operation using the reporting contract. Do not change shared field names to fit one member's private code.

Use complete when processing finished, degraded for useful partial output, insufficient_evidence when no useful supported result can be produced, and error for a computation failure. Complete does not mean healthy. Keep unavailable upstream reports null. Keep numerical decision scores distinct from calibrated probabilities and include the method identifiers required by the schema.

### Shared runner and evidence

Member 3 builds the observation adapter once, using the exact summary_v1 or sequence_v1 wrapper, and supplies shared context and source evidence. All owners use the same adapter rather than implementing different timing and unit rules. Preserve original source roots and hashes. Software metadata is outside the learned feature matrix.

Connect the real agents in the report workflow order. If Agent 1 fails, Agent 2 and Agent 5 must still handle missing forecasts. If no inspection exists, Agent 7 reports that limit and Agent 8 can request more evidence. Validate at every boundary before passing reports onward. Keep automatic action flags false.

### Checks already available

Run from the repository root after pulling the source changes:

```bash
uv run python tools/check_agent_interfaces.py
uv run pytest -q tests/regression/test_agent_interfaces.py
uv run pytest -q tests/regression/test_maintenance_report_contract.py
```

The interface checker should report 8 interfaces, 16 examples and passed true; its regression file currently has 41 tests. Report-contract tests validate the supplied JSON format and reject prohibited states. These checks do not train models, run the new agents or prove their accuracy. Agent-specific training and evaluation commands still need to be implemented and documented by each owner; no nonexistent training command is implied here.

## What each owner hands over

| Deliverable | Required contents |
| --- | --- |
| Agent implementation | run adapter, schema validation, missing/error cases and standalone usage command. Agent 7 also supplies build_report. |
| Numerical model bundle where applicable | Model, preprocessing, tag/feature order, label mapping, calibrated settings if used, hashes and named seed configuration. Agents 1, 2 and 5 supply these. |
| Evaluation | Baseline comparison, validation selection reason, final untouched-test metrics, eligible counts and limitations. Rule agents supply exact behavioural tests instead of invented accuracy claims. |
| Reproducible instructions | Exact commands the owner actually ran, locked dependencies, input release/splits and expected output files. Secrets are excluded. |
| Connection tests | Supplied fixture tests, real upstream-output tests, unavailable reports, wrong contexts and duplicate evidence roots. |

An owner is finished when another member can load their implementation and artifacts, reproduce evaluation and run it on the agreed message without changing fields. Model quality thresholds must be stated and agreed from the measured baseline results; no arbitrary success percentage is established in this guide.

### Scope every implementation must preserve

Use the supported hydraulic and sensor tasks and the bounded roof reference facts/inspection records. Unsupported roof strength/failure, damaged vapour or fitting emission laws, causal mechanical cascades, remaining useful life, field qualification and automatic plant control stay outside the implemented claims. Unknown mechanisms are not negative training examples.

We can build all eight software roles with the current data, but that does not make every industrial failure mechanism learnable. The practical goal is a connected, source-traceable advisory system with evaluated models and honest unknown results where evidence is missing.

### Implementation references

The detailed field and timing reference remains in docs/agent_interface_reference.md. Exact eight-agent contracts remain in contracts/agents/v1/. Report output is defined separately in contracts/reports/.

Model API references: scikit-learn MultiOutputRegressor at https://scikit-learn.org/stable/modules/generated/sklearn.multioutput.MultiOutputRegressor.html and OneVsRestClassifier at https://scikit-learn.org/stable/modules/generated/sklearn.multiclass.OneVsRestClassifier.html. These describe output wrappers, not evidence that a particular model wins on Verum. Optional sequence layers are documented at https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html.
