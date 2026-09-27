"""Reproduce the dataset facts quoted in docs/METHODOLOGY.md against the local data.

    python training/section0_facts.py  -> reports/section0_facts.json (+ prints divergences)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import rail_features
from _paths import DATA, REPORTS, now
from diagnostics import door, shm
from diagnostics.common import save_json
from diagnostics.metrics import interval_iou

EXPECTED = {
    "door_train_rows": 18036, "door_test_rows": 6253, "door_segments": 110, "door_test_segments": 38,
    "door_normal": 80, "door_abnormal": 30, "rail_train_files": 272, "rail_test_files": 68,
    "rail_normal": 234, "rail_side_i": 14, "rail_side_ii": 24, "rail_fault_min_transitions": 654,
    "rail_normal_ge_654": 101, "rail_normal_flat": 38, "shm_train_files": 64, "shm_test_files": 16,
    "shm_rows": 581120, "acv_train_cases": 6,
}


def main():
    f = {}
    d = door.parse(DATA / "Door" / "Train.csv")
    te = door.parse(DATA / "Door" / "Test.csv")
    lab = pd.read_csv(DATA / "Door" / "Train_Segments_Answer.csv", dtype=str)
    f["door_train_rows"], f["door_test_rows"] = len(d.frame), len(te.frame)
    segs = door.segment(d.t, 1.0, (0.03, 10.0))["segments"]
    f["door_segments"] = len(segs)
    f["door_test_segments"] = len(door.segment(te.t, 1.0, (0.03, 10.0))["segments"])
    t0, _ = door.parse_timestamps(lab.start_time)
    t1, _ = door.parse_timestamps(lab.end_time)
    f["door_mean_iou"] = float(np.mean([interval_iou(d.t[a], d.t[b], x, y) for (a, b), x, y in zip(segs, t0, t1)]))
    f["door_normal"] = int((lab.status == "Normal").sum())
    f["door_abnormal"] = int((lab.status == "Abnormal resistance").sum())
    integ = {}
    for (a, b), (_, r) in zip(segs, lab.iterrows()):
        v = door.cycle_features(d.frame.iloc[a:b + 1], d.t[a:b + 1])["current_integral_mAs"]
        integ.setdefault(f"{r.operation}/{r.status}", []).append(v)
    f["door_integral_ranges"] = {k: [round(min(v), 1), round(max(v), 1)] for k, v in integ.items()}

    rl = pd.read_csv(DATA / "Rail_Corrugation" / "Train_Labels.csv")
    rows = rail_features.extract_all("Train")
    tr = pd.Series({r["file"]: r["transitions"] for r in rows})
    y = rl.set_index("filename").label.loc[tr.index]
    f["rail_train_files"] = len(rows)
    f["rail_test_files"] = len(list((DATA / "Rail_Corrugation" / "Test").glob("*.csv")))
    f["rail_normal"], f["rail_side_i"], f["rail_side_ii"] = [int((y == c).sum()) for c in ("Normal", "Side I", "Side II")]
    f["rail_fault_min_transitions"] = int(tr[y != "Normal"].min())
    f["rail_normal_ge_654"] = int(((y == "Normal") & (tr >= 654)).sum())
    f["rail_normal_flat"] = int(((y == "Normal") & (tr == 0)).sum())

    sl = pd.read_csv(DATA / "SHM" / "Train_Labels.csv")
    f["shm_train_files"] = len(sl)
    f["shm_test_files"] = len(list((DATA / "SHM" / "Test").glob("*.csv")))
    f["shm_rows"] = len(shm.parse(DATA / "SHM" / "Train" / "train01.csv").x)
    f["shm_target"] = {"min": float(sl.damage.min()), "median": float(sl.damage.median()), "max": float(sl.damage.max()),
                       "below_0.1": int((sl.damage < 0.1).sum())}
    f["acv_train_cases"] = len(list((DATA / "ACV" / "Train").glob("*.xlsx")))

    diverge = {k: {"expected": v, "observed": f.get(k)} for k, v in EXPECTED.items() if f.get(k) != v}
    if f["door_mean_iou"] != 1.0:
        diverge["door_mean_iou"] = {"expected": 1.0, "observed": f["door_mean_iou"]}
    out = {"created": now(), "facts": f, "divergences": diverge,
           "note": "Reproduction of the documented dataset facts against local data. Divergences must be reconciled before release."}
    save_json(REPORTS / "section0_facts.json", out)
    print("divergences:", diverge or "none")


if __name__ == "__main__":
    main()
