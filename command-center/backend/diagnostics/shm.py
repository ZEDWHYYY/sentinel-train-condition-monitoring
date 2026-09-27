"""SHM: headerless stress parsing, gated rainflow cycles, extreme-amplitude
features, damage regression and evidence."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ParseError, Profile, QualityIssue, ReviewReason, chart, minmax_downsample

UNIT = "stress (unit not documented)"


@dataclass
class SHMData:
    x: np.ndarray
    header: str | None
    issues: list[QualityIssue] = field(default_factory=list)
    sample_index: np.ndarray | None = None
    input_rows: int = 0
    missing_count: int = 0


def parse(path: str | Path) -> SHMData:
    try:
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False, skip_blank_lines=False, encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001
        raise ParseError("unreadable_csv", f"Could not read the file as CSV: {e}") from e
    if raw.empty:
        raise ParseError("empty_file", "The file is empty.")
    issues: list[QualityIssue] = []
    if raw.shape[1] > 1 and str(raw.iloc[0,0]).strip().lower()=="stress":
        issues.append(QualityIssue("extra_columns", "info", f"{raw.shape[1]-1} auxiliary column(s) ignored.", treatment="Only the named stress column is analyzed; auxiliary timestamps do not establish an undocumented sampling rate."))
        raw=raw.iloc[:,:1]
    if raw.shape[1] != 1:
        raise ParseError("shm_not_single_channel",
                         f"Expected one stress column, found {raw.shape[1]}.",
                         "Upload one headerless stress column per file, as in the official SHM data.")
    col = raw[0].str.strip()
    header = None
    first = pd.to_numeric(col.iloc[:1], errors="coerce")
    if first.isna().iloc[0] and col.iloc[0] != "":
        header = col.iloc[0]
        col = col.iloc[1:]
    x = pd.to_numeric(col, errors="coerce").to_numpy(dtype=float)
    if header is not None:
        issues.append(QualityIssue("shm_header_detected", "info", f"Row 1 ('{header[:40]}') is text and was treated as a header.",
                                   treatment="Excluded from the stress series."))
    bad = ~np.isfinite(x)
    sample_index=np.arange(len(x))
    input_rows=len(x)
    missing_count=int(bad.sum())
    if bad.any():
        rows = (np.flatnonzero(bad) + (2 if header else 1)).tolist()
        issues.append(QualityIssue("missing_values", "warning",
                                   f"{int(bad.sum())} non-numeric or empty sample(s).", rows=rows,
                                   treatment="Removed before cycle counting; neighbours are joined, which can merge cycles.",
                                   effect="Damage may be misestimated if gaps hide peaks.",
                                   next_step="Check the listed rows."))
        x = x[~bad]
        sample_index=sample_index[~bad]
    if len(x) < 100:
        raise ParseError("shm_too_short", f"Only {len(x)} valid samples.", "Upload a full stress segment.")
    if np.max(np.abs(x))>1e6:
        raise ParseError("shm_stress_scale", "Stress exceeds the supported raw-data scale (possible unit mismatch or extreme outlier).", "Verify the stress calibration and match the supplied raw-data scale; stress units are undocumented, so no automatic conversion is possible.")
    return SHMData(x=x, header=header, issues=issues, sample_index=sample_index,input_rows=input_rows,missing_count=missing_count)


def profile(d: SHMData) -> Profile:
    x = d.x
    return Profile(rows=len(x), columns=1, sample_rate_hz=None,
                   sample_rate_source="not documented — sample-index axis used",
                   coverage=f"{len(x):,} samples", channels=[{
                       "name": "stress", "kind": "analog", "unit": UNIT, "min": float(x.min()),
                       "median": float(np.median(x)), "max": float(x.max()), "mean": float(x.mean()),
                       "std": float(x.std())}], missing_fraction=d.missing_count/max(d.input_rows,1),
                   extra={"input_rows":d.input_rows,"dropped_rows":d.missing_count,"unit_assumption":"Stress units and sampling rate are not documented."})


# ---------------------------------------------------------------- cycles

def turning_points(x: np.ndarray) -> np.ndarray:
    """Local extrema after removing consecutive duplicates; keeps both ends."""
    keep = np.r_[True, np.diff(x) != 0]
    y = x[keep]
    if len(y) < 3:
        return y
    d = np.diff(y)
    rev = np.flatnonzero(np.sign(d[1:]) != np.sign(d[:-1])) + 1
    return y[np.r_[0, rev, len(y) - 1]]


def hysteresis_gate(tp: np.ndarray, gate: float) -> np.ndarray:
    """Drop reversals whose excursion is smaller than `gate` (range units)."""
    if gate <= 0 or len(tp) < 3:
        return tp
    out = [tp[0]]
    for v in tp[1:]:
        if len(out) >= 2 and (out[-1] - out[-2]) * (v - out[-1]) >= 0:
            # continuing the same direction: extend the extremum
            if abs(v - out[-2]) > abs(out[-1] - out[-2]):
                out[-1] = v
            continue
        if abs(v - out[-1]) >= gate:
            out.append(v)
        elif len(out) >= 2 and abs(v - out[-2]) > abs(out[-1] - out[-2]):
            out[-1] = v
    arr = np.asarray(out)
    # re-normalise to strict alternation
    if len(arr) >= 3:
        d = np.diff(arr)
        keep = np.r_[True, np.sign(d[1:]) != np.sign(d[:-1]), True]
        arr = arr[keep]
    return arr


def rainflow(rev: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ASTM E1049 three-point rainflow on a reversal sequence.
    Returns (ranges, means, counts) with counts 1.0 (full) or 0.5 (half)."""
    stack: list[float] = []
    rng, mean, cnt = [], [], []
    for v in rev.tolist():
        stack.append(v)
        while len(stack) >= 3:
            x = abs(stack[-1] - stack[-2])
            y = abs(stack[-2] - stack[-3])
            if x < y:
                break
            if len(stack) == 3:
                rng.append(y)
                mean.append((stack[-2] + stack[-3]) / 2)
                cnt.append(0.5)
                stack.pop(0)
            else:
                rng.append(y)
                mean.append((stack[-2] + stack[-3]) / 2)
                cnt.append(1.0)
                last = stack.pop()
                stack.pop()
                stack.pop()
                stack.append(last)
    for a, b in zip(stack[:-1], stack[1:]):
        rng.append(abs(b - a))
        mean.append((a + b) / 2)
        cnt.append(0.5)
    return np.asarray(rng), np.asarray(mean), np.asarray(cnt)


def cycles(x: np.ndarray, gate: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return rainflow(hysteresis_gate(turning_points(x), gate))


def features(x: np.ndarray, gate: float, exponents=(3.0, 4.0, 5.0)) -> dict:
    tp = turning_points(x)
    r, m, n = rainflow(hysteresis_gate(tp, gate))
    f = {
        "p2p": float(x.max() - x.min()),
        "rms": float(np.sqrt(np.mean(x ** 2))),
        "std": float(x.std()),
        "mean": float(x.mean()),
        "raw_reversals": int(len(tp)),
        "gated_cycles": float(n.sum()),
        "max_cycle_range": float(r.max()) if len(r) else 0.0,
        "q99_cycle_range": float(np.quantile(r, 0.99)) if len(r) else 0.0,
        "top5_range_mean": float(np.sort(r)[-5:].mean()) if len(r) else 0.0,
        "gate": gate,
    }
    for e in exponents:
        f[f"damage_sum_m{e:g}"] = float(np.sum(n * r ** e))
    return f


def power_sum(r: np.ndarray, n: np.ndarray, m: float) -> float:
    return float(np.sum(n * r ** m))


# ---------------------------------------------------------------- inference

def predict(feats: dict, cyc: tuple[np.ndarray, np.ndarray, np.ndarray], model: dict) -> float:
    kind = model["kind"]
    if kind == "power_law":
        r, _, n = cyc
        s = power_sum(r, n, model["m"])
        return float(math.exp(model["log_c"]) * s)
    if kind == "log_linear":
        z = model["intercept"] + sum(w * math.log(max(feats[k], 1e-12)) for k, w in model["coef"].items())
        return float(math.exp(z))
    if kind == "constant":
        return float(model["value"])
    raise ValueError(f"Unknown SHM model kind {kind}")


def analyze_file(d: SHMData, file_id: str, model: dict) -> dict:
    sel = model["selected"]
    gate = model["gate"]
    cyc = cycles(d.x, gate)
    feats = features(d.x, gate)
    pred = predict(feats, cyc, sel)
    reasons: list[ReviewReason] = []
    rng = model["feature_ranges"]
    for k in ("p2p", "rms", "max_cycle_range"):
        lo, hi = rng[k]
        if not (lo <= feats[k] <= hi):
            reasons.append(ReviewReason(
                "outside_training_range",
                f"{k.replace('_', ' ')} = {feats[k]:.3g} lies outside the training range {lo:.3g}–{hi:.3g}; "
                "the damage model is extrapolating.",
                "Confirm signal units, measurement point and calibration before accepting the damage magnitude.",
                "trace"))
            break
    alt = model.get("challenger")
    if alt:
        ag = alt.get("gate", gate)
        p2 = predict(feats if ag == gate else features(d.x, ag), cyc if ag == gate else cycles(d.x, ag), alt)
        ratio = max(pred, p2) / max(min(pred, p2), 1e-300)
        if ratio > model["review"]["disagreement_ratio"]:
            reasons.append(ReviewReason(
                "model_disagreement",
                f"The selected estimate ({pred:.4g}) and the validated challenger ({p2:.4g}) differ by a factor {ratio:.1f}.",
                "Inspect the largest stress cycles; confirm the file covers a normal operating segment.", "cycles"))
    if pred < model["review"]["low_target_below"] and model["validation"]["selected"]["mape_low_half"] >= 0.15:
        reasons.append(ReviewReason(
            "low_target_regime",
            f"Estimated damage {pred:.3g} is in the low range where validation relative error was highest "
            f"(low-half MAPE {model['validation']['selected']['mape_low_half']:.0%}).",
            "Treat the magnitude as approximate; compare with other segments from the same measurement point.",
            "cycles"))
    if not np.isfinite(pred) or pred <= 0:
        return {"id": file_id, "file_id": file_id, "prediction": None, "available": False,
                "unavailable_reason": "Model produced a non-finite or non-positive value.",
                "review_reasons": [r.to_dict() for r in reasons], "evidence_state": "outside_supported",
                "observations": [], "features": feats}
    top = np.sort(cyc[0])[-10:][::-1]
    obs = [f"Estimated cumulative damage for this segment: {pred:.4g} (dimensionless Miner-type damage, as defined by the dataset).",
           f"Peak-to-peak stress range was {feats['p2p']:.2f} (training range {rng['p2p'][0]:.1f}–{rng['p2p'][1]:.1f}); "
           f"the largest counted cycle had range {feats['max_cycle_range']:.2f}.",
           f"After ignoring excursions smaller than {gate:g} stress units, {feats['gated_cycles']:.0f} cycles were counted "
           f"(from {feats['raw_reversals']:,} raw reversals). Large cycles dominate the estimate.",
           ]
    return {"id": file_id, "file_id": file_id, "prediction": pred, "available": True,
            "features": feats, "top_cycle_ranges": top.tolist(),
            "review_reasons": [r.to_dict() for r in reasons],
            "evidence_state": "review_suggested" if reasons else "no_trigger", "observations": obs}


# ---------------------------------------------------------------- evidence

def trace_chart(d: SHMData, source: str, i0: int = 0, i1: int | None = None, max_points: int = 1500) -> dict:
    total = d.input_rows or len(d.x)
    i1 = total if i1 is None else min(i1, total)
    i0 = max(0, min(i0, i1 - 1))
    original = d.sample_index if d.sample_index is not None else np.arange(len(d.x))
    # Reconstruct only the requested display window; gaps stay gaps, not a shorter clock.
    idx = np.arange(i0, i1)
    values = np.full(i1-i0, np.nan)
    selected = (original >= i0) & (original < i1)
    values[original[selected]-i0] = d.x[selected]
    first_row = 2 if d.header else 1
    return chart("Stress trace", "Dynamic stress", UNIT, "Sample index (sampling rate not documented)",
                 f"{source}, rows {i0 + first_row}–{i1 - 1 + first_row}",
                 [{"name": "stress", "role": "primary", **minmax_downsample(idx, values, max_points)}],
                 caption="Min/max display buckets retain peaks; original sample positions are preserved. Missing samples are blank, although a display bucket may contain both finite and missing samples. Cycle counting joins finite observations.")


def cycle_hist_chart(item: dict, cyc_ranges: np.ndarray, model: dict, source: str) -> dict:
    r = cyc_ranges
    if len(r) == 0:
        edges = np.array([0.0, 1.0])
        counts = np.array([0.0])
    else:
        edges = np.linspace(0, max(r.max(), 1e-9), 25)
        counts, _ = np.histogram(r, bins=edges)
    return chart("Counted stress cycles by range", "Rainflow cycle count", "log10(cycles + 1), dimensionless", "Cycle range (raw stress units, undocumented)", source,
                 [{"name": "cycles", "role": "primary", "x": ((edges[:-1] + edges[1:]) / 2).tolist(),
                   "y": np.log10(np.asarray(counts, dtype=float) + 1).tolist()}],
                 kind="bar", caption="Bar height is log10(count + 1). The few large-range cycles on the right "
                                     "carry most of the damage under a power-law (S–N) view.")


def export_rows(items: list[dict]) -> list[dict]:
    return [{"file_id": i["file_id"], "prediction": repr(float(i["prediction"]))} for i in items]


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file_id", "prediction"])
        w.writeheader()
        w.writerows(rows)
