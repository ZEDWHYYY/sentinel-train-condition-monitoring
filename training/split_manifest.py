"""Write the saved split manifest: every validation partition used by
training/train_*.py, keyed by input SHA-256, reconstructed with the same code paths.

    python training/split_manifest.py -> reports/validation/split_manifest.json
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import rail_features
import train_door
import train_rail
from _paths import DATA, REPORTS, now
from diagnostics.common import save_json, sha256_file


def main():
    man = {"created": now(), "note": "Partitions used for every reported local validation figure. File identity = SHA-256."}
    # Door: contiguous blocks of labelled cycles in the continuous Train stream
    lab = pd.read_csv(DATA / "Door" / "Train_Segments_Answer.csv", dtype=str)
    blocks = np.array_split(np.arange(len(lab)), train_door.N_BLOCKS)
    man["door"] = {"input": {"file": "Train.csv", "sha256": sha256_file(DATA / "Door" / "Train.csv")},
                   "unit": "labelled cycle (segment_id), contiguous in time",
                   "folds": [{"fold": k, "held_out": lab.segment_id.iloc[b].tolist(),
                              "time_range": [lab.start_time.iloc[b[0]], lab.end_time.iloc[b[-1]]]} for k, b in enumerate(blocks)],
                   "gap_threshold_s": train_door.GAP_S}
    # ACV: leave one whole case out
    al = pd.read_csv(DATA / "ACV" / "Train_Labels.csv", dtype=str)
    man["acv"] = {"unit": "whole case (workbook)", "scheme": "leave-one-case-out",
                  "cases": [{"file": f, "sha256": sha256_file(DATA / "ACV" / "Train" / f), "faulty_car": c}
                            for f, c in zip(al.filename, al.faulty_car)]}
    # Rail: stratified 5-fold per seed, identical to train_rail.pipeline_cv
    rows = rail_features.extract_all("Train")
    rl = pd.read_csv(DATA / "Rail_Corrugation" / "Train_Labels.csv").set_index("filename").label
    files = [r["file"] for r in rows]
    y = rl.loc[files].to_numpy()
    tr = np.array([r["transitions"] for r in rows])
    seeds = {}
    for s in train_rail.SEEDS:
        fold = np.empty(len(files), int)
        groups = [r["sha"] for r in rows]
        for k, (_, te) in enumerate(train_rail.folds(train_rail.N_FOLDS, s).split(np.zeros(len(y)), y, groups)):
            fold[te] = k
        seeds[str(s)] = fold.tolist()
    man["rail"] = {"unit": "file (1-s recording)", "scheme": f"stratified group {train_rail.N_FOLDS}-fold (group = SHA-256), seeds {train_rail.SEEDS}",
                   "files": [{"file": f, "sha256": r["sha"], "label": lab_, "pulse_transitions": int(t),
                              "speed_matched": bool(lab_ != "Normal" or t >= train_rail.SPEED_MATCH_MIN)}
                             for f, r, lab_, t in zip(files, rows, y, tr)],
                   "fold_by_seed": seeds,
                   "note": "No acquisition/run metadata exists, so grouping by run is impossible (disclosed)."}
    sl = pd.read_csv(DATA / "SHM" / "Train_Labels.csv")
    man["shm"] = {"unit": "file", "scheme": "leave-one-file-out (gate and exponent chosen inside each fold)",
                  "files": [{"file": f, "sha256": sha256_file(DATA / "SHM" / "Train" / f), "damage": float(d)}
                            for f, d in zip(sl.filename, sl.damage)]}
    man["test_inputs"] = {
        "door": [{"file": "Test.csv", "sha256": sha256_file(DATA / "Door" / "Test.csv")}],
        "acv": [{"file": p.name, "sha256": sha256_file(p)} for p in sorted((DATA / "ACV" / "Test").glob("*.xlsx"))],
        "rail": [{"file": r["file"], "sha256": r["sha"]} for r in rail_features.extract_all("Test")],
        "shm": [{"file": p.name, "sha256": sha256_file(p)} for p in sorted((DATA / "SHM" / "Test").glob("*.csv"))],
        "note": "Held-out inputs were processed only by frozen models; never used for fitting or threshold selection.",
    }
    dup = {}
    for task in ("rail", "shm"):
        shas = [f["sha256"] for f in man[task]["files"]]
        dup[task] = len(shas) - len(set(shas))
    man["duplicate_training_files"] = dup
    save_json(REPORTS / "validation" / "split_manifest.json", man)
    print("split manifest written; duplicate training files:", dup)


if __name__ == "__main__":
    main()
