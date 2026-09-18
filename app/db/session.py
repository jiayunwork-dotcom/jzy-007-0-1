"""数据库引擎与会话管理。

默认 SQLite（便于单机部署与测试），Docker Compose 下通过
``DATABASE_URL`` 切换到 PostgreSQL。SQLite 开启 WAL 与 busy timeout，
降低并发写入时的锁冲突。
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings


def _make_engine() -> Engine:
    url = settings.database_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30
    engine = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)
    if url.startswith("sqlite") and url != "sqlite://":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """建表（幂等）。在应用启动时调用。"""
    # SQLite 文件库时确保目录存在
    url = settings.database_url
    if url.startswith("sqlite:///"):
        import os
        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
    from . import models  # noqa: F401  确保模型已注册
    models.Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话，出错回滚。"""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> bool:
    """供健康检查使用的连通性探测。"""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
