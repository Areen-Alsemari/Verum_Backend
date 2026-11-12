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
