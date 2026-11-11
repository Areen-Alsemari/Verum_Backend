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
