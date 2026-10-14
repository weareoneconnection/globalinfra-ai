"""Pytest bootstrap for services/api.

Sets up an isolated SQLite database *before* ``app.main`` (and therefore
``app.config.settings``) is imported, so these tests never touch a real
Postgres instance and never collide with a developer's local
``globalinfra.db``. Settings are read once at import time
(``settings = Settings()`` in ``app/config.py``), so the environment
variables below must be set before the first ``import app...`` happens.
"""
import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

TEST_DB_PATH = API_DIR / "test_globalinfra.db"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("REQUIRE_API_KEY", "false")
# The whole suite shares one TestClient host; keep the per-minute limiter out
# of the way (its behaviour is tested explicitly in test_phase7.py).
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """A TestClient shared across the whole test session.

    The app's lifespan hook (table creation + demo seeding) runs once on
    entry, exactly like a real deployment's startup, which is what lets
    ``test_api.py`` exercise the seeded demo case end to end.
    """
    with TestClient(app) as c:
        yield c
