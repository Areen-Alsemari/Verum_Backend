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
