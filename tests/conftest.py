"""测试夹具：每个测试用独立的临时 SQLite 库，通过 TestClient 驱动 ASGI。"""
from __future__ import annotations

import os
import tempfile

import pytest

# 必须在导入 app.config 之前指定临时数据库
_tmp_dir = tempfile.mkdtemp(prefix="bs_test_")
_DB_PATH = os.path.join(_tmp_dir, "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import models  # noqa: E402
from app.db.session import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepared_db():
    init_db()
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    with engine.begin() as conn:
        conn.execute(models.CalcRecord.__table__.delete())
        conn.execute(models.BatchRecord.__table__.delete())
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


BASE = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.03, "q": 0.01, "sigma": 0.25}
