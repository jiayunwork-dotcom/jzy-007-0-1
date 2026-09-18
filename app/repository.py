"""核算记录的写入与条件查询。"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import PricingRecord


def save_record(session: Session, **fields) -> PricingRecord:
    record = PricingRecord(**fields)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def query_records(
    session: Session,
    *,
    endpoint: Optional[str] = None,
    option_type: Optional[str] = None,
    status: Optional[str] = None,
    batch_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[PricingRecord], int]:
    conditions = []
    if endpoint:
        conditions.append(PricingRecord.endpoint == endpoint)
    if option_type:
        conditions.append(PricingRecord.option_type == option_type)
    if status:
        conditions.append(PricingRecord.status == status)
    if batch_id:
        conditions.append(PricingRecord.batch_id == batch_id)

    total = session.scalar(
        select(func.count()).select_from(PricingRecord).where(*conditions)
    )
    rows = session.scalars(
        select(PricingRecord)
        .where(*conditions)
        .order_by(PricingRecord.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), int(total or 0)


def record_to_dict(rec: PricingRecord) -> dict:
    return {
        "id": rec.id,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "endpoint": rec.endpoint,
        "status": rec.status,
        "batch_id": rec.batch_id,
        "batch_index": rec.batch_index,
        "option_type": rec.option_type,
        "spot": rec.spot,
        "strike": rec.strike,
        "expiry": rec.expiry,
        "rate": rec.rate,
        "dividend": rec.dividend,
        "sigma": rec.sigma,
        "market_price": rec.market_price,
        "price": rec.price,
        "d1": rec.d1,
        "d2": rec.d2,
        "delta": rec.delta,
        "gamma": rec.gamma,
        "vega": rec.vega,
        "theta": rec.theta,
        "rho": rec.rho,
        "implied_vol": rec.implied_vol,
        "error_param": rec.error_param,
        "error_message": rec.error_message,
    }
