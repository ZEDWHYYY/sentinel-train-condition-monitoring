"""Part 2: triage cards, the local investigation lifecycle, the Attention feed, the editable policy and the job brief."""
import numpy as np

from diagnostics import triage


# ---------------------------------------------------------------- triage
def test_triage_cards_cover_every_subsystem_and_policy_edits_apply():
    door_item = {"id": "cycle-001", "prediction": "Abnormal resistance", "review_reasons": [], "operation": "Close",
                 "features": {"current_integral_mAs": 2100}, "decision": {"cutoff": 1837, "rule": "relative"}, "start_time": "2023-7-5-0-5-46-252"}
    c = triage.card_for("door", door_item, {})
    assert c["severity"] == "high" and "Cycle 001" in c["where"] and c["policy_illustrative"]
    c2 = triage.card_for("door", door_item, {}, {"door": {"abnormal_no_review": "medium"}, "edited": True})
    assert c2["severity"] == "medium" and not c2["policy_illustrative"]
    acv_item = {"id": "case", "leading_car": "03", "margin_K": 0.03, "ranked_cars": ["03", "04", "01"], "review_reasons": []}
    assert triage.card_for("acv", acv_item, {})["severity"] == "low"
    acv_item["margin_K"] = 0.9
    assert triage.card_for("acv", acv_item, {})["severity"] == "high"
    rail_item = {"id": "Test9.csv", "file_id": "Test9.csv", "prediction": "Side II", "review_reasons": [],
                 "decision": {"stage1_fault_score": 0.76}, "side_summary": {"cars": [1, 2], "side_I_rms": [0.5, 0.6], "side_II_rms": [0.7, 1.1]}}
    r = triage.card_for("rail", rail_item, {})
    assert r["severity"] == "high" and "Side II, car 2" in r["where"]
    shm_item = {"id": "t", "file_id": "t.csv", "prediction": 0.82, "review_reasons": [{"code": "outside_training_range", "next_check": "x", "message": "m"}]}
    s = triage.card_for("shm", shm_item, {})
    assert s["severity"] == "high" and "extrapolation" in s["how_sure"]
    summary = triage.stream_summary("door", [door_item] * 3 + [{**door_item, "prediction": "Normal"}], [c] * 3 + [triage.card_for("door", {**door_item, "prediction": "Normal"}, {})])
    assert "needs attention" in summary["text"] and summary["top_severity"] == "high"


# ---------------------------------------------------------------- API: lifecycle, attention, policy, brief
_SEED = [1]


def _shm_run(client, tmp_path):
    p = tmp_path / "s.csv"
    _SEED[0] += 1  # distinct content per run, so tests never share a recording (the feed dedupes by file hash)
    rng = np.random.default_rng(_SEED[0])
    p.write_text("\n".join(str(v) for v in (rng.standard_normal(3000) * 8).round(3)))
    r = client.post("/api/v1/runs", json={}).json()
    client.post(f"/api/v1/runs/{r['id']}/local-path", json={"path": str(p)})
    rid = client.post(f"/api/v1/runs/{r['id']}/analyze", json={}).json()["runs"][0]
    import time
    for _ in range(300):
        if client.get(f"/api/v1/runs/{rid}").json()["state"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    return rid


def test_lifecycle_attention_policy_and_brief(client, tmp_path):
    rid = _shm_run(client, tmp_path)
    res = client.get(f"/api/v1/runs/{rid}/results").json()["results"][0]
    item = res["items"][0]
    assert item["triage"]["severity"] in triage.SEVERITIES and res["operator_summary"]["text"]
    # label the asset (user-entered provenance)
    assert client.patch(f"/api/v1/runs/{rid}/label", json={"label": "Bogie frame · point P7"}).json()["label"] == "Bogie frame · point P7"
    # attention feed lists the finding as open (include info-tier so a low-damage synthetic file appears)
    att = client.get("/api/v1/attention", params={"include_info": "true"}).json()
    card = next(c for c in att["cards"] if c["result_id"] == res["id"])
    assert card["status"] == "open" and card["asset_label"] == "Bogie frame · point P7" and card["action"]
    # lifecycle: invalid, nameless, then valid; never touches the CSV
    assert client.put(f"/api/v1/results/{res['id']}/status", json={"item_id": item["id"], "status": "done"}).status_code == 400
    assert client.put(f"/api/v1/results/{res['id']}/status", json={"item_id": item["id"], "status": "investigating"}).status_code == 400
    ok = client.put(f"/api/v1/results/{res['id']}/status", json={"item_id": item["id"], "status": "investigating", "assessor": "Tan", "note": "checking"})
    assert ok.json()["saved"] and ok.json()["status"]["revision"] == 1
    closed = client.put(f"/api/v1/results/{res['id']}/status", json={"item_id": item["id"], "status": "closed", "assessor": "Tan", "expected_revision": 1})
    assert closed.status_code == 200
    att2 = client.get("/api/v1/attention", params={"include_info": "true"}).json()
    assert not any(c["result_id"] == res["id"] for c in att2["cards"])
    att3 = client.get("/api/v1/attention", params={"include_info": "true", "include_closed": "true"}).json()
    assert next(c for c in att3["cards"] if c["result_id"] == res["id"])["status"] == "closed"
    csv_text = client.get(client.post("/api/v1/exports", json={"kind": "csv", "run_id": rid}).json()["download"]).text
    assert "closed" not in csv_text and csv_text.startswith("file_id,prediction")
    # policy: defaults are illustrative; an edit is stored, validated and reversible
    pol = client.get("/api/v1/triage/policy").json()["policy"]
    assert pol["illustrative"] is True
    bad = client.put("/api/v1/triage/policy", json={"policy": {"shm": {"high_damage": "lots"}}})
    assert bad.status_code == 400
    bad2 = client.put("/api/v1/triage/policy", json={"policy": {"shm": {"nope": 1}}})
    assert bad2.status_code == 400
    upd = client.put("/api/v1/triage/policy", json={"policy": {"shm": {"medium_damage": 0.0, "medium": "high"}}, "assessor": "Tan"}).json()["policy"]
    assert upd["illustrative"] is False and upd["shm"]["medium_damage"] == 0.0
    res2 = client.get(f"/api/v1/runs/{rid}/results").json()["results"][0]
    assert res2["items"][0]["triage"]["severity"] == "high"
    assert client.put("/api/v1/triage/policy", json={"reset": True}).json()["policy"]["illustrative"] is True
    # job brief export: self-contained HTML naming the action and the lifecycle state
    b = client.post("/api/v1/exports", json={"kind": "brief", "result_id": res["id"], "item_id": item["id"]}).json()
    html = client.get(b["download"]).text
    assert "job brief" in html and "Recommended action" in html and "Closed" in html and "Bogie frame" in html
    assert "not an LTA policy document" in html
    ref = client.get("/api/v1/triage/reference").json()
    assert set(ref["checklists"]) == {"door", "acv", "rail", "shm"}


def test_lifecycle_assignee_due_csv_and_strength_order(client, tmp_path):
    rid = _shm_run(client, tmp_path)
    res = client.get(f"/api/v1/runs/{rid}/results").json()["results"][0]
    item = res["items"][0]
    bad = client.put(f"/api/v1/results/{res['id']}/status", json={"item_id": item["id"], "status": "acknowledged", "assessor": "Lim", "due": "next week"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_due"
    ok = client.put(f"/api/v1/results/{res['id']}/status", json={"item_id": item["id"], "status": "acknowledged", "assessor": "Lim",
                                                                  "assignee": "Depot team B", "due": "2026-10-01"}).json()["status"]
    assert ok["assignee"] == "Depot team B" and ok["due"] == "2026-10-01"
    card = next(c for c in client.get("/api/v1/attention", params={"include_info": "true"}).json()["cards"] if c["result_id"] == res["id"])
    assert card["assignee"] == "Depot team B" and card["due"] == "2026-10-01" and card["status_by"] == "Lim"
    assert "strength" in card
    csv_text = client.get("/api/v1/attention.csv", params={"include_info": "true"}).text
    assert csv_text.splitlines()[0].startswith("severity,severity_label,subsystem") and "Depot team B" in csv_text
    # ordering inside a tier: strongest evidence first
    feed = client.get("/api/v1/attention", params={"include_info": "true"}).json()["cards"]
    tiers = {}
    for c in feed:
        tiers.setdefault((c["priority"], c["severity"]), []).append(c.get("strength") or 0.0)
    for vals in tiers.values():
        assert vals == sorted(vals, reverse=True)


def test_rail_card_carries_heat_and_strength():
    rail_item = {"id": "Test9.csv", "file_id": "Test9.csv", "prediction": "Side II", "review_reasons": [],
                 "decision": {"stage1_fault_score": 0.76}, "side_summary": {"cars": [1, 2], "side_I_rms": [0.5, 0.6], "side_II_rms": [0.7, 1.1]}}
    c = triage.card_for("rail", rail_item, {})
    assert c["strength"] == 0.76 and c["heat"]["predicted_side"] == "Side II" and c["heat"]["side_II"] == [0.7, 1.1]
