# Tracing the runner

The runner can record each analysed window to LangSmith as a trace. The feature is off by default, is meant for synthetic data only, and changes no request or response of any agent.

## Enabling it

Install the optional extra and set environment variables. Nothing is read from a file by the runner.

```bash
pip install "verum[tracing]"
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...        # set in the shell or a secret store, never in the repository
export LANGSMITH_PROJECT=verum      # optional
export LANGSMITH_ENDPOINT=...       # optional
```

Tracing is on only when `LANGSMITH_TRACING` is `true` and a key is present. With either missing, or with `langsmith` not installed, the runner behaves exactly as without this feature: it imports nothing, builds no summary and opens no connection. A failure of the tracing side (no network, a rejected key, a changed response) is swallowed and never reaches the analysis.

## What is recorded

One trace per call of `run_analysis`, named `verum.run_analysis`, with one child per agent call (`verum.agent.<role>`) and, when the bundle is verified, `verum.verify_bundle`. The final report assembly (`build_report`) belongs to an agent package and is not traced.

- Inputs and outputs are summaries: identifiers, report status, the `advisory_only` flag and the fixed flags of the result, the decision state of the decision role, counts, the runner's own issue and note codes, and SHA-256 digests of each request and report.
- Metadata: episode identifier (the case identifier unless the caller passes `episode_id`), window index (passed by the caller, or derived when the cutoff is a whole number of 300 s steps), cutoff, revision, execution mode, contract version, git commit, and the digest of the inspection parameters when the caller passes it (`inspection_parameters_sha256`, read from the episode's provenance file; a value that is not a SHA-256 hex string is dropped).
- Tags: `synthetic`, `verum`, and `contract:<version>`.

## What is not sent

No request or report body, observation value, reference content, history record or free text of an agent (summaries, limitations, issue messages). No ground-truth label, fault name or truth file: the runner never holds them, and the summaries are built from fixed keys, so nothing else can be forwarded. No key and no error message.

## Limits

A trace leaves the machine, so it must not be enabled on real plant data. A verification made after the run appears as a late child of the finished parent. The window index is derived only from the 300 s grid; otherwise it is absent.
