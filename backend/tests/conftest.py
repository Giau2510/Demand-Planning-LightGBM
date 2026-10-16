import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DF_DISABLE_SCHEDULER"] = "1"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DF_DATA_DIR", str(tmp_path / "data"))
    # never read/write the real per-user bootstrap file from tests
    monkeypatch.setenv("DF_STORAGE_CONFIG", str(tmp_path / "bootstrap" / "storage.json"))
    for k in ("DF_LOGS_DIR", "DF_BACKUPS_DIR", "DF_REPORTS_DIR"):
        monkeypatch.delenv(k, raising=False)
    from app import db, timeutil
    from app.bq import connector, secret_store
    # never read or write the real Windows Credential Manager from tests (the explicit round-trip test uses its own
    # WindowsCredentialStore instance)
    secret_store.set_store(secret_store.MemoryStore())
    db.migrate()
    yield tmp_path / "data"
    timeutil.set_now_override(None)
    connector.set_client_factory(None)
    connector.set_auth_probe(None)
    secret_store.set_store(None)


@pytest.fixture
def fast_model():
    """Small, fast model/backtest settings so ML tests run in seconds."""
    from app import settings_service as ss
    ss.update("model", {"num_boost_round": 40, "backtest_folds": 2, "backtest_horizon_days": 7,
                        "backtest_step_days": 7, "min_total_history_days": 42})
    ss.update("quality", {"min_backtest_points": 20})


@pytest.fixture
def small_demo(fast_model):
    from app.data.demo import create_demo_batch
    return create_demo_batch(days=150, n_skus=8, seed=3)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.api import background
    from app.main import create_app
    background.SYNC_MODE = True
    with TestClient(create_app(), headers={"X-DF-Client": "web"}) as c:
        yield c
    background.SYNC_MODE = False
