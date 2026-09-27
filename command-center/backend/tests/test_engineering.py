"""Contract/adversarial tests. Assertions encode intended behavior, not fixture names in inference."""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from diagnostics import acv, door, rail, registry, shm
from diagnostics.common import ParseError, REPO_ROOT
from diagnostics.model_store import load_model
from .test_api_exports import wait

FIXTURES=REPO_ROOT/"tests/fixtures"
SUBS=("door","acv","rail","shm")
CASES=("healthy","faulty","borderline","missing_column","extra_columns","wrong_scale","gaps",
       "duplicate_timestamps","outliers","single_row","empty","large","wrong_subsystem")
BLOCKED={"missing_column","wrong_scale","single_row","empty","outliers"}


def fixture(sub,case):
    return FIXTURES/sub/f"{case}.csv"


def check_diagnosis(d):
    assert d["condition"] in ("Normal","Watch","Action required","Unavailable")
    actions=[d["primary"],*d["alternatives"]]
    assert 3 <= len(d["alternatives"]) <= 5
    scores=[a["confidence"] for a in actions]
    assert all(isinstance(s,(int,float)) and math.isfinite(s) and 0 <= s <= 1 for s in scores)
    assert len(set(scores))>1
    assert [a["confidence"] for a in d["alternatives"]]==sorted([a["confidence"] for a in d["alternatives"]],reverse=True)
    for a in actions:
        assert a["instruction"] and a["reason"] and a["confidence_basis"]
        assert a["evidence"]
        for e in a["evidence"]:
            assert e["signal"] and e["unit"] and e["window"] and e["chart_id"]
            assert e["value"] is not None
    assert 2 <= len(d["primary"]["evidence"]) <= 4


@pytest.mark.parametrize("sub",SUBS)
@pytest.mark.parametrize("case",CASES)
def test_fixture_parser_inference(sub,case):
    p=fixture(sub,case)
    if case in BLOCKED or case=="wrong_subsystem":
        with pytest.raises(ParseError) as exc:
            registry.analyze_file(sub,p,p.name)
        assert exc.value.message and exc.value.suggestion
        return
    r=registry.analyze_file(sub,p,p.name)
    assert r["available"],r
    assert r["profile"]["rows"]>1
    check_diagnosis(r["diagnosis"])
    assert len(r["preview"]["rows"])<=8
    if case=="healthy":
        assert r["diagnosis"]["condition"]!="Action required"
    if case=="faulty":
        assert r["diagnosis"]["condition"]=="Action required"
        assert "No action" not in r["diagnosis"]["primary"]["instruction"]
    if case=="borderline":
        assert r["diagnosis"]["condition"]=="Watch"
    if case in ("gaps","duplicate_timestamps","extra_columns","large"):
        if case != "large" or sub=="rail":
            assert r["issues"]
    if case=="large":
        assert r["profile"]["rows"]>=100000
    json.dumps(r,allow_nan=False)


@pytest.mark.parametrize("sub",SUBS)
@pytest.mark.parametrize("case",CASES)
def test_every_fixture_upload_api(client,sub,case):
    rid=client.post("/api/v1/runs",json={"subsystem":sub}).json()["id"]
    p=fixture(sub,case)
    with p.open("rb") as f:
        up=client.post(f"/api/v1/runs/{rid}/files",files={"files":(p.name,f,"text/csv")})
    assert up.status_code==200,up.text
    f=up.json()["files"][0]
    if case in BLOCKED:
        assert f["status"] in ("unreadable","exploration_only"),f
        assert f["recognition"]["reason"] and f["recognition"].get("suggestion")
        return
    if case=="wrong_subsystem":
        assert f["subsystem"]!=sub and f["recognition"].get("conflict"),f
        bad=client.patch(f"/api/v1/runs/{rid}/interpretation",json={"file_id":f["id"],"subsystem":sub})
        assert bad.status_code==422
        assert bad.json()["error"]["suggestion"]
        return
    if f["status"]=="awaiting_input":
        confirmed=client.patch(f"/api/v1/runs/{rid}/interpretation",json={"file_id":f["id"],"subsystem":sub})
        assert confirmed.status_code==200,confirmed.text
        f=confirmed.json()
    assert f["subsystem"]==sub and f["status"]=="ready",f
    assert f["recognition"]["validation"]["rows"]>1
    started=client.post(f"/api/v1/runs/{rid}/analyze",json={}).json()
    run=wait(client,started["runs"][0])
    assert run["state"]=="completed",run
    rows=client.get(f"/api/v1/runs/{run['id']}/results").json()["results"]
    assert len(rows)==1
    full=client.get(f"/api/v1/results/{rows[0]['id']}").json()["payload"]
    check_diagnosis(full["diagnosis"])
    if case=="faulty": assert full["diagnosis"]["condition"]=="Action required"
    if case=="healthy": assert full["diagnosis"]["condition"]!="Action required"
    ev=client.get(f"/api/v1/results/{rows[0]['id']}/diagnostic-charts")
    assert ev.status_code==200,ev.text
    charts=ev.json()["charts"]
    assert charts and all(c["unit"] and c["series"] for c in charts)


@pytest.mark.parametrize("sub",SUBS)
def test_repeated_inference_and_borderline_confidence(sub):
    def result(case): return registry.analyze_file(sub,fixture(sub,case),f"{case}.csv")
    a=result("faulty")
    registry._parsed.cache_clear()
    assert result("faulty")==a
    b=result("borderline")
    assert b["diagnosis"]["primary"]["confidence"] < a["diagnosis"]["primary"]["confidence"]


def test_invalid_door_date_is_not_clamped():
    ts,bad=door.parse_timestamps(pd.Series(["2026-13-1-0-0-0-0","2026-1-1-0-0-0-1000","2026-1-1-25-0-0-0"]))
    assert bad==[0,1,2] and np.isnan(ts).all()


def test_rail_arbitrary_129_columns_not_recognized(tmp_path):
    p=tmp_path/"other.csv"
    pd.DataFrame(np.zeros((1100,129)),columns=[f"x{i}" for i in range(129)]).to_csv(p,index=False)
    assert registry.recognize(p,p.name)["path"]!="recognized"
    with pytest.raises(ParseError): rail.parse(p)


def test_shm_gap_provenance():
    d=shm.parse(fixture("shm","gaps"))
    assert shm.profile(d).missing_fraction>0
    assert d.sample_index[40]==50
    assert d.x[40]!=0


def test_door_feature_integral():
    d=door.parse(fixture("door","healthy"))
    c=d.frame.iloc[:160]
    f=door.cycle_features(c,d.t[:160])
    assert f["duration_s"]==pytest.approx(3.2,abs=1e-5)
    assert f["current_integral_mAs"]==pytest.approx(1824,rel=.02)


def test_acv_peer_features_localize_injected_car():
    d=acv.parse(fixture("acv","faulty"))
    ev=acv.car_evidence(d,load_model("acv")["params"])
    assert ev["cars"]["03"]["peer_residual_mean_K"]==pytest.approx(3,abs=.04)
    assert acv.rank(acv.score_cars(ev,"A0"))[0]=="03"


def test_shm_fifth_power_scaling():
    d=shm.parse(fixture("shm","healthy"))
    model=load_model("shm")["selected"]
    x=np.array([0.,20.,-20.,20.,0.])
    a=shm.predict({},shm.cycles(x,0),model)
    b=shm.predict({},shm.cycles(x*2,0),model)
    assert b/a==pytest.approx(32.)


def test_acv_workbook_detection():
    p=FIXTURES/"acv/healthy.xlsx"
    assert registry.recognize(p,p.name)["subsystem"]=="acv"
    assert acv.parse(p).cars==[f"{i:02d}" for i in range(1,9)]


def test_acv_workbook_full_api_and_csv(client):
    rid=client.post("/api/v1/runs",json={}).json()["id"]
    p=FIXTURES/"acv/healthy.xlsx"
    with p.open("rb") as f:
        response=client.post(f"/api/v1/runs/{rid}/files",files={"files":("=formula.xlsx",f,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code==200
    assert response.json()["files"][0]["subsystem"]=="acv"
    client.post(f"/api/v1/runs/{rid}/analyze",json={})
    assert wait(client,rid)["state"]=="completed"
    result=client.get(f"/api/v1/runs/{rid}/results").json()["results"][0]
    report=client.get(f"/api/v1/results/{result['id']}/findings.csv")
    assert report.status_code==200
    assert "'=formula.xlsx" in report.text
    assert "confidence_basis" in report.text and "not a calibrated probability" in report.text


def test_shm_chart_keeps_gaps_and_correct_original_rows():
    d=shm.parse(fixture("shm","gaps"))
    c=shm.trace_chart(d,"gaps.csv",i0=30,i1=60)
    assert c["series"][0]["x"]==list(range(30,60))
    assert c["series"][0]["min"][10:20]==[None]*10
    assert "rows 31–60" in c["source"]
    assert "dimensionless" in shm.cycle_hist_chart({},np.array([1.,2.]),{},"test")["unit"]


def test_rail_out_of_range_car_does_not_complete_schema():
    cols=["Rotating speed"]+[f"{kind} of bearing in position {pos} of car {car}" for car in range(1,9) for pos in range(1,9) for kind in ("Vibration","Shock")]
    cols[1]=cols[1].replace("car 1","car 9")
    assert len(rail.channel_map(cols)[1])==127


def test_unavailable_evidence_is_not_fabricated():
    from diagnostics.recommendations import unavailable_advice
    d=unavailable_advice({"profile":{"rows":120,"coverage":"120 samples"}},"shm-trace","Restore usable stress samples")
    assert d["condition"]=="Unavailable"
    assert all(a["confidence"]==0 for a in [d["primary"],*d["alternatives"]])


def test_acv_quiet_but_ambiguous_ranking_cannot_clear_as_normal():
    r=registry.analyze_file("acv",fixture("acv","healthy"),"quiet.csv")
    assert r["items"][0]["review_reasons"], "Control should have near-tied peer evidence"
    assert r["diagnosis"]["condition"]=="Watch"
    assert r["diagnosis"]["primary"]["confidence"]<.25
