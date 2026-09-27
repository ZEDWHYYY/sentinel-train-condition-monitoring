"""T07-T10: official metric implementations."""
import pytest

from diagnostics.metrics import acv_case_score, door_iou_f1, rail_macro_f1, shm_score

N, A = "Normal", "Abnormal resistance"


def test_door_perfect_match():
    t = [(0, 10, N), (20, 30, A)]
    assert door_iou_f1(t, t)["score"] == pytest.approx(1.0)


def test_door_wrong_label_cannot_match():
    assert door_iou_f1([(0, 10, N)], [(0, 10, A)])["score"] == 0.0


def test_door_duplicate_prediction_penalised():
    r = door_iou_f1([(0, 10, N)], [(0, 10, N), (0, 10, N)])
    assert r["n_matched"] == 1
    assert r["score"] == pytest.approx(2 * 1 / 3)


def test_door_partial_overlap_proportional():
    r = door_iou_f1([(0, 10, N)], [(5, 15, N)])
    assert r["score"] == pytest.approx(5 / 15)


def test_door_greedy_highest_iou_first():
    # prediction overlapping two truths is matched to the better one
    truth = [(0, 10, N), (8, 20, N)]
    pred = [(8, 19, N)]
    r = door_iou_f1(truth, pred)
    assert r["matches"][0][0] == 1


def test_door_empty():
    assert door_iou_f1([], [])["score"] == 0.0
    assert door_iou_f1([(0, 1, N)], [])["score"] == 0.0


def test_acv_rank_decay():
    ranked = ["03", "01", "05", "02", "04", "06", "07", "08"]
    assert acv_case_score(ranked, "03") == 1.0
    assert acv_case_score(ranked, "01") == 0.875
    assert acv_case_score(ranked, "05") == 0.75
    assert acv_case_score(ranked, "08") == 0.125
    assert acv_case_score(ranked[:-1], "08", 8) == 0.0


def test_rail_macro_f1_majority_scores_poorly():
    y = ["Normal"] * 90 + ["Side I"] * 5 + ["Side II"] * 5
    r = rail_macro_f1(y, ["Normal"] * 100)
    assert r["macro_f1"] < 0.34
    assert r["per_class"]["Side I"]["support"] == 5
    assert set(r["confusion"]) == {"Normal", "Side I", "Side II"}


def test_shm_guide_example():
    r = shm_score([0.10, 0.30, 0.50, 0.70, 0.90], [0.15, 0.28, 0.55, 0.68, 0.85])
    assert r["score"] == pytest.approx(0.85, abs=0.001)


def test_shm_floor_and_zero_label():
    assert shm_score([0.1, 0.3, 0.5, 0.7, 0.9], [0.5] * 5)["score"] == 0.0
    with pytest.raises(ValueError):
        shm_score([0.0, 1.0], [0.1, 1.0])
    with pytest.raises(ValueError):
        shm_score([1.0], [float("nan")])


# ---------------------------------------------------------------- adversarial cases (audit §1.2)
def test_door_nested_prediction_scores_by_iou_once():
    # one prediction covering two truths can only match one; the other is a miss
    r = door_iou_f1([(0, 10, N), (10, 20, N)], [(0, 20, N)])
    assert r["n_matched"] == 1 and r["matched_iou_sum"] == pytest.approx(0.5)
    assert r["score"] == pytest.approx(2 * 0.5 / (2 + 1))


def test_door_greedy_is_not_optimal_but_deterministic():
    # greedy takes the 0.9 pair first even though 0.6+0.6 would sum higher; the Info Kit prescribes greedy
    truth = [(0, 10, N), (10, 20, N)]
    pred = [(1, 10, N), (0, 20, N)]
    r = door_iou_f1(truth, pred)
    assert r["matches"][0][:2] == (0, 0)
    assert r["n_matched"] == 2


def test_door_overlap_with_wrong_label_is_fp_and_miss():
    r = door_iou_f1([(0, 10, A)], [(0, 10, N), (30, 40, A)])
    assert r["n_matched"] == 0 and r["score"] == 0.0


def test_door_zero_length_segments_do_not_crash():
    assert door_iou_f1([(5, 5, N)], [(5, 5, N)])["score"] == 0.0


def test_acv_duplicate_or_unknown_cars():
    assert acv_case_score(["03", "03", "01"], "01", 8) == pytest.approx((8 - 2) / 8)
    assert acv_case_score(["09"], "01") == 0.0
    assert acv_case_score([], "01") == 0.0


def test_rail_worked_example_and_absent_class():
    # Info Kit worked example: per-class F1 0.97 / 0.40 / 0.60 -> 0.657 (construct labels giving those F1s approximately)
    y = ["Normal"] * 100 + ["Side I"] * 10 + ["Side II"] * 10
    p = ["Normal"] * 97 + ["Side I"] * 3 + ["Side I"] * 4 + ["Normal"] * 6 + ["Side II"] * 6 + ["Normal"] * 4
    r = rail_macro_f1(y, p)
    assert 0.6 < r["macro_f1"] < 0.75
    # a class absent from truth and prediction contributes 0 (three-class average, documented)
    r2 = rail_macro_f1(["Normal", "Side II"], ["Normal", "Side II"])
    assert r2["macro_f1"] == pytest.approx(2 / 3)
    assert r2["per_class"]["Side I"]["support"] == 0


def test_shm_tiny_truths_dominate_and_negative_prediction_allowed_by_metric():
    r = shm_score([0.01, 1.0], [0.02, 1.0])
    assert r["mape"] == pytest.approx(0.5)
    assert shm_score([0.5], [-0.5])["score"] == 0.0
