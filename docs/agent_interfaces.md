# Verum agent development guide

## What we are building

We are building eight connected parts of Verum. Each part receives information, does its own job, and returns a result in an agreed format. Everyone can develop their part using the supplied example messages, then connect the real implementations without changing the message format.

Use the existing full data package. Keep the original readings, prepared examples and train/validation/test splits. This implementation does not require another simulation campaign or replacement data package.

The prepared forecasting targets and current interface use five minutes. We will keep that task for this implementation. It predicts future readings; it does not promise an hour of warning before equipment fails. The full readings can still be used as model inputs. Longer forecasting targets are not part of the supplied prepared examples.

| Agent | Its job |
| --- | --- |
| 1 Predictive Health | Predict reported sensor values for the next five-minute window. |
| 2 Anomaly Detection | Find unusual readings and data-quality problems. |
| 3 Topology and Dependency | Look up which assets are connected and which paths could be relevant. |
| 4 Historical and Asset Intelligence | Retrieve supplied asset facts and records with their sources. |
| 5 Diagnostic Reasoning | Compare possible supported faults and explain supporting or conflicting evidence. |
| 6 Inspection Planning | Suggest inspection options and check their requirements, cost and duration. |
| 7 Inspection Quality and Documentation | Check whether readings and inspection records are complete and usable. |
| 8 Evidence Verification and Decision | Check the combined evidence and produce an assessment for human review. |

The stored message version is `1.0.0`. It identifies the agreed format so that different implementations can recognise compatible messages. It is not a model score or a claim that the agents are unfinished. Keep the version field unchanged when implementing these interfaces.

## How the parts connect

Every agent follows the same call:

```python
response = agent.run(request)
```

The request is the information sent to the agent. The response is the result it sends back. Each owner builds this function for their assigned agent. A model, graph lookup or checking rule can run inside it.

| Shared field | Plain meaning |
| --- | --- |
| `agent` | Which agent the message belongs to. |
| `request_id` | Which call the answer belongs to. |
| `context` | The case, the analysis time and the data/reference version. |
| `evidence` | The available source records, with identifiers and checksums. |
| `input` | The specific information this agent receives. |
| `report_id` | A unique identifier for the returned result. |
| `status` | Whether the agent finished, returned a partial result, lacked evidence or failed. |
| `result` | The agent's actual answer. |

The common data adapter and runner owner builds the shared message fields and source links. Other owners use the example messages to start immediately; they do not each write a different case/time/source format. The exact fields are already defined in the JSON files. Do not rename them to match a private implementation.

| Status | Meaning |
| --- | --- |
| `complete` | The requested work finished. This does not mean the equipment is healthy. |
| `degraded` | A useful partial answer is available, with gaps explained. |
| `insufficient_evidence` | There is not enough evidence to return a useful result. |
| `error` | The computation failed. |

All reports used together must belong to the same case and analysis time. A missing report stays missing. An unavailable measurement stays unknown. Do not replace either with zero, normal equipment or a successful check. Reports based on the same readings are not independent confirmation of a fault.

## The three numerical agents

### Agent 1 Predictive Health

Input: sensor summaries or sequences in `input.observations`, the requested sensor identifiers and the five-minute forecast horizon. Output: a list of forecasts containing the sensor identifier, unit, predicted mean and any supported uncertainty interval. No validated health-score or remaining-life target is supplied.

Train using the Predictive Health role files. Use `target.future_measurements` only where `target.supervised_loss_mask` is true and the selected sensor has a target. Keep missing targets unknown. Evaluate prediction error separately for each sensor and unit.

### Agent 2 Anomaly Detection

Input: observations and an optional forecast report from Agent 1. Output: anomaly events, affected sensors/assets, the method used and any limits on the result.

Use `target.data_quality` for reading-quality tasks. For the physical reference task, use `target.reference_supervision` and its nested `supervised_loss_mask`. Unknown physical labels must not become healthy cases. A missing forecast report does not prevent Agent 2 from analysing observations.

### Agent 5 Diagnostic Reasoning

Input: observations plus available reports from Agents 1, 2, 3, 4 and 7. Output: possible supported faults, their evidence, disagreements and unanswered questions. More than one fault may be possible.

Build it in two parts. First, train the diagnostic model on observations using the eligible `injected_components` and `injected_change_present` targets. Second, compare that model's candidates with the other agents' reports using explicit checks. Keep these checks outside the learned model's input. This avoids waiting for everyone else's predictions before training.

Use `target.supervised_loss_mask`. If an upstream report is missing, its comparison result is unknown. Do not adjust confidence by made-up percentages when other agents agree or disagree.

### Choosing prepared examples or full readings

Start with the supplied role examples if the model uses the existing summaries. Use the raw readings if the model needs an ordered sequence. In either case, keep the same eligible target and episode split. The 87 million readings provide detail; the 180k role records provide prepared inputs and targets for different jobs. They are not extra independent copies to combine.

For raw sequences, use the release manifest to find an episode's observation file and shared example file. Use the shared example's recorded prediction time. Include only readings available during the preceding 300 seconds, then attach that example's existing target. Read one episode at a time. The exact time fields and sequence format are in the technical reference.

## The five reference and evidence agents

| Agent | What it receives | What it returns and how to build it |
| --- | --- | --- |
| 3 Topology and Dependency | Asset queries, the supplied graph and optional reported equipment states. | Connected assets and relevant paths. Use graph queries. A commanded valve state is not proof of its physical position. |
| 4 Historical and Asset Intelligence | Asset queries, supplied specifications and available records. | Relevant facts with source links, plus explicit missing information. Use retrieval. Do not invent maintenance history. |
| 6 Inspection Planning | Diagnosis, the inspection catalogue, target assets and known requirements. | Inspection options, their requirements, cost, duration and limitations. Use catalogue retrieval and checks. Unknown requirements remain unknown. |
| 7 Inspection Quality and Documentation | Available performed inspection results, request details, catalogue information, process coverage and optional observations. | Missing/invalid fields, unit and timing checks, usable measurements and retest needs. Use record checks; do not turn an incomplete record into a confirmed equipment condition. |
| 8 Evidence Verification and Decision | Diagnosis, inspection plan, quality report and source references. | An assessment with conflicts, missing evidence and suggested next steps for a human. Check availability, source identity, consistency and evidence quality. |

Agents 3, 4 and 6 have reference examples for testing retrieval and rules. They do not have large independent datasets for training new models from scratch. Agents 7 and 8 have quality/evidence examples, but only a small covered inspection subset. Check the record's `use` field before choosing its target format.

Inspection Planning returns a proposal; it does not perform or approve the inspection. The existing submission format requires a numerical information-gain estimate and at least two competing hypotheses. If a justified estimate is unavailable, keep it unknown and report the submission blocker. Do not insert zero or invent an alternative hypothesis.

A new available inspection result leads to a new analysis. Agent 7 checks that result; Agents 5 and 8 can then update their assessments. Human review remains part of the workflow. Agent 8 provides the final assessment format the frontend will display, with source links to the underlying reports.

## What each owner delivers

| Owner | Work to finish |
| --- | --- |
| Member 1 | Agent 1, its forecasting model, preprocessing and evaluation. |
| Member 2 | Agent 2, its quality/physical detection tasks and evaluation. |
| Member 3 | Agents 3 and 4, plus common request preparation and the runner that connects reports. |
| Member 4 | Agents 5 and 8, keeping the observation model separate from evidence checks. |
| Member 5 | Agents 6 and 7, including catalogue matching and record/workflow checks. |

Each owner uses the exact request and response examples in `contracts/agents/v1/examples/`. File names start with the agent's role key and end with `.request.json` or `.response.json`. The example responses demonstrate the format and unknown cases; they are not trained predictions or training labels.

Before calling an implementation, use `validate_request(request)`. Before sharing its result, use `validate_response(request, response)`. Both functions are available from `verum.contracts.agent_interfaces`. These checks reject incompatible messages, stale case/time information and unsupported fields.

Run these checks from the repository root:

```bash
uv run python tools/check_agent_interfaces.py
uv run pytest -q tests/regression/test_agent_interfaces.py
```

Expected: the first command reports 8 interfaces, 16 examples and `passed: true`. The second reports 41 passed.

An owner's work is complete when their agent can run on its own, follows the shared format, includes its needed model/preprocessing files, has reproducible evaluation, handles missing/error cases, and works with example reports from its dependencies. Test the formats early. Then replace example reports with real outputs and test the connected system.

Format checks establish that the messages connect correctly. Model accuracy and useful warning time are checked through evaluation of the implemented agents; they cannot be guaranteed before those agents exist.

The JSON schemas remain the exact field reference. The longer explanations are preserved in `docs/agent_interface_reference.md`. Use this guide for the work plan and the technical reference only when implementing a specific field or check.
