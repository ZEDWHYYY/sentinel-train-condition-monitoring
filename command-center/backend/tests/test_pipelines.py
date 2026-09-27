"""Parser, pipeline and score-critical checks (T02-T05, T12-T13, T16, T41-T43)."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from .conftest import requires_data
from diagnostics import acv, door, rail, registry, shm
from diagnostics.common import REPO_ROOT, minmax_downsample
from diagnostics.metrics import interval_iou
from diagnostics.model_store import load_model


# ---------------------------------------------------------------- generic
def test_minmax_downsample_keeps_impulse():  # T13
    y = np.zeros(100_000)
    y[54_321] = 9.0
    d = minmax_downsample(np.arange(len(y)), y, 1000)
    assert max(v for v in d["max"] if v is not None) == 9.0
    assert d["aggregated"]


def test_door_timestamps_non_padded():  # T02
    t, bad = door.parse_timestamps(pd.Series(["2023-7-5-0-0-3-760", "2023-12-15-10-9-8-7", "bad"]))
    assert bad == [2]
    assert t[1] - t[0] == pytest.approx((pd.Timestamp("2023-12-15 10:09:08.007") - pd.Timestamp("2023-07-05 00:00:03.760")).total_seconds())


def test_shm_rainflow_astm_example():  # T43 hand-computable
    r, _, n = shm.rainflow(np.array([-2, 1, -3, 5, -1, 3, -4, 4, -2.0]))
    got = {}
    for a, b in zip(r, n):
        got[a] = got.get(a, 0) + b
    assert got == {3.0: 0.5, 4.0: 1.5, 6.0: 0.5, 8.0: 1.0, 9.0: 0.5}


def test_shm_header_detection_and_first_row(tmp_path):  # T03
    p = tmp_path / "x.csv"
    p.write_text("1.5\n2.0\n-1.0\n" + "\n".join(str(np.sin(i)) for i in range(200)))
    d = shm.parse(p)
    assert d.header is None and d.x[0] == 1.5
    q = tmp_path / "y.csv"
    q.write_text("stress\n1.5\n" + "\n".join(str(np.sin(i)) for i in range(200)))
    d2 = shm.parse(q)
    assert d2.header == "stress" and d2.x[0] == 1.5


def test_rail_channel_map_semantic_and_shuffled():  # T05
    heads = ["Rotating speed"] + [f"{k} of bearing in position {p} of car {c}" for c in range(1, 9) for p in range(1, 9)
                                  for k in ("Vibration", "Shock")]
    sp, m, how = rail.channel_map(heads)
    assert sp == 0 and len(m) == 128 and how.startswith("semantic")
    assert m[(1, 1, "vibration")] == 1 and m[(1, 2, "vibration")] == 3
    rng = np.random.default_rng(0)
    shuffled = list(rng.permutation(heads))
    sp2, m2, _ = rail.channel_map(shuffled)
    assert all(shuffled[m2[k]] == heads[m[k]] for k in m)
    assert rail.SIDE_OF_POS[1] == "Side I" and rail.SIDE_OF_POS[2] == "Side II"


def test_rail_pulse_counts_transitions_not_double():  # T05 factor-of-two fixture
    s = np.tile([0, 0, 1, 1], 250).astype(np.float32)  # 250 full pulses
    arr = np.zeros((1000, 129), np.float32)
    arr[:, 0] = s
    d = rail.RailData(data=arr, speed_col=0, cmap={}, map_method="test")
    sp = rail.speed_pulse(d)
    assert sp["rising_edges"] == 249 or sp["rising_edges"] == 250
    assert sp["transitions"] == 2 * sp["rising_edges"] or abs(sp["transitions"] - 2 * sp["rising_edges"]) <= 1


def test_door_digital_constant_not_flagged_dead(tmp_path):  # T12
    rows = ["Datetime," + ",".join(door.COLUMNS[1:])]
    for i in range(60):
        rows.append(f"2023-7-5-0-0-{i // 50}-{(i % 50) * 20}," + ",".join(["100", "400", "50", "24", "35", "1", "0", "0", "0", "0", "0", "0", "0", "0", "1", str(700 - 10 * i)]))
    p = tmp_path / "d.csv"
    p.write_text("\n".join(rows))
    d = door.parse(p)
    assert not [i for i in d.issues if "dead" in i.description.lower() or i.code == "flatline"]


# ---------------------------------------------------------------- official data
@requires_data
def test_T41_door_segmenter_and_direction(data_root):
    d = door.parse(data_root / "Door" / "Train.csv")
    lab = pd.read_csv(data_root / "Door" / "Train_Segments_Answer.csv", dtype=str)
    t0, _ = door.parse_timestamps(lab.start_time)
    t1, _ = door.parse_timestamps(lab.end_time)
    model = load_model("door")
    seg = door.segment(d.t, model["segmentation"]["gap_threshold_s"], tuple(model["segmentation"]["review_band_s"]))
    assert len(seg["segments"]) == 110
    ious = [interval_iou(d.t[a], d.t[b], x, y) for (a, b), x, y in zip(seg["segments"], t0, t1)]
    assert np.mean(ious) == 1.0
    res = door.analyze(d, model)
    assert [i["operation"] for i in res["items"]] == lab.operation.tolist()
    test = door.parse(data_root / "Door" / "Test.csv")
    assert len(door.segment(test.t, 1.0, (0.03, 10.0))["segments"]) == 38


def test_T41_gap_in_band_flags_review(tmp_path):
    rows = ["Datetime," + ",".join(door.COLUMNS[1:])]
    t = 0
    for i in range(120):
        t += 20 if i != 60 else 3000  # 3 s gap inside the unpopulated band
        rows.append(f"2023-7-5-0-{(t // 60000)}-{(t // 1000) % 60}-{t % 1000}," + ",".join(
            ["300", "400", "50", "24", "35", "1", "0", "0", "0", "0", "0", "0", "0", "0", "1", str(max(0, 700 - 6 * i))]))
    p = tmp_path / "gap.csv"
    p.write_text("\n".join(rows))
    res = door.analyze(door.parse(p), load_model("door"))
    codes = {r["code"] for it in res["items"] for r in it["review_reasons"]}
    assert "ambiguous_gap" in codes


@requires_data
def test_T04_acv_sheet_ids_and_permutation(data_root):
    d = acv.parse(data_root / "ACV" / "Test" / "acv_test_case.xlsx")
    assert d.sheet == "故障案例3-0620_20210624"
    assert d.cars == [f"0{i}" for i in range(1, 9)]
    model = load_model("acv")
    a = acv.analyze(d, model)["items"][0]
    assert sorted(a["ranked_cars"]) == d.cars and len(set(a["ranked_cars"])) == 8
    perm = dict(zip(d.cars, reversed(d.cars)))
    sig = {k: v.rename(columns=perm)[sorted(perm.values())] for k, v in d.signals.items()}
    b = acv.analyze(acv.ACVData(d.time, d.cars, sig, d.sheet, d.mapping), model)["items"][0]
    sa = {c["car"]: c["score_K"] for c in a["cars"]}
    sb = {c["car"]: c["score_K"] for c in b["cars"]}
    assert all(sa[c] == pytest.approx(sb[perm[c]]) for c in d.cars)


@requires_data
def test_T04_acv_rich_workbook(data_root):
    d = acv.parse(data_root / "ACV" / "Train" / "acv_case_04.xlsx")
    r = acv.analyze(d, load_model("acv"))
    assert len(r["items"][0]["ranked_cars"]) == 8
    assert any(i.code == "acv_alias_mapping" for i in d.issues)


@requires_data
def test_T42_rail_validation_record():
    v = json.loads((REPO_ROOT / "reports" / "validation" / "rail.json").read_text())
    sel = v["experiments"][v["selected"]]
    assert "speed_matched" in sel and "full_set" in sel
    assert sel["speed_matched"]["n"] == 101 + 38
    assert any(k.endswith("WITH_speed") for k in v["experiments"])
    assert not v["speed_matched_collapse"]
    assert v["side_gate"]["established"] in (True, False)
    assert not load_model("rail")["uses_speed"]
    assert "group" in v["protocol"] and v["duplicates"]["exact_duplicate_training_files"] >= 0


@requires_data
def test_T14_duplicate_files_share_a_fold():
    m = json.loads((REPO_ROOT / "reports" / "validation" / "split_manifest.json").read_text())
    by_sha: dict[str, list[int]] = {}
    for i, f in enumerate(m["rail"]["files"]):
        by_sha.setdefault(f["sha256"], []).append(i)
    for seed, folds in m["rail"]["fold_by_seed"].items():
        for idx in by_sha.values():
            assert len({folds[i] for i in idx}) == 1, f"identical files split across folds (seed {seed})"
    train = {f["sha256"] for f in m["rail"]["files"]}
    assert not [t for t in m["test_inputs"]["rail"] if t["sha256"] in train]


@requires_data
def test_T42_rail_flat_speed_still_predicts(data_root, tmp_path):
    src = data_root / "Rail_Corrugation" / "Train" / "Train1.csv"
    df = pd.read_csv(src)
    df.iloc[:, 0] = 0
    p = tmp_path / "flat.csv"
    df.to_csv(p, index=False)
    it = rail.analyze_file(rail.parse(p), "flat.csv", load_model("rail"))
    assert it["prediction"] in ("Normal", "Side I", "Side II")
    assert it["speed_pulse"]["transitions"] == 0


@requires_data
def test_T43_shm_record():
    v = json.loads((REPO_ROOT / "reports" / "validation" / "shm.json").read_text())
    c = v["candidates"]
    best = c[v["selected"]]["score"]
    assert best > c["S0_constant"]["score"] and best > c["S0_median_constant"]["score"]
    assert c["S1_power_gated"]["score"] >= c["S1_power_ungated"]["score"] - 1e-9
    assert "mape_low_half" in c[v["selected"]] and "mape_high_half" in c[v["selected"]]
    assert "m" in v["final_params"]["selected"]


@requires_data
def test_T03_shm_filename_does_not_change_prediction(data_root, tmp_path):
    src = data_root / "SHM" / "Test" / "test01.csv"
    other = tmp_path / "renamed_99.csv"
    shutil.copy(src, other)
    m = load_model("shm")
    a = shm.analyze_file(shm.parse(src), "test01.csv", m)["prediction"]
    b = shm.analyze_file(shm.parse(other), "renamed_99.csv", m)["prediction"]
    assert a == b and np.isfinite(a) and a > 0


@requires_data
def test_T16_repeat_inference_is_identical(data_root):
    p = data_root / "Door" / "Test.csv"
    a = registry.analyze_file("door", p, "Test.csv")
    registry._parsed.cache_clear()
    b = registry.analyze_file("door", p, "Test.csv")
    assert [i["prediction"] for i in a["items"]] == [i["prediction"] for i in b["items"]]


def test_T14_no_filename_or_id_features():
    for t in ("rail",):
        m = load_model(t)
        feats = m["stage1_features"] + m["stage2_features"]
        assert not [f for f in feats if any(k in f.lower() for k in ("file", "transition", "speed", "car_id"))]
    acv_m = load_model("acv")
    assert "car" not in " ".join(acv_m["feature_contract"]).lower().replace("cars", "")
