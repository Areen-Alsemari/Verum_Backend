# Detector experiment: pre-registered plan

Status: written and committed before any candidate was fitted or scored. Every number below that affects a result (constants, thresholds, rules) is fixed here. Nothing is tuned afterwards. If the plan turns out to be wrong, the results report says so and the plan is not edited.

## 1. Question

Can a physics-based detector, trained only on fault-free windows, beat both the trivial "flag everything" baseline and the current Agent 2 random forest on validation windows? A negative answer is an acceptable outcome and will be reported as such.

Reference numbers that motivated the question (from earlier reviews, test split, not re-measured here): forest test F1 0.3516 against 0.3015 for always-flag, AUROC about 0.51 at matched episode stage, average precision 0.236 against prevalence about 0.18, training average precision 1.0.

## 2. What was looked at before this plan was written

Disclosed so that the plan can be judged:

- The structure of the role views, of the raw observation rows and of the declared topology (field names, counts, the 28 declared connections, the 30 instruments).
- The number of distinct operating regimes (the combination of the 16 on/off tags: pump, valve and level-switch states) among fault-free train windows: 12, with the five largest holding 1,242, 1,227, 1,179, 1,168 and 1,099 windows. All 3,484 fault-free validation windows fall in a regime that has at least 30 fault-free train windows, but only 296 of the 496 faulty validation windows do.
- Nothing else about validation or test: no score of any kind has been computed, no model fitted, and the test split has not been opened.

Consequence, written into the rules below: "this operating regime was not seen in fault-free training" must never act as a fault signal, because that would reward a property of how the simulator schedules fault episodes rather than a physical effect.

## 3. Data rules

- Splits: train and validation only. The test split is never opened, listed, hashed or read. The harness installs an audit hook that raises on any attempt to open a file under the data folder that is not (a) a train or validation role view, (b) a train or validation example file, (c) the raw observations of an episode that belongs to train or validation, (d) the public reference, or (e) the release manifest files that list hashes. The results report shows the list of files the hook saw and the count of rejected attempts (expected: zero).
- Windows: only windows whose supervised label mask is true (the label is valid). A window is faulty when it has at least one injected component, otherwise fault-free. Validation: 3,980 windows, 496 faulty, prevalence 0.1246.
- Fitting: only fault-free train windows (8,579). Pre-onset windows of fault episodes that are labelled fault-free count as fault-free.
- Thresholds and every hyperparameter: no hyperparameter is tuned. All constants are fixed in section 5. The only quantity chosen on validation is the alarm threshold, set by a stated false-alarm target (section 6), never by maximising any score that uses fault labels.
- Test split: held untouched for one later run.

## 4. Inputs

Allowed (the complete list):

- For each of the 14 numeric tags (FT-001, FT-201, LT-101, LT-102, LT-103, PT-001, PT-201, PT-202A, PT-202B, PT-203, TT-001, TT-101, TT-102, TT-103) and from the window summary: `mean`, `slope_per_s`, `standard_deviation`. Units are never mixed: every statistic is computed per tag.
- For each of those tags, the raw sample values of the same 300-second window, used only by the CUSUM in C1. The raw rows are filtered by simulation time only, not by arrival time, quality flag or availability status. This is more information than the Agent 2 request carries today; if C1 wins only through CUSUM the result is about a change of the input contract, and the report will say so.
- For the 16 on/off tags: the latest value, used only to form the regime key and the pump-state selector of C3. The regime key picks which fault-free baseline a window is compared with. It is never scored.

Forbidden (a test asserts that no such column is used): `latest_received_age_s_*` and every other arrival or age field, counts of rows or samples, missing-sample counts, quality flags and quality counts, any field containing "age", "count", "rows", "missing", "quality" or "available", schedule or clock features, window position, episode stage, cutoff time, episode identifiers, fault labels and fault-window metadata. Position and episode are used only to stratify and resample the evaluation, never as model inputs.

Regime rule: a regime with at least 200 fault-free train windows gets its own baseline. Any other regime, including one never seen, uses the pooled fault-free baseline, and its windows are scored exactly like the others. No candidate may add a novelty score for an unseen or rare regime.

Robust scale rule used everywhere: scale = max(1.4826 times the median absolute deviation, 1e-6 + 0.01 times (P99 minus P1) of the same column over pooled fault-free train windows). Missing numeric values are replaced by the baseline median (z = 0) and the share of replaced values is reported.

## 5. Candidates (all unsupervised, fitted on fault-free train windows)

### C1: per-tag baseline with CUSUM

- For each tag and each regime (or the pooled baseline): median and robust scale of `mean`, `slope_per_s` and sqrt(`standard_deviation`).
- Per-tag components: z-score of each of the three window statistics, and a CUSUM component: the raw 300-second series is standardised with the regime median of `mean` and a sample scale sqrt(robust scale of `mean`, squared, plus the median of `standard_deviation`, squared); the two-sided CUSUM with reference value k = 0.5 is run over the window and its maximum is taken; log(1 + maximum) is standardised with the median and robust scale of the same quantity over fault-free train windows of that tag (pooled over regimes).
- Per-tag score: maximum of the absolute values of the four components.
- Window score: mean of the three largest per-tag scores (top-3 mean).

### C2: PCA monitoring (two variants)

- Columns: the three allowed statistics of each tag, with sqrt(`standard_deviation`) as the spread column; each column standardised with the robust rule above.
- PCA fitted on the standardised fault-free train columns of the regime (pooled when the regime has fewer than 200 windows). Number of components: the smallest number that explains at least 95% of the variance, decided on fault-free train data only.
- T-squared on the retained components and squared prediction error (SPE) on the residual. Limits are the 99th percentiles of the fault-free train T-squared and SPE of that regime. Window score: maximum of T-squared divided by its limit and SPE divided by its limit.
- C2a: all 14 tags (42 columns). C2b: one PCA per process group, window score is the maximum over groups. The reference declares no groups; they are read from the declared connections: receipt side (FT-001, PT-001, TT-001: receipt meter, receipt header), storage (LT-101, LT-102, LT-103, TT-101, TT-102, TT-103: the three tank branches), transfer (PT-201, PT-202A, PT-202B, PT-203, FT-201: suction header, pumps, discharge header, delivery meter).

### C3: topology residuals

The reference does not say where an instrument sits; the tag-to-location mapping below follows the tag names and is an assumption of this experiment. The declared connections give a single line (receipt meter, receipt header, three parallel tank branches, suction header, two parallel pump branches, discharge header, delivery meter) with measured flow only at its two ends, so a mass balance is possible for the plant as a whole and not for inner pipe segments.

- R1 plant mass balance: FT-001 mean minus FT-201 mean, minus the storage term, the sum over the three tanks of a_i times 3600 times the level slope of LT-10i. The coefficients a_i and an intercept are fitted by least squares on fault-free train windows (all regimes pooled). The residual is the score input.
- R2 pump head: for each pump state (only A running, only B running, both running), PT-202x minus PT-201 (x the running pump) against FT-201 mean, a quadratic fit on fault-free train windows of that pump state. With both pumps running, the larger of the two residuals.
- R3 discharge loss: PT-202x minus PT-203 against FT-201 mean, quadratic, per pump state, same fit rule.
- R4 receipt line: PT-001 against FT-001 mean, quadratic, per regime (pooled for regimes below 200 windows).
- Noise-aware margin: each residual r is standardised with the robust scale of the fault-free train residuals of its fit group (sigma), then dead-zoned: z = max(0, |r| - 1 sigma) / sigma. The dead zone is one sigma for every residual.
- Window score: the maximum of the z values that apply to the window (a pump residual applies only when a pump is running).

### C4: fusion (fixed rule, no label-trained stacking)

For each of C1, C2a, C2b and C3 a calibrated p-value: p = (number of fault-free train windows with score at least this score + 1) / (number of fault-free train windows + 1). Fused score = minus log10 of the smallest of the four p-values. No weights.

## 6. Metrics and baselines

Baselines: always-flag (constant score), a random score (uniform, seed 20261108), and C0, the current Agent 2 random forest run as is (its raw positive-class score, shipped artifact, on the same windows).

Metrics, computed on validation windows:

- Average precision against prevalence 0.1246.
- AUROC overall.
- AUROC at matched episode stage: for every episode position that holds both faulty and fault-free windows, the AUROC among the windows at that position; the pooled value weights each position by its number of faulty-times-fault-free pairs.
- False-alarm rate on fault-free windows at the chosen threshold, and recall by fault type at the same threshold. The threshold targets a 5% false-alarm rate and is cross-fitted: validation episodes are split into two folds by the parity of the episode identifier read as hexadecimal; the threshold used on one fold is the 95th percentile (numpy linear interpolation) of the fault-free window scores of the other fold. Reported values pool both folds.
- Fault types: restriction (single component, mechanism restriction_position_visible or restriction_obstruction), pump, bias, drift, stuck, leak, misrouting, and multi-component (more than one injected component).
- Confidence intervals: 95% percentile bootstrap, 1,000 resamples, seed 20261108, resampling whole episodes (windows of one episode are not independent).
- Not reported: F1 of any kind, point-adjusted or otherwise.

## 7. Controls

- Shuffle test: 200 permutations of the labels (seed 20261108); report the mean and the 2.5% to 97.5% range of AP, AUROC and matched-stage AUROC (the last with permutations inside each position). Expected: AP near prevalence, AUROC near 0.5.
- Matched-position control: matched-stage AUROC for every candidate and for C0.
- Constant-feature control: for every candidate, the 10 tags or residuals with the largest mean contribution to the score on faulty windows are printed. Every base column used is checked: if it takes fewer than 3 distinct values or has zero variance across faulty windows, the candidate is flagged as using an artefact (the earlier 161.071 s value was of this kind).

## 8. Stop rule and time-box

If no candidate among C1, C2a, C2b, C3, C4 has both (a) validation average precision with 95% interval lower bound above 0.1246 and (b) matched-stage AUROC with lower bound above 0.55, the experiment stops and the report states that no candidate beat chance. No further variants are added, no hyperparameter is revisited, and no candidate beyond those listed is run. A candidate that passes both is reported with its full table; passing the stop rule is not a claim of usefulness, only that it is not distinguishable from chance by this test.

## 9. Reproduction

All code is under the experiment tool folder (a plain folder, not a package). The results report lists the exact commands, the seed 20261108 and the commit of the code.

## 10. Amendment 1

Written after the scoring stage had been run once and before any label-based metric was computed. The scoring stage uses labels only to choose the fault-free train windows.

What was found, with a label-free check of the fitted baselines against the validation windows: the temperature tags (TT-001, TT-101, TT-102, TT-103) hold one of a few discrete set points per episode. Train fault-free windows sit at 25, 35 and 45 degrees C (25 is the median), validation windows at 35, 40 and 45, so 40 degrees C was held out of training. The median absolute z-score of the temperature level is about 0.1 on train and about 62 on validation, so the registered C1, C2 and C4 scores are dominated by a temperature shift that has nothing to do with faults. Section 2 did not anticipate this.

What stays: the registered candidates C1, C2a, C2b, C3 and C4 are run exactly as registered. They are the only candidates the stop rule of section 8 applies to, and their table comes first in the results.

What is added, as an exploratory sensitivity that cannot change the outcome of the stop rule: one variant of each of C1, C2a, C2b and C4, named C1s, C2as, C2bs and C4s. They are identical to the registered ones except that the level components of the four temperature tags (the `mean` column and the CUSUM component) are set to zero before scoring; slope and spread of those tags are kept. C3 does not use temperature and is not repeated. C4s fuses C1s, C2as, C2bs and C3 with the same rule. They are reported in a separate table labelled as sensitivity. No other variant will be added.

## 11. Amendment 2

Written on branch detector-v2 after the first experiment and the split audit, and before anything was run with the key defined here.

### 11.1 Correction of Amendment 1

Amendment 1 stated that 40 degrees C was held out of training. That is wrong. Train contains 40 degrees C: 203 episodes and 1,010 fault-free eligible windows. The shift between train and validation is in the mixture, not in the set of values. Train fault-free windows are 54% at 25 degrees C, while validation has none at 25 degrees C; validation windows are 55% at 40 degrees C against 12% of train. The sensitivity variants of Amendment 1 are unchanged; only the stated reason is corrected. Section 10 is left as written so that the correction stays visible.

### 11.2 Change of the regime key

Reason: a regime key must not contain fault effects.

The key of the first experiment (sections 4 and 5) was the state of the 16 on/off tags of the window: LSHH-101, LSHH-102, LSHH-103, P-101A, P-101B and the valve contact states XV-PAI, XV-PAO, XV-PBI, XV-PBO, XV-R000, XV-R101, XV-R102, XV-R103, XV-S101, XV-S102 and XV-S103, each as the latest value in the window summary. Restriction and misrouting act on valve positions, so for those windows the key differs from every fault-free key because of the fault. The evidence is in `reports/detector_v2_regime_audit.md`: 405 of 490 train restriction windows and all nine misrouting windows carry a key that no fault-free train window has. A baseline or a 200-window guard built on that key separates those windows by construction.

New key: the operator-set operating conditions of the episode, (atmosphere, temperature in degrees C, flow set point in m3/h). The stress flag is a set condition and equals temperature 45 degrees C in every train and validation episode, so it adds nothing to the key. The values are read from the label file of train and validation episodes only (strata block); no fault field is read for the key. The audit hook is widened to allow exactly that file for train and validation episodes and nothing else under the evaluator folder.

All other rules are unchanged: a regime with at least 200 fault-free train windows has its own baseline, any other regime uses the pooled baseline, and no novelty score is added. The pump-state selector of C3 (R2 and R3) is not part of the key; it is read from the pump run tags of the window, as before.

Counts under the new key (full table in the evidence document): 32 regimes occur; 13 have 200 or more fault-free train windows and hold 6,084 of 8,579 fault-free train windows; 2,944 of 3,980 validation windows fall in regimes without an own baseline and use the pooled baseline. All regimes at 25 degrees C are train only; validation has none there.

### 11.3 Re-run

C3 and C4 are re-run on validation with the new key, with the same constants, thresholds and cross-fitting as before. Every metric of the first run is reported next to the new value, including recall at 5% false alarms for each fault type, restriction and misrouting in particular. C1 and C2 are not part of the re-run requested; their per-regime baselines also change with the key, and they are re-run only as inputs to C4. Nothing is tuned and the result does not reopen the stop rule of section 8.

## 12. Phase B: enhancements under grouped cross-validation (registered before any Phase B run)

Written on branch detector-v2 after the Amendment 2 re-run (section 11.3) and before any Phase B score was computed. The Amendment 2 re-run is reported as it came out. The constants below are fixed; none is tuned.

### 12.1 Evaluation protocol

- Unit: (family, atmosphere, temperature) of a train episode, as in the campaign split rule. Units are sorted lexicographically and unit i goes to fold i mod 5.
- Grouped cross-validation (CV): for each fold, every component is fitted on the fault-free windows of the other units only (baselines, regressions, PCA, residual fits, calibration references), and all eligible windows of the held-out units, faulty and fault-free, are scored. Fault-free windows of a faulty episode (before onset) count as fault-free. The out-of-fold (OOF) scores of all eligible train windows are pooled for the metrics.
- Validation benchmark: fit on all fault-free train windows, score validation. It is the held-out-combination benchmark and is reported separately. It does not enter the stop rule.
- Regime key: operator-set conditions (section 11.2). A regime with 200 or more fault-free windows in the fit set of the fold has its own baseline; every other regime uses the pooled baseline.
- Metrics, unchanged from section 6: average precision (AP) against prevalence, AUROC, matched-stage AUROC, false-alarm rate (FAR) and recall by fault type at a 5% FAR threshold cross-fitted by the parity of the episode identifier, 95% percentile bootstrap over whole episodes (1,000 resamples, seed 20261108).
- Added: false alarms per day = FAR times 288 (windows are 300 s long, 288 per day). Detection delay: for each faulty episode, the cutoff of the first alarmed faulty window minus the earliest fault onset, in seconds; the median and quartiles over episodes with an alarm are reported together with the share of faulty episodes never alarmed (censored, not imputed). Windows are 300 s apart, so delays are multiples of 300 s up to the position of the onset inside a window.
- Localisation: on single-component faulty windows of the sensor faults (bias, drift, stuck), whether the faulty tag is first (top-1) or among the first three (top-3) when the 14 tags are ranked by the per-tag evidence of the system. The declared reference gives no instrument-to-equipment mapping, so leak, restriction, misrouting and pump windows are not scored for localisation and the report says so.
- Paired differences: for a system against the previous one, the difference of AP and of matched-stage AUROC is bootstrapped on the same episode resamples; the 95% percentile interval is reported.

### 12.2 Baseline system B0

The registered candidates rebuilt on the summary columns only, with the new key and run under grouped CV: C1n (C1 without the CUSUM component, because a raw-series pass per fold is outside the time-box; the CUSUM is kept in the Amendment 2 validation re-run), C2a, C2b, C3 and the fusion C4n (minimum calibrated p-value of C1n, C2a, C2b, C3, calibrated on the fit-set scores). All constants as in sections 4 and 5. C4n is the system S0. A system always means a fusion.

### 12.3 Candidates

Each is applied once, in this order, to the previous kept system; each has a physical reason.

- E1, set-point-conditioned baselines. Reason: in a fault-free plant the flows, pressures and temperatures follow the set conditions, so the expected value of each column is a smooth function of them; a regression generalises to combinations with few fault-free windows, where a regime median does not exist. For each of the 42 columns, least squares on [1, t, t squared, q, q squared, t times q, inland], with t = (temperature - 35)/10 and q = (set point - 450)/150, fitted on the fit-set fault-free windows. The expected value replaces the regime median; the scale is the robust scale rule of section 4 on the residuals of the fit-set windows (pooled). C1n, C2a and C2b use these residuals; C3 is unchanged.
- E2, mass balance compensated for tank inventory change. Reason: the inventory change of the three tanks is the level slope times the tank area, and flow-meter error grows with flow. The R1 of C3 already contains the storage term with fitted areas; E2 adds a flow-proportional meter term and a set-point term: FT-001 mean minus FT-201 mean regressed on [three level slopes times 3600, 1, FT-201 mean, set point]. The fitted tank areas are reported and must be positive; a negative area is reported as a failure of the physical reading. The stop rule applies to the difference from the previous system.
- E3, related sensor pair residuals for bias and drift. Reason: instruments that measure the same quantity must agree in a healthy plant, so an offset or drift in one shows as a residual that does not depend on the process state. R5: each of TT-101, TT-102 and TT-103 mean minus the median of the three, standardised on the fit-set fault-free windows with the robust scale rule, dead zone of one sigma, value = the largest over the three tags. R6: PT-202A mean minus PT-202B mean when both pumps run, standardised in the same way. Both are added to the residuals of C3 (the window score of C3 is the maximum over all applicable residuals).
- E4, out-of-sample calibration of the fusion. Reason: the p-values of C4 are computed from scores of the same windows the baselines were fitted on, which understates the scores of unseen fault-free windows. Inside the fit set of each outer fold, the units are split into 4 inner folds by the same rule (sorted, i mod 4). For each inner fold, all components are refitted on the other inner folds and the fault-free windows of the held-out inner fold are scored. The pooled scores of those windows are the reference of each component; p = (number of reference scores at least the score + 1)/(number of reference scores + 1). The components used for the outer scoring are fitted on the whole fit set, as before. The fusion rule is unchanged.

### 12.4 Controls for every candidate and every system

- Shuffle: 200 permutations of the labels within position (seed 20261108) on the OOF scores.
- Placebo: matched-stage AUROC on positions 1 to 5, label = the episode contains a fault later, bootstrap over episodes. A system that separates these windows reads the kind of episode, not a fault.
- Constant-column check: the columns each component reads are printed; any with fewer than 3 distinct values or zero variance across faulty windows flags the component. For E1 the regressors (the set conditions) are listed as inputs and checked in the same way over all windows.
- Condition-only reference: a score equal to the fault prevalence of the window's regime among fit-set windows, fitted per fold. It shows how much a function of the set conditions alone achieves; a system near it is reading the conditions.
- Top contributors, as before.

### 12.5 Stop rule and time-box

A candidate is kept only if its system improves the grouped-CV AP and the grouped-CV matched-stage AUROC over the previous kept system, with the 95% bootstrap interval of each paired difference above zero. Otherwise it is reported and dropped, and the next candidate is applied to the previous kept system. No candidate beyond E1 to E4 is run and no constant is revisited. Each candidate gets one scoring run; a run that fails because of a code error is repaired and repeated once. The validation benchmark is reported for every system and is not used to decide.

## 13. Stage three: C3 alone (registered before any run of this stage)

Written on branch detector-v2 after the grouped cross-validation results (section 12) and before any quantity of this section was computed. The candidate is C3 alone, the topology residuals of section 5 with the operator-set condition key of section 11.2. C1, C2, C4 and every fusion are dropped. C3 is the same in every system of section 12, so the saved scores of the baseline system are used: out-of-fold (OOF) scores of the 9,832 eligible train windows from the 5 grouped folds, and the validation scores of the model fitted on all fault-free train windows. Nothing is refitted and no constant is changed.

### 13.1 What was looked at before this section was written

Only the structure of the saved arrays, no score. Train: 1,603 episodes, 290 with at least one faulty-labelled eligible window, 349 with no fault in the label file, 964 whose fault lies after their last eligible window. Validation: 673 episodes, 120 with faulty windows, 136 with no fault, 417 with a late fault. Episodes have 2 to 12 eligible windows (median 5), every faulty episode has gaps in its window positions (windows with an invalid label are not eligible), and no position is duplicated.

### 13.2 Definitions

- Fault-free episode: an episode without any faulty-labelled eligible window (train 1,313, validation 553). Its eligible windows are all labelled fault-free.
- Faulty episode: an episode with at least one faulty-labelled eligible window. Its fault type is the type of its first faulty window. Its onset is the earliest onset in its label file.
- Fault-free window: a window labelled fault-free, including the windows before onset in faulty episodes.
- Window threshold (reference): the 95th percentile of fault-free window scores of the other parity fold, as in section 6, giving a window false-alarm rate (FAR) of 5%.

### 13.3 Operating characterisation (part 1)

Window level at the reference threshold: FAR, false alarms per day = FAR times 288, recall by fault type, with the 95% bootstrap over episodes of section 6, out of fold and on validation.

Alarm policies, fixed here. A policy is k of the last n, with (k, n) in {(1, 1), (2, 3), (3, 5)}. At a window at position t the policy is alarming when at least k of the windows at positions t-n+1 to t that exist in the episode have a score above the threshold; a missing position does not count as above. The policy is evaluated at eligible windows only. All three policies are reported, including bad ones.

Threshold of a policy: the target is that no more than 5% of fault-free episodes contain an alarming window. The threshold is the smallest value among the fault-free-episode window scores of the calibration set such that the policy, applied to the calibration episodes, alarms in at most 5% of them (strictly above the threshold counts as exceeding). Calibration sets: out of fold, the OOF scores of the fault-free episodes of the other folds; on validation, the OOF scores of all fault-free train episodes (scores of windows that the model did not see). The threshold is not re-estimated inside the bootstrap.

Reported per policy, out of fold and on validation: fault-free episodes with any alarm (count, share); window-level alarm rate on fault-free windows and false alarms per day = that rate times 288; episode-level detection rate = share of faulty episodes with the policy alarming at one or more faulty-labelled windows, overall and by fault type; delay = cutoff of the first alarming faulty window minus the earliest onset, quartiles over detected episodes, with the number never detected; window recall by fault type = share of faulty windows at which the policy is alarming.

### 13.4 Controls

- Shuffle, window level: 200 permutations of window labels (within position for the matched-stage statistic), seed 20261108, for AP, AUROC and matched-stage AUROC of the C3 score. Shuffle, episode level: 200 permutations that give the onsets of the faulty episodes to randomly chosen episodes (same number, onsets in random order) and recompute the detection rate of each policy; expected value is the alarm rate of the policy over arbitrary windows after a random time.
- Placebo: matched-stage AUROC of the C3 score on positions 1 to 5 with label = the episode contains a fault later (as in section 12.4), and for each policy the difference in alarming rate on fault-free windows at positions 1 to 5 between episodes that later contain a faulty window and episodes that never do, with a bootstrap interval.
- Constant-column check: the columns C3 reads are listed and checked as before.

### 13.5 Residual signature matrix (part 2)

For each fault type (and fault-free windows as a reference row), out of fold and on validation: the mean share of each residual R1 to R4 in the C3 score (residual divided by the sum of the four), the fraction of windows in which it is the top contributor (largest value; all four zero counts as no top contributor, reported as its own column), and the fraction in which it exceeds its own threshold. A residual's own threshold is the 95th percentile of that residual among fault-free windows of the other folds out of fold, and among OOF fault-free train windows on validation; strictly above counts. Descriptive only, nothing is tuned on it.

Classification, fixed here: a fault type has a distinct signature when the largest exceed fraction among R1 to R4 is at least 0.30 and at least twice the second largest; no usable signature when the largest is below 0.15; shared otherwise. A type is called distinct only if the classification agrees out of fold and on validation; otherwise the disagreement is reported.

### 13.6 Runtime feasibility and commanded lineup (parts 3 and 4)

Read-only. No model is run and nothing is evaluated for part 4. Part 3 lists every input C3 uses and states for each whether the Agent 2 request carries it at runtime, what the request lacks, whether the topology and the tag-to-location mapping fit a small pinned parameter file, and how the mapping is derived and what is unverified. Part 4 states whether the commanded valve or lineup state is in the request, whether it is independent of the injected fault, how a commanded-against-observed valve check would be defined and what could make it leak the label.

## 14. Stage four: pooled R4 and a stress test of C3 (registered before any run of this stage)

Written on branch detector-v2 after the C3 characterisation (section 13) and before any quantity of this section was computed. Nothing in the grouped-CV protocol of section 12 changes: the same 5 folds by unit, the same fit rule (fault-free windows of the other units), the same metrics.

### 14.1 Pooled R4

C3 with the R4 receipt-line fit made once on all fault-free windows of the fit set (a quadratic of PT-001 against FT-001 mean, one scale), used for every window, and no per-regime fit. R1, R2 and R3 are unchanged. The scoring does not read the atmosphere, the temperature or the flow set point. Compared with the per-regime C3 of section 13, out of fold and on validation:

- AP, AUROC and matched-stage AUROC; window false-alarm rate and recall at the 5% window target (section 13.2); recall by fault type;
- the episode-level policies 1/1, 2/3 and 3/5 with the threshold rule of section 13.3;
- the paired difference pooled minus per-regime of AP and of matched-stage AUROC, 95% bootstrap over episodes on shared resamples;
- the shuffle and placebo controls of section 13.4.

No decision rule is attached: the result is reported either way. The per-regime C3 is the one saved in section 13.

### 14.2 Minimal-input check

The inputs of the pooled version are listed from the code and tested by perturbation: the scores must not change when (a) every window statistic outside the twelve listed below is replaced by an arbitrary constant, (b) the regime key and the order of the windows are scrambled, and (c) a window is scored alone instead of among the others. The twelve inputs are the window mean of FT-001, FT-201, PT-001, PT-201, PT-202A, PT-202B and PT-203, the window slope of LT-101, LT-102 and LT-103, and the latest value of P-101A and P-101B. The contract example request of Agent 2 is read, without change, to confirm that each of the twelve is a field of its summary signals with the expected unit, and one window is scored from it.

### 14.3 Stress test (no tuning, nothing refitted)

Models are those of the grouped-CV folds and of the validation fit, unchanged. Window inputs are perturbed, seeded by numpy `default_rng([20261108, code, fold])` with code 10 + m for m missing tags and 20 + k for noise at k times, and fold 0 to 4 out of fold and 5 on validation. One draw per setting.

(a) Missing tags. For every window, m of the twelve inputs, chosen at random without replacement, are made unknown, for m in {1, 2, 3}. Unknown is neither zero nor healthy. A residual is unavailable when an input it reads is unknown: R1 reads FT-001, FT-201 and the three level slopes; R2 reads PT-202x, PT-201, FT-201 and the pump state; R3 reads PT-202x, PT-203, FT-201 and the pump state; R4 reads PT-001 and FT-001; the pump state needs both pump tags, and x is the running pump. A residual that does not apply (pump not running) is not available either. The window score is the maximum over the available residuals. A window with none is unscorable.

(b) Noise. Gaussian noise is added to the window statistics of the ten numeric inputs, independently, with standard deviation k times s, k in {1, 2, 3}, where s is chosen so that the input alone would move the residual it enters by one fault-free residual scale of the fitted model: FT-001 and FT-201 by the scale of R1; each level slope by the scale of R1 divided by 3600 times the fitted tank area; PT-001 by the scale of the pooled R4; PT-202A and PT-202B by the scale of the R2 fit of that pump; PT-201 by the mean of the two R2 scales; PT-203 by the mean of the two R3 scales. The pump tags receive no noise.

Both perturbations apply to all windows, faulty and fault-free. The alarm threshold is fixed: the threshold of the unperturbed windows of the same set (95th percentile of the fault-free window scores of the other parity fold, section 13.2), applied unchanged to the perturbed scores, so the false-alarm rate may rise. Unscorable windows are ranked below every scorable window for AP and AUROC and count as not alarmed. Reported for each setting, out of fold and on validation: AP, matched-stage AUROC (95% bootstrap over episodes), false-alarm rate and recall at the fixed threshold, and the share of windows (all, and faulty) that are scorable. It is a realism check; no setting is used to change the detector.

### 14.4 What a deployed Agent 2 can claim

A short section of the report states, from sections 13 and 14 only: window-level evidence, the policy that needs history, and the residual-level statements the signatures support (pump with R2; drift and leak with R1), with the ambiguity between a leak and a flow-meter error in R1 stated. A per-asset breakdown of the signature for sensor faults is added there as a descriptive check of that statement; it is not tuned on and it changes nothing.
