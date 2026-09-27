# Model card — SHM

- **Version:** `shm-S1_power_gated-1.0.0`
- **Method:** Gated rainflow power-law damage surrogate (`S1_power_gated`)
- **Created:** 2026-09-18T23:37:30
- **Training fingerprint:** `3380d686f169d988…`
- **Official metric:** max(0, 1 − MAPE) (official), MAPE as a fraction
- **Local validation (leave-one-file-out, 64 files):** max(0, 1−MAPE) = 0.975

These are local development-validation figures on the supplied training data. They are not organizer results and do not guarantee held-out performance.

## Protocol

Leave-one-file-out over 64 training files. For power-law and log-linear candidates the rainflow gate (grid [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]) and exponent m (grid 2.0–8.0 step 0.05) are selected inside each fold. No line/load-condition metadata exists, so grouped folds are not possible (disclosed).

## Candidates compared

| Candidate | Score | MAPE | Low-half MAPE | High-half MAPE |
|---|---|---|---|---|
| S0_constant | 0.417 | 0.583 | 0.338 | 0.828 |
| S0_median_constant | 0.028 | 0.972 | 1.340 | 0.604 |
| S1_power_gated | 0.975 | 0.025 | 0.032 | 0.019 |
| S1_power_ungated | 0.975 | 0.025 | 0.032 | 0.019 |
| S1b_loglinear | 0.787 | 0.213 | 0.238 | 0.188 |
| S2_ridge_log | 0.881 | 0.119 | 0.142 | 0.096 |

Selected formula: D = c · Σ nᵢ · rᵢ^m over gated rainflow cycles (r = range); gate 5.0, fitted exponent m = 5.00 (exploratory peak-range prior: 4.06).
Gating effect: gated 0.975 vs ungated 0.975. With proper rainflow pairing and m≈5, small cycles contribute negligibly, so gating does not change the score.

Selection rule: Highest LOO score; among candidates within 0.01 of it, the lowest low-target-half MAPE; a gated/ungated tie goes to the gated definition. The challenger (for disagreement review) is the best structurally different deployable candidate.

## Known limitations

- Material S–N constants are not supplied; the power-law constants are fitted to the dataset's damage labels, not physically calibrated.
- Half the files have damage < 0.1 and dominate MAPE; see low/high half figures.
- Sampling rate and stress unit are undocumented; features use sample index and raw units.
- No line/load-condition labels, so errors by operating condition cannot be reported.

## Environment

- python: 3.13.6
- numpy: 2.5.3
- pandas: 3.0.6
- scipy: 1.18.1
- scikit-learn: 1.9.1
- platform: macOS-27.0-arm64-arm-64bit-Mach-O
