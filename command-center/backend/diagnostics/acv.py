"""ACV: header-driven workbook parsing, cooling-mode registry, peer/target
cooling-residual evidence and a transparent per-case car ranking."""
from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ParseError, Profile, QualityIssue, ReviewReason, chart, minmax_downsample

CAR_RE = re.compile(r"^\s*Car\s+(\d+)\s*-\s*(.+?)\s*$")

# Semantic signal -> accepted header parameter names. First entry is the
# 67-column official schema name; later entries are recorded aliases (the rich
# case-04 schema). The mapping used for every file is stored with its result.
SIGNALS = {
    "indoor": ["Indoor Average Temperature", "Passenger Cabin Temperature Detected Value"],
    "target": ["ACV Control Temperature (Cooling)", "Target Temperature Value"],
    "mode": ["ACV Running Mode"],
    "valid": ["ACV Information Valid"],
    "outdoor": ["Outdoor Average Temperature", "Fresh Air Temperature Detected Value"],
    "setting": ["ACV Setting Mode", "ACV Control Mode"],
}
REQUIRED = ("indoor", "target", "mode")
COOLING_MODES = {"Automatic Cooling", "Full Cooling", "Half Cooling"}
KNOWN_NON_COOLING = {"Stop", "Stopped", "Ventilation", "Emergency Ventilation", "Self-Check",
                     "Invalid", "Automatic Heating", "Heating"}
MAX_SHEETS = 20
MAX_CELLS = 30_000_000


@dataclass
class ACVData:
    time: pd.Series
    cars: list[str]
    signals: dict[str, pd.DataFrame]  # semantic -> DataFrame(columns=cars)
    sheet: str | None
    mapping: dict[str, dict[str, str]]
    issues: list[QualityIssue] = field(default_factory=list)
    n_columns: int = 0


def sheet_candidates(path: Path) -> list[dict]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            if any(n.lower().endswith("vbaproject.bin") for n in z.namelist()):
                raise ParseError("macro_workbook", "Workbooks containing macros are not accepted.",
                                 "Save the workbook as a plain .xlsx without macros.")
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as e:  # noqa: BLE001
        raise ParseError("unreadable_workbook", f"Could not open the workbook: {e}",
                         "Upload an .xlsx exported from the ACV system.") from e
    if len(xl.sheet_names) > MAX_SHEETS:
        raise ParseError("too_many_sheets", f"Workbook has {len(xl.sheet_names)} sheets (limit {MAX_SHEETS}).")
    out = []
    for s in xl.sheet_names:
        head = pd.read_excel(xl, sheet_name=s, nrows=0)
        cars = {m.group(1) for c in head.columns if (m := CAR_RE.match(str(c)))}
        out.append({"sheet": s, "cars": sorted(cars), "columns": len(head.columns),
                    "compatible": len(cars) >= 2})
    return out


def parse(path: str | Path, sheet: str | None = None) -> ACVData:
    path = Path(path)
    issues: list[QualityIssue] = []
    if path.suffix.lower() == ".csv":
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except Exception as e:
            raise ParseError("unreadable_csv", f"Could not read ACV CSV: {e}", "Upload a comma-separated ACV case with Time and per-car headers.") from e
        chosen = None
    else:
        cands = sheet_candidates(path)
        compat = [c for c in cands if c["compatible"]]
        if sheet is None:
            if not compat:
                raise ParseError("acv_no_compatible_sheet",
                                 "No sheet has 'Car <NN> - <parameter>' columns.",
                                 "Upload an ACV case workbook with per-car headers.")
            if len(compat) > 1:
                raise ParseError("acv_sheet_ambiguous",
                                 "More than one sheet looks like an ACV case: "
                                 + ", ".join(c["sheet"] for c in compat),
                                 "Choose the sheet to analyse.")
            sheet = compat[0]["sheet"]
        elif sheet not in [c["sheet"] for c in cands]:
            raise ParseError("acv_sheet_missing", f"Sheet '{sheet}' not found.")
        chosen = sheet
        df = pd.read_excel(path, sheet_name=sheet, dtype=str, engine="openpyxl")
        if df.size > MAX_CELLS:
            raise ParseError("workbook_too_large", f"Sheet has {df.size} cells (limit {MAX_CELLS}).")
    return _from_frame(df, chosen, issues)


def _from_frame(df: pd.DataFrame, sheet: str | None, issues: list[QualityIssue]) -> ACVData:
    if len(df) < 140:
        raise ParseError("acv_too_short", f"Only {len(df)} rows; at least 140 samples are needed (20 settling + 120 comparison samples).", "Upload at least 70 minutes of 30-second telemetry with several cars cooling.")
    per_car: dict[str, dict[str, str]] = {}
    for c in df.columns:
        m = CAR_RE.match(str(c))
        if m:
            per_car.setdefault(m.group(1), {})[m.group(2)] = c
    if not per_car:
        raise ParseError("acv_no_car_columns", "No 'Car <NN> - <parameter>' columns found.",
                         "Upload an ACV case with per-car headers.")
    time_col = next((c for c in df.columns if str(c).strip().lower() == "time"), None)
    if time_col is None:
        raise ParseError("acv_no_time", "No 'Time' column found.", "The case must include the sample time column.")
    t = pd.to_datetime(df[time_col], errors="coerce", format="mixed")
    if t.notna().sum() < 2:
        raise ParseError("acv_no_valid_time", "The Time column has fewer than two readable timestamps.", "Use date/time values such as 2026-01-01 12:00:00.")
    if t.isna().any():
        issues.append(QualityIssue("acv_time_parse", "warning", f"{int(t.isna().sum())} unreadable time values.", treatment="Rows without a usable clock excluded from comparison."))
    keep=t.notna()
    df=df.loc[keep].copy()
    t=t.loc[keep]
    if not t.is_monotonic_increasing:
        issues.append(QualityIssue("timestamps_out_of_order", "warning", "Time values were out of order.", treatment="Rows sorted stably by parsed time."))
    order=t.sort_values(kind="stable").index
    df=df.loc[order].reset_index(drop=True)
    t=t.loc[order].reset_index(drop=True)
    duplicates=int(t.duplicated().sum())
    if duplicates:
        issues.append(QualityIssue("repeated_timestamps", "warning", f"{duplicates} duplicate timestamps.", treatment="Kept in recorded order; repeated measurements can bias means."))
    steps=t.diff().dt.total_seconds()
    if ((steps > 30.5) | ((steps > 0) & (steps < 29.5))).any():
        issues.append(QualityIssue("acv_cadence", "warning", "Time spacing differs from the documented 30 seconds.", treatment="No interpolation; valid exposure counts samples at the documented 30 s rate.", effect="Cooling hours are approximate; gaps are not counted as observed cooling."))
    extras=[str(c) for c in df if not CAR_RE.match(str(c)) and str(c).lower() not in ("time","car model","train number","car type","train no.")]
    if extras:
        issues.append(QualityIssue("extra_columns", "info", f"Auxiliary columns ignored: {', '.join(extras[:5])}.", treatment="Not used for ranking."))
    cars = sorted(per_car)
    mapping: dict[str, dict[str, str]] = {}
    signals: dict[str, pd.DataFrame] = {}
    for sem, names in SIGNALS.items():
        cols = {}
        used = {}
        for car in cars:
            for nm in names:
                if nm in per_car[car]:
                    cols[car] = df[per_car[car][nm]]
                    used[car] = nm
                    break
        if used:
            mapping[sem] = used
            frame = pd.DataFrame(cols, index=df.index).reindex(columns=cars)
            if sem in ("indoor", "target", "outdoor"):
                frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf,-np.inf],np.nan)
            else:
                frame = frame.apply(lambda s: s.astype("string").str.strip())
            signals[sem] = frame
    missing = [s for s in REQUIRED if s not in signals]
    if missing:
        raise ParseError("acv_missing_signal",
                         "Required ACV signal(s) not found: " + ", ".join(missing)
                         + ". Needed: indoor temperature, cooling target temperature and running mode.",
                         "Upload a case using the official ACV headers.")
    aliased = {s: sorted({v for v in m.values()} - {SIGNALS[s][0]}) for s, m in mapping.items()}
    aliased = {s: v for s, v in aliased.items() if v}
    if aliased:
        issues.append(QualityIssue("acv_alias_mapping", "info",
                                   "Signals mapped from recorded aliases: "
                                   + "; ".join(f"{s} ← {', '.join(v)}" for s, v in aliased.items()),
                                   treatment="Alias mapping recorded with the result.",
                                   effect="Prediction uses the same semantic features as the official schema."))
    for car in cars:
        miss = [s for s in REQUIRED if s not in mapping or car not in mapping[s]]
        if miss:
            issues.append(QualityIssue("acv_car_missing_signal", "warning",
                                       f"Car {car} lacks {', '.join(miss)}.", scope=f"car {car}",
                                       effect="Car cannot be scored; ranked as insufficient evidence."))
    empty = [car for car in cars if signals["indoor"][car].isna().all()]
    if empty:
        issues.append(QualityIssue("acv_car_no_data", "warning",
                                   f"Car(s) {', '.join(empty)} have no recorded temperature values.",
                                   scope="cars " + ", ".join(empty),
                                   effect="These cars cannot be assessed; their rank position is a tie order, not evidence."))
    modes = pd.unique(signals["mode"].to_numpy().ravel())
    unknown = sorted(str(m) for m in modes if isinstance(m, str) and m not in COOLING_MODES | KNOWN_NON_COOLING)
    if unknown:
        issues.append(QualityIssue("acv_unknown_mode", "warning",
                                   f"Unrecognised running mode value(s): {', '.join(unknown[:8])}",
                                   treatment="Rows in unknown modes excluded from cooling comparison.",
                                   effect="Less cooling evidence available."))
    ind_vals = signals["indoor"].to_numpy(dtype=float)
    finite_ind=ind_vals[np.isfinite(ind_vals)]
    if not len(finite_ind):
        raise ParseError("acv_no_temperature", "No finite cabin temperatures are available.", "Restore cabin temperature samples for several cooling cars.")
    if np.median(finite_ind)>60 or np.median(finite_ind)<-10 or np.abs(finite_ind).max()>1e6:
        raise ParseError("acv_temperature_scale", "Cabin temperatures have an unsupported scale or extreme outlier; expected °C, not Kelvin/Fahrenheit.", "Convert temperatures to °C using the sensor metadata and correct corrupt readings.")
    implausible = np.isfinite(ind_vals) & ((ind_vals < 5) | (ind_vals > 50))
    if implausible.any():
        cars_hit = [c for c, col in zip(cars, implausible.T) if col.any()]
        issues.append(QualityIssue("acv_implausible_temperature", "warning",
                                   f"{int(implausible.sum())} cabin-temperature value(s) outside 5–50 °C (e.g. 0 °C readings) "
                                   f"on car(s) {', '.join(cars_hit)}.", scope="cars " + ", ".join(cars_hit),
                                   treatment="Kept as recorded and shown in charts; not removed or interpolated.",
                                   effect="Likely sensor dropouts. They mostly fall outside settled cooling periods; "
                                          "check the affected car's trace before relying on its rank.",
                                   next_step="Inspect the dips in the car's cabin-temperature chart."))
    missing_frac = float(signals["indoor"].isna().to_numpy().mean())
    if missing_frac > 0:
        issues.append(QualityIssue("missing_values", "info",
                                   f"{missing_frac:.1%} of indoor-temperature cells are empty (measured before cleaning).",
                                   treatment="Not filled or interpolated."))
    issues.append(QualityIssue("temperature_unit_assumption", "info", "Temperature values are interpreted as °C; the source headers do not declare units.", treatment="No unit conversion applied."))
    return ACVData(time=t, cars=cars, signals=signals, sheet=sheet, mapping=mapping, issues=issues,
                   n_columns=len(df.columns))


def profile(d: ACVData) -> Profile:
    t = d.time.dropna()
    step = float(t.diff().dt.total_seconds().median()) if len(t) > 1 else None
    chans = []
    for sem, fr in d.signals.items():
        v = fr.to_numpy()
        entry = {"name": sem, "cars": len(fr.columns), "missing": int(pd.isna(v).sum())}
        if sem in ("indoor", "target", "outdoor"):
            fv = fr.to_numpy(dtype=float)
            fin = fv[np.isfinite(fv)]
            entry.update({"kind": "analog", "unit": "°C (assumed from values; unit not stated in header)",
                          "min": float(fin.min()) if len(fin) else None,
                          "median": float(np.median(fin)) if len(fin) else None,
                          "max": float(fin.max()) if len(fin) else None})
        else:
            entry.update({"kind": "state", "values": pd.Series(v.ravel()).value_counts().head(8).to_dict()})
        chans.append(entry)
    return Profile(rows=len(d.time), columns=d.n_columns, sample_rate_hz=(1 / step) if step else None,
                   sample_rate_source="measured median time step", coverage=(
                       f"{t.iloc[0]} to {t.iloc[-1]} (recorded clock, timezone unknown)" if len(t) else "unknown"),
                   channels=chans, missing_fraction=float(d.signals["indoor"].isna().to_numpy().mean()),
                   extra={"cars": d.cars, "sheet": d.sheet, "mapping": d.mapping})


# ---------------------------------------------------------------- features

def cooling_mask(d: ACVData, settle_rows: int) -> pd.DataFrame:
    mode = d.signals["mode"]
    cool = mode.isin(list(COOLING_MODES)).fillna(False).astype(bool)
    if "valid" in d.signals:
        v = d.signals["valid"]
        cool &= (v == "Valid").fillna(False) | v.isna().all()
    cool &= d.signals["indoor"].notna() & d.signals["target"].notna()
    if settle_rows > 0:
        # exclude the first settle_rows samples after each entry into cooling
        settled = pd.DataFrame(False, index=cool.index, columns=cool.columns)
        for c in cool.columns:
            g = (cool[c] != cool[c].shift()).cumsum()
            k = cool[c].groupby(g).cumcount()
            settled[c] = cool[c] & (k >= settle_rows)
        cool = settled
    return cool


def car_evidence(d: ACVData, params: dict) -> dict:
    cool = cooling_mask(d, params["settle_rows"])
    ind = d.signals["indoor"].where(cool)
    tgt = d.signals["target"].where(cool)
    cars = d.cars
    target_res = ind - tgt
    peer_res = pd.DataFrame(index=ind.index, columns=cars, dtype=float)
    for c in cars:
        others = ind.drop(columns=c)
        n_peers = others.notna().sum(axis=1)
        med = others.median(axis=1).where(n_peers >= params["min_peers"])
        peer_res[c] = ind[c] - med
    out = {}
    for c in cars:
        pr = peer_res[c].dropna()
        tr = target_res[c].dropna()
        n = int(len(pr))
        ok = n >= params["min_valid_rows"]
        out[c] = {
            "valid_cooling_rows": n,
            "valid_cooling_hours": n * params["row_seconds"] / 3600.0,
            "peer_residual_mean_K": float(pr.mean()) if ok else None,
            "target_residual_mean_K": float(tr.mean()) if ok and len(tr) else None,
            "fraction_warmer_than_peers_1K": float((pr > 1.0).mean()) if ok else None,
            "sufficient": ok,
        }
    return {"cars": out, "peer_residual": peer_res, "target_residual": target_res, "cooling": cool}


def score_cars(ev: dict, method: str) -> dict[str, float | None]:
    cars = ev["cars"]
    ok = [c for c, e in cars.items() if e["sufficient"]]
    if method == "A0":
        return {c: (cars[c]["peer_residual_mean_K"] if c in ok else None) for c in cars}
    # A1: peer residual plus target residual centred on the case median (fixed unit weights)
    tr = [cars[c]["target_residual_mean_K"] for c in ok if cars[c]["target_residual_mean_K"] is not None]
    med = float(np.median(tr)) if tr else 0.0
    out = {}
    for c in cars:
        e = cars[c]
        if c not in ok:
            out[c] = None
        else:
            t = e["target_residual_mean_K"]
            out[c] = e["peer_residual_mean_K"] + ((t - med) if t is not None else 0.0)
    return out


def rank(scores: dict[str, float | None]) -> list[str]:
    """Scored cars by descending score, ties by car ID; unscored cars last (tie order)."""
    scored = sorted([c for c, s in scores.items() if s is not None], key=lambda c: (-scores[c], c))
    unscored = sorted([c for c, s in scores.items() if s is None])
    return scored + unscored


def hot_period_leader(d: ACVData, ev: dict, min_rows: int) -> dict | None:
    """Secondary evidence (docs/EXPERIMENTS.md E2, A2c): the peer-residual ranking restricted to the hottest third of the
    recording, judged by the median cabin temperature of all cars. A leak shows most under high load. Not the
    prediction — the frozen A0 ranking is — but agreement or disagreement is reported."""
    pm = d.signals["indoor"].median(axis=1)
    if pm.notna().sum() < 3:
        return None
    hot = (pm >= pm.quantile(2 / 3)).to_numpy()
    pr = ev["peer_residual"][hot]
    counts = pr.notna().sum()
    means = pr.mean().where(counts >= min_rows)
    if means.notna().sum() < 2:
        return None
    order = sorted([c for c in means.index if pd.notna(means[c])], key=lambda c: (-float(means[c]), c))
    return {"leader": order[0], "ranking": order, "scores_K": {c: float(means[c]) for c in order},
            "rows": int(hot.sum()), "threshold_C": float(pm.quantile(2 / 3))}


def daily_leaders(d: ACVData, ev: dict, min_rows: int) -> list[dict]:
    t = d.time
    days = t.dt.date
    out = []
    for day in sorted(days.dropna().unique()):
        m = (days == day).to_numpy()
        pr = ev["peer_residual"][m]
        counts = pr.notna().sum()
        means = pr.mean().where(counts >= min_rows)
        if means.notna().sum() < 2:
            continue
        lead = means.idxmax()
        out.append({"day": str(day), "leader": lead, "score": float(means.max())})
    return out


def analyze(d: ACVData, model: dict) -> dict:
    params = model["params"]
    ev = car_evidence(d, params)
    scores = score_cars(ev, model["method"])
    order = rank(scores)
    scored = [c for c in order if scores[c] is not None]
    reasons: list[ReviewReason] = []
    margin = None
    if len(scored) >= 2:
        margin = scores[scored[0]] - scores[scored[1]]
        if margin < params["tie_margin_K"]:
            reasons.append(ReviewReason(
                "competing_candidates",
                f"Cars {scored[0]} and {scored[1]} are close: score difference {margin:.2f} K "
                f"(review threshold {params['tie_margin_K']:.2f} K).",
                f"Inspect comparable active-cooling periods for Car {scored[0]} and Car {scored[1]}.",
                f"car:{scored[1]}"))
    insufficient = [c for c in order if scores[c] is None]
    if insufficient:
        reasons.append(ReviewReason(
            "insufficient_evidence",
            f"Car(s) {', '.join(insufficient)} had fewer than {params['min_valid_rows']} valid cooling samples; "
            "they are listed last in car-ID order, which is not evidence that they are healthy.",
            "Obtain a recording with valid active-cooling data for these cars.", "coverage"))
    if len(scored) < 2:
        reasons.append(ReviewReason("no_peer_reference", "Fewer than two cars could be scored; no peer comparison is possible.",
                                    "Upload a case with cooling data for several cars.", "coverage"))
    hot = hot_period_leader(d, ev, params["min_valid_rows"] // 3)
    if scored and hot and hot["leader"] != scored[0]:
        reasons.append(ReviewReason(
            "hot_period_disagreement",
            f"During the hottest third of the recording Car {hot['leader']} was the warmest relative to its peers, not Car {scored[0]}. "
            "A leak shows most under high load, so the overall leader is less certain.",
            f"Compare Cars {scored[0]} and {hot['leader']} during the hottest hours; check both before dispatching to one car.",
            f"car:{hot['leader']}"))
    leaders = daily_leaders(d, ev, params["min_valid_rows"] // 2)
    if scored and leaders:
        agree = sum(l["leader"] == scored[0] for l in leaders)
        if agree / len(leaders) < params["stability_min_fraction"]:
            reasons.append(ReviewReason(
                "unstable_candidate",
                f"Car {scored[0]} leads on only {agree} of {len(leaders)} recorded days.",
                "Compare the days on which a different car led; check for mode or data changes.", "daily"))
    cars_out = []
    for i, c in enumerate(order, 1):
        e = ev["cars"][c]
        cars_out.append({"car": c, "rank": i, "score_K": scores[c], **e})
    lead = scored[0] if scored else None
    headline = (f"Car {lead} is the leading refrigerant-leak candidate" if lead else
                "Prediction unavailable: no car has enough valid cooling data")
    available = lead is not None
    item = {
        "id": "case",
        "ranked_cars": order,
        "leading_car": lead,
        "margin_K": margin,
        "cars": cars_out,
        "daily_leaders": leaders,
        "hot_period": hot,
        "review_reasons": [r.to_dict() for r in reasons],
        "evidence_state": "review_suggested" if reasons else "no_trigger",
        "observations": _observations(ev, scored, scores, params, hot),
        "prediction": "|".join(order),
    }
    return {"task": "acv", "headline": headline, "available": available,
            "summary": {"cars": len(order), "scored_cars": len(scored), "review": 1 if reasons else 0,
                        "score_definition": model["score_definition"], "mapping": d.mapping},
            "items": [item]}


def _observations(ev: dict, scored: list[str], scores: dict, params: dict, hot: dict | None = None) -> list[str]:
    if not scored:
        return ["No car had enough valid active-cooling samples to compare."]
    c = scored[0]
    e = ev["cars"][c]
    obs = [f"During {e['valid_cooling_hours']:.1f} h of valid active cooling, Car {c}'s cabin was on average "
           f"{e['peer_residual_mean_K']:+.2f} K relative to the median of the other cooling cars at the same time."]
    if hot:
        same = hot["leader"] == c
        obs.append((f"In the hottest third of the recording (cabin median ≥ {hot['threshold_C']:.1f} °C) Car {hot['leader']} was also the warmest "
                    f"relative to peers ({hot['scores_K'][hot['leader']]:+.2f} K), which supports the ranking." if same else
                    f"In the hottest third of the recording (cabin median ≥ {hot['threshold_C']:.1f} °C) Car {hot['leader']} led instead "
                    f"({hot['scores_K'][hot['leader']]:+.2f} K vs Car {c} {hot['scores_K'].get(c, float('nan')):+.2f} K) — secondary evidence, "
                    "not the prediction."))
    if e["target_residual_mean_K"] is not None:
        obs.append(f"Its cabin averaged {e['target_residual_mean_K']:+.2f} K relative to its own cooling target "
                   f"and was more than 1 K warmer than peers {e['fraction_warmer_than_peers_1K']:.0%} of the time.")
    if len(scored) > 1:
        c2 = scored[1]
        obs.append(f"Next candidate: Car {c2} (score {scores[c2]:+.2f} K vs {scores[c]:+.2f} K). "
                   "Scores are relative ranking evidence, not leak probabilities; refrigerant pressure is not in this telemetry.")
    return obs


# ---------------------------------------------------------------- evidence

def car_chart(d: ACVData, car: str, source: str, max_points: int = 1500) -> dict:
    t = d.time
    x = ((t - t.iloc[0]).dt.total_seconds() / 3600.0).to_numpy()
    ind = d.signals["indoor"][car].to_numpy(dtype=float)
    peers = d.signals["indoor"].drop(columns=car).median(axis=1).to_numpy(dtype=float)
    tgt = d.signals["target"][car].to_numpy(dtype=float)
    cool = d.signals["mode"][car].isin(list(COOLING_MODES)).fillna(False).to_numpy()
    bands = []
    if len(cool):
        edges = np.flatnonzero(np.diff(np.r_[0, cool.astype(int), 0]))
        for a, b in zip(edges[::2], edges[1::2]):
            if b - a > 2:
                bands.append({"x0": float(x[a]), "x1": float(x[min(b, len(x) - 1)]), "tone": "context",
                              "label": "active cooling"})
    series = [
        {"name": f"Car {car} cabin temperature", "role": "primary", **minmax_downsample(x, ind, max_points)},
        {"name": "Median of other cars", "role": "reference", **minmax_downsample(x, peers, max_points)},
        {"name": f"Car {car} cooling target", "role": "secondary", **minmax_downsample(x, tgt, max_points)},
    ]
    return chart(f"Car {car}: cabin temperature vs peers and target", "Indoor average temperature",
                 "°C (assumed)", f"Hours since {t.iloc[0]}", f"{source}, sheet {d.sheet or 'CSV'}",
                 series, bands=bands[:400], reference="Contemporaneous median of the other cars (all modes)",
                 caption="Shaded periods are when this car reported an active cooling mode. The ranking uses only "
                         "valid, settled cooling samples; the plotted peer line is shown for context.")


def score_chart(item: dict) -> dict:
    cars = [c for c in item["cars"]]
    return chart("Leak-candidate score by car", "Cooling residual score", "K", "Car", "ranking evidence",
                 [{"name": "score", "role": "primary", "x": [c["car"] for c in cars],
                   "y": [c["score_K"] for c in cars],
                   "labels": ["insufficient data" if c["score_K"] is None else "" for c in cars]}],
                 kind="bar", caption="Higher = warmer than peers and target during active cooling. Relative evidence only.")


def export_rows(file_id: str, result: dict) -> list[dict]:
    return [{"file_id": file_id, "ranked_cars": "|".join(result["items"][0]["ranked_cars"])}]


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file_id", "ranked_cars"])
        w.writeheader()
        w.writerows(rows)
