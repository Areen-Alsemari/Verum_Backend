# Maintenance assessment report contract

Agent 7 owns this separate documentation output after Agent 8 returns its current assessment. It does not change the eight agent run messages or create another agent. The report assembler, optional Cohere client and frontend are not implemented by this contract.

Use the shared context definition from `contracts/agents/v1/common.schema.json` through a local JSON Schema registry. Validate against Draft 2020-12 with format checking and finite-number checks. Do not fetch schema references from the network.

The example copies the existing conservative Agent 8 interface fixture and its canonical response hash. It contains no invented measurements or equipment condition. Empty evidence lists in that example are intentional because its source assessment states that evidence is missing.

Schema validation checks format only. The future assembler must also validate the source request/response pairs with `validate_response`, require one current successful or degraded Agent 8 response, compare every source context, recompute canonical source hashes, reject duplicate report/finding identifiers, resolve evidence identifiers and preserve original evidence roots. `assessment_state` must equal Agent 8's decision_state. Every finding, inspection option and next step must cite a consumed source report; narrative citations must resolve too. The runner supplies the source responses and evidence registry separately rather than trusting links asserted by the report itself.

Copy measurement values and units, option fields and next steps from validated sources; distinguish hypotheses from confirmed observations. Include missing agents and evidence in missing_information and limitations. Reject non-finite values. No proposed inspection is completed work. Template assembly is the default; optional Cohere text cannot replace factual fields or authorise work. A human approval workflow is outside this output contract.

See `docs/agent_interfaces.md` for ownership, build instructions, Cohere constraints and frontend responsibilities.
