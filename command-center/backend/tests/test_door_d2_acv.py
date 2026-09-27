"""Audit follow-ups: Door D2 stream-relative rule, ACV hot-period evidence, SHM export bound."""

import numpy as np
import pandas as pd
import pytest

from .conftest import requires_data
from diagnostics import door, exports
from diagnostics.model_store import load_model


def _door_stream(tmp_path, n_cycles=3, scale=1.0):
    rows = ["Datetime," + ",".join(door.COLUMNS[1:])]
    t = 0
    for c in range(n_cycles):
        for i in range(150):
            t += 20
            cur = int((300 + 1500 * np.exp(-((i - 20) / 8) ** 2)) * scale)
            rows.append(f"2023-7-5-0-{t // 60000}-{(t // 1000) % 60}-{t % 1000}," + ",".join(
                [str(cur), "400", "50", "24", "35", "1", "0", "0", "0", "0", "0", "0", "0", "0", "1", str(max(0, 700 - 5 * i))]))
        t += 15000
    p = tmp_path / f"s{scale}.csv"
    p.write_text("\n".join(rows))
    return p


def test_D2_falls_back_to_absolute_cutoff_with_few_cycles(tmp_path):
    m = load_model("door")
    assert m["method"] == "D2" and "relative_rule" in m
    res = door.analyze(door.parse(_door_stream(tmp_path, n_cycles=3)), m)
    codes = {r["code"] for it in res["items"] for r in it["review_reasons"]}
    assert "baseline_unavailable" in codes
    assert all(it["decision"]["rule"] == "absolute" for it in res["items"])
    assert any("fell back" in n for n in res["summary"]["stream_notes"])


def test_D2_rejects_implausible_baseline():
    m = load_model("door")
    feats = [({"current_integral_mAs": 9000.0 + i}, "Open") for i in range(10)]
    b = door.stream_baselines(feats, m)
    assert b["Open"]["baseline"] is None and "outside the plausible window" in b["Open"]["reason"]


@requires_data
def test_D2_predictions_invariant_to_current_scaling(data_root, tmp_path):
    m = load_model("door")
    d = door.parse(data_root / "Door" / "Train.csv")
    base = [i["prediction"] for i in door.analyze(d, m)["items"]]
    d.frame[door.CURRENT] = d.frame[door.CURRENT] * 1.15
    scaled = [i["prediction"] for i in door.analyze(d, m)["items"]]
    assert scaled == base
    d.frame[door.CURRENT] = d.frame[door.CURRENT] / 1.15 + 100.0
    offset = [i["prediction"] for i in door.analyze(d, m)["items"]]
    assert sum(a != b for a, b in zip(offset, base)) <= 2


@requires_data
def test_D2_reproduces_training_labels_and_uses_relative_rule(data_root):
    m = load_model("door")
    d = door.parse(data_root / "Door" / "Train.csv")
    lab = pd.read_csv(data_root / "Door" / "Train_Segments_Answer.csv", dtype=str)
    res = door.analyze(d, m)
    assert all(it["decision"]["rule"] == "relative" for it in res["items"])
    agree = np.mean([it["prediction"] == s for it, s in zip(res["items"], lab.status)])
    assert agree >= 0.99


@requires_data
def test_acv_hot_period_evidence_present(data_root):
    from diagnostics import acv
    d = acv.parse(data_root / "ACV" / "Train" / "acv_case_06.xlsx")
    it = acv.analyze(d, load_model("acv"))["items"][0]
    assert it["hot_period"] and it["hot_period"]["leader"] in d.cars
    assert sorted(it["ranked_cars"]) == d.cars  # ranking itself unchanged by the evidence


def test_exports_reject_zero_shm():
    assert exports.validate_rows("shm", [{"file_id": "a.csv", "prediction": "0.0"}])
    assert not exports.validate_rows("shm", [{"file_id": "a.csv", "prediction": "0.01"}])
