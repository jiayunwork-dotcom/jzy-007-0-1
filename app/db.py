"""持久化层：SQLAlchemy 引擎、会话与核算记录表。

- 默认 SQLite（本地开发与测试），Docker Compose 注入 PostgreSQL；
- 每次请求一个会话（get_session 依赖），写操作各自提交，
  并发请求之间互不共享会话，历史记录不会串扰。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config


def _make_engine(url: str):
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            # 内存库全进程共享一个连接，供测试使用
            return create_engine(url, connect_args=connect_args, poolclass=StaticPool)
        return create_engine(url, connect_args=connect_args)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class PricingRecord(Base):
    """一次核算请求与结果的完整留痕。"""

    __tablename__ = "pricing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    endpoint: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok / error / infeasible
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    batch_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 请求参数
    option_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    spot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    strike: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expiry: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dividend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sigma: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 核算结果
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    d1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    d2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gamma: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vega: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    theta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rho: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_vol: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 失败留痕
    error_param: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def init_db(retries: int = 10, delay: float = 1.0) -> None:
    """建表；依赖的数据库尚未就绪时按次重试（容器编排启动竞态）。"""
    for attempt in range(retries):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


def get_session():
    """FastAPI 依赖：每请求一个会话，用完即关。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
