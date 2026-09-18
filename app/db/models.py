"""ORM 模型。

* :class:`CalcRecord` 每次核算请求一条（定价 / 希腊值 / 隐含波动率，
  以及批量中的每一组各一条），批量项通过 ``batch_id`` 关联到批量汇总。
* :class:`BatchRecord` 一次批量请求一条汇总。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class BatchRecord(Base):
    __tablename__ = "batch_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)

    items: Mapped[list["CalcRecord"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="CalcRecord.item_index"
    )


class CalcRecord(Base):
    __tablename__ = "calc_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    endpoint: Mapped[str] = mapped_column(String(32), index=True)  # price/greeks/iv/batch_price
    success: Mapped[bool] = mapped_column(index=True)

    # 合约参数（失败时尽量保留已解析到的部分）
    S: Mapped[float | None] = mapped_column(Float, nullable=True)
    K: Mapped[float | None] = mapped_column(Float, nullable=True)
    T: Mapped[float | None] = mapped_column(Float, nullable=True)
    r: Mapped[float | None] = mapped_column(Float, nullable=True)
    q: Mapped[float | None] = mapped_column(Float, nullable=True)
    sigma: Mapped[float | None] = mapped_column(Float, nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    market_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 结果 / 错误
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 批量关联
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("batch_records.id"), nullable=True, index=True
    )
    item_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    batch: Mapped["BatchRecord | None"] = relationship(back_populates="items")
