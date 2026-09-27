"""Official PS3 metrics, implemented exactly as the four Info Kits define them."""
from __future__ import annotations

from typing import Sequence

import numpy as np

DOOR_LABELS = ("Normal", "Abnormal resistance")
RAIL_LABELS = ("Normal", "Side I", "Side II")


def interval_iou(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    return inter / union if union > 0 else 0.0


def door_iou_f1(truth: Sequence[tuple[float, float, str]],
                pred: Sequence[tuple[float, float, str]]) -> dict:
    """Same-label greedy one-to-one IoU matching; score = 2S/(N+M).

    Ties in IoU are broken deterministically by (truth index, prediction index).
    """
    pairs = []
    for i, (t0, t1, tl) in enumerate(truth):
        for j, (p0, p1, pl) in enumerate(pred):
            if tl != pl:
                continue
            iou = interval_iou(t0, t1, p0, p1)
            if iou > 0:
                pairs.append((-iou, i, j, iou))
    pairs.sort()
    used_t, used_p, s, matches = set(), set(), 0.0, []
    for _, i, j, iou in pairs:
        if i in used_t or j in used_p:
            continue
        used_t.add(i)
        used_p.add(j)
        s += iou
        matches.append((i, j, iou))
    n, m = len(truth), len(pred)
    recall = s / n if n else 0.0
    precision = s / m if m else 0.0
    score = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0
    return {"score": score, "soft_recall": recall, "soft_precision": precision,
            "matched_iou_sum": s, "n_true": n, "n_pred": m, "n_matched": len(matches),
            "matches": matches}


def acv_case_score(ranked: Sequence[str], true_car: str, n_cars: int | None = None) -> float:
    n = n_cars if n_cars is not None else len(ranked)
    if true_car not in ranked or n == 0:
        return 0.0
    r = list(ranked).index(true_car) + 1
    return (n - (r - 1)) / n


def rail_macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> dict:
    per = {}
    for c in RAIL_LABELS:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[c] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn}
    confusion = {t: {p: sum(1 for a, b in zip(y_true, y_pred) if a == t and b == p)
                     for p in RAIL_LABELS} for t in RAIL_LABELS}
    return {"macro_f1": float(np.mean([per[c]["f1"] for c in RAIL_LABELS])),
            "per_class": per, "confusion": confusion}


def shm_score(y_true: Sequence[float], y_pred: Sequence[float]) -> dict:
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    if np.any(yt == 0):
        raise ValueError("SHM MAPE undefined: a true damage value is zero (organizer policy needed).")
    if not np.all(np.isfinite(yp)):
        raise ValueError("SHM predictions must be finite.")
    rel = np.abs(yt - yp) / np.abs(yt)
    mape = float(rel.mean())
    return {"mape": mape, "score": max(0.0, 1.0 - mape), "relative_errors": rel.tolist()}
