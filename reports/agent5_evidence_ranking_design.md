# Agent 5: using the Agent 2 assessment to update hypothesis scores (design note)

Read-only survey made before any change on the branch `agent5-evidence-ranking`, which starts from `agent5-mechanism-evidence`. The question is whether a multiplicative odds update from the Agent 2 window assessment could re-rank the hypotheses of Agent 5 without changing which hypotheses exist.

## 1. How Agent 5 produces and scores hypotheses today

- `DiagnosticModel.predict_candidates` builds an observation vector and scores each candidate with a fitted classifier. A pinned artifact holds one gradient-boosting classifier per mechanism and 41 classifiers for mechanism and asset pairs. A candidate is kept only if its probability is at or above a per-key decision threshold stored in the artifact (0.2 to 0.99; mechanism thresholds 0.2 to 0.6). Two rule-based candidates (a stuck reading, a static tank-level drift) have fixed scores of 0.75 and 0.70. Candidates are sorted by score, ties by mechanism and asset.
- `format_hypotheses` turns the sorted list into hypotheses. The identifier is `HYP-<rank>-<mechanism>-<asset>`, so the rank at the time of creation is part of the identifier. The score is a `decision_score` with the method identifier of the classifier, with a suffix `_low_support_uncalibrated` for the low-support mechanisms, and `calibration_id` null. The classifiers were selected on validation windows; their probabilities are not calibrated.
- `enrich_hypothesis_with_rules` fills `support_evidence_ids`, `conflict_evidence_ids` and `unresolved_questions` and returns `{**hypothesis, ...}`. It never touches the score or the identifier, and its docstring says so. The list is returned in the order of creation, which is descending score, and `ranking_basis` says `decision_score_descending`.
- The set of hypotheses is fixed by the thresholds above and does not depend on any upstream report. The model reads the observation summary only, never a report.

## 2. Where an odds update could be applied

- After `enrich_hypothesis_with_rules`, in the agent, as a separate step that maps each hypothesis to a new score and then sorts. It needs the anomaly report (already in `inputs`), the family of the hypothesis (`family_of` in `mechanism.py`), and a table of likelihood ratios.
- Identifiers and components stay as they are, including the rank number inside the identifier. After a re-sort the list order can differ from the numbers in the identifiers; the identifier is only an opaque key for every consumer found (below).
- The set of hypotheses cannot change, because the update only rewrites a score and does not remove or add a candidate.
- Scores of hypotheses with no family, no expected residual, an unknown residual or no usable window assessment would not change (likelihood ratio 1). A report without a window assessment gives the previous output exactly.
- The updated score should carry a different `method_id`, because it is no longer the classifier probability. The contract holds no range for a decision score (only a calibrated probability is limited to 0 to 1), so keeping it in 0 to 1 is a choice that keeps the old scale.

## 3. What Agent 8 and the other readers take from the scores

- Agent 8 reads hypothesis identifiers, `conflict_evidence_ids` and the failed upstream checks. It does not read the score or the order (no reference to `score` or to the first hypothesis in its source).
- Agent 6 (inspection planning) reads the hypotheses whose components name a target asset, by identifier. It does not read the score.
- Agent 7 prints the score, its kind, method and calibration in the report text, and lists hypotheses in the order it receives them.
- The contract validator checks the shape of the score and, for a calibrated probability only, the range.

## 4. What could break

- The order of the list and the number inside the identifier would disagree after a re-sort. A consumer that parses the number as a rank would be wrong; none found does.
- A score that is a classifier probability multiplied by an evidence ratio is not a probability. It stays uncalibrated, and the reliability table of the evaluation will show whether the update helps or hurts that.
- Agent 2 evidence is not independent of the observation vector the classifier already reads (the same tags, the same window). Multiplying the classifier score by a ratio estimated against fault-free windows double counts shared information; this is a bias the evaluation must show, not one the update can remove.
- Likelihood ratios estimated on train windows reflect the Agent 2 fit on those windows. The residual states must be taken from models that did not see the window (out of fold), or the ratios for `within_normal` and `exceeded` in fault-free windows are too optimistic.
- Existing Agent 5 tests that use the artifact order must keep passing when the assessment is absent.
- Hypotheses on fault-free windows do not disappear: a lowered score only moves them down. Whether they stay above the decision threshold is a property of the score, not of the set.

## 5. Pre-registration (written before any estimation or evaluation run)

Everything below is fixed now. The estimation and the evaluation are run once with these definitions; any change after a result is seen is reported as a deviation.

### 5.1 Estimation of the likelihood ratios

- Data: windows of the train split with a valid label only. No validation or test window is read by the estimation. The audit hook of the detector experiments is installed and the number of rejected opens must be zero.
- Residual states: the Agent 2 residual code applied to the window summary, with models fitted on the other folds (five folds that hold out whole units, as in the Agent 2 fit), so that a window is never scored by a model that saw it. A residual is `exceeded` when its value is above the pinned threshold of that residual, `within_normal` when it is computed and not above it, and unknown when it cannot be computed.
- Family of a window: for a window with exactly one injected component, the family given by `family_of` in `mechanism.py` (including the pressure-transmitter families) for its mechanism and asset. Windows with several injected components are not used for the ratios. Fault-free windows have no injected component. Activity of the fault (a stopped pump) is not filtered.
- Ratio: for a family F, an expected residual R of F and a state s, LR(R, s, F) = P(s | F, R computed) / P(s | fault-free, R computed), each probability as (count + 1) / (computed windows + 2). The ratio is bounded to 0.05 at the lowest and 20 at the highest. A state `unknown` gives 1. A family with no expected residual gives 1. A family with fewer than 10 windows in which R is computed gives 1.
- Several expected residuals: a family with two expected residuals uses the product of the two ratios only if the two are independent enough, which is checked on train: the phi coefficient between the two exceeded indicators, in the fault-free windows and in the windows of the family. If the absolute value is above 0.5 in either, only the residual with the larger absolute log ratio for the states of the window is used.
- The ratios are stored in a pinned file in the Agent 5 package, written by a script in `tools/agents` that is byte-identical on a second run.

### 5.2 The update

For a score s strictly between 0 and 1 and a combined ratio L, odds = s / (1 - s), odds' = odds * L, and s' = odds' / (1 + odds'), rounded to 6 decimals. A score of exactly 0 or 1 stays. The method identifier gets the suffix `+a2_evidence_v1` when L is not 1. With no usable window assessment, no family, an unknown expected residual or no expected residual, the hypothesis is unchanged. The list is then sorted by the new score (ties as before); identifiers and components are not touched.

### 5.3 Evaluation

- Data: the 181-window sample of the earlier reports (only its 169 validation windows are scored, the 12 train windows were used by the estimation) and the full validation split (every window with a valid label), each through the runner with the installed agents. For the full split the Agent 5 request of each window is built by the runner and stored, then every variant of Agent 5 is run on the stored requests. The test split is never opened.
- Faulty windows are those with at least one injected component. A hypothesis matches when its mechanism and asset equal an injected pair (as in the earlier reports); for the family measure the five families of the earlier reports (pump, restriction, leak, sensor fault, misrouting) are used. Top-1 and top-3 accuracy are the share of faulty windows with a match in the first or in the first three hypotheses; a window with no hypothesis is a miss.
- Reported: top-1 and top-3 for family and for mechanism and asset, overall and per family of the injected fault; hypotheses and scores on fault-free windows, with counts at or above the own threshold of each hypothesis, at or above 0.5 and at or above 0.9; the share of windows in which the first hypothesis changes; a reliability table of the score by bin against the share of hypotheses that match an injected fault; 95% percentile intervals from 1,000 bootstrap resamples of whole episodes (seed 20261108), paired for differences.
- Controls: (a) ablation, the window assessments removed from the stored requests, must give output identical to the previous Agent 5; (b) shuffle, the window assessments permuted across the windows of the set (five seeded permutations), must give no gain.

### 5.4 Stop rule

The change is kept only if, on the full validation split, the top-1 accuracy for family or for mechanism and asset improves with the lower bound of the paired bootstrap difference above zero, and the number of hypotheses on fault-free windows above their threshold does not increase. The threshold is read three ways and none may increase: at or above the own decision threshold of the hypothesis (the artifact thresholds, 0.5 for the two rule candidates), at or above 0.5, and at or above 0.9. Because the first condition is met by construction when the set of hypotheses is fixed, the two fixed levels are the ones that can fail. Two accuracy measures are looked at, so a pass on either has a larger chance of passing by luck than 5%; both intervals are reported. If the rule fails, the code is removed and the negative result is reported.
