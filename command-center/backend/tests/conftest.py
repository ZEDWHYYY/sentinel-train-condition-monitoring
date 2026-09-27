import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SENTINEL_STORE", tempfile.mkdtemp(prefix="sentinel-test-store-"))

from diagnostics.common import DATASET_ROOT  # noqa: E402

requires_data = pytest.mark.skipif(not DATASET_ROOT.exists(), reason="official PS3 datasets not present")


@pytest.fixture(scope="session")
def data_root() -> Path:
    return DATASET_ROOT


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import main
    with TestClient(main.app) as c:
        yield c
