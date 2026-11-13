# Agent 5: residual-pattern candidates pass the stop rule and are kept

Results of the evaluation pre-registered in `reports/agent5_candidates_design.md` (section 5). When the classifier of Agent 5 proposes nothing and the anomaly window is alarming, Agent 5 now reads the expected-residual table of `mechanism.py` backwards and proposes every family whose expected residuals are all exceeded. The change passes all four conditions of the stop rule on the validation split and is kept. Existing hypotheses, ids, scores and citations are unchanged.

## 1. Outcome

| condition | before | after | holds |
|---|---|---|---|
| (a) faulty windows with a hypothesis | 355 of 496 | 444 of 496 | yes |
| (b) family top-1 over all 496 faulty windows (no hypothesis counts as wrong) | 0.609 | 0.696 | yes: +0.087, 95% interval +0.042 to +0.134 |
| (c) fault-free hypotheses with a score at or above 0.9 | 28 | 28 | yes (by construction: candidates carry no score) |
| (d) gain above the largest of five shuffle gains | | +0.087 against +0.012 | yes |

The code that was evaluated is commit `d9db2b2` of the branch `agent5-candidates`.

## 2. What was run

- The 3,980 validation windows with a valid label (496 faulty, 3,484 fault-free, 673 episodes). Each episode ran through the runner in window order as one chained run, so the persistence statement of the runner was settled where it could be; roles 1 to 4 and 7 were the installed agents and the roles after the diagnosis were placeholders. The Agent 5 request of each window was stored and every variant ran on the stored requests.
- previous: the Agent 5 of `integration` (commit `4c0bc94`), run from a separate checkout of that commit. new, absent and the shuffles: this branch.
- The test split was never opened and no train file was read. The audit hook recorded no rejected open. The detector guard (`tools/detector/guard.py`) matches paths written with forward slashes, so on Windows it classifies every release path as outside the release and would refuse nothing; it was checked that it lets a test-split path through. Every run here installed a wrapper that turns backslashes into forward slashes before calling the guard's own classification, and that wrapper was checked to refuse the test-split role view and an evaluator file. The guard itself is outside the scope of this change and was not edited.
- The evaluation scripts are not part of the branch (the change is limited to the Agent 5 package, its tests and reports); they follow `tools/agents/run_runner_sample.py` and the scripts of the evidence-ranking report.

## 3. Controls

| control | result |
|---|---|
| absent: window assessment removed, this branch against `integration` (status, issues, result, whole response) | identical in 3,980 of 3,980 |
| windows where the classifier proposes a hypothesis: whole response, this branch against `integration` | identical in 633 of 633 |
| windows without a hypothesis and without a candidate: whole response | identical in 3,233 of 3,233 |
| windows that gain candidates | 114 (89 faulty, 25 fault-free) |

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

Faulty windows, previous against new, with the paired difference over whole episodes (1,000 resamples, seed 20261108):

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

## 6. Deviations from the pre-registration

- The shuffle takes the anomaly result and the persistence statement of the donor window, but not its list of recent assessments: the contract refuses a request whose recent assessments are later than its cutoff. Agent 5 does not read that list.
- The guard wrapper described in section 2 was added because the guard does not judge Windows paths. This does not change what may be opened.
- Nothing was tuned. The trial runs before the evaluation used 7 fault-free windows of 2 episodes, to check the scripts; no rule, order or text was changed after them.

## 7. Gates

Run on commit `d9db2b2`; the later commits change reports only.

| gate | result |
|---|---|
| fast tests (`pytest -m fast`) | 2352 passed, 2 skipped, 17 failed, 297 deselected |
| the 17 failures, re-run alone | 7 pass (runner timeout tests that failed while the evaluation loaded every core); 10 also fail on `integration` and are unrelated: 8 campaign tests need 20 GB free disk and 15 GB was free, the service guard test fails on the Windows path issue of section 2, one service test fails with a `KeyError` |
| Agent 5 tests (`tests/agents/diagnostic_reasoning`, 11 new) | all passed |
| ruff (`src tests tools`) | all checks passed |
| strict mypy (352 files) | no issues |
| interface check (`tools/check_agent_interfaces.py`) | 8 interfaces, 16 examples, passed |
| isolation checks (`tests/leakage`) | 44 passed |
| `local/checks` | not run: the folder does not exist in this checkout |
| bare full `pytest` | not run |

## 8. Limits

- All data are synthetic validation windows from one simulated terminal. Nothing here says how the candidates behave on field data.
- Family-level hypotheses do not localise. The valve, leak, flow-meter and level families name no asset, so Agent 6 gets no target from them. Only the pump and pressure-transmitter candidates name an asset, because the Agent 2 event names that pump or that tag.
- The mechanism field of a family-level candidate is a fixed stand-in (`restriction_position_visible`, `drift`), because the contract has no value for "one of these mechanisms". The exact mechanism-and-asset measure barely moves (+0.012) for that reason and because most candidates name no asset.
- The order among candidates is a fixed convention, not evidence. It is the main reason family top-1 gains less than family top-3.
- Candidates have no score, so condition (c) holds by construction. The 25 fault-free windows that gain candidates are the cost to watch.
- Agent 2 evidence is computed from the same window that the classifier reads; the candidates add coverage, not an independent second opinion.
- The implementation version of Agent 5 was not changed, so that a request without an alarming assessment gives a byte-identical response.
