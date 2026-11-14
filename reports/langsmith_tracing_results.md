# LangSmith tracing in the runner: results

Branch `langsmith-tracing`, from `runner-agent6-targets` (cf27382). Seven commits (the last is this report), none pushed, all under the repository identity, none with a trailer. No agent, contract, schema or message was changed. The design is in `reports/langsmith_tracing_design.md`; how to use the feature is in `docs/runner_tracing.md`.

## 1. What was built

- `src/verum/agents/runner/tracing.py` (the runner package is `verum.agents.runner`, so the file is there and not at `src/verum/runner/`): a `Tracer` that guards a `Sink`, a `LangSmithSink` that is the only code importing `langsmith` (lazily), and the summary builders. Off unless `LANGSMITH_TRACING` is `true` and `LANGSMITH_API_KEY` is non-empty; off is a pass-through.
- `run.py`: `run_analysis` opens the parent `verum.run_analysis`, `_run_role` opens one `verum.agent.<role>` child around each agent call, and the parent is closed with the error type when the run raises. New optional keywords: `tracer`, `episode_id`, `window_index`, `inspection_parameters_sha256`.
- `bundle.py`: `verify_bundle` records a `verum.verify_bundle` child. `Bundle` has one new field, `trace`, excluded from comparison and repr. Because verification normally happens after `run_analysis` returns, this child is a late child of the finished parent.
- `pyproject.toml`: optional extra `tracing = ["langsmith>=0.14.17"]`. The runner does not require the package.
- `tools/agents/check_tracing_identical.py`: the 181-window comparison, run under the audit hook and guard.
- 25 new tests in `tests/agents/runner/test_runner_tracing.py` (24 run, 1 skipped; see 3.7).

## 2. Deviations from the design and the task

1. The design planned to find the inspection parameters digest by importing `verum.inspection.parameters`. That module is not on this branch (it is on `inspection-review-fixes`), and the isolation test of the runner allows imports of the contract package and the shared helpers only. The first fast run failed on this. The digest is now an optional argument, validated as 64 hex characters and dropped otherwise, and the commit is read with `git rev-parse` directly. The design report was amended and says so.
2. Three documentation-style tests failed on the first fast run (module docstring over 10 lines, definition docstring over 8 lines, file names in docstrings). The docstrings were shortened; a comparison of the syntax trees without docstrings confirms the last commit changed no code.
3. The runner has no window index and no separate episode identifier. The episode identifier defaults to the case identifier, and the window index defaults to `as_of_s / 300` only when that is a whole number; otherwise it is absent. The caller can pass either.
4. `build_report` is in the Agent 7 package and is not called by the runner, so it is not traced.

## 3. Gates, each reported separately

Run on the final commit (b094146) unless stated.

| gate | result |
|---|---|
| fast tests with `data/` | 2318 passed, 1 skipped (the real-package test), 297 deselected |
| fast tests without `data/` (`data/` moved aside and restored) | 2315 passed, 4 skipped (three reference-dataset tests and the real-package test), 297 deselected |
| ruff (`ruff check src tests tools`) | all checks passed |
| strict mypy (`mypy`, 337 files) | no issues |
| interface checks (`tools/check_agent_interfaces.py`) | 8 interfaces, 16 examples, passed |
| `local/checks` | 14 passed |
| 181-window byte-identical check | passed, see 3.1 |
| mutation check | 34 of 34 caught, see 3.2 |
| bare full `pytest` | **not run**, as instructed (about 78 minutes) |

### 3.1 The 181-window check

`tools/agents/check_tracing_identical.py` rebuilt the sample (169 validation, 12 train, fixed seed), ran every window in its chain twice on the code of commit dd532dc, and compared requests, reports, issues and notes with the stored bundles of the earlier run of this branch's parent (`out_t6_after`). Commit b094146 differs from dd532dc in docstrings only (checked on the syntax trees).

| pass | windows | requests identical | reports identical | issues identical | notes identical |
|---|---|---|---|---|---|
| tracing off (environment unset; the default path) | 181 | 181 | 181 | 181 | 181 |
| tracing on, recording sink, `verify_bundle` also called | 181 | 181 | 181 | 181 | 181 |

In the traced pass 1810 spans were recorded (10 per window: one parent, eight agent children, one verification), 1629 of them children of a parent. The truth strings of each window (fault types, mechanisms and faulty assets, read from the sample rows for this check only) were searched for in every span: 0 found. The audit hook summary: opens only in the examples (2416), knowledge (2), role views (4) and the manifest (2); no rejected open; no test-split file touched.

### 3.2 Mutation check

A scratch copy was changed one edit at a time and the tracing test file run against it (the repository was not edited). 34 edits, all caught: switch ignored; key ignored; start and end not guarded; setup not guarded; summary failure not swallowed; request body sent; report text sent; issue message sent; error text sent; a forbidden key sent; a fault word sent; synthetic tag dropped; child not parented; verification not traced; role spans removed; summary that changes the request; step error not recorded; step that swallows the error; parent not closed on error; git commit missing; sink that never posts; window index guessed; copy of a bundle not sharing the trace; inputs built when off; metadata built when off; decision state dropped; fixed flags dropped; child status dropped; runner issue code dropped; episode identifier ignored; passed tracer ignored; digest not validated; digest never added. Two edits survived the first round (the start guard and the swallowing of a summary failure) because the tests did not isolate them; the tests were strengthened and the second round caught both. The comparison tool in 3.1 was not itself mutation-checked.

### 3.3 What the tests cover

Off by default and with each variable missing; fallback when the package is missing; nothing imported or built when off; byte-identical requests, reports, issues, notes and evidence with tracing off, with a recording sink, and with sinks that fail on start, on child start and on end; names, parents and order of the spans; child status, decision state and fixed flags; a failed agent; tags and metadata; window index and digest rules; no forbidden key, fault word, body or label in any payload, with fault words planted in agent texts; an error in a traced block; a rejected run; sharing the trace on copy; the sink against a fake run tree, including an unreachable endpoint (every post and patch raising a connection error).

## 4. Limits

- `langsmith` is not installed in this environment. `LangSmithSink` was tested against a fake `RunTree` that follows the API read from the package source (version 0.14.17, downloaded to the scratchpad with permission, not installed), not against the real package. The test that points the real package at a closed local port (`http://127.0.0.1:9`) is written and skipped here; it has not been run, so the behaviour of the real client with an unreachable endpoint is not verified by this work.
- `uv` is not installed here, so `uv.lock` was not regenerated and is unchanged. The new extra is in `pyproject.toml` but not in the lock; `uv lock` must be run where `uv` is available, and a locked sync will report the lock as stale until then.
- No trace was ever sent to LangSmith, and no key or environment file was read, printed or committed.
- The fast suite with `data/` runs existing tests that read files under `data/` themselves, outside the audit hook; this work did not inspect which files they open.
- Late child: the verification span starts after its parent has ended. LangSmith accepts this, but the parent's duration does not include it.
- `reports/inspection_review_fixes.md` was untracked before this work and was left alone.
