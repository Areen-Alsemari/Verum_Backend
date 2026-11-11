# Verum agent interfaces

## Purpose and implementation boundary

Version 1.0.0 defines the eight advisory components and their connections for the supported representative terminal. The end-to-end result is a source-bearing assessment: reported-signal forecasts, anomalies, declared dependencies, available asset facts, alternative diagnostic hypotheses, feasible inspection options, inspection quality and an evidence-sufficiency decision for human review. It does not authorize maintenance or control, certify equipment condition, or extend the supported physical scope.

The machine-readable definitions are in `contracts/agents/v1/`. The manifest names the eight roles, schemas and connection examples. The interfaces are the implementation target for the five owners. The definitions and validator implement no agents, trained models, orchestration service or frontend endpoint. Existing simulator schemas and configuration are unchanged.

The existing source of responsibilities is the eight-role contract in `config/extensions/agent_dataset_v1.json`; supported capabilities and exclusions are in `config/extensions/project_scope_v1.json`. Observations and original inspection/history rows retain their existing frozen schema definitions. New message contracts live outside the frozen schema directory.

## One boundary for all implementations

Every implementation provides `run(request) -> response`, with JSON-compatible dictionaries at the boundary. The structural Python protocol is `verum.contracts.agent_interfaces.Agent`. An implementation may call a model, query a graph, retrieve records or run explicit checks internally; the caller does not depend on those internal choices. The call returns an advisory report and has no inspection-dispatch or process-control side effect.

| Request field | Type and meaning |
| --- | --- |
| `interface_version` | Exactly `1.0.0`; incompatible changes require another major interface version. |
| `message_type` | Exactly `request`. |
| `agent` | One of the eight established role keys; each schema fixes its own key. |
| `request_id` | Nonempty opaque identifier for this call. It is unrelated to the frozen inspection request identifier. |
| `context` | Case, analysis revision, cutoff, reference identity and execution mode described below. |
| `evidence` | Registry of available source records and upstream reports, with stable references, content hashes and original evidence roots. |
| `input` | Closed, role-specific payload. No target, loss mask, fault truth or evaluator row. |

| Response field | Type and meaning |
| --- | --- |
| `interface_version`, `message_type`, `agent` | Version `1.0.0`, literal `response`, and the producing role key. |
| `request_id`, `context` | Must match the request exactly. |
| `report_id` | Unique immutable identifier for this report. Used to connect it as evidence in another request. |
| `implementation` | Component name/version, nullable model/artifact hash, and nullable feature-profile identifier. |
| `status` | `complete`, `degraded`, `insufficient_evidence` or `error`. |
| `consumed_evidence_ids` | Registry entries actually used; every cited output source must be included. |
| `issues` | Structured `code`, `message` and `evidence_ids` entries. Errors and insufficient-evidence results require at least one. |
| `limitations` | Explicit limits of the returned assessment or method. |
| `advisory_only` | Always `true`. |
| `result` | Role-specific object for complete/degraded execution; `null` for error/insufficient evidence. |

`complete` means the requested supported computation finished; it does not mean an asset is healthy or that a hypothesis is proven. `degraded` permits a partial useful report with explicit gaps. `insufficient_evidence` means no usable role result can be produced. `error` means the computation failed. An inconclusive diagnostic result can be a successful computation. Never substitute zero risk, an empty confirmed fault list or a healthy label for a failed dependency.

Each owner accepts the same request format, validates before processing, preserves the request identifier/context, and validates the response before publishing it. They do not import another owner's implementation. The runner supplies requests and routes reports; it is the only component responsible for scheduling dependencies and retrieving private model artifacts.

## Context is application metadata

| Context field | Definition |
| --- | --- |
| `case_id` | Opaque case identity for routing and report association; never a learned feature. |
| `analysis_id` | Identity of one analysis snapshot; all connected reports share it. |
| `revision` | Nonnegative revision counter. New evidence or a later cutoff creates a new revision and analysis identifier. |
| `as_of_s` | Nonnegative simulation query cutoff, used only by adapters and explicit timing checks. |
| `as_of_utc` | Source-established query date/time or `null`; supports date-based checks without inventing a date. |
| `data_release` | Exactly `verum_reference_v2` for this contract version. |
| `reference_snapshot_sha256` | SHA-256 of the published reference file used by this snapshot. |
| `scope_id` | Exactly `verum_supported_reference_v2`. |
| `execution_mode` | `runtime` or `contract_fixture`; connected reports must use the same mode. |

Case IDs, absolute episode clocks, request IDs, report IDs, source locations and evidence hashes never enter learned observation features. Explicit rule checks may use the cutoff, dates and source metadata. Absolute timestamps are converted to relative times before numerical model input. API authentication, durable storage and wall-clock service timeouts belong to the later runner/service implementation rather than these physical-data inputs.

A report from another case, revision, cutoff, reference snapshot or execution mode is not silently reused. A current report may explicitly say that its data is missing or stale; copying an old report and changing its context is not a valid refresh. Pure reference lookups may reuse cached facts internally, but issue a new correctly bound report for the current request.

## Evidence registry and independence

Each registry record has `evidence_id`, `kind`, `source_ref`, `available_at_s`, `content_sha256`, `root_evidence_ids` and `provenance`. Supported kinds are original observation window/prefix, derived observation representation, declared reference, inspection request, inspection result, synthetic history and derived agent report. Source references use the corresponding `observations:`, `features:`, `reference:`, `inspection_request:`, `inspection_result:`, `history:` or `report:` namespace. They are stable record locators, not arbitrary filesystem paths.

Source evidence identifies itself as its single root. A derived report or observation representation lists the original source evidence roots, not other derived records as roots. A representation requires original observation roots; a report that used no source evidence may have an empty root list. All roots must resolve in the request's registry and cannot postdate the derived evidence. Summary and sequence representations of one observation prefix keep the same original observation root even though their feature hashes differ. Reports based on the same observations are correlated evidence: agreement among forecasting, anomaly and diagnostic models is not three independent measurements. Consumers preserve the roots and do not multiply confidence merely because several agents repeat the same signal.

A source registry entry must be available at or before the query cutoff. Its availability records a confirmed visible time; a gateway query can supply a conservative visibility bound at its own cutoff when an exact earlier release time is unavailable. This is not a claimed physical performance timestamp. Unknown availability without such a visible query does not establish a bound. Unknown availability does not permit exposing its measurement. Agent 8 can receive a separate metadata-only proposal with an unknown or future claimed availability time, allowing rejection without revealing unavailable content. The registry is not a place to store a future result and trust the consumer to ignore it.

`content_hash` defines canonical JSON hashing for derived messages and prepared observation representations. Original observation evidence binds the causal source rows used by the adapter, including any earlier readings needed for carried values. Derived observation-representation evidence binds the exact supplied summary or sequence. Original source-file hashes remain in the dataset inventory; they are not interchangeable with a canonical JSON content hash. The reference snapshot identifier is the source file's byte hash. Performed inspection evidence binds the exact frozen result row. Upstream report evidence binds the complete immutable report with `source_ref` equal to `report:` plus its report identifier.

Hashes establish content identity, not physical truth, trusted authorship or field qualification. The runner must obtain records from the existing time-gated gateway and approved reference snapshot, verify source identities and available times, and construct the registry. Contract validation is not a replacement for that access boundary or an authentication mechanism.

## Observation input and model compatibility

Agents 1, 2 and 5 accept `observations`. Agents 3, 6 and 7 can optionally use it for supported state or quality checks. It has one of the following exact representations; an artifact only accepts the representation it was trained and checked with.

| Representation | Structure and use |
| --- | --- |
| `summary_v1` | `summary` contains the existing `clock_basis`, zero relative `current_time_s`, 300-second `lookback_s` and `signals`. Signal fields match the current latest-value, missing/quality counts, age/censoring flags and numerical summary contract. |
| `sequence_v1` | `sequence` contains a 300-second lookback and channels with `tag_id`, `unit` and ordered samples. Samples contain `available_offset_s`, `measured_offset_s`, `value`, `quality_flag` and `availability_status`. Arrival offsets lie in `(-300, 0]`; measurement time cannot follow arrival time. |

Both carry `evidence_ids` separately from the numerical payload. The numerical model receives only its approved summary or sequence fields, not the transport context or registry. Sample values remain in reported source units; pressure units state their basis, such as `barg`. A conversion must be explicit and versioned with the model's preprocessing. Boolean contacts remain discrete and do not receive continuous-signal statistics. Missing values retain masks; a previous reading is not a fresh measurement.

The sequence representation defines a future owner's loader boundary; this change does not implement the loader or train a sequence model. Owners select one representation in the saved artifact's feature profile. Numerical learned preprocessing is fitted on train only. A malformed input or incompatible feature profile produces an explicit error, never silent padding with physically meaningful zeros.

## Agent 1 Predictive Health

| Item | Contract |
| --- | --- |
| Role key | `predictive_health` |
| Input | `observations`, `target_tag_ids`, `forecast_horizon_s` exactly 300. |
| Output | `forecasts`, plus `health_score: null`, `remaining_useful_life: null`, `field_qualified: false`. |
| Forecast item | `tag_id`, matching `unit`, `quantity: reported_mean`, `horizon_s: 300`, nullable `value`, nullable `interval`, `evidence_ids`, `limitations`. |
| Interval | If implemented and calibrated: lower/upper bounds, coverage probability and calibration identifier. Otherwise `null`. No assumed uncertainty band. |
| Training source | Prepared Predictive Health inputs and eligible `target.future_measurements`; alternatively aligned raw observation sequences with the same targets. |
| Model mask | `target.supervised_loss_mask`, with a present target for the chosen channel. The mask never enters runtime input. |
| Consumers | Optional context for Agent 2 and explicit evidence for Agent 5. |

The task is forecasting reported signals, not actual hidden plant state. Null predictions remain unavailable; they do not imply a healthy channel. The artifact records preprocessing, forecast horizon, feature profile and model identity. The owner tests channel matching, missing data, unit handling and held-out forecast error.

## Agent 2 Anomaly Detection

| Item | Contract |
| --- | --- |
| Role key | `anomaly_detection` |
| Input | `observations` and nullable `forecast_report` using Agent 1's complete response contract. |
| Output | `events`, `coverage` as assessed/partial/unknown, `no_event_means_healthy: false`, and an optional `window_assessment`. |
| Event item | `event_id`, `tag_ids`, `asset_ids`, category, nullable method-bearing score, `method_id`, `evidence_ids`, `limitations`. |
| Categories | Missing reading, non-good quality, reported-signal departure, supported physical reference event. An event is not itself a fault diagnosis. |
| Training source | `target.data_quality` and, separately, eligible `target.reference_supervision`. |
| Physical mask | Nested `target.reference_supervision.supervised_loss_mask`. Unknown physical labels are not healthy training cases. |
| Consumers | Agent 5; Agent 8 sees their provenance through the diagnostic evidence chain. |

Version 1's learned detector uses observations. The optional forecast report supports an explicit comparison outside that learned feature vector; the detector does not silently gain new upstream prediction inputs. Forecast absence does not prevent the standalone observation task. Departure thresholds require a documented fitted method and validation-based selection. No arbitrary physical tolerance is inserted to make an event appear.

### Window assessment and persistence

The optional `result.window_assessment` states how one scored window stands. It is not an event and has no `evidence_ids`. It holds `score` (the largest computed residual in fault-free scale units), `window_threshold`, `exceeded` (score strictly above the threshold), `complete` (every residual that applies to the window was computed), `persistence_rule` (`k`, `n`, `threshold`) and `residuals`, exactly four entries in the order R1_mass_balance, R2_pump_head, R3_discharge_loss, R4_receipt_line. Each entry has a `state`: `exceeded` exactly when the residual has an event, `within_normal` when it was computed and is not above its own threshold, or `unknown` with a `reason` when it was not computed or does not apply. An unknown residual is never within normal. The assessment is absent when `result` is null, which is the case for `insufficient_evidence` and `error`.

Agents 5 and 8 may receive `recent_anomaly_assessments`, the last windows of the same run, oldest first, each as `{as_of_s, window_assessment}` with a null assessment where a window had none, and `persistence`, the answer of the published rule over them: `rule`, `windows_held`, `windows_exceeding`, `windows_unknown` and `alarming`. `alarming` is null (unknown) until `n` windows are held and whenever a window of the last `n` has no assessment, or an assessment that is incomplete or made under another rule, unless `k` windows already exceed. It is false only when `n` windows are known and fewer than `k` exceed; the schema refuses false with an unknown window or without a rule. Both fields are optional. A recent assessment may not be later than the request cutoff. The runner computes them and attaches them to these two roles only; the two agents do not read them yet.

## Agent 3 Topology and Dependency

| Item | Contract |
| --- | --- |
| Role key | `topology_dependency` |
| Input | `query_asset_ids`, direction upstream/downstream/both, `declared_connections`, `reference_evidence_ids`, nullable `observations`. |
| Connection | `edge_id`, `from_node`, `to_node`, matching the published graph. |
| Output | `direct_connections`, `reachable_nodes`, `routing_assessment`, `actual_routing_confirmed: false`, `evidence_ids`. |
| Routing states | Declared only, ambiguous or unknown. Connectivity does not certify actual flow or propagation of a fault. |
| Data source | Public reference graph; optional reported state from the current observation input. |
| Consumers | Agent 5, with relevant paths exposed for human inspection. |

The implementation performs declared graph queries and records source evidence. It can derive structural reachability from the graph but must not infer a true valve position from a command or contact. Query/graph consistency and expected traversal paths are the owner's acceptance tests; repeated reference fixtures are not a large independent training corpus.

## Agent 4 Historical and Asset Intelligence

| Item | Contract |
| --- | --- |
| Role key | `historical_asset_intelligence` |
| Input | `query_asset_ids`, supplied `assets`, source-bearing `declared_facts`, current visible `history`, `reference_evidence_ids`. |
| Fact item | `fact_id`, `asset_id`, scalar `field_path`/`value`, nullable unit and parameter status, `source_locator`, `evidence_ids`. Compound source structures are flattened to explicit scalar paths. |
| Output | `asset_records`, `facts`, `history`, `history_status`, `missing_asset_ids`, `evidence_ids`. |
| History states | No verified past maintenance supplied, simulated records available, unknown. |
| Data source | Published asset registry/specifications and explicit visible simulated records. |
| Consumers | Agent 5 and human source drill-down. |

Retrieval returns source facts rather than filling missing specifications with common values. An unresolved physical parameter stays unresolved. The current published reference supplies no verified maintenance history. Synthetic records, if available from the gateway, retain that provenance and are never described as actual terminal history. The response cannot introduce facts or history absent from its supplied input.

## Agent 5 Diagnostic Reasoning

| Item | Contract |
| --- | --- |
| Role key | `diagnostic_reasoning` |
| Input | `observations`, and nullable `forecast_report`, `anomaly_report`, `topology_report`, `asset_report`, `inspection_quality_report`; optional `recent_anomaly_assessments` and `persistence`. |
| Learned component | Observation input only in version 1; trained against eligible supported injected-component targets. |
| Output | `hypotheses`, `assessment`, `upstream_checks`, `field_diagnosis_qualified: false`, nullable `ranking_basis`. |
| Hypothesis | `hypothesis_id`, one or more supported `components`, nullable method-bearing `score`, support/conflict evidence IDs, unresolved questions. |
| Components | Supported mechanism plus nullable asset/tag identifiers. Multiple components may coexist; never force one root cause. |
| Assessment | Candidates available or inconclusive. An empty hypothesis list is inconclusive, not verified healthy equipment. |
| Consumers | Agents 6 and 8. |

Supported mechanisms are leak, position-visible restriction, obstruction restriction, pump head degradation, sensor bias, drift, stuck reading and eligible misrouting a. No unsupported roof/fitting/cascade mechanism is introduced through a component label. The mask used in training is `target.supervised_loss_mask`; original hidden scenario labels do not override an unknown window.

The implementation has two explicit parts. First, its observation model produces candidate components and model scores. Second, evidence comparison checks relevant forecasts, anomaly reports, declared paths, supplied asset facts and usable inspections. The second part reports support, conflicts and unknowns; it does not invent numerical confidence multipliers or retrain the model on other agents' example answers.

`upstream_checks` contains exactly one entry for each of the five nullable report fields, identified by that field name. Missing reports produce unknown checks. A current report can still contain unknowns; schema validity does not prove its conclusion. Uncalibrated decision scores remain method-specific. `calibrated_probability` requires a calibration identifier and a value in [0, 1]; no generic confidence is assumed or averaged across roles.

If a future model consumes actual upstream predictions as learned features, that is a separately versioned feature/training change. It requires training-time out-of-fold or otherwise held-out upstream predictions, matched deployment preprocessing and end-to-end evaluation. Version 1 does not require that training architecture.

## Agent 6 Inspection Planning

| Item | Contract |
| --- | --- |
| Role key | `inspection_planning` |
| Input | Nullable `diagnosis_report`, current public `catalog`, `catalog_evidence_ids`, requested `target_asset_ids`, public `assets`, available `workflow_requests`, nullable `observations`, sourced `constraint_checks`, and explicit nullable cost/time `budget`. |
| Output | `options`, nullable `selection_policy_id`, nullable `recommended_option_id`, `dispatch_authorized: false`. |
| Option | Identifier, existing action ID, target asset, addressed hypothesis IDs, feasibility, precondition checks, exact catalogue cost/duration, nullable information gain/method, limits and evidence references. |
| Feasibility | Eligible for human review, blocked or unknown. Every catalogue precondition needs a sourced passing check before eligibility. |
| Selection | A recommendation needs an eligible option and a declared selection policy. No implied optimal-policy or information-gain label. |
| Consumers | Agent 8 and a human approval UI. Agent 7 later checks performed records. |

The planner returns proposals only. Missing process readings, permits, measurement capability or hardware evidence do not become passed prerequisites. Costs and durations are read from the supplied catalogue. A method's unmodelled outputs and unresolved uncertainty remain explicit limitations; the catalogue does not establish equipment acceptance.

The frozen inspection request requires a numerical `agent_reported_information_gain_bits` and at least two competing hypotheses. The new plan therefore is deliberately not that dispatch request. If information gain is unresolved, the proposed option leaves it null and cannot be converted into that frozen submission payload by substituting zero or an invented alternative hypothesis. A future approval adapter must obtain a justified estimate and satisfy the original request contract, or return an explicit submission blocker. The planning agent never fabricates an approval, permit or intervention.

## Agent 7 Inspection Quality and Documentation

| Item | Contract |
| --- | --- |
| Role key | `inspection_quality_documentation` |
| Input | Available performed `inspection_results`, their `result_evidence_ids`, available `inspection_requests`, public `catalog` and evidence references, source-bearing `process_coverage`, nullable `observations`. |
| Reused rows | The frozen inspection-result schema is referenced locally and further constrained to `workflow_status: performed`. |
| Coverage | Target asset, start/end seconds within the cutoff, source evidence and coverage identifier. This is public process coverage, not hidden evaluator validity annotations. |
| Output | `record_checks`, `observed_quality`, `retest_result_ids`. |
| Record checks | Result identifier, pass/fail/unknown checks, nullable measurement usability/scope support, `equipment_condition_confirmed: false`, evidence references. |
| Ordinary quality | Tag identifier, missing/non-good sample counts, latest-reading missing flag and evidence references. |
| Consumers | Agents 5 and 8 after new inspection evidence becomes available. |

Checks cover record structure, source identity, units, metric compatibility, workflow ordering, process coverage and supported uncertainty metadata. The runner supplies request/approval context through the sourced frozen request rows; absence yields an unknown check. A performed result alone does not prove all workflow prerequisites were valid. Missing calibration dates or a missing query date cannot pass a date-based calibration check.

The current role dataset mixes ordinary record-quality exercises and a small covered inspection subset. The owner distinguishes record kinds with `use` and preserves original split/parent membership. Numerical findings or outcome-category strings are not promoted to a known equipment condition. A usable measurement needs every required check to pass and scope support to be known; unknown is not acceptance.

## Agent 8 Evidence Verification and Decision

| Item | Contract |
| --- | --- |
| Role key | `evidence_verification_decision` |
| Input | Nullable `diagnosis_report`, `inspection_plan_report`, `inspection_quality_report`, and `evidence_proposals`; optional `recent_anomaly_assessments` and `persistence`. Underlying sources resolve through the common registry. |
| Proposal | Identifier, source reference, nullable claimed available time and claimed evidence IDs only. No future measurement value. |
| Output | Decision state, source-bearing summary, hypothesis report IDs, per-proposal evidence checks, conflicts, next steps and fixed human/advisory flags. |
| Admission checks | Nullable time admissibility, provenance verification, quality acceptance, supported scope and usability, with reasons and source references. |
| Decision states | Assessment available, more evidence required, review required or inconclusive. None means process safe or equipment certified. |
| Next steps | Human review, collect evidence, review records or continue observation. Advisory descriptions, not control commands. |
| Fixed flags | `human_decision_required: true`, `automatic_action_authorized: false`, `equipment_condition_confirmed: false`. |

Every proposed evidence item gets one assessment. Future proposals are inadmissible without reading their values. Missing or unverified source identity cannot establish provenance. Usability requires all admission checks to pass. Reports sharing evidence roots are not independent confirmations. Conflicting evidence is retained, not averaged away or hidden by a final confidence number.

The ordinary role data supplies proposal/admissibility exercises, not expert maintenance decisions. The implementation can check timing/provenance rules and any supported supervised admissibility component separately. The final summary must distinguish model hypotheses, declared design facts, observations and unknowns. A human remains responsible for maintenance/control decisions.

## Runner sequence and frontend boundary

1. Create a current context and registry from the time-gated gateway plus the approved public reference. Build the feature representation used by each numerical artifact. Do not expose evaluator directories, labels or masks.
2. Run Agents 1, 2, 3 and 4 on the snapshot. Agent 2 is independently runnable; an optional forecast comparison may follow Agent 1 without changing its learned detector.
3. Run Agent 5 with observations and whichever current upstream reports are available. Missing reports remain explicit unknowns.
4. Run Agent 6 when inspection options are needed. An initial Agent 8 assessment may run without an inspection plan or result and report the missing evidence.
5. A human may review an inspection proposal. Actual submission uses a separate adapter and the existing approval/service contract; no agent approves its own proposal.
6. When a performed result is available, create a new analysis revision. Run Agent 7 with the current result and coverage. Refresh other reports for that revision as needed, then reassess with Agents 5, 6 and 8. Do not pass reports from an earlier revision as current evidence.
7. Return Agent 8's validated response as the frontend assessment boundary. The frontend can expand the referenced visible agent reports and source records through a filtered report store. No raw evaluator/truth route is introduced.

The runner executes an explicit pass per snapshot; it does not create an unbounded automatic inspection loop. It validates upstream context and hashes before routing. Dependency errors are represented by null or failed reports and structured issues rather than waiting indefinitely or returning a fabricated normal result. HTTP routes, report persistence, authentication and runtime scheduling are implementation work after this contract definition.

## Independent development and acceptance

| Owner | Boundary ownership |
| --- | --- |
| Member 1 | Predictive Health implementation, forecast artifact and evaluation. |
| Member 2 | Anomaly Detection implementation, quality/physical tasks and evaluation. |
| Member 3 | Topology/Asset Intelligence implementations, common adapter/runner and integration assembly. |
| Member 4 | Diagnostic Reasoning and Evidence Verification implementations; keep observation models and evidence rules separate. |
| Member 5 | Inspection Planning and Inspection Quality implementations, catalogue matching and workflow checks. |

Shared contract changes have one reviewer/owner and a versioned update. Owners consume each other's messages, not private classes or training scripts. Their separate implementation/test directories avoid shared-file editing. Dependencies and lockfile updates are coordinated. Existing schemas, physical selections, data, labels and splits remain unchanged.

The JSON connection examples deliberately return unavailable or limited evidence without manufactured predictions. They are `contract_fixture` messages, not model training labels or performance benchmarks. Request examples use a training summary and published reference data. A runtime request rejects fixture-mode upstream reports. Owners supply their own normal, missing-data, conflict and error tests with source-bearing outcomes.

Run the existing dependency setup and then the following contract checks from the repository root:

```bash
uv run python tools/check_agent_interfaces.py
uv run pytest -q tests/regression/test_agent_interfaces.py
```

The standalone check reports eight interfaces, sixteen example messages and `passed: true`. The tests additionally exercise stale contexts, future evidence, changed hashes, unit mismatches, invented retrieved facts, unsupported inspection recommendations and control/qualification flags. These checks establish connection rules, not model accuracy or physical validation.

During implementation, call `validate_request(request)` before `run` and `validate_response(request, response)` before publishing. The functions live in `verum.contracts.agent_interfaces`. An owner is complete when its component obeys the shared messages, supplies reproducible task-specific evaluation, handles unknowns and failures, records its artifact/preprocessing identity where applicable, and passes contract tests with both example and real reports.

## Structured report assembly

Agent 7 also owns a separate documentation operation after Agent 8 returns its current assessment. This operation consumes a verified bundle of same-analysis reports and evidence and returns the closed JSON maintenance assessment defined in `contracts/reports/maintenance_report.schema.json`. It does not add fields to the eight existing run messages or create a ninth agent. The frontend renders that JSON and exports PDF. See `docs/agent_interfaces.md` for build instructions, model comparisons, reporting ownership and optional Cohere wording boundaries.
