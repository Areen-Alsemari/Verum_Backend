# Window assessment and persistence: results

Checks made on the branch `contract-window-assessment` after the change: the same 181 windows through the full runner before and after, the persistence rule on real episodes, and a mutation check. The earlier survey is `reports/contract_window_assessment_impact.md`. The sample is the one of `reports/agent2_before_after.md`: 169 validation windows and 12 train windows, drawn by a seeded stratified sampler. The test split was not opened in any run.

## 1. Before and after on the same 181 windows

Before is the state of the previous branch (`agent2-topology-residuals`); after is this branch. Each window is run as a case of its own, as in the earlier comparison, so every window is the first window of its run and its persistence answer is null.

| measure | before | after |
|---|---|---|
| windows through `verify_bundle` | 181 of 181 | 181 of 181 |
| final report built | 181 of 181 | 181 of 181 |
| crashes and runner issues | 0 and 0 | 0 and 0 |
| responses of Agents 1, 3, 4, 5, 6, 7 and 8 | - | identical in all 181 windows |
| requests of Agents 1, 3, 4, 6, 7 and of Agent 2 | - | identical in all 181 windows |
| requests of Agents 5 and 8 | - | identical in all 181 windows once the two new fields, the embedded Agent 2 report and its evidence row are set aside |
| Agent 2 response | - | the same apart from the version (2.0.0 to 2.1.0), the artifact hash, three added limitation lines and one replaced, and the new `window_assessment` (present in 181 of 181) |
| final reports | - | differ in 181 of 181, and only in the content hash of the Agent 2 source report and in the added limitation lines |

The requests of the other roles compared after removing the Agent 2 report and its row from the evidence list, because the changed Agent 2 report changes both. Nothing else differs.

## 2. Persistence on real episodes

The windows of each episode were run in time order as one run (`tools/agents/run_runner_sample.py --chain`), with a window without an assessment inserted for every skipped position. All 181 windows pass `verify_bundle` and build a final report. The answer in the Agent 5 and Agent 8 requests was recomputed independently from the stored Agent 2 assessments of the earlier windows: 0 differences in 181 windows, for both roles.

Answers of the 2 of 3 rule (threshold 1.74), by what the run held when the window was reached:

| episodes | windows with fewer than 3 held | windows with 3 held: true | false | null |
|---|---|---|---|---|
| fault-free (sample, track) | 48 | 1 | 32 | 1 |
| faulty (sample, track) | 49 | 19 | 5 | 14 |
| train sanity windows (one window each) | 12 | 0 | 0 | 0 |

All 15 null answers with 3 windows held come from a skipped position among the last three: the sampled windows of an episode are not consecutive, and a skipped window counts as an unknown one. No window in the sample had an incomplete assessment that alone left the answer unknown. The sample is stratified and its non-track windows are mostly isolated, so these counts say nothing about the alarm rate of a real run.

The threshold of the rule was set by the fit from the pooled out-of-fold train scores at a 5% fault-free episode target. A separate read-only check on the validation split gave 42 of 553 fault-free episodes alarming (0.076), the pooled figure of `reports/detector_v4_pooled_stress.md`. The validation share is above 5%, which the Agent 2 limitations state.

## 3. Mutation check

Each change was applied alone to a scratch copy of the tree and the tests of the runner persistence, Agent 2 and the contract were run. All 21 were caught.

| mutation | first failing test |
|---|---|
| treat unknown as false | test_a_missing_assessment_gives_unknown_not_false |
| treat a missing assessment as not exceeding | test_a_missing_assessment_gives_unknown_not_false |
| off by one window (n - 1) | test_two_of_three_exceeding_is_true |
| off by one window (n + 1) | test_only_the_last_n_windows_count |
| answer before n windows are held | test_the_first_window_gives_no_answer |
| count a score equal to the threshold | test_a_score_equal_to_the_threshold_does_not_exceed |
| use the window threshold instead of the rule threshold | test_two_of_three_exceeding_is_true |
| require more than k windows | test_two_of_three_exceeding_is_true |
| treat an incomplete window as settled | test_a_window_that_is_within_but_incomplete_is_not_settled |
| ignore a different rule in an old window | test_an_assessment_under_another_rule_is_not_settled |
| an exception leaves persistence false | test_a_malformed_assessment_leaves_persistence_unknown |
| accept a window out of order | test_the_log_refuses_another_run_and_a_window_out_of_order |
| attach the fields to the wrong agent as well (Agent 6) | test_only_agents_5_and_8_receive_the_fields |
| leave Agent 8 without the fields | test_the_first_window_carries_the_fields_and_no_answer |
| report an unknown residual as within normal | test_an_unknown_residual_is_never_within_normal_and_says_why |
| call a window complete when residuals are unknown | test_an_unknown_residual_is_never_within_normal_and_says_why |
| exceeded at exactly the window threshold | test_the_window_flag_follows_the_strict_comparison_with_the_threshold |
| publish the window threshold as the rule threshold | test_a_healthy_window_is_assessed_within_normal_with_the_published_rule |
| an event at exactly the own threshold (states follow) | test_a_residual_at_exactly_its_own_threshold_gives_no_event |
| drop the causal check on recent assessments | test_recent_assessments_must_be_past_and_in_order |
| accept an unknown residual without a reason | test_a_damaged_assessment_is_refused[<lambda>3] |

## 4. Generated and pinned files that changed

- `src/verum/agents/anomaly_detection/artifacts/topology_residual_v1.json`, written by the fit script, which gives the same bytes on a second run (sha256 b3517147...f89747); its pin in `parameters.py`.
- `tests/agents/fixtures/chained/diagnostic_reasoning.request.json` and `tests/agents/fixtures/chained/evidence_verification_decision.request.json`, written by the chained fixture script. The other fifteen files of the set, the responses and the index, did not change.
- The schemas in `contracts/agents/v1/` were edited by hand; the contract examples were not touched.
- No digest or lockfile hash changed: `uv.lock` and `pyproject.toml` are as before.
