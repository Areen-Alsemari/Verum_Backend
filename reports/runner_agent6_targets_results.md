# Runner: Agent 6 gets only the assets that Agent 5 implicates

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
