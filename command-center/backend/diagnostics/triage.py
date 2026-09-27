"""Part 2 (organizer FAQ): turn each machine finding into something an operator can act on.

For every result item this module derives a *triage card*: what was found, where, how sure the
evidence is, the recommended action, the next check, and a severity tier. Severity comes from an
explicit, editable policy whose defaults are ILLUSTRATIVE (they are not an LTA standard) and are
labelled as such wherever they are shown. Nothing here changes a prediction or an official CSV;
the cards are derived views over the frozen result payloads.
"""
from __future__ import annotations

import copy
from typing import Any

SEVERITIES = ("high", "medium", "low", "info")
SEVERITY_LABELS = {"high": "Act now", "medium": "Plan a check", "low": "Watch", "info": "Information"}
STATUSES = ("open", "acknowledged", "investigating", "confirmed", "not_found", "closed")
STATUS_LABELS = {"open": "Open", "acknowledged": "Acknowledged", "investigating": "Investigating",
                 "confirmed": "Outcome: fault confirmed", "not_found": "Outcome: nothing found", "closed": "Closed"}

# Editable policy. Every number is an illustrative default chosen from the training data ranges and
# common maintenance practice, not from any operator's standard; the UI shows this label and lets
# the user change the values. Stored in the local settings table once edited.
DEFAULT_POLICY: dict[str, Any] = {
    "version": "triage-policy-1.0",
    "illustrative": True,
    "note": "Illustrative defaults. Edit to match your operating policy; changes are stored locally and never alter predictions.",
    "door": {
        "abnormal_no_review": "high",
        "abnormal_with_review": "medium",
        "normal_with_review": "low",
        "abnormal_share_high": 0.25,   # share of cycles abnormal in one stream that escalates the stream summary
    },
    "acv": {
        "clear_margin_K": 0.5,          # top-two margin at or above this = a clear candidate (one sensor step)
        "weak_margin_K": 0.1,           # below this the ranking is treated as inconclusive
        "clear": "high", "competing": "medium", "inconclusive": "low",
    },
    "rail": {
        "strong_score": 0.65,           # stage-1 fault score at or above this = strong evidence
        "strong": "high", "near_threshold": "medium", "normal_with_review": "low",
    },
    "shm": {
        "high_damage": 0.5,             # Legacy workflow reference, NOT a calibrated physical failure limit
        "medium_damage": 0.2,
        "high": "high", "medium": "medium", "low": "low",
        "extrapolating": "medium",      # features outside the training range raise at least to this tier
    },
}

_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


def merge_policy(stored: dict | None) -> dict:
    pol = copy.deepcopy(DEFAULT_POLICY)
    if stored:
        for k, v in stored.items():
            if isinstance(v, dict) and isinstance(pol.get(k), dict):
                pol[k].update(v)
            else:
                pol[k] = v
        pol["illustrative"] = False if stored.get("edited") else pol["illustrative"]
    return pol


def _at_least(a: str, b: str) -> str:
    return a if _ORDER[a] <= _ORDER[b] else b


def _codes(item: dict) -> set[str]:
    return {r.get("code") for r in item.get("review_reasons", [])}


def _door_card(item: dict, payload: dict, pol: dict) -> dict:
    p = pol["door"]
    abnormal = item.get("prediction") == "Abnormal resistance"
    review = bool(item.get("review_reasons"))
    x = (item.get("features") or {}).get("current_integral_mAs")
    op = item.get("operation") or "movement (direction unresolved)"
    dec = item.get("decision") or {}
    relative = dec.get("rule") == "relative"
    if abnormal and not review:
        sev = p["abnormal_no_review"]
        sure = ("Clear: relative to this door's own normal level, the motor drew more current than any normal training cycle did relative to its door, and no data problem was found."
                if relative else "Clear: the motor drew more current than any normal training cycle and no data problem was found.")
        action = "Inspect the slide rails, rubber strips and leaf alignment for resistance; use local maintenance procedures for any service decision."
    elif abnormal:
        sev, sure = p["abnormal_with_review"], "Probable but not certain: the reading is above the cutoff yet inside a range no training cycle covered, or the cycle had a data issue."
        action = "Inspect the door at the next depot visit; compare with a repeat cycle before booking a repair."
    elif review:
        sev, sure = p["normal_with_review"], "Uncertain: predicted Normal, but the reading sits between the training Normal and Abnormal ranges."
        action = "No immediate action. Keep the door under observation and re-check on the next recording."
    else:
        sev, sure = "info", "Consistent with normal operation."
        action = "Continue scheduled inspection; a Normal model label does not certify safe operation."
    where = f"{item.get('id', 'cycle').replace('cycle-', 'Cycle ')} · {op.lower()} at recorder time {_clock(item.get('start_time'))}"
    what = ("Abnormal resistance predicted during this door movement" if abnormal else "Normal resistance during this door movement")
    detail = (f"Motor-current integral {x:.0f} mA·s vs cutoff {dec.get('cutoff', 0):.0f} mA·s" if x is not None and dec.get("cutoff") else "")
    card = _card(sev, what, where, sure, action, item, detail, "door")
    card["strength"] = (x / dec["cutoff"]) if x is not None and dec.get("cutoff") else 0.0  # how far above the cutoff
    return card


def _acv_card(item: dict, payload: dict, pol: dict) -> dict:
    p = pol["acv"]
    lead = item.get("leading_car")
    margin = item.get("margin_K")
    ranked = item.get("ranked_cars") or []
    if lead is None:
        return _card("info", "No car could be assessed", "Whole train", "No car had enough valid cooling data.", "Obtain a recording with active cooling on several cars.", item, "", "acv")
    if margin is not None and margin >= p["clear_margin_K"]:
        sev, sure = p["clear"], f"Clear: Car {lead} was {margin:.2f} K further above its peers than the next car (one sensor step is 0.5 K)."
        action = f"Check Car {lead}'s ACV unit for refrigerant leakage: pressure test, sight glass, and superheat/subcooling readings."
    elif margin is not None and margin >= p["weak_margin_K"]:
        sev, sure = p["competing"], f"Competing: Car {lead} leads Car {ranked[1] if len(ranked) > 1 else '?'} by only {margin:.2f} K."
        action = f"Check Car {lead} first, then Car {ranked[1] if len(ranked) > 1 else '?'}; a single check on one car may miss the leak."
    else:
        sev, sure = p["inconclusive"], (f"Inconclusive: the top cars differ by {margin:.2f} K, far below one sensor step (0.5 K). The ranking order is weak evidence." if margin is not None else "Inconclusive.")
        action = "Do not act on the car order alone. Record cabin temperatures during a hot period with all cars in cooling, then re-run."
    what = f"Car {lead} is the leading refrigerant-leak candidate"
    where = f"Car {lead} (then {', '.join('Car ' + c for c in ranked[1:3])})"
    card = _card(sev, what, where, sure, action, item, f"Ranking {' | '.join(ranked)}", "acv")
    card["strength"] = float(margin or 0.0)
    return card


def _rail_card(item: dict, payload: dict, pol: dict) -> dict:
    p = pol["rail"]
    label = item.get("prediction")
    dec = item.get("decision") or {}
    score = dec.get("stage1_fault_score")
    ss = item.get("side_summary") or {}
    where = "Recording " + str(item.get("file_id", ""))
    peak = _rail_peak(ss)
    if peak:
        where += f" · highest vibration {peak}"
        if label in ("Side I", "Side II") and not peak.startswith(label + ","):
            where += (f" — the predicted side ({label}) comes from the side-contrast model (spectral bands, kurtosis, crest factor), "
                      "not from the raw level, which corrugation raises on both rails")
    if label in ("Side I", "Side II"):
        if score is not None and score >= p["strong_score"]:
            sev, sure = p["strong"], f"Strong: fault-detection score {score:.2f} is well above the 0.50 threshold."
        else:
            sev, sure = p["near_threshold"], f"Probable: fault-detection score {score:.2f} is close to the 0.50 threshold." if score is not None else "Probable."
        what = f"{label} rail corrugation signature detected"
        action = (f"Refer the section covered by this recording to track maintenance for a {label} rail surface inspection "
                  "(corrugation gauge or visual); repeat the recording on the next pass to confirm.")
    elif item.get("review_reasons"):
        sev, sure = p["normal_with_review"], "Predicted Normal but close to the decision threshold or with unusual features."
        what, action = "No corrugation signature, borderline", "Keep this section on the watch list; compare with the next pass."
    else:
        sev, sure, what, action = "info", "No target corrugation signature detected; other vibration anomalies are not excluded.", "No corrugation signature", "Compare vibration amplitude and data quality before accepting the recording as normal."
    card = _card(sev, what, where, sure, action, item, f"Fault score {score:.2f}" if score is not None else "", "rail")
    card["strength"] = float(score or 0.0)
    if ss.get("cars"):
        card["heat"] = {"cars": ss["cars"], "side_I": ss.get("side_I_rms"), "side_II": ss.get("side_II_rms"), "unit": "m/s²",
                        "predicted_side": label if label in ("Side I", "Side II") else None}
    return card


def _shm_card(item: dict, payload: dict, pol: dict) -> dict:
    p = pol["shm"]
    d = item.get("prediction")
    codes = _codes(item)
    if d is None:
        return _card("info", "Damage estimate unavailable", str(item.get("file_id", "")), "The model could not produce a value.", "Check the file.", item, "", "shm")
    if d >= p["high_damage"]:
        sev, sure = p["high"], f"Estimated segment damage {d:.2f} D exceeds the illustrative review reference; it is not a calibrated structural failure criterion."
        action = "Escalate this measurement point for structural review; verify the sensor calibration and compare with other segments from the same point."
    elif d >= p["medium_damage"]:
        sev, sure = p["medium"], f"Estimated damage {d:.2f} is moderate."
        action = "Include this measurement point in the next planned structural inspection."
    else:
        sev, sure = p["low"], f"Estimated damage {d:.3g} is small."
        action = "Retain the segment for trend review; only accumulate confirmed consecutive segments from the same measurement point."
    if "outside_training_range" in codes:
        sev = _at_least(sev, p["extrapolating"])
        sure += " The stress levels are outside the training range, so the magnitude is an extrapolation."
    card = _card(sev, f"Cumulative fatigue damage estimated at {d:.3g}", "Measurement point of " + str(item.get("file_id", "")), sure, action, item, "", "shm")
    card["strength"] = float(d)
    return card


def _rail_peak(ss: dict) -> str:
    try:
        cars = ss["cars"]
        best = None
        for side, key in (("Side I", "side_I_rms"), ("Side II", "side_II_rms")):
            for c, v in zip(cars, ss[key]):
                if best is None or v > best[2]:
                    best = (side, c, v)
        return f"{best[0]}, car {best[1]} ({best[2]:.2f} m/s²)" if best else ""
    except (KeyError, TypeError):
        return ""


def _clock(native: str | None) -> str:
    if not native:
        return "?"
    p = str(native).split("-")
    if len(p) != 7:
        return str(native)
    return f"{int(p[3]):02d}:{int(p[4]):02d}:{int(p[5]):02d}"


def _card(sev: str, what: str, where: str, sure: str, action: str, item: dict, detail: str, subsystem: str) -> dict:
    nxt = [r.get("next_check") for r in item.get("review_reasons", []) if r.get("next_check")]
    return {"severity": sev, "severity_label": SEVERITY_LABELS[sev], "what": what, "where": where, "how_sure": sure,
            "action": action, "next_check": nxt[0] if nxt else _default_next_check(subsystem), "detail": detail,
            "review_count": len(item.get("review_reasons", [])), "strength": 0.0}


def _default_next_check(subsystem: str) -> str:
    return {"door": "Compare the next recording of the same door against this one.",
            "acv": "Re-run on a recording that covers a hot period with all cars cooling.",
            "rail": "Repeat the recording on the next pass over the same section.",
            "shm": "Compare with other segments from the same measurement point."}[subsystem]


def card_for(subsystem: str, item: dict, payload: dict, policy: dict | None = None) -> dict:
    pol = merge_policy(policy)
    fn = {"door": _door_card, "acv": _acv_card, "rail": _rail_card, "shm": _shm_card}[subsystem]
    card = fn(item, payload, pol)
    card["policy_version"] = pol["version"]
    card["policy_illustrative"] = bool(pol.get("illustrative", True))
    return card


def stream_summary(subsystem: str, items: list[dict], cards: list[dict], pol: dict | None = None) -> dict:
    """One-paragraph operator summary for a whole result (a Door stream, an ACV case, a Rail/SHM file)."""
    pol = merge_policy(pol)
    counts = {s: sum(1 for c in cards if c["severity"] == s) for s in SEVERITIES}
    top = min(cards, key=lambda c: _ORDER[c["severity"]]) if cards else None
    if subsystem == "door" and items:
        n = len(items)
        abn = sum(1 for i in items if i.get("prediction") == "Abnormal resistance")
        share = abn / n if n else 0.0
        text = (f"{abn} of {n} door movements drew abnormally high motor current" if abn else f"All {n} door movements look normal")
        if share >= pol["door"]["abnormal_share_high"]:
            text += f" ({share:.0%} of the recording) — this door needs attention, not just the single worst cycle"
        return {"text": text + ".", "top_severity": top["severity"] if top else "info", "counts": counts}
    return {"text": top["what"] + "." if top else "No findings.", "top_severity": top["severity"] if top else "info", "counts": counts}


CHECKLISTS = {
    "door": ["Confirm the door and car from the recording context (the file has no door identity).",
             "Cycle the door manually; listen and feel for binding along the full travel.",
             "Inspect slide rails and rollers for foreign objects, wear or lack of lubrication.",
             "Inspect the rubber sealing strips and the leaf alignment / deformation.",
             "Record a new cycle after rectification and compare its motor-current trace with the Normal reference."],
    "acv": ["Read high- and low-side refrigerant pressures on the indicated car's unit; compare with the neighbouring cars.",
            "Check superheat/subcooling and the sight glass for bubbles.",
            "Leak-test joints, valves and the condenser/evaporator coils.",
            "Verify the cabin temperature sensor reads plausibly (0 °C dropouts were seen in the telemetry).",
            "After repair, record a full day of cooling and re-run the comparison."],
    "rail": ["Identify the track section from the run log for the time of this recording (position is not in the data).",
             "Walk the indicated rail side; look for the periodic wavy wear pattern and listen on the next pass.",
             "Measure corrugation depth/wavelength with a gauge or trolley if available.",
             "Check sleeper spacing, fastenings and curve geometry as contributing factors.",
             "If confirmed, refer to the grinding/milling programme and re-record after treatment."],
    "shm": ["Confirm the measurement point and the sensor calibration date.",
            "Compare this segment's damage with other segments from the same point (file numbers are not a time order).",
            "Inspect the structure near the measurement point for cracks or fretting if the estimate is large.",
            "Check whether the load condition (AW0/AW4) or line explains a high value.",
            "Keep accumulating segments; Miner's rule sums damage across them."],
}

# How each finding type maps to a maintenance decision. General condition-monitoring practice, not an LTA
# policy document; labelled as such in the UI.
MAINTENANCE_MAP = {
    "door": {"finding": "Abnormal opening/closing resistance", "decision": "Condition-based door maintenance: inspection and rectification of rails, seals or leaf before a jam or motor overload occurs.",
             "instead_of": "Manual onboard inspection on a fixed schedule."},
    "acv": {"finding": "Refrigerant leak localised to a car", "decision": "Targeted leak test and recharge on one unit instead of checking all eight cars; earlier repair before cooling capacity is lost in summer.",
            "instead_of": "Waiting for passenger complaints or an ACV shutdown."},
    "rail": {"finding": "Corrugation on one rail side", "decision": "Referral of the section to the rail grinding/milling programme; prioritisation by severity across sections.",
             "instead_of": "Periodic manual track walks and noise complaints."},
    "shm": {"finding": "Cumulative fatigue damage per segment", "decision": "Structural inspection prioritised by accumulated damage at each measurement point; input to life-extension decisions.",
            "instead_of": "Fixed-interval structural inspections."},
}
