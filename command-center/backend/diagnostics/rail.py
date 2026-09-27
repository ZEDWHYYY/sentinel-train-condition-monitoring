"""Rail corrugation: semantic channel map, per-channel time/spectral features,
side aggregation, two-stage classification and evidence."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch
from scipy.stats import kurtosis

from .common import ParseError, Profile, QualityIssue, ReviewReason, chart, minmax_downsample

FS = 10_000.0
N_CARS, N_POS = 8, 8
SIDE_OF_POS = {p: ("Side I" if p % 2 == 1 else "Side II") for p in range(1, 9)}
BANDS = [(20, 100), (100, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 5000)]
CH_FEATS = ["log_rms", "log_peak", "kurtosis", "crest"] + [f"log_band_{a}_{b}" for a, b in BANDS]
LABELS = ("Normal", "Side I", "Side II")
WELCH = {"nperseg": 1024, "noverlap": 512, "window": "hann", "detrend": "constant"}
CH_RE = re.compile(r"^\s*(Vibration|Shock)\s+of\s+bearing\s+in\s+position\s+(\d)\s+of\s+car\s+(\d)\s*$", re.I)
SPEED_NAMES = {"rotating speed", "rotational speed", "speed"}


def channel_map(headers: list[str]) -> tuple[int | None, dict[tuple[int, int, str], int], str]:
    """Return (speed column index, {(car,pos,kind): column index}, method)."""
    m: dict[tuple[int, int, str], int] = {}
    speed = None
    for i, h in enumerate(headers):
        hs = str(h).strip()
        mm = CH_RE.match(hs)
        if mm and 1 <= int(mm.group(3)) <= N_CARS and 1 <= int(mm.group(2)) <= N_POS:
            m[(int(mm.group(3)), int(mm.group(2)), mm.group(1).lower())] = i
        elif hs.lower() in SPEED_NAMES:
            speed = i
    if len(m) == 128:
        return speed, m, "semantic header names"
    return speed, m, "incomplete"


@dataclass
class RailData:
    data: np.ndarray  # (n_samples, n_cols) float32
    speed_col: int | None
    cmap: dict
    map_method: str
    issues: list[QualityIssue] = field(default_factory=list)


def parse(path: str | Path) -> RailData:
    try:
        head = pd.read_csv(path,nrows=0,encoding="utf-8-sig")
        sp, cm, _ = channel_map(list(head.columns))
        if len(cm)!=128 or sp is None:
            raise ParseError("rail_channel_map",f"Expected speed pulse plus 128 named axle-box channels; found {len(cm)} channels and {'a' if sp is not None else 'no'} speed column.", "Restore the official semantic headers for all 8 cars × 8 positions × vibration/shock and Rotating speed.")
        used=[head.columns[i] for i in sorted({sp,*cm.values()})]
        extras=[c for c in head.columns if c not in used]
        df = pd.read_csv(path, usecols=used, dtype=np.float32, engine="c", encoding="utf-8-sig")
    except ParseError:
        raise
    except ValueError as e:
        raise ParseError("rail_non_numeric", f"Non-numeric values in the recording: {e}",
                         "Upload the official 129-column numeric export.") from e
    except Exception as e:  # noqa: BLE001
        raise ParseError("unreadable_csv", f"Could not read the file as CSV: {e}") from e
    headers = list(df.columns)
    speed, cmap, method = channel_map(headers)
    if len(cmap) != 128:
        raise ParseError("rail_channel_map", f"Could not map 128 vibration/shock channels ({len(cmap)} found).",
                         "Upload the official Rail format: speed plus 128 axle-box channels.")
    arr = df.to_numpy(dtype=np.float32, copy=False)
    issues: list[QualityIssue] = []
    if extras:
        issues.append(QualityIssue("extra_columns","info",f"Auxiliary columns ignored: {', '.join(extras[:5])}.",treatment="Only named acceleration channels and speed pulse are used; auxiliary timestamps do not replace the documented 10 kHz clock."))
    if method.startswith("official column order"):
        issues.append(QualityIssue("rail_positional_map", "warning",
                                   "Channel names were not recognised; the official column order was assumed.",
                                   effect="Side assignment depends on this assumption.",
                                   next_step="Confirm the export uses the official column order."))
    n = arr.shape[0]
    if n < 1024:
        raise ParseError("rail_too_short",f"Only {n} samples; at least 1,024 samples are required for the spectral window.","Upload the complete 10,000-sample (1 s) recording.")
    analog=arr[:,list(cmap.values())]
    if np.any(np.isfinite(analog).sum(axis=0)<1024):
        raise ParseError("rail_missing_channel", "At least one acceleration channel has fewer than 1,024 finite samples.", "Restore the missing sensor channel or upload a complete recording.")
    if np.nanmax(np.abs(analog))>1e5:
        raise ParseError("rail_acceleration_scale", "Acceleration exceeds the supported m/s² scale (unit mismatch or extreme outlier).", "Verify acceleration is in m/s² and correct the corrupt samples.")
    if abs(n - FS) > 1:
        issues.append(QualityIssue("rail_duration", "warning",
                                   f"{n} samples found; official files hold 10,000 (1 s at 10 kHz).",
                                   effect="Features are computed on the available samples at the documented 10 kHz rate."))
    nan = ~np.isfinite(arr)
    if nan.any():
        issues.append(QualityIssue("missing_values", "warning",
                                   f"{int(nan.sum())} missing/non-finite values ({nan.mean():.3%}).",
                                   treatment="After demeaning each channel, missing samples are zero-filled at their original positions for spectral analysis.",
                                   effect="The regular sample clock is preserved, but spectral power can be biased."))
    flat = [f"car {c} pos {p} {k}" for (c, p, k), i in cmap.items() if np.nanstd(arr[:, i]) == 0]
    if flat:
        issues.append(QualityIssue("rail_flat_channel", "warning",
                                   f"{len(flat)} analog channel(s) are constant: {', '.join(flat[:6])}",
                                   treatment="Kept; side medians are robust to a few flat channels.",
                                   effect="Possible sensor or acquisition problem on those positions.",
                                   next_step="Check the listed sensors."))
    return RailData(data=arr, speed_col=speed, cmap=cmap, map_method=method, issues=issues)


def speed_pulse(d: RailData) -> dict:
    """Count transitions of the 0/1 tooth pulse. Speed in km/h is NOT derived:
    the dataset audit found the naive conversion implausible and unverified."""
    if d.speed_col is None:
        return {"transitions": None, "rising_edges": None, "available": False}
    s = d.data[:, d.speed_col]
    s = s[np.isfinite(s)]
    b = (s > 0.5).astype(np.int8)
    tr = int(np.count_nonzero(np.diff(b)))
    rising = int(np.count_nonzero(np.diff(b) == 1))
    return {"transitions": tr, "rising_edges": rising, "available": tr > 0}


def channel_features(d: RailData) -> np.ndarray:
    """(8 cars, 8 positions, 2 kinds, len(CH_FEATS)) at full resolution."""
    idx = np.array([[[d.cmap[(c, p, k)] for k in ("vibration", "shock")] for p in range(1, 9)]
                    for c in range(1, 9)])
    X = d.data[:, idx.reshape(-1)].astype(np.float64)
    X = X - np.nanmean(X, axis=0, keepdims=True)
    X = np.where(np.isfinite(X), X, 0.0)
    rms = np.sqrt(np.mean(X ** 2, axis=0))
    peak = np.max(np.abs(X), axis=0)
    kurt = kurtosis(X, axis=0, fisher=True, bias=True)
    crest = np.where(rms > 0, peak / np.where(rms > 0, rms, 1), np.nan)
    f, P = welch(X, fs=FS, axis=0, **WELCH)
    bands = []
    for a, b in BANDS:
        sel = (f >= a) & (f < b)
        bands.append(np.log10(np.trapezoid(P[sel], f[sel], axis=0) + 1e-12))
    eps = 1e-9
    feats = np.stack([np.log10(rms + eps), np.log10(peak + eps), kurt, crest] + bands, axis=1)
    return feats.reshape(N_CARS, N_POS, 2, len(CH_FEATS))


def psd(d: RailData, car: int, pos: int, kind: str) -> tuple[np.ndarray, np.ndarray]:
    x = d.data[:, d.cmap[(car, pos, kind)]].astype(np.float64)
    x = np.where(np.isfinite(x), x, 0.0)
    return welch(x, fs=FS, **WELCH)


def side_features(ch: np.ndarray) -> dict[str, float]:
    """Compact side-aware file features (speed-free)."""
    out = {}
    side_pos = {"I": [0, 2, 4, 6], "II": [1, 3, 5, 7]}
    for kname, k in (("vib", 0), ("shock", 1)):
        for fi, fname in enumerate(CH_FEATS):
            vals = {s: ch[:, p, k, fi].ravel() for s, p in side_pos.items()}
            med = {s: float(np.nanmedian(v)) for s, v in vals.items()}
            mx = {s: float(np.nanmax(v)) for s, v in vals.items()}
            out[f"{kname}_{fname}_med_all"] = (med["I"] + med["II"]) / 2
            out[f"{kname}_{fname}_max_all"] = max(mx.values())
            out[f"{kname}_{fname}_contrast_med"] = med["I"] - med["II"]
            out[f"{kname}_{fname}_contrast_max"] = mx["I"] - mx["II"]
            # per-car side contrast, then median/max over cars (localised side fault)
            per_car = np.nanmedian(ch[:, [0, 2, 4, 6], k, fi], axis=1) - np.nanmedian(ch[:, [1, 3, 5, 7], k, fi], axis=1)
            out[f"{kname}_{fname}_contrast_carmed"] = float(np.nanmedian(per_car))
    return out


def side_summary(ch: np.ndarray) -> dict:
    """Per-car, per-side vibration RMS (m/s²) for the side comparison view."""
    rms = 10 ** ch[:, :, 0, 0]
    return {"cars": list(range(1, 9)),
            "side_I_rms": [float(np.median(rms[c, [0, 2, 4, 6]])) for c in range(8)],
            "side_II_rms": [float(np.median(rms[c, [1, 3, 5, 7]])) for c in range(8)],
            "position_rms": rms.tolist()}


# ---------------------------------------------------------------- inference

def predict_from_features(feats: dict, model: dict) -> tuple[str, dict]:
    from .model_store import load_estimator
    s1 = load_estimator(model, "stage1")
    x1 = np.array([[feats[k] for k in model["stage1_features"]]])
    p_fault = float(s1.predict_proba(x1)[0, list(s1.classes_).index(1)])
    detail = {"stage1_fault_score": p_fault, "stage1_threshold": model["stage1_threshold"]}
    if p_fault < model["stage1_threshold"]:
        return "Normal", detail
    if model["side_policy"]["established"]:
        s2 = load_estimator(model, "stage2")
        x2 = np.array([[feats[k] for k in model["stage2_features"]]])
        p2 = float(s2.predict_proba(x2)[0, list(s2.classes_).index(1)])
        detail["stage2_side_II_score"] = p2
        return ("Side II" if p2 >= 0.5 else "Side I"), detail
    pol = model["side_policy"]
    val = feats[pol["feature"]]
    detail["side_policy_feature"] = pol["feature"]
    detail["side_policy_value"] = val
    detail["side_policy_cutoff"] = pol["cutoff"]
    return (pol["if_greater"] if val > pol["cutoff"] else pol["otherwise"]), detail


def analyze_file(d: RailData, file_id: str, model: dict) -> dict:
    ch = channel_features(d)
    feats = side_features(ch)
    sp = speed_pulse(d)
    label, detail = predict_from_features(feats, model)
    reasons: list[ReviewReason] = []
    thr = model["stage1_threshold"]
    lo, hi = model["review"]["stage1_band"]
    if lo <= detail["stage1_fault_score"] <= hi:
        reasons.append(ReviewReason(
            "near_boundary",
            f"Fault-detection score {detail['stage1_fault_score']:.2f} is close to the decision threshold {thr:.2f}.",
            "Compare side vibration levels with the Normal reference; verify with another pass over the same section.",
            "sides"))
    if label != "Normal" and not model["side_policy"]["established"]:
        reasons.append(ReviewReason(
            "side_not_established",
            "Corrugation-like vibration was detected, but side assignment was not established in validation; "
            "the side shown follows a documented deterministic policy, not diagnostic evidence.",
            "Verify the encoder interpretation and compare Side I and Side II channels under a known operating condition.",
            "sides"))
    if not sp["available"] and label != "Normal":
        reasons.append(ReviewReason(
            "no_speed_signal",
            "The speed pulse channel shows no activity. The prediction uses speed-independent features only.",
            "Confirm whether the vehicle was moving and whether the encoder was connected.", "speed"))
    rng = model.get("feature_ranges", {})
    out_of_range = [k for k in model["stage1_features"] if k in rng and not (rng[k][0] <= feats[k] <= rng[k][1])]
    if len(out_of_range) >= max(1, int(0.1 * len(model["stage1_features"]))):
        reasons.append(ReviewReason(
            "outside_training_range",
            f"{len(out_of_range)} fault-detection feature(s) fall outside the training range "
            f"(e.g. {out_of_range[0]}).",
            "Confirm sensor units and mounting; compare with a recording from a known-normal section.", "sides"))
    ss = side_summary(ch)
    obs = _observations(ss, label, detail, model, sp)
    return {
        "id": file_id, "file_id": file_id, "prediction": label, "decision": detail,
        "speed_pulse": sp, "side_summary": ss,
        "features": {k: feats[k] for k in model["stage1_features"][:6]},
        "review_reasons": [r.to_dict() for r in reasons],
        "evidence_state": "review_suggested" if reasons else "no_trigger",
        "observations": obs, "channel_map": d.map_method,
    }


def _observations(ss: dict, label: str, detail: dict, model: dict, sp: dict) -> list[str]:
    i = float(np.median(ss["side_I_rms"]))
    ii = float(np.median(ss["side_II_rms"]))
    ref = model["reference"]["normal_side_rms_median"]
    obs = [f"Median axle-box vibration RMS was {i:.3f} m/s² on Side I and {ii:.3f} m/s² on Side II, "
           f"compared with about {ref:.3f} m/s² for Normal training files."]
    if label == "Normal":
        obs.append(f"The fault-detection score {detail['stage1_fault_score']:.2f} is below the frozen threshold "
                   f"{detail['stage1_threshold']:.2f}: no target corrugation signature detected in this recording.")
    else:
        obs.append(f"The fault-detection score {detail['stage1_fault_score']:.2f} is above the frozen threshold "
                   f"{detail['stage1_threshold']:.2f}, which supports corrugation on at least one side.")
        if not model["side_policy"]["established"]:
            obs.append("The side label follows a documented policy because validation did not establish reliable "
                       "Side I vs Side II separation. It is not evidence of the affected side.")
    obs.append("Location along the track is not in the data; this does not localise a defect geographically.")
    return obs[:4]


# ---------------------------------------------------------------- evidence

def sides_chart(item: dict, source: str) -> dict:
    ss = item["side_summary"]
    return chart("Vibration level by car and side", "Axle-box vibration RMS (median of side positions)", "m/s²",
                 "Car", source,
                 [{"name": "Side I (positions 1,3,5,7)", "role": "primary", "x": ss["cars"], "y": ss["side_I_rms"]},
                  {"name": "Side II (positions 2,4,6,8)", "role": "secondary", "x": ss["cars"], "y": ss["side_II_rms"]}],
                 kind="grouped_bar",
                 caption="Corrugation raises vibration on the axle boxes running over the affected rail. Fault recordings raise "
                         "vibration on both sides, so the side is decided by a model using several side-contrast features "
                         "(spectral bands, kurtosis, crest factor), not by bar height alone.")


def waveform_chart(d: RailData, car: int, pos: int, kind: str, source: str, t0: float = 0.0, t1: float | None = None,
                   max_points: int = 1500) -> dict:
    i = d.cmap[(car, pos, kind)]
    y = d.data[:, i].astype(np.float64)
    x = np.arange(len(y)) / FS
    a = int(max(0, t0) * FS)
    b = int(min(len(y), (t1 if t1 is not None else len(y) / FS) * FS))
    col = i + 1
    return chart(f"Car {car}, position {pos} ({SIDE_OF_POS[pos]}) — {kind}", f"Axle-box {kind} acceleration", "m/s²",
                 "Seconds (10 kHz documented rate)", f"{source}, column {col}, samples {a}–{b - 1}",
                 [{"name": kind, "role": "primary", **minmax_downsample(x[a:b], y[a:b], max_points)}],
                 caption="Raw full-rate signal shown with min/max bucketing so peaks are preserved.")


def psd_chart(d: RailData, car: int, pos: int, kind: str, model: dict, source: str) -> dict:
    f, p = psd(d, car, pos, kind)
    ref = model["reference"]["psd"][kind]
    sel = (f >= 10) & (f <= 5000)
    series = [{"name": "This channel", "role": "primary", "x": f[sel].tolist(),
               "min": np.log10(p[sel] + 1e-12).tolist(), "max": np.log10(p[sel] + 1e-12).tolist(), "aggregated": False}]
    rf = np.asarray(ref["f"])
    rs = (rf >= 10) & (rf <= 5000)
    series.append({"name": "Normal training 10–90th pct", "role": "band", "x": rf[rs].tolist(),
                   "min": np.asarray(ref["p10"])[rs].tolist(), "max": np.asarray(ref["p90"])[rs].tolist(),
                   "aggregated": False})
    return chart(f"Spectrum — car {car}, position {pos} ({SIDE_OF_POS[pos]}) {kind}", "Welch PSD (log10)",
                 "log10((m/s²)²/Hz)", "Frequency (Hz)", source, series,
                 reference=f"Normal training files, all positions (n={ref['n']})",
                 caption="Welch PSD, 1024-sample Hann window, 50% overlap at 10 kHz. The band is a reference range, not a confidence interval.")


def export_rows(items: list[dict]) -> list[dict]:
    return [{"file_id": i["file_id"], "prediction": i["prediction"]} for i in items]


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file_id", "prediction"])
        w.writeheader()
        w.writerows(rows)


def profile(d: RailData) -> Profile:
    arr = d.data
    return Profile(rows=arr.shape[0], columns=arr.shape[1], sample_rate_hz=FS,
                   sample_rate_source="documented (Rail Info Kit: 10,000 Hz)",
                   coverage=f"{arr.shape[0] / FS:.3f} s", channels=[
                       {"name": "Rotating speed", "kind": f"pulse (0/1) · {speed_pulse(d)['transitions']} transitions in the file",
                        "min": float(np.nanmin(arr[:, d.speed_col])) if d.speed_col is not None else None,
                        "max": float(np.nanmax(arr[:, d.speed_col])) if d.speed_col is not None else None},
                       {"name": "128 axle-box channels", "kind": "analog", "unit": "m/s²",
                        "min": float(np.nanmin(arr[:, 1:])), "median": float(np.nanmedian(arr[:, 1:])),
                        "max": float(np.nanmax(arr[:, 1:])), "missing": int((~np.isfinite(arr[:, 1:])).sum())}],
                   missing_fraction=float((~np.isfinite(arr)).mean()), extra={"channel_map": d.map_method})
