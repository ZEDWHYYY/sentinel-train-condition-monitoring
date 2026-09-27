# Prediction outputs

| File | What it is |
|---|---|
| [`predictions.zip`](predictions.zip) | **Prediction archive.** It contains exactly `door_predictions.csv`, `acv_predictions.csv`, `rail_predictions.csv` and `shm_predictions.csv`, at the root of the zip with no folders. |
| [`predictions/`](predictions) | The same four CSV files, unzipped so they can be read on GitHub. They are byte-identical to the zip members, which the test suite checks. |
| [`predictions_manifest.json`](predictions_manifest.json) | Provenance: the app analyses the zip was built from, row counts and SHA-256 of every CSV, the zip's SHA-256, and the model versions. |

The predictions come from the 86 held-out test inputs the organizers distributed (Door 1 stream, ACV 1 workbook, Rail 68 files, SHM 16 files), analysed through the app's *Analyse an official test batch* and packaged by *Export prediction bundle*. The CSV schemas are:

- **Door:** `start_time,end_time,prediction`, one row per detected cycle, using the dataset's own timestamp format. Labels are `Normal` or `Abnormal resistance`.
- **ACV:** `file_id,ranked_cars`, listing every car, most likely first, separated by `|`. Car identifiers are exactly as in the file's headers (`03`, not `Car 3`).
- **Rail:** `file_id,prediction`, with labels `Normal`, `Side I` or `Side II`.
- **SHM:** `file_id,prediction`, with a numeric cumulative-damage value.

To reproduce them, see [Reproduce the predictions](../README.md#reproduce-the-predictions-from-the-command-line). The latest app, ZIP and CLI parity check is in [`reports/prediction_export_verification.json`](../reports/prediction_export_verification.json).
