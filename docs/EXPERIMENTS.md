# Pre-registered model experiments

Every change to a frozen model was run as a pre-registered experiment. The hypothesis and the promotion rule were written down before the experiment ran, and if the rule was not met, the current model stayed. Three experiments were run. One change was promoted (Door D2); two were not, and they are reported here anyway.

**Rules that applied to every experiment**

- Evaluation uses training data only, with the same fold definitions as the headline validation (see [METHODOLOGY](METHODOLOGY.md)).
- Organizer test files are never used for fitting, threshold choice or selection. Unlabelled test inputs were inspected only to check that they parse.
- Code: `training/experiments/`. Recorded results: `reports/validation/experiments/<id>.json`.

## E1 — Door: stream-relative cutoff (D2)

**Motivation.** The Door Info Kit (§1.2) warns that "data distributions differ among doors; applying a uniform threshold leads to false alarms and missed detection". A rule with a fixed mA·s cutoff cannot transfer to a door whose Normal cycles draw more current, and we have only one training door.

**Hypothesis.** Within one direction (Open or Close), abnormal resistance raises the motor-current integral by a roughly constant *ratio* relative to that door's own Normal level. A rule expressed as a ratio to a robust per-stream baseline should therefore transfer across doors, and a fixed absolute cutoff should not.

**Method D2.** For each direction in the stream being analysed, the baseline `b` is the 25th percentile of that direction's cycle integrals (robust while up to 75% of cycles are abnormal). A cycle is Abnormal if `x > b · r_dir`. The ratio `r_dir` is frozen from training as the geometric midpoint between the largest Normal ratio and the smallest Abnormal ratio, with `b_train` computed the same way on the training stream. **Frozen fallbacks:** if a direction has fewer than 8 cycles, or `b` lies outside 0.8–1.25× the training Normal median for that direction, use the absolute cutoff (D0) and add a `baseline_unavailable` review reason.

**Evaluation.** (a) Unshifted: the five contiguous time blocks, with the held-out block's baseline computed from the held-out block alone, as a real stream would be. (b) Synthetic door shift: the held-out block's motor current is multiplied by 0.90, 0.95, 1.05, 1.10, 1.15 and 1.20, and offset by −50, +50 and +100 mA, before feature extraction. D0 and D2 are scored on the same blocks.

**Promotion rule (fixed in advance).** Promote D2 if (i) its unshifted blocked-CV mean is at least D0's mean − 0.01, and (ii) its mean over the six multiplicative shifts is at least D0's + 0.05.

| | Unshifted IoU-F1 | Mean over ×0.90–1.20 | −50 mA | +50 mA | +100 mA |
|---|---|---|---|---|---|
| D0 absolute cutoff | 0.991 | **0.711** | 0.982 | 0.836 | 0.273 |
| D1 direction-conditioned logistic regression | 0.991 | 0.820 | 0.964 | 0.955 | 0.282 |
| **D2 stream-relative** | 0.991 | **0.991** | 0.982 | 0.991 | 0.991 |

**Decision: promoted** as `door-D2-1.1.0` (ratio cutoffs: Open 1.0986×, Close 1.1290×). There were zero fallbacks to the absolute cutoff on the unshifted blocks. **Caveat:** a ratio rule is invariant to multiplicative scaling *by construction*. The informative evidence is the unshifted parity and the additive offsets, and no second real door exists to test on.

**Effect on the exported Door predictions** (inference only, no tuning): 8 of 38 test cycles are Abnormal (D0: 10). The two that changed:

| Cycle | Start | D0 | D2 | Why |
|---|---|---|---|---|
| 22 (Close, 1769 mA·s) | `2023-7-5-0-13-17-531` | Abnormal resistance | Normal | 1.087× this stream's Close baseline, below the training Normal maximum ratio 1.107×. It sits at the top of a 1751–1769 mA·s cluster that the absolute cutoff (1768.0) split. |
| 33 (Open, 2010 mA·s) | `2023-7-5-0-20-55-731` | Abnormal resistance | Normal + `near_boundary` review | 1.081×, between the Normal maximum (1.033×) and Abnormal minimum (1.168×) ratios and below the 1.0986× cutoff. Ambiguous under both rules, so it is flagged for review. |

Review flags on `Test.csv` fell from 15 to 1, because the shifted clusters are Normal *relative to this door*. Whether that is correct is unknown until the organizers score it. The pre-registered evidence says a ratio rule is the safer choice on a different door.

## E2 — ACV: physically motivated alternative rankers

**Motivation.** A refrigerant leak reduces cooling capacity. Under load, you would expect three signatures: the cabin sits further above its own target than its peers do, the unit spends more of its cooling time at full demand, and the cabin cools more slowly after cooling starts.

**Candidates** (fixed formulas, no fitted weights, all on the same settled, valid cooling samples as the deployed A0 score):

- **A2a shortfall:** mean of `(cabin − target)` for the car minus the peer median of the same quantity at the same time.
- **A2b full-demand share:** the car's fraction of cooling samples in `Full Cooling`, minus the peer median.
- **A2c hot-period residual:** A0 restricted to the hottest third of timestamps.
- **A2d cooling slope:** mean temperature change over the first 20 samples after each entry into cooling, car minus peer median.
- **A3 combined:** mean of within-case z-scores of A0 and A2a.

**Evaluation.** Leave-one-case-out on the six training cases, reporting mean rank-decay, top-1 count and the normalised margin `(true − runner-up) / (max − min)`.

**Promotion rule (fixed in advance).** Promote a candidate only if its mean is above 0.979 (that is, 6/6 top-1) **and** its mean normalised margin is at least A0's. Six cases cannot separate candidates that tie.

| Ranker | Mean rank-decay | Top-1 | Normalised margin |
|---|---|---|---|
| **A0 peer residual (deployed)** | 0.979 | 5/6 | 0.358 |
| A2a shortfall | 0.979 | 5/6 | 0.250 |
| A2b full-demand share | 0.625 | 0/6 | −0.873 |
| A2c hot-period residual | **1.000** | **6/6** | 0.340 |
| A2d cooling slope | 0.604 | 2/6 | −0.532 |
| A3 z-mean of A0 and A2a | 0.979 | 5/6 | 0.331 |

**Decision: not promoted.** A2c met the score condition but not the margin condition (0.340 < 0.358), so A0 stays as the prediction. A2c is shown in the app as secondary evidence (the `hot_period_disagreement` review reason). On the test case the two disagree (Car 03 overall, Car 04 in the hottest third, both about +0.03 K apart), and the app says so.

## E3 — Rail: bounded stage-1 alternatives

**Candidates** on the same cached features and the same hash-grouped folds and seeds: R2a, a `HistGradientBoostingClassifier` stage 1 (300 iterations, balanced sample weights); R2b, a direct three-class Random Forest on stage-1 plus stage-2 features (no two-stage split).

**Promotion rule (fixed in advance).** Promote only if the speed-matched mean macro F1 is at least 0.793 + 0.017 (one seed standard deviation) **and** the full-set mean is at least 0.805 **and** the speed-matched Side I F1 (seed 0) is at least 0.667. Any promotion adds one more selection round to the optimism already disclosed.

| Candidate | Speed-matched macro F1 | Full-set macro F1 |
|---|---|---|
| **R1b RF + side model (deployed)** | 0.793 | 0.810 |
| R2a HistGradientBoosting stage 1 | 0.776 ± 0.022 | 0.788 ± 0.047 |
| R2b direct three-class RF | 0.811 ± 0.021 | 0.803 ± 0.012 |

**Decision: not promoted.** R2b misses the full-set bar by 0.002, which is equivalent within seed noise, so the deployed `rail-R1b_RF_sidemodel-1.0.0` was kept rather than adding another selection round.

## Correctness fixes (no pre-registration needed)

- Adversarial tests for the official metrics (nested predictions, greedy versus optimal matching, a wrong label inside an overlap, zero-length segments).
- The SHM exporter rejects non-positive predictions.
- Door position sign and travel minimum are fitted inside each fold.

All exported CSVs were rebuilt through the app after E1, and the command-line predictor was confirmed byte-identical to the app for all four tasks.
