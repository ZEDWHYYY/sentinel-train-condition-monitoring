import datetime as _dt
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "command-center" / "backend"))

from diagnostics.common import ARTIFACT_DIR, DATASET_ROOT, sha256_file  # noqa: E402

DATA = DATASET_ROOT
REPORTS = ROOT / "reports"


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def fingerprint(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(map(Path, paths)):
        h.update(p.name.encode())
        h.update(sha256_file(p).encode())
    return h.hexdigest()


__all__ = ["ROOT", "DATA", "REPORTS", "ARTIFACT_DIR", "now", "fingerprint"]
