"""历史记录的持久化与条件查询。"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BatchRecord, CalcRecord


def _json_safe(value: Any) -> Any:
    """JSON 列不接受 NaN/Infinity（PG 直接报错），统一转成字符串。"""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def save_calc_record(
    session: Session,
    *,
    endpoint: str,
    success: bool,
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    batch_id: str | None = None,
    item_index: int | None = None,
    commit: bool = True,
) -> CalcRecord:
    params = params or {}
    is_call = params.get("is_call")
    record = CalcRecord(
        endpoint=endpoint,
        success=success,
        S=params.get("S"),
        K=params.get("K"),
        T=params.get("T"),
        r=params.get("r"),
        q=params.get("q"),
        sigma=params.get("sigma"),
        market_price=params.get("market_price"),
        option_type=(("call" if is_call else "put") if is_call is not None else None),
        result=_json_safe(result) if success and result is not None else None,
        error_code=(error or {}).get("code") if error else None,
        error_field=(error or {}).get("field") if error else None,
        error_message=(error or {}).get("message") if error else None,
        batch_id=batch_id,
        item_index=item_index,
    )
    session.add(record)
    if commit:
        session.commit()
    else:
        session.flush()  # 生成主键 id，供批量结果引用
    return record


def save_batch_summary(
    session: Session, *, total: int, succeeded: int, failed: int, commit: bool = False
) -> BatchRecord:
    batch = BatchRecord(total=total, succeeded=succeeded, failed=failed)
    session.add(batch)
    session.flush()  # 拿到 batch.id
    if commit:
        session.commit()
    return batch


def _parse_iso(value: str, field: str) -> datetime:
    from datetime import timezone
    txt = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as exc:
        from ..errors import InvalidParameterError
        raise InvalidParameterError(
            f"参数 {field} 需要 ISO-8601 时间（如 2026-09-18T00:00:00Z），实际为 {value!r}",
            field=field,
        ) from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def query_history(
    session: Session,
    *,
    endpoint: str | None = None,
    option_type: str | None = None,
    success: bool | None = None,
    batch_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CalcRecord], int]:
    stmt = select(CalcRecord)
    count_stmt = select(CalcRecord)
    filters = []
    if endpoint:
        filters.append(CalcRecord.endpoint == endpoint)
    if option_type:
        filters.append(CalcRecord.option_type == option_type)
    if success is not None:
        filters.append(CalcRecord.success == success)
    if batch_id:
        filters.append(CalcRecord.batch_id == batch_id)
    if start:
        filters.append(CalcRecord.created_at >= start)
    if end:
        filters.append(CalcRecord.created_at <= end)
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    from sqlalchemy import func
    total = session.execute(
        select(func.count()).select_from(count_stmt.subquery())
    ).scalar_one()

    rows = list(session.execute(
        stmt.order_by(CalcRecord.created_at.desc(), CalcRecord.id)
        .limit(limit).offset(offset)
    ).scalars().all())
    return rows, total
