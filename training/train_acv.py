"""ACV: leave-one-case-out evaluation of fixed (untuned) ranking rules A0/A1,
permutation-invariance check, artifact freeze."""
from __future__ import annotations

import numpy as np
import pandas as pd

from _paths import DATA, fingerprint, now
from diagnostics import acv
from diagnostics.metrics import acv_case_score

PARAMS = {
    "settle_rows": 20,          # 10 min at 30 s: cabin temperature lags a mode change
    "min_peers": 3,
    "min_valid_rows": 120,      # 1 h of valid settled cooling
    "row_seconds": 30,
    "tie_margin_K": 0.5,        # one sensor resolution step (values are quantised to 0.5 K)
    "stability_min_fraction": 0.5,
}
DEFS = {
    "A0": "Mean over valid, settled active-cooling samples of (car cabin temperature − median cabin temperature of the other cooling cars at the same time), in K.",
    "A1": "A0 plus the car's mean (cabin − own cooling target) residual, centred on the case median of that residual; fixed unit weights.",
}


def load_cases():
    labels = pd.read_csv(DATA / "ACV" / "Train_Labels.csv", dtype=str)
    cases = {}
    for _, r in labels.iterrows():
        cases[r.filename] = (acv.parse(DATA / "ACV" / "Train" / r.filename), r.faulty_car)
    return cases


def permute_cars(d: acv.ACVData, perm: dict[str, str]) -> acv.ACVData:
    sig = {k: v.rename(columns=perm)[sorted(perm.values())] for k, v in d.signals.items()}
    return acv.ACVData(time=d.time, cars=sorted(perm.values()), signals=sig, sheet=d.sheet,
                       mapping=d.mapping, issues=[], n_columns=d.n_columns)


def run():
    cases = load_cases()
    results = {}
    for method in ("A0", "A1"):
        per = []
        for name, (d, true_car) in cases.items():
            model = {"method": method, "params": PARAMS, "score_definition": DEFS[method]}
            r = acv.analyze(d, model)["items"][0]
            rank = r["ranked_cars"].index(true_car) + 1
            per.append({"case": name, "true_car": true_car, "rank": rank,
                        "score": acv_case_score(r["ranked_cars"], true_car, len(r["ranked_cars"])),
                        "ranking": r["ranked_cars"], "margin_K": r["margin_K"],
                        "review": [x["code"] for x in r["review_reasons"]],
                        "true_car_score_K": next(c["score_K"] for c in r["cars"] if c["car"] == true_car)})
        s = [p["score"] for p in per]
        results[method] = {"per_case": per, "mean": float(np.mean(s)), "min": float(np.min(s)),
                           "top1": sum(p["rank"] == 1 for p in per), "top3": sum(p["rank"] <= 3 for p in per)}
    selected = "A0" if results["A0"]["mean"] >= results["A1"]["mean"] else "A1"

    # permutation test: relabel cars within a case -> ranking permutes identically
    rng = np.random.default_rng(7)
    perm_ok = True
    for name, (d, _) in cases.items():
        cars = d.cars
        shuffled = list(rng.permutation(cars))
        perm = dict(zip(cars, shuffled))
        model = {"method": selected, "params": PARAMS, "score_definition": DEFS[selected]}
        a = acv.analyze(d, model)["items"][0]
        b = acv.analyze(permute_cars(d, perm), model)["items"][0]
        sa = {c["car"]: c["score_K"] for c in a["cars"]}
        sb = {c["car"]: c["score_K"] for c in b["cars"]}
        if any((sa[c] is None) != (sb[perm[c]] is None) or (sa[c] is not None and abs(sa[c] - sb[perm[c]]) > 1e-9) for c in cars):
            perm_ok = False
    test = acv.parse(DATA / "ACV" / "Test" / "acv_test_case.xlsx")
    validation = {
        "task": "acv", "created": now(), "metric": "Linear rank-decay (n − r + 1)/n, mean over cases (official)",
        "protocol": "Leave-one-case-out over 6 training cases. A0 and A1 are fixed, preregistered rules with no fitted "
                    "weights, so no tuning occurs inside folds; LOO scores equal per-case scores.",
        "params": PARAMS, "definitions": DEFS, "candidates": results, "selected": selected,
        "selection_rule": "Higher mean LOO score; ties go to the simpler A0.",
        "permutation_invariance": perm_ok,
        "test_schema": {"sheet": test.sheet, "cars": test.cars, "columns": test.n_columns,
                        "mapping_signals": sorted(test.mapping)},
        "limitations": [
            "Six cases are six independent fault examples; ranking generalisation is weakly evidenced.",
            "Case 04 uses a rich schema; its indoor/target/mode signals come from recorded aliases, and cars 05–08 have no data.",
            "Cases 05 and 06 have no outdoor temperature; the ranker does not use outdoor temperature.",
            "Scores are relative evidence among cars in one case, not leak probabilities.",
        ],
    }
    model = {
        "task": "acv", "version": f"acv-{selected}-1.0.0", "method": selected,
        "method_name": "Peer/target cooling-residual ranking",
        "created": now(),
        "training_fingerprint": fingerprint(sorted((DATA / "ACV" / "Train").glob("*.xlsx"))),
        "params": PARAMS, "score_definition": DEFS[selected],
        "feature_contract": ["indoor temperature", "cooling target temperature", "running mode", "information valid (optional)"],
        "cooling_modes": sorted(acv.COOLING_MODES), "estimators": {},
        "validation_summary": {"loo_mean": results[selected]["mean"], "top1": results[selected]["top1"]},
        "limitations": validation["limitations"],
    }
    return model, validation
