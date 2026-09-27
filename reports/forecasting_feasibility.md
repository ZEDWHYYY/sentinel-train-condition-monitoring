# Forecasting feasibility

**Decision: evaluated, not promoted. No forecast is shown in the app or included in any prediction CSV.**
Evaluation code: `training/forecast_acv.py`. Recorded results: `reports/validation/forecast_acv.json`. The results are also shown on the app's *Method and validation* page.

## Which data could support a forecast

| Question | Door | ACV | Rail | SHM |
|---|---|---|---|---|
| Timestamps / order | One continuous stream (local clock, timezone unknown) | Yes — 30 s samples (10 s in case 04) over ~1–4 days per case | No — independent 1 s recordings | No — file numbers are random |
| History of a degrading quantity | No — per-cycle labels from one session | Partly — continuous cabin temperature and cooling residual | No | No — "cumulative" is a per-segment target |
| Failure onset / time-to-failure labels | No | No — each leak is present for the whole recording | No | No |

Only ACV has contiguous telemetry, so ACV is the only candidate for a forecast.

## ACV telemetry forecast — evaluated

- **Target.** Change in a car's cabin temperature over 10, 30 and 60 minutes.
- **Inputs at the forecast origin (no future information).** The car's cabin temperature, its changes over the previous 30 s to 10 min, the difference to the contemporaneous peer median, the difference to its cooling target, and the cooling-mode flag.
- **Model.** Ridge regression.
- **Baseline.** Persistence (no change).
- **Protocol.** Leave-one-case-out. Every sample of the held-out case is a forecast origin. Origin and target must lie in the same contiguous block, so gaps are never bridged.
- **Promotion rule, fixed before running.** At least 15% lower MAE than persistence, and better in at least 5 of 6 held-out cases, at both 30 and 60 min.

| Horizon | Ridge MAE | Persistence MAE | Change in error | Held-out cases improved |
|---|---|---|---|---|
| 10 min | 0.505 K | 0.490 K | +9.0% worse | 4 / 6 |
| 30 min | 0.695 K | 0.699 K | +3.6% worse (mean of per-case changes) | 4 / 6 |
| 60 min | 0.842 K | 0.823 K | +2.6% worse | 3 / 6 |

The forecaster does not beat persistence in cases 04 and 05. Their cabin temperature is driven by mode switching and outside conditions that are not known in advance. **Not promoted.**

## What would change the decision

Two kinds of data would make a validated early-warning claim possible:
- telemetry covering a leak's onset, before and after;
- months of history for the same train, with maintenance and repair records.

Without those, SENTINEL makes diagnostic claims only: which cycle, car, side or segment the evidence points to now, with its limitations. No remaining-useful-life, failure date or failure probability is produced anywhere.
