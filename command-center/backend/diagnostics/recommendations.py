"""Deterministic evidence-based checks; never calibrated fault/repair probabilities.

Policy, formulas and limitations are documented in docs/RECOMMENDATION_POLICY.md.
No filenames, fixture labels or held-out answers participate in decisions.
"""
from __future__ import annotations

import math
import numpy as np

VERSION = "engineering-evidence-1.0"
CONFIDENCE_NOTE = "Confidence is an evidence support score, not a calibrated probability of a fault or a successful repair."


def bounded(x):
    return round(float(np.clip(x,0,1)),6)


def evidence(signal,value,unit,window,chart_id,reference=None):
    return dict(signal=signal,value=value,unit=unit,window=window,chart_id=chart_id,reference=reference)


def action(key,instruction,score,reason,ev,basis,urgency="Next planned check"):
    return dict(id=key,instruction=instruction,confidence=bounded(score),reason=reason,evidence=ev,
                confidence_basis=basis,urgency=urgency)


def diagnosis(condition,why,primary,alternatives,**extra):
    return dict(condition=condition,explanation=why,primary=primary,
                alternatives=sorted(alternatives,key=lambda a:(-a["confidence"],a["id"])),
                confidence_note=CONFIDENCE_NOTE,policy_version=VERSION,**extra)


def build(sub,data,result,model):
    return {"door":door_advice,"acv":acv_advice,"rail":rail_advice,"shm":shm_advice}[sub](data,result,model)


def door_advice(data,res,model):
    items=res["items"]
    top=max(items,key=lambda i:i["features"]["current_integral_mAs"]/i["decision"]["cutoff"])
    feat,dec=top["features"],top["decision"]
    x,cut=feat["current_integral_mAs"],dec["cutoff"]
    distance=abs(x-cut)
    gap=max(abs(dec["abnormal_min"]-dec["normal_max"]),1)
    completeness=1-feat["missing_current_rows"]/max(feat["rows"],1)
    support=distance/(distance+gap)*completeness
    n=len(items)
    abnormal=sum(i["prediction"]!="Normal" for i in items)
    missing=sum(i["features"]["missing_current_rows"] for i in items)
    warnings=any(i["severity"]=="warning" for i in res["issues"])
    window=f"{top['start_time']} to {top['end_time']} (recorder clock)"
    ev=[evidence("Motor-current integral",x,"mA·s",window,"door-current",f"Decision cutoff {cut:.1f} mA·s; {dec['basis']}"),
        evidence("Movement duration",feat["duration_s"],"s",window,"door-current"),
        evidence("Abnormal movements",abnormal,"cycles",res["profile"]["coverage"],"door-integrals",f"{n} cycles assessed")]
    cond="Action required" if abnormal and x/cut>=1.15 else "Watch" if abnormal or warnings or top["review_reasons"] else "Normal"
    if abnormal:
        instruction="Inspect the door travel path for resistance"
        why=f"{abnormal} of {n} movements exceed their current-integral cutoff; the strongest is {x/cut:.2f}× its cutoff."
    elif cond=="Watch":
        instruction="Repeat the affected door recording before clearing it"
        why=f"No movement exceeds its cutoff, but {sum(bool(i['review_reasons']) for i in items)} movements or the source data need review."
    else:
        instruction="Keep the door on its scheduled inspection cycle"
        why=f"All {n} movements are below their direction-specific current-integral cutoff."
    primary=action("door-primary",instruction,support,why,ev,
                   f"|integral−cutoff| / (|integral−cutoff| + training boundary gap) × finite-current fraction = {support:.3f}.",
                   "Inspect before next service decision" if cond=="Action required" else "Next recording" if cond=="Watch" else "Routine")
    repeat=(abnormal+1)/(n+2) if abnormal else 1/(n+2)
    travel=feat["position_travel"] or 0
    travel_support=model["position_travel_min"]/(model["position_travel_min"]+travel+1)
    alternatives=[
        action("door-repeat","Compare repeat movements of the same door",repeat,
               f"{abnormal}/{n} movements were above cutoff; compare whether resistance recurs.",ev[2:],"Laplace-smoothed abnormal-movement fraction (abnormal+1)/(cycles+2)."),
        action("door-position","Check the leaf alignment through its full travel",travel_support,
               f"The selected movement covers {travel:.0f} raw position units; position alone does not identify the cause.",
               [evidence("Door leaf travel",travel,"raw position units (undocumented)",window,"door-position",f"Training minimum travel {model['position_travel_min']:.0f}")],
               "Training minimum travel / (training minimum + observed travel + 1); support for verifying incomplete travel, not probability of misalignment."),
        action("door-sensor","Verify current sensor scaling and missing samples",(missing+1)/(len(data.t)+2),
               f"{missing} current samples are missing in {len(data.t)} rows; verify mA scaling before interpreting an unusual load.",
               [evidence("Missing current",missing,"samples",res["profile"]["coverage"],"door-current")],
               "Laplace-smoothed missing-current fraction (missing+1)/(rows+2).")]
    return diagnosis(cond,why,primary,alternatives,selected_item=top["id"])


def acv_advice(data,res,model):
    from .acv import car_evidence
    it=res["items"][0]
    scored=[c for c in it["cars"] if c["score_K"] is not None]
    if not scored:
        return unavailable_advice(res,"acv-temperature","Record settled active cooling on several cars")
    top=scored[0]
    car=top["car"]
    margin=it["margin_K"] or 0
    score=top["score_K"]
    peer=car_evidence(data,model["params"])["peer_residual"][car].dropna()
    n=len(peer)
    persistent=(int((peer>1).sum())+1)/(n+2)
    quiet=(int((peer.abs()<1).sum())+1)/(n+2)
    # A quiet peer residual cannot clear a recording with an ambiguous ranking
    # or acquisition/model review reasons. There is no healthy ACV calibration.
    needs_review=bool(it.get("review_reasons")) or any(q["severity"]=="warning" for q in res["issues"])
    cond="Action required" if score>=1 and margin>=.5 else "Watch" if score>=.25 or len(scored)<len(data.cars) or needs_review else "Normal"
    support=persistent*margin/(margin+.5) if cond=="Action required" else min(quiet,abs(score)/(abs(score)+1)) if cond=="Watch" else quiet
    valid_idx=peer.index
    window=f"{data.time.iloc[valid_idx[0]]} to {data.time.iloc[valid_idx[-1]]} (settled cooling rows only)"
    ev=[evidence(f"Car {car} temperature above peers",score,"K",window,"acv-temperature","Inspection signal: ≥1 K; comparison uses other settled cooling cars"),
        evidence("Top-two ranking gap",margin,"K",window,"acv-ranking","Competing-candidate band: 0.5 K"),
        evidence("Valid cooling exposure",top["valid_cooling_hours"],"h",window,"acv-temperature",f"{n} samples × documented 30 s")]
    if cond=="Action required":
        instruction=f"Inspect Car {car}'s cooling circuit and verify refrigerant pressure"
        why=f"Car {car} averages {score:+.2f} K above cooling peers and leads the next candidate by {margin:.2f} K."
    elif cond=="Watch":
        instruction=f"Compare Cars {car} and {scored[1]['car'] if len(scored)>1 else car} during settled cooling"
        why=f"The top car is {score:+.2f} K above peers; the {margin:.2f} K ranking gap or incomplete coverage limits localisation."
    else:
        instruction="Continue routine cooling checks and compare the next recording"
        why=f"No car has a material peer-temperature residual in this recording (largest {score:+.2f} K); telemetry cannot exclude a leak."
    primary=action("acv-primary",instruction,support,why,ev,
                   "Clear anomaly: smoothed share >1 K × margin/(margin+0.5 K). Watch: min(quiet share, |residual|/(|residual|+1 K)). Normal: smoothed share within ±1 K.",
                   "Check at next maintenance opportunity" if cond=="Action required" else "Next cooling period")
    alternatives=[]
    for candidate in scored[1:4]:
        c=candidate["car"]
        r=max(candidate["score_K"],0)
        tr=abs(candidate["target_residual_mean_K"] or 0)
        support=r/(r+1) * candidate["valid_cooling_rows"]/(candidate["valid_cooling_rows"]+model["params"]["min_valid_rows"])
        alternatives.append(action("acv-car-"+c,f"Compare Car {c}'s cabin sensor and cooling response",support,
                                   f"Car {c}: {candidate['score_K']:+.2f} K against peers; {tr:.2f} K from target.",
                                   [evidence(f"Car {c} peer residual",candidate["score_K"],"K",window,"acv-ranking")],
                                   "Positive peer residual/(residual+1 K) × valid rows/(valid rows+120)."))
    while len(alternatives)<3:
        key=len(alternatives)
        alternatives.append(action(f"acv-coverage-{key}","Restore telemetry for the unscored cars",(len(data.cars)-len(scored))/(len(data.cars)+key+1),
                                   f"{len(scored)} of {len(data.cars)} cars could be compared.",ev[2:],"Unscored cars divided by total cars plus evidence-count smoothing."))
    # Positive equal-temperature controls can yield zero residual for all alternatives;
    # their differing observed target offsets still justify sensor/target comparisons.
    for a,c in zip(alternatives,scored[1:4]):
        if a["confidence"]==0:
            v=abs(c["target_residual_mean_K"] or 0)
            a["confidence"]=bounded(v/(v+1) / (c["valid_cooling_rows"]+1)**.5)
            a["confidence_basis"]="Target-offset/(target-offset+1 K) divided by sqrt(valid rows+1); weak support to verify the sensor/target."
    return diagnosis(cond,why,primary,alternatives,selected_car=car)


def rail_advice(data,res,model):
    it=res["items"][0]
    ss,dec=it["side_summary"],it["decision"]
    med_i=float(np.median(ss["side_I_rms"]))
    med_ii=float(np.median(ss["side_II_rms"]))
    rms=max(med_i,med_ii)
    ref=model["reference"]["normal_side_rms_median"]
    ratio=rms/ref
    p=dec["stage1_fault_score"]
    spectral_fault=it["prediction"]!="Normal"
    # A broad signal anomaly must not be hidden by a target-class classifier.
    condition="Action required" if spectral_fault or ratio>=3 else "Watch" if ratio>=.75 or it["review_reasons"] else "Normal"
    observed_side="Side I" if med_i>=med_ii else "Side II"
    side=it["prediction"] if spectral_fault else observed_side
    support=p if spectral_fault else ratio/(ratio+1) if condition!="Normal" else 1-p
    window=f"0 to {len(data.data)/10000:.4f} s (10,000 Hz)"
    ev=[evidence("Side I median vibration RMS",med_i,"m/s²",window,"rail-sides",f"Normal training median {ref:.3f} m/s²"),
        evidence("Side II median vibration RMS",med_ii,"m/s²",window,"rail-sides"),
        evidence("Frozen corrugation detection score",p,"dimensionless score",window,"rail-spectrum","Class threshold 0.5; uncalibrated model vote")]
    if spectral_fault:
        instruction=f"Inspect the {side} rail surface in the recorded section"
        why=f"The frozen model detects {side} corrugation (score {p:.2f}); median vibration reaches {ratio:.2f}× the normal reference."
    elif ratio>=3:
        instruction="Inspect the unusually high axle-box vibration and verify the sensors"
        why=f"Vibration is {ratio:.2f}× the normal reference despite a Normal corrugation label; this is a signal anomaly, not confirmed corrugation."
    elif condition=="Watch":
        instruction="Repeat the rail recording under a comparable operating condition"
        why=f"Vibration is {ratio:.2f}× the normal reference and/or features fall outside training; the target-class result needs context."
    else:
        instruction="Continue routine rail monitoring on the next pass"
        why=f"Corrugation score {p:.2f} is below 0.50 and vibration is {ratio:.2f}× the normal reference."
    primary=action("rail-primary",instruction,support,why,ev,"Target fault: frozen forest fault score. Broad signal anomaly: RMS ratio/(ratio+1). Normal: 1−fault score. Scores are not probabilities.",
                   "Inspect before accepting the recording as normal" if condition=="Action required" else "Next comparable pass")
    side_gap=abs(med_i-med_ii)/(med_i+med_ii+1e-12)
    alternatives=[
        action("rail-side",f"Compare {observed_side} axle-box channels across cars",side_gap,
               f"The side RMS difference is {abs(med_i-med_ii):.3f} m/s²; amplitude alone does not establish the faulty side.",ev[:2],"Absolute side RMS difference divided by their sum."),
        action("rail-mount","Verify accelerometer mounting and acceleration units",abs(ratio-1)/(abs(ratio-1)+2),
               f"The largest side median is {ratio:.2f}× the training Normal median.",ev[:2],"|RMS ratio−1|/(|RMS ratio−1|+2): support for checking a domain shift."),
        action("rail-repeat","Confirm the corrugation signature on a repeat pass",1-abs(2*p-1),
               f"Detection score {p:.3f} sits {abs(p-.5):.3f} from the decision boundary.",ev[2:],"1−|2×fault score−1|: model ambiguity requiring another recording.")]
    car=int(np.argmax(ss["side_I_rms"] if side=="Side I" else ss["side_II_rms"]))+1
    return diagnosis(condition,why,primary,alternatives,selected_car=str(car),selected_position=1 if side=="Side I" else 2,model_prediction=it["prediction"])


def shm_advice(data,res,model):
    it=res["items"][0]
    if not it.get("available"):
        return unavailable_advice(res,"shm-trace","Verify the stress signal before estimating damage")
    f=it["features"]
    d=it["prediction"]
    hi=model["feature_ranges"]["p2p"][1]
    ratio=f["p2p"]/hi
    condition="Action required" if ratio>=1.5 else "Watch" if d>=.2 or it["review_reasons"] else "Normal"
    support=ratio/(ratio+1) if condition=="Action required" else 1/(1+ratio) if condition=="Normal" else abs(ratio-1)/(abs(ratio-1)+1)
    window=f"Samples 0–{(data.input_rows or len(data.x))-1}; sampling rate not supplied"
    ev=[evidence("Estimated segment damage",d,"dimensionless D",window,"shm-cycles","Dataset-fitted fatigue surrogate; not remaining life"),
        evidence("Peak-to-peak stress",f["p2p"],"raw stress units (undocumented)",window,"shm-trace",f"Training range maximum {hi:.2f}"),
        evidence("Counted stress cycles",f["gated_cycles"],"cycles",window,"shm-cycles",f"Gate {model['gate']} raw stress units")]
    if condition=="Action required":
        instruction="Verify sensor calibration and inspect the high-stress measurement point"
        why=f"Stress range is {ratio:.2f}× the largest training range; the damage estimate is extrapolated, not proof of a structural fault."
    elif condition=="Watch":
        instruction="Compare stress cycles with a matched segment from the same point"
        why=f"Estimated segment damage is {d:.3g} D; the load regime or model range needs review before maintenance decisions."
    else:
        instruction="Retain this segment for routine structural trend review"
        why=f"Estimated segment damage is {d:.3g} D and no high-stress anomaly is established; this does not certify structural health."
    primary=action("shm-primary",instruction,support,why,ev,
                   "High stress: range ratio/(ratio+1). Watch: |ratio−1|/(|ratio−1|+1). Routine: 1/(1+ratio). Based on training-maximum range; no fault calibration.",
                   "Review before using extrapolated damage" if condition=="Action required" else "Planned structural review")
    alternatives=[
        action("shm-peaks","Inspect the largest stress cycles in the trace",f["max_cycle_range"]/(f["max_cycle_range"]+hi),
               f"Largest counted range {f['max_cycle_range']:.2f} raw stress units; large cycles dominate the fifth-power sum.",ev[1:],"Largest cycle range/(largest range+training maximum range)."),
        action("shm-load","Confirm measurement point and load condition before comparing segments",d/(d+1),
               f"This segment contributes {d:.3g} D under the fitted model; AW0/AW4 and chronology are not recorded.",ev[:1],"Estimated segment D/(D+1): support for checking context before accumulation, not failure probability."),
        action("shm-gaps","Check missing stress samples and acquisition continuity",(data.missing_count+1)/((data.input_rows or len(data.x))+2),
               f"{data.missing_count} samples were removed before counting cycles; any gaps can hide extrema.",
               [evidence("Missing stress samples",data.missing_count,"samples",window,"shm-trace")],"Laplace-smoothed missing sample fraction (missing+1)/(input samples+2).")]
    return diagnosis(condition,why,primary,alternatives)


def unavailable_advice(res,chart_id,instruction):
    window=res["profile"]["coverage"]
    n=res["profile"]["rows"]
    ev=[evidence("Recorded samples",n,"rows",window,chart_id),evidence("Usable prediction",0,"available estimates",window,chart_id)]
    primary=action("unavailable",instruction,0,"The recording does not support a usable estimate.",ev,"Zero usable estimates: confidence is unavailable, represented by zero.","Correct data first")
    alternatives=[action(f"unavailable-{k}",title,0,"Diagnostic coverage is insufficient to rank this check.",ev[:1],"Unscored: no diagnostic evidence. Zero is not a probability.") for k,title in enumerate(("Check required signal coverage","Confirm source units and sampling","Collect a complete repeat recording"))]
    return diagnosis("Unavailable",primary["reason"],primary,alternatives)
