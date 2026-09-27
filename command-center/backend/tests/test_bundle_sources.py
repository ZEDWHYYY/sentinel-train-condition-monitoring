"""Official-input provenance: synthetic fixtures can exercise software, never bundle coverage."""
import hashlib
import io
import zipfile

import pytest

from diagnostics import exports
from diagnostics.common import REPO_ROOT, sha256_file
from .conftest import requires_data
from .test_api_exports import run_path, wait


@requires_data
@pytest.mark.parametrize("sub", ["door", "acv", "rail", "shm"])
def test_download_is_exact_provided_test_input(client, sub):
    p = exports.official_test_paths()[sub][0]
    response = client.get(f"/api/v1/samples/{sub}")
    assert response.status_code == 200
    assert response.headers["x-sentinel-source"] == "official-test-input"
    assert p.name in response.headers["content-disposition"]
    assert hashlib.sha256(response.content).hexdigest() == sha256_file(p)


def test_missing_dataset_never_substitutes_dummy_download(client, monkeypatch, tmp_path):
    monkeypatch.setattr(exports, "DATASET_ROOT", tmp_path)
    response = client.get("/api/v1/samples/door")
    assert response.status_code == 503
    assert "No synthetic substitute" in response.json()["error"]["suggestion"]


def test_bundle_zip_holds_ordinary_files_anyone_can_read(monkeypatch, tmp_path):
    monkeypatch.setattr(exports, "official_test_hashes", lambda: {"shm": {"a.csv": "h"}})
    blob, _ = exports.build_bundle({"shm": [("a.csv", {"items": [{"prediction": 0.5}]})]}, {"shm": {"a.csv": "h"}})
    for archive in (zipfile.ZipFile(io.BytesIO(blob)), zipfile.ZipFile(REPO_ROOT / "prediction_exports" / "predictions.zip")):
        for info in archive.infolist():
            assert info.external_attr >> 16 == 0o100644, (info.filename, oct(info.external_attr >> 16))


def test_browsable_prediction_folder_matches_exported_zip():
    folder = REPO_ROOT / "prediction_exports" / "predictions"
    with zipfile.ZipFile(REPO_ROOT / "prediction_exports" / "predictions.zip") as exported:
        assert sorted(p.name for p in folder.iterdir()) == sorted(exported.namelist()) == [
            "acv_predictions.csv", "door_predictions.csv", "rail_predictions.csv", "shm_predictions.csv"]
        for name in exported.namelist():
            assert (folder / name).read_bytes() == exported.read(name), name


@pytest.mark.parametrize("sub", ["door", "acv", "rail", "shm"])
def test_official_names_without_matching_content_are_rejected(sub):
    expected = {"Test.csv": "official-content-digest"}
    assert exports.official_source_errors(sub, ["Test.csv"], {}, expected)
    assert exports.official_source_errors(sub, ["Test.csv"], {"Test.csv": "dummy-content-digest"}, expected)
    assert not exports.official_source_errors(sub, ["Test.csv"], expected, expected)
    assert exports.official_source_errors(sub, ["Test.csv", "Test.csv"], expected, expected)
    assert exports.official_source_errors(sub, ["Test.csv"], expected, {})


def test_reference_fingerprint_cache_refreshes_for_changed_content(monkeypatch, tmp_path):
    monkeypatch.setattr(exports, "DATASET_ROOT", tmp_path)
    p = tmp_path / "Door" / "Test.csv"
    p.parent.mkdir()
    p.write_bytes(b"first")
    first = exports.official_test_hashes()["door"]["Test.csv"]
    p.write_bytes(b"other")
    assert exports.official_test_hashes()["door"]["Test.csv"] != first


def upload_door(client, source, name):
    rid = client.post("/api/v1/runs", json={"subsystem": "door"}).json()["id"]
    with source.open("rb") as f:
        response = client.post(f"/api/v1/runs/{rid}/files", files={"files": (name, f, "text/csv")})
    assert response.status_code == 200
    assert response.json()["files"][0]["status"] == "ready"
    assert client.post(f"/api/v1/runs/{rid}/analyze", json={}).status_code == 200
    assert wait(client, rid)["state"] == "completed"
    return rid


@requires_data
@pytest.mark.parametrize("kind,name", [("synthetic", "healthy.csv"), ("synthetic", "Test.csv"), ("training", "Test.csv")])
def test_bundle_rejects_dummy_or_training_even_when_renamed(client, data_root, kind, name):
    p = REPO_ROOT / "tests/fixtures/door/healthy.csv" if kind == "synthetic" else data_root / "Door/Train.csv"
    rid = upload_door(client, p, name)
    response = client.post("/api/v1/exports", json={"kind": "bundle", "runs": {"door": rid}})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "bundle_invalid"
    assert "official test" in " ".join(response.json()["error"]["errors"])
    candidates = client.get("/api/v1/prediction_exports/inventory").json()["candidates"]["door"]
    assert rid not in {c["id"] for c in candidates}


@requires_data
def test_real_door_upload_is_verified_and_missing_reference_blocks_export(client, data_root, monkeypatch, tmp_path):
    rid = upload_door(client, data_root / "Door/Test.csv", "Test.csv")
    response = client.post("/api/v1/exports", json={"kind": "bundle", "runs": {"door": rid}})
    assert response.status_code == 200, response.text
    coverage = response.json()["manifest"]["coverage"]["door"]
    assert coverage["source_verification"] == "filename_and_sha256"
    assert coverage["source_files"] == {"Test.csv": sha256_file(data_root / "Door/Test.csv")}
    with zipfile.ZipFile(io.BytesIO(client.get(response.json()["download"]).content)) as z:
        with zipfile.ZipFile(REPO_ROOT / "prediction_exports/predictions.zip") as old:
            assert z.read("door_predictions.csv") == old.read("door_predictions.csv")
    candidates = client.get("/api/v1/prediction_exports/inventory").json()["candidates"]["door"]
    assert rid in {c["id"] for c in candidates}
    monkeypatch.setattr(exports, "DATASET_ROOT", tmp_path)
    assert not client.get("/api/v1/prediction_exports/inventory").json()["candidates"]["door"]
    blocked = client.post("/api/v1/exports", json={"kind": "bundle", "runs": {"door": rid}})
    assert blocked.status_code == 422
    assert "unavailable" in " ".join(blocked.json()["error"]["errors"])


@requires_data
def test_complete_official_batches_export_only_original_prediction_csvs(client):
    selected = {}
    counts = {"door": 1, "acv": 1, "rail": 68, "shm": 16}
    for sub, paths in exports.official_test_paths().items():
        assert len(paths) == counts[sub]
        rid, _ = run_path(client, paths[0] if sub == "door" else paths[0].parent)
        assert wait(client, rid)["state"] == "completed"
        selected[sub] = rid
    response = client.post("/api/v1/exports", json={"kind": "bundle", "runs": selected})
    assert response.status_code == 200, response.text
    manifest = response.json()["manifest"]
    assert {s: len(c["source_files"]) for s, c in manifest["coverage"].items()} == counts
    blob = client.get(response.json()["download"]).content
    with zipfile.ZipFile(io.BytesIO(blob)) as z, zipfile.ZipFile(REPO_ROOT / "prediction_exports/predictions.zip") as old:
        assert sorted(z.namelist()) == sorted(exports.CSV_NAMES.values())
        for name in z.namelist():
            assert z.read(name) == old.read(name), name
