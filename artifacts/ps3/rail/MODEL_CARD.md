# Model card — RAIL

- **Version:** `rail-R1b_RF_sidemodel-1.0.0`
- **Method:** Two-stage: RandomForestClassifier fault detection on side-aggregated features + Extra Trees side model (`R1b_RF_sidemodel`)
- **Created:** 2026-09-19T00:35:56
- **Training fingerprint:** `b6978852d2a0831f…`
- **Official metric:** Macro F1 over Normal/Side I/Side II (official)
- **Local validation (speed-matched grouped CV (headline)):** Macro F1 = 0.793 (full set 0.810)

These are local development-validation figures on the supplied training data. They are not organizer results and do not guarantee held-out performance.

## Protocol

Stratified group 5-fold CV (group = file SHA-256, so byte-identical files share a fold) repeated over seeds [0, 1, 2, 3, 4]; out-of-fold full two-stage pipeline. No acquisition/run metadata exists, so grouping by run is not possible (disclosed).

## Candidates compared

| Configuration | Full-set macro F1 | Speed-matched macro F1 |
|---|---|---|
| R0_rule_majority | 0.384 ± 0.019 | 0.424 ± 0.007 |
| R1_ET_majority | 0.533 ± 0.007 | 0.545 ± 0.009 |
| R1_ET_contrast | 0.633 ± 0.015 | 0.634 ± 0.017 |
| R1_ET_sidemodel | 0.752 ± 0.024 | 0.740 ± 0.032 |
| R1_ET_sidemodel_WITH_speed | 0.759 ± 0.024 | 0.739 ± 0.016 |
| R1b_RF_sidemodel | 0.810 ± 0.012 | 0.793 ± 0.017 |
| R1b_RF_sidemodel_WITH_speed | 0.810 ± 0.013 | 0.791 ± 0.017 |

Majority-class (all Normal) baseline macro F1: 0.308.
Side-discrimination gate: **established** — ExtraTrees: balanced accuracy 0.879 (permutation 95th pct 0.688); Logistic: balanced accuracy 0.852 (permutation 95th pct 0.697). Criterion: mean balanced accuracy >= 0.7 over 5 seeds of stratified group 5-fold CV on the 38 fault files AND above the 95th percentile of a label-permutation baseline.
Speed inventory: training fault files have ≥ 654 transitions; test files median 750, 9 flat. Speed-derived features excluded from the deployed model (the default); the ablation is recorded.
Speed-matched collapse: no.

Confusion (seed 0, full set, rows = truth):

| truth \ predicted | Normal | Side I | Side II |
|---|---|---|---|
| Normal | 224 | 2 | 8 |
| Side I | 3 | 9 | 2 |
| Side II | 0 | 2 | 22 |

Selection rule: Highest speed-matched mean macro F1 among speed-free configurations; the side model is eligible only if the gate passed. The RF stage-1 challenger was added after a bounded stage-1 comparison on the same folds, so these are model-selection validation figures, not an untouched final test.

## Known limitations

- No acquisition/run provenance: files from the same run may share folds, which can inflate scores.
- Fault files were acquired at higher pulse rates than half of the Normal files (speed confound); the speed-matched figure is the honest headline.
- Side assignment passed the gate.
- The pulse-to-km/h conversion is unverified; no speed is shown to users.

## Environment

- python: 3.13.6
- numpy: 2.5.3
- pandas: 3.0.6
- scipy: 1.18.1
- scikit-learn: 1.9.1
- platform: macOS-27.0-arm64-arm-64bit-Mach-O
