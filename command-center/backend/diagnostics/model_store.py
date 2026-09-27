"""Load frozen, locally built model bundles. Estimator files are verified
against the SHA-256 recorded in the bundle before unpickling; uploads can
never supply model objects."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import joblib

from .common import ARTIFACT_DIR, load_json, sha256_file


class ModelUnavailable(Exception):
    pass


def bundle_dir(task: str) -> Path:
    return ARTIFACT_DIR / task


@lru_cache(maxsize=8)
def load_model(task: str) -> dict:
    p = bundle_dir(task) / "model.json"
    if not p.exists():
        raise ModelUnavailable(f"No frozen {task} model found at {p}. Run training/train_all.py.")
    m = load_json(p)
    if m.get("task") != task:
        raise ModelUnavailable(f"Model bundle at {p} is for task {m.get('task')!r}, not {task!r}.")
    return m


_EST: dict[tuple[str, str], object] = {}


def load_estimator(model: dict, name: str):
    key = (model["version"], name)
    if key in _EST:
        return _EST[key]
    spec = model["estimators"][name]
    path = bundle_dir(model["task"]) / spec["file"]
    if not path.exists():
        raise ModelUnavailable(f"Estimator file missing: {path}")
    if sha256_file(path) != spec["sha256"]:
        raise ModelUnavailable(f"Estimator file {path.name} does not match its recorded hash; refusing to load.")
    est = joblib.load(path)
    # Fixed accumulation order makes repeated uploads bit-for-bit reproducible.
    # This changes execution parallelism, not learned trees or class thresholds.
    if "n_jobs" in est.get_params():
        est.set_params(n_jobs=1)
    _EST[key] = est
    return est


def model_status() -> dict:
    out = {}
    for t in ("door", "acv", "rail", "shm"):
        try:
            m = load_model(t)
            out[t] = {"available": True, "version": m["version"], "method": m.get("method_name")}
        except ModelUnavailable as e:
            out[t] = {"available": False, "reason": str(e)}
    return out
