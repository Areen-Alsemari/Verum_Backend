# Agent 5: residual-pattern candidates pass the stop rule and are kept

Results of the evaluation pre-registered in `reports/agent5_candidates_design.md` (section 5). When the classifier of Agent 5 proposes nothing and the anomaly window is alarming, Agent 5 now reads the expected-residual table of `mechanism.py` backwards and proposes every family whose expected residuals are all exceeded. The change passes all four conditions of the stop rule on the validation split and is kept. Existing hypotheses, ids, scores and citations are unchanged.

## 1. Outcome

| condition | before | after | holds |
|---|---|---|---|
| (a) faulty windows with a hypothesis | 355 of 496 | 444 of 496 | yes |
| (b) family top-1 over all 496 faulty windows (no hypothesis counts as wrong) | 0.609 | 0.696 | yes: +0.087, 95% interval +0.042 to +0.134 |
| (c) fault-free hypotheses with a score at or above 0.9 | 28 | 28 | yes (by construction: candidates carry no score) |
| (d) gain above the largest of five shuffle gains | | +0.087 against +0.012 | yes |

Every interval in this report is a 95% percentile interval from 1,000 resamples of whole episodes (673 episodes, seed 20261108), paired for differences: the windows of an episode are drawn together, never single windows.

What the gain costs:

| cost | count | where |
|---|---|---|
| fault-free validation windows that gain candidates (no score, so condition (c) cannot see them) | 25 of 3,484, with 100 unscored hypotheses | section 4, where the windows are listed |
| fault-free windows of the 181-window sample whose Agent 8 decision escalates from `more_evidence_required` to `review_required` | 5 of the 82 fault-free validation windows of the sample (none of its 6 fault-free train windows) | section 5, where the windows are listed |

The code that was evaluated is commit `d9db2b2` of the branch `agent5-candidates`. Commit `59d8134` raises the implementation version to 1.1.0 and was scored again; every hypothesis is the same in all 3,980 windows (section 3).

## 2. What was run

- The 3,980 validation windows with a valid label (496 faulty, 3,484 fault-free, 673 episodes). Each episode ran through the runner in window order as one chained run, so the persistence statement of the runner was settled where it could be; roles 1 to 4 and 7 were the installed agents and the roles after the diagnosis were placeholders. The Agent 5 request of each window was stored and every variant ran on the stored requests.
- previous: the Agent 5 of `integration` (commit `4c0bc94`), run from a separate checkout of that commit. new, absent and the shuffles: this branch.
- The test split was never opened and no train file was read. The audit hook recorded no rejected open. The detector guard (`tools/detector/guard.py`) matches paths written with forward slashes, so on Windows it classifies every release path as outside the release and would refuse nothing; it was checked that it lets a test-split path through. The runs that opened the release folder (the collection, the two sample runs and the fixture check) installed a wrapper, kept outside the repository, that turns backslashes into forward slashes before calling the guard's own classification; it was checked to refuse the test-split role view and an evaluator file. Opens it allowed: collection, examples 756, role views 2, manifest 1 (main process); each sample run, examples 2,416, knowledge 2, role views 4, manifest 2. The guard was not edited. A re-run under the repository's own guard is still to be done (section 7).
- The scripts are `tools/agents/evaluate_agent5_candidates.py` (collect and score) and `tools/agents/report_agent5_candidates.py` (the tables of sections 1 to 5). The score phase reads only the stored requests and opens nothing under the release folder.

## 3. Controls

| control | at `d9db2b2` (version 1.0.0) | at `59d8134` (version 1.1.0) |
|---|---|---|
| absent: window assessment removed, this branch against `integration` | whole response identical in 3,980 of 3,980 | identical apart from `implementation.version` in 3,980 of 3,980; the whole response differs in all 3,980 |
| windows where the classifier proposes a hypothesis, this branch against `integration` | identical in 633 of 633 | identical apart from the version in 633 of 633 |
| windows without a hypothesis and without a candidate | identical in 3,233 of 3,233 | identical apart from the version in 3,233 of 3,233 |
| windows that gain candidates | 114 (89 faulty, 25 fault-free) | the same 114 |
| hypotheses of every variant, second scoring against the first | | identical in 3,980 of 3,980 |
| `integration` responses, second scoring against the first | | identical in 7,960 of 7,960 |

Shuffle: the anomaly result (window assessment and events) and the persistence statement were taken from another window, five seeded permutations over the split.

| variant | coverage | family top-1 | difference against previous (95% interval) | fault-free windows with a hypothesis |
|---|---|---|---|---|
| previous | 0.716 | 0.609 | | 278 |
| new | 0.895 | 0.696 | +0.087 (+0.042 to +0.134) | 303 |
| shuffle 0 | 0.732 | 0.611 | +0.002 (+0.000 to +0.006) | 590 |
| shuffle 1 | 0.738 | 0.615 | +0.006 (+0.000 to +0.014) | 591 |
| shuffle 2 | 0.752 | 0.621 | +0.012 (+0.002 to +0.024) | 584 |
| shuffle 3 | 0.736 | 0.609 | +0.000 (+0.000 to +0.000) | 587 |
| shuffle 4 | 0.734 | 0.615 | +0.006 (+0.000 to +0.014) | 591 |

An assessment from another window raises candidates in about 300 more fault-free windows and gains almost nothing on faulty ones, so the gain comes from the assessment of the window itself.

## 4. Validation split in detail

Faulty windows, previous against new, with the paired difference and its interval over whole episodes:

| measure | previous | new | difference (95% interval) |
|---|---|---|---|
| coverage | 0.716 | 0.895 | +0.179 (+0.113 to +0.247) |
| family top-1 | 0.609 | 0.696 | +0.087 (+0.042 to +0.134) |
| family top-3 | 0.625 | 0.782 | +0.157 (+0.098 to +0.220) |
| exact top-1 (mechanism and asset) | 0.431 | 0.444 | +0.012 (+0.002 to +0.028) |
| exact top-3 | 0.442 | 0.456 | +0.014 (+0.002 to +0.032) |

By the family of the injected fault:

| injected | windows | no hypothesis before | gain a candidate | family top-1 before | after | exact top-1 before | after |
|---|---|---|---|---|---|---|---|
| leak | 57 | 35 | 20 | 0.070 | 0.158 | 0.000 | 0.000 |
| misrouting | 15 | 5 | 0 | 0.667 | 0.667 | 0.667 | 0.667 |
| pump | 72 | 7 | 7 | 0.750 | 0.833 | 0.694 | 0.778 |
| restriction | 156 | 5 | 2 | 0.929 | 0.936 | 0.821 | 0.821 |
| sensor fault | 152 | 80 | 51 | 0.355 | 0.533 | 0.007 | 0.007 |
| several components | 44 | 9 | 9 | 0.795 | 0.886 | 0.568 | 0.568 |

Fault-free windows:

| variant | windows with a hypothesis | hypotheses | score at or above 0.9 | null score |
|---|---|---|---|---|
| previous | 278 | 301 | 28 | 0 |
| new | 303 | 401 | 28 | 100 |

The real cost is 25 of 3,484 fault-free windows that gain candidates (100 hypotheses without a score). Condition (c) cannot see them, because they carry no score. In 14 of the 25 the first candidate is a restriction at a pump outlet valve.

| fault-free window | first candidate | candidates |
|---|---|---|
| `04ce98bef31f9e2f0544c31e` | restriction-at-a-pump-outlet-valve | 2 |
| `1803186884f3dbc6a0f8c484` | restriction-at-a-pump-outlet-valve | 2 |
| `1c1c2ba0358ac14677683f64` | restriction-at-a-pump-outlet-valve | 2 |
| `1cbb765c2419b165efb7b50e` | restriction-at-a-pump-outlet-valve | 2 |
| `1e789aa0669e1840dc1622b8` | restriction-at-a-pump-outlet-valve | 2 |
| `2ce1a490e0137051188533c6` | restriction-at-a-pump-outlet-valve | 2 |
| `2e9f430704a7baafc6b3d8bc` | pump-a-discharge-transmitter-fault @PT-202A | 6 |
| `3031c81f27f3e8b1b6882050` | pump-b-discharge-transmitter-fault @PT-202B | 9 |
| `3ff8c48f131f458fa03bac75` | pump-a-discharge-transmitter-fault @PT-202A | 9 |
| `40510e5a3919515a44f6af82` | leak-between-the-two-meters | 3 |
| `54a5f551bc7aeb43eccad57d` | pump-a-discharge-transmitter-fault @PT-202A | 6 |
| `54b53c0c55f2f5e76a8fccf8` | restriction-at-a-pump-outlet-valve | 2 |
| `5b1d9bdfcb1b192b8f139a92` | leak-between-the-two-meters | 3 |
| `6e819b2b6fb0d51c3b2e77f7` | restriction-at-a-pump-outlet-valve | 5 |
| `7e0068a277d7716b9fae4e55` | restriction-at-a-pump-outlet-valve | 2 |
| `8038dbd2f866404c9d4fd285` | restriction-at-a-pump-outlet-valve | 2 |
| `8bad061801a63fb3ffed3c9f` | pump-a-discharge-transmitter-fault @PT-202A | 6 |
| `b2601eb437633e27da1540fc` | pump-b-discharge-transmitter-fault @PT-202B | 6 |
| `b54fd4599c4b3be0841ea0c3` | restriction-at-a-pump-outlet-valve | 2 |
| `c2352f4eb6491279f99d2d6b` | pump-b-discharge-transmitter-fault @PT-202B | 9 |
| `d299a7a64b7620cba11a25c4` | pump-a-discharge-transmitter-fault @PT-202A | 6 |
| `d3b19aa327f1a06d48aaf122` | pump-head-loss @P-101A | 6 |
| `eda6840897aaa1ced9d9c1f7` | restriction-at-a-pump-outlet-valve | 2 |
| `f19069a50b0256983bd87df4` | restriction-at-a-pump-outlet-valve | 2 |
| `f25d6c40bc632ae9c65e7779` | restriction-at-a-pump-outlet-valve | 2 |

First candidate in the 114 windows that gain candidates, against the injected family (most frequent):

| first candidate | injected | windows |
|---|---|---|
| pump A discharge transmitter fault (PT-202A) | sensor fault | 23 |
| leak between the two meters | sensor fault | 19 |
| restriction at a pump outlet valve | fault-free | 14 |
| pump A discharge transmitter fault (PT-202A) | leak | 7 |
| pump head loss (P-101A) | sensor fault | 7 |
| leak between the two meters | leak | 5 |
| pump A discharge transmitter fault (PT-202A) | fault-free | 5 |
| pump head loss (P-101B) | pump | 4 |

A window that gains candidates gets 2 to 9 of them (2 in 15 windows, 3 in 42, 5 in 4, 6 in 38, 9 in 15). Top-3 gains more than top-1 because the fixed order is often wrong about which family comes first: R1 puts the leak family before the sensor families, and many sensor-fault windows that raise R1 get the leak family first.

Persistence in the windows that gain candidates: known alarming in 92 (68 faulty, 24 fault-free), unknown in 22 (21 faulty, 1 fault-free). Of the 52 faulty windows that still have no hypothesis, 48 have a window score below the window threshold (8 of them with a residual above its own threshold) and 4 have persistence known to be false.

## 5. The 181-window sample

The sample (169 validation, 12 train windows) was run with `tools/agents/run_runner_sample.py --chain` on this branch and on `integration`, under the wrapped guard (no rejected open, no test-split file). `verify_bundle` passes and a final report is built in 181 of 181 windows in both runs.

| role | reports that change |
|---|---|
| Agent 5 diagnostic_reasoning | 25 of 181 |
| Agent 6 inspection_planning | 17 of 181 |
| Agent 8 evidence_verification_decision | 25 of 181 (decision state changes in 17) |
| Agents 1, 2, 3, 4 and 7 | 0 of 181 |

- The 25 windows are the windows that gain candidates: 19 faulty, 6 fault-free. No window with a previous hypothesis changes.
- Windows in which an Agent 5 hypothesis names an asset or a tag: 38 before, 55 after.
- Agent 6 report status:

| before | after | windows |
|---|---|---|
| degraded | degraded | 38 |
| insufficient_evidence | degraded | 17 |
| insufficient_evidence | insufficient_evidence | 126 |

- In the 17 windows that move, Agent 6 now has targets named by the pump and transmitter candidates (for example PT-202A, P-101A, PT-201 and PT-203 together in 12 windows) and 60 options in all, every one `unknown`: Agent 6 establishes a precondition only for a request with a single target, and these requests have one to four. Options over the sample go from 40 to 100. Of the 25 windows, 8 (all faulty) gain only family-level candidates and give Agent 6 no target.
- Agent 8 decision state: `more_evidence_required` to `review_required` in 17 windows (12 faulty, 5 fault-free), through the supported-hypothesis alert, since the anomaly check of the diagnosis now passes. In the other 8 windows the decision was already `review_required` and only the cited reports change. Overall: `more_evidence_required` 144 to 127, `review_required` 37 to 54.
- The five fault-free windows that escalate, all from the stratified part of the sample: `670321e9e913e5c2f385b51b`, `895298a3cb68336e6115b650`, `8aabe3cd81bc3b4d9ec55284`, `cc3661419c1cbd714ab3a849`, `e52a6ecf9bc407f77c154743`.
- The sample was run on `d9db2b2`. The version raise of `59d8134` changes the `implementation.version` field of every Agent 5 report and nothing else, as section 3 shows on the split.

## 6. Where the stand-in mechanism is shown

The mechanism of a candidate stands for its family: `drift` for the sensor families, including the pressure-transmitter candidates that name a tag, and `restriction_position_visible` for the valve families. Every consumer in the repository was read:

| consumer | shows the mechanism | how |
|---|---|---|
| maintenance report builder (`src/verum/agents/inspection_quality_documentation/report.py:265`) | yes | one finding per hypothesis, kind `hypothesis`, statement "Unconfirmed hypothesis: drift (asset=None, tag=None); score: unavailable". The family statement and the caveat that the mechanism names the family only go to `missing_information` with the other unresolved questions, not next to the finding |
| run service, report route (`/api/runs/<id>/report`) | yes | serves that maintenance report unchanged |
| run service, event stream (`src/verum/service/events.py`) | no | agent statuses, the Agent 8 decision and flags, persistence and note codes only |
| Agent 8 (`src/verum/agents/evidence_verification_decision`) | no | reads hypothesis ids, citations and the anomaly check; its summary and the report narrative are fixed text ("a departure that a proposed candidate would produce") |
| Agent 6 and the runner | no | read assets and tags only |
| frontend | none in this repository | |

So the stand-in reaches a reader in one place: the hypothesis findings of the maintenance report, and through it the service report route. The finding says "Unconfirmed hypothesis", but it does not say next to the mechanism that the mechanism stands for a family. Fixing that needs a change in the report builder (Agent 7), which is outside this branch.

## 7. Deviations from the pre-registration

- The shuffle takes the anomaly result and the persistence statement of the donor window, but not its list of recent assessments: the contract refuses a request whose recent assessments are later than its cutoff. Agent 5 does not read that list.
- The guard wrapper described in section 2 was added because the guard does not judge Windows paths. This does not change what may be opened. The re-run under the repository's own guard, after commit `c757866` of `compressed-workflow-scenario2` is merged, has not been done: neither that commit nor that branch exists in this clone or on `origin`.
- Nothing was tuned. The trial runs before the evaluation used 7 fault-free windows of 2 episodes, to check the scripts; no rule, order or text was changed after them.

## 8. Reproducing the results

From the repository root, with the release folder at `data/reference_release_v2/verum_reference_v2/` and on a platform where the guard judges the paths (section 2). `<cache>`, `<prev>`, `<new>`, `<before>` and `<after>` are any new paths outside the repository.

```bash
git worktree add --detach ../verum-integration 4c0bc94
```

```bash
PYTHONPATH=src python tools/agents/evaluate_agent5_candidates.py collect --cache <cache>
```

```bash
PYTHONPATH=../verum-integration/src python tools/agents/evaluate_agent5_candidates.py score --mode prev --cache <cache> --out <prev>.json.gz
```

```bash
PYTHONPATH=src python tools/agents/evaluate_agent5_candidates.py score --mode new --cache <cache> --out <new>.json.gz
```

```bash
python tools/agents/report_agent5_candidates.py split <prev>.json.gz <new>.json.gz
```

```bash
PYTHONPATH=../verum-integration/src python tools/agents/run_runner_sample.py --chain --out <before>
```

```bash
PYTHONPATH=src python tools/agents/run_runner_sample.py --chain --out <after>
```

```bash
python tools/agents/report_agent5_candidates.py sample <before> <after>
```

## 9. Gates

The full fast suite was run on an idle machine (nothing else running) on commit `59d8134` and, for comparison, on `integration` (`4c0bc94`) with the same `data/` folder linked into its checkout.

| run | passed | failed | skipped |
|---|---|---|---|
| fast suite, `59d8134` | 2347 | 22 | 2 |
| fast suite, `integration` | 2349 | 9 | 2 |

The 22 failures at `59d8134`:

| failures | cause | at `integration` |
|---|---|---|
| 1, documentation style, repository path in a docstring | the new report script named two script files in its docstring | not present there; fixed in `e57845f`, the style tests pass (6 of 6) |
| 8, campaign (`tests/regression/test_campaign*.py`) | the campaign runner needs 20 GB free disk and 15 GB was free | fail identically |
| 1, `tests/service/test_service_guard.py::test_the_installed_hook_raises_on_a_test_file_and_ignores_other_paths` | the service guard does not judge Windows paths (the file opens instead of being refused) | fails identically |
| 12, `tests/agents/runner/test_runner_run.py` (the failing-agent and issue-code tests) | each run uses a 0.1 s agent timeout and expects exactly one issue; after the predictive_health or inspection_quality_documentation tests have run in the same process, a second agent also times out | order-dependent at `integration` too: with `tests/agents/predictive_health` run first, the same 13 runner tests fail at `integration` (12 and 13 failures in two runs); the file alone passes 70 of 70 three times on each commit; the full `integration` run passed them by chance |

The 9 failures at `integration` are exactly the 8 campaign tests and the service guard test. The service test that failed with a `KeyError` in the first, loaded run passed in both idle runs. No failure involves Agent 5: the runner tests use placeholder agents only.

| gate | result |
|---|---|
| Agent 5 tests (`tests/agents/diagnostic_reasoning`, 11 new) | all passed |
| ruff (`src tests tools`) | all checks passed |
| strict mypy (352 files) | no issues |
| interface check (`tools/check_agent_interfaces.py`) | 8 interfaces, 16 examples, passed |
| isolation checks (`tests/leakage`) | 44 passed |
| `local/checks` | not run: the folder does not exist in this checkout |
| bare full `pytest` | not run |

After `59d8134` only `e57845f` (a docstring of the report script) and this report changed; for those the documentation style tests and ruff were run, not the full fast suite again.

## 10. Limits

- All data are synthetic validation windows from one simulated terminal. Nothing here says how the candidates behave on field data.
- Family-level hypotheses do not localise. The valve, leak, flow-meter and level families name no asset, so Agent 6 gets no target from them. Only the pump and pressure-transmitter candidates name an asset, because the Agent 2 event names that pump or that tag.
- The mechanism field of a family-level candidate is a fixed stand-in (`restriction_position_visible`, `drift`), because the contract has no value for "one of these mechanisms". The exact mechanism-and-asset measure barely moves (+0.012) for that reason and because most candidates name no asset.
- The order among candidates is a fixed convention, not evidence. It is the main reason family top-1 gains less than family top-3.
- Candidates have no score, so condition (c) holds by construction. The 25 fault-free windows that gain candidates are the cost to watch.
- Agent 2 evidence is computed from the same window that the classifier reads; the candidates add coverage, not an independent second opinion.
- The implementation version of Agent 5 is now 1.1.0. No fixture or test binds to it: the chained fixtures are built with placeholder agents (`build_chained_fixtures.py --check` passes after the raise, and a regeneration gives the same content), and the contract example uses its own implementation name.
