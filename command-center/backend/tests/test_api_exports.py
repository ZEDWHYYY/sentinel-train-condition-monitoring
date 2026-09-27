"""API contract, persistence, isolation and export tests (T11, T17-T18, T21-T23, T35)."""
import io
import time
import zipfile

from .conftest import requires_data
from diagnostics import exports


def wait(client, rid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        r = client.get(f"/api/v1/runs/{rid}").json()
        if r["state"] not in ("queued", "running"):
            return r
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def run_path(client, path):
    r = client.post("/api/v1/runs", json={}).json()
    fs = client.post(f"/api/v1/runs/{r['id']}/local-path", json={"path": str(path)}).json()["files"]
    a = client.post(f"/api/v1/runs/{r['id']}/analyze", json={"idempotency_key": r["id"]}).json()
    return a["runs"][0], fs


def test_T23_default_app_starts_no_legacy(client):
    import sys
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    for mod in ("sentinel", "torch", "three"):
        assert mod not in sys.modules


def test_T11_unsupported_file_is_actionable(client, tmp_path):
    r = client.post("/api/v1/runs", json={}).json()
    up = client.post(f"/api/v1/runs/{r['id']}/files", files=[("files", ("notes.md", b"# hi", "text/markdown"))]).json()
    f = up["files"][0]
    assert f["status"] == "unreadable" and "Unsupported" in f["recognition"]["reason"]
    res = client.post(f"/api/v1/runs/{r['id']}/analyze", json={})
    assert res.status_code == 400 and res.json()["error"]["code"] == "nothing_to_analyze"


def test_path_traversal_name_is_sanitised(client):
    r = client.post("/api/v1/runs", json={}).json()
    up = client.post(f"/api/v1/runs/{r['id']}/files", files=[("files", ("../../evil.csv", b"1.0\n2.0\n", "text/csv"))]).json()
    assert up["files"][0]["original_name"] == "evil.csv"


def test_T17_serializers_and_validation():
    door_res = [("Test.csv", {"items": [{"t0": 2, "start_time": "b", "end_time": "c", "prediction": "Normal"},
                                         {"t0": 1, "start_time": "a", "end_time": "b", "prediction": "Abnormal resistance"}]})]
    rows = exports.rows_for("door", door_res)
    assert [r["start_time"] for r in rows] == ["a", "b"]
    assert exports.to_csv_bytes("door", rows).decode().splitlines()[0] == "start_time,end_time,prediction"
    assert exports.validate_rows("rail", [{"file_id": "a.csv", "prediction": "uncertain"}])
    assert exports.validate_rows("shm", [{"file_id": "a.csv", "prediction": "nan"}])
    assert exports.validate_rows("rail", [{"file_id": "a.csv", "prediction": "Normal"}, {"file_id": "a.csv", "prediction": "Normal"}])
    acv_rows = exports.rows_for("acv", [("case.xlsx", {"items": [{"ranked_cars": ["03", "01", "02"]}]})])
    assert acv_rows[0]["ranked_cars"] == "03|01|02"


def test_T18_zip_root_only():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub/door_predictions.csv", "x")
        z.writestr("notes.txt", "x")
    errs = exports.validate_zip(buf.getvalue())
    assert len(errs) >= 2


@requires_data
def test_T25_T21_T22_T35_end_to_end(client, data_root):
    rid, _ = run_path(client, data_root / "SHM" / "Test" / "test01.csv")
    run = wait(client, rid)
    assert run["state"] == "completed"
    res = client.get(f"/api/v1/runs/{rid}/results").json()["results"][0]
    ev = client.get(f"/api/v1/results/{res['id']}/evidence").json()["charts"]
    assert ev and all(c["unit"] and c["source"] for c in ev)
    # review persistence + conflict
    item = res["items"][0]["id"]
    s = client.put(f"/api/v1/results/{res['id']}/review", json={"item_id": item, "assessment": "disagrees", "note": "n"})
    assert s.json()["saved"]
    c = client.put(f"/api/v1/results/{res['id']}/review", json={"item_id": item, "assessment": "agrees", "expected_revision": 0})
    assert c.status_code == 409
    full = client.get(f"/api/v1/results/{res['id']}").json()
    assert full["reviews"][-1]["assessment"] == "disagrees"
    # review never changes the machine prediction or CSV
    e = client.post("/api/v1/exports", json={"kind": "csv", "run_id": rid}).json()
    csv_text = client.get(e["download"]).text
    assert csv_text.splitlines()[1].startswith("test01.csv,") and "disagree" not in csv_text
    # exact repeat detected
    rid2, fs2 = run_path(client, data_root / "SHM" / "Test" / "test01.csv")
    assert fs2[0]["repeats"], "repeat of identical content should be surfaced"
    wait(client, rid2)
    r2 = client.get(f"/api/v1/runs/{rid2}/results").json()["results"][0]
    assert r2["repeat_of"] == res["id"]
    # isolation: second run has its own review list
    assert client.get(f"/api/v1/results/{r2['id']}").json()["reviews"] == []
    # priority requires provenance
    bad = client.put(f"/api/v1/results/{res['id']}/priority", json={"item_id": item, "level": "urgent_assessment"})
    assert bad.status_code == 400


@requires_data
def test_bundle_blocks_incomplete_coverage(client, data_root):
    rid, _ = run_path(client, data_root / "SHM" / "Test" / "test02.csv")
    wait(client, rid)
    r = client.post("/api/v1/exports", json={"kind": "bundle", "runs": {"shm": rid}})
    assert r.status_code == 422
    assert any("missing official test file" in e for e in r.json()["error"]["errors"])


def test_hosted_server_reads_local_files_only_inside_its_dataset_folder(client, monkeypatch, tmp_path):
    import api_v1
    dataset = tmp_path / "datasets"
    (dataset / "SHM").mkdir(parents=True)
    inside = dataset / "SHM" / "s.csv"
    inside.write_text("\n".join(str((i % 7) - 3.0) for i in range(500)))
    secret = tmp_path / "secret.csv"
    secret.write_text("key,value\ntoken,abc\n")
    (dataset / "SHM" / "link.csv").symlink_to(secret)
    monkeypatch.setattr(api_v1, "DATASET_ROOT", dataset)
    monkeypatch.setattr(api_v1, "LOCAL_PATHS", "dataset")
    rid = client.post("/api/v1/runs", json={}).json()["id"]
    for outside in (secret, dataset / ".." / "secret.csv", dataset / "SHM" / "link.csv", tmp_path / "missing.csv"):
        response = client.post(f"/api/v1/runs/{rid}/local-path", json={"path": str(outside)})
        assert response.status_code == 403, outside
        assert response.json()["error"]["code"] == "path_not_allowed"
    folder = client.post(f"/api/v1/runs/{rid}/local-path", json={"path": str(dataset / "SHM")})
    assert folder.status_code == 200
    assert [f["original_name"] for f in folder.json()["files"]] == ["s.csv"]


def test_prediction_download_refuses_unfinished_or_unknown_runs(client):
    draft = client.post("/api/v1/runs", json={}).json()["id"]
    response = client.get(f"/api/v1/runs/{draft}/predictions.csv")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_complete"
    assert client.get("/api/v1/runs/run_missing/predictions.csv").status_code == 404


def test_priority_and_idempotent_analyze(client, tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("\n".join(str((i % 7) - 3.0) for i in range(500)))
    r = client.post("/api/v1/runs", json={}).json()
    client.post(f"/api/v1/runs/{r['id']}/local-path", json={"path": str(p)})
    a = client.post(f"/api/v1/runs/{r['id']}/analyze", json={"idempotency_key": "abc"}).json()
    b = client.post(f"/api/v1/runs/{r['id']}/analyze", json={"idempotency_key": "abc"}).json()
    assert b.get("duplicate_request") and a["runs"][0] in b["runs"]
    wait(client, a["runs"][0])


@requires_data
def test_mixed_upload_each_subsystem_gets_its_own_files(client, data_root, tmp_path):
    """One upload with two subsystems is split into two analyses; each must analyse only its own files with its own
    parser. Regression: the first analysis was queued before the other group's files were moved, so the worker ran
    them through the wrong parser and the second analysis finished with no results."""
    import shutil
    shutil.copy(data_root / "SHM" / "Train" / "train01.csv", tmp_path / "seg.csv")
    shutil.copy(data_root / "ACV" / "Train" / "acv_case_01.xlsx", tmp_path / "case.xlsx")
    r = client.post("/api/v1/runs", json={}).json()
    client.post(f"/api/v1/runs/{r['id']}/local-path", json={"path": str(tmp_path)})
    runs = client.post(f"/api/v1/runs/{r['id']}/analyze", json={"idempotency_key": r["id"]}).json()["runs"]
    assert len(runs) == 2
    for rid in runs:
        run = wait(client, rid)
        assert run["state"] == "completed", (run["subsystem"], [(f["original_name"], f["error"]) for f in run["files"]])
        res = client.get(f"/api/v1/runs/{rid}/results").json()["results"]
        assert len(res) == 1, (run["subsystem"], [(f["original_name"], f["status"], f["error"]) for f in run["files"]])
