"""pytest 全局配置：把数据库切到临时 SQLite 文件，再导入应用。"""
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="bs_pricing_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
