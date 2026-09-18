"""HTTP 路由：定价、希腊值、隐含波动率、批量、历史、配置、算例、健康检查。

路由函数声明为普通 ``def``（非 async def），SQLAlchemy 这类阻塞式调用
会被 FastAPI 放到线程池执行，多个请求各自持有独立的 DB 会话，
彼此互不共享可变状态。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import services
from ..config import settings
from ..db import repository as repo
from ..db.models import CalcRecord
from ..db.session import get_session
from ..errors import InvalidParameterError, NotFoundError, ServiceError
from ..pricing import validation as valid
from .schemas import RawBatchBody, RawBody

router = APIRouter()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _raw_dict(request_data: RawBody) -> dict[str, Any]:
    return request_data.model_dump(exclude_unset=True)


def _error_payload(exc: ServiceError) -> dict[str, Any]:
    return exc.to_body()["error"]


def _best_effort_params(raw: Any) -> dict[str, Any] | None:
    """校验失败时尽量抽出可辨认的合约字段，供历史审计。"""
    import math
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("S", "K", "T", "r", "q", "sigma", "market_price"):
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            out[key] = float(value)
    direction = raw.get("option_type")
    if isinstance(direction, str) and direction.strip().lower() in ("call", "c", "put", "p"):
        out["is_call"] = direction.strip().lower() in ("call", "c")
    elif isinstance(raw.get("is_call"), bool):
        out["is_call"] = raw["is_call"]
    return out or None


def _record_one(
    session: Session,
    endpoint: str,
    params: dict[str, Any] | None,
    ok: bool,
    result: dict[str, Any] | None,
    exc: ServiceError | None,
    *,
    batch_id: str | None = None,
    item_index: int | None = None,
    commit: bool = True,
) -> CalcRecord:
    return repo.save_calc_record(
        session,
        endpoint=endpoint,
        success=ok,
        params=params,
        result=result,
        error=(_error_payload(exc) if exc else None),
        batch_id=batch_id,
        item_index=item_index,
        commit=commit,
    )


def _parse_request(request: Request, model: type[RawBody] | type[RawBatchBody]):
    try:
        payload = request.state.json_body
    except AttributeError:
        raise InvalidParameterError("请求体必须是 JSON 对象", field="body")
    try:
        return model.model_validate(payload)
    except ValidationError:
        if model is RawBatchBody:
            raise InvalidParameterError(
                "请求体必须形如 {\"items\": [ {...}, {...} ]}，且 items 为对象数组",
                field="items",
            )
        raise InvalidParameterError("请求体必须是 JSON 对象", field="body")


# ---------------------------------------------------------------------------
# 单张定价 / 希腊值
# ---------------------------------------------------------------------------

@router.post("/price")
def price(request: Request, session: Session = Depends(get_session)):
    parsed = _parse_request(request, RawBody)
    raw = _raw_dict(parsed)
    params: dict[str, Any] | None = None
    try:
        params = valid.validate_pricing_request(raw)
        body = services.price_body(params)
        record = _record_one(session, "price", params, True, body, None)
        body["record_id"] = record.id
        return body
    except ServiceError as exc:
        _record_one(session, "price", params or _best_effort_params(raw),
                    False, None, exc)
        raise


@router.post("/greeks")
def greeks(request: Request, session: Session = Depends(get_session)):
    parsed = _parse_request(request, RawBody)
    raw = _raw_dict(parsed)
    params: dict[str, Any] | None = None
    try:
        params = valid.validate_pricing_request(raw)
        body = services.greeks_body(params)
        record = _record_one(session, "greeks", params, True, body, None)
        body["record_id"] = record.id
        return body
    except ServiceError as exc:
        _record_one(session, "greeks", params or _best_effort_params(raw),
                    False, None, exc)
        raise


# ---------------------------------------------------------------------------
# 隐含波动率
# ---------------------------------------------------------------------------

@router.post("/implied-vol")
def implied_vol(request: Request, session: Session = Depends(get_session)):
    parsed = _parse_request(request, RawBody)
    raw = _raw_dict(parsed)
    params: dict[str, Any] | None = None
    try:
        params = valid.validate_iv_request(raw)
        body = services.iv_body(params)
        record = _record_one(session, "implied_vol", params, True, body, None)
        body["record_id"] = record.id
        return body
    except ServiceError as exc:
        _record_one(session, "implied_vol", params or _best_effort_params(raw),
                    False, None, exc)
        raise


# ---------------------------------------------------------------------------
# 批量定价
# ---------------------------------------------------------------------------

@router.post("/batch-price")
def batch_price(request: Request, session: Session = Depends(get_session)):
    parsed = _parse_request(request, RawBatchBody)

    batch = repo.save_batch_summary(session, total=0, succeeded=0, failed=0)
    results: list[dict[str, Any]] = []
    succeeded = failed = 0

    for index, item_raw in enumerate(parsed.items, start=1):
        item_params: dict[str, Any] | None = None
        entry: dict[str, Any] = {"index": index}
        try:
            if not isinstance(item_raw, dict):
                raise InvalidParameterError(
                    "该组参数必须是 JSON 对象",
                    field=f"items[{index}]",
                )
            item_params = valid.validate_pricing_request(item_raw)
            body = services.price_body(item_params)
            entry["ok"] = True
            entry["result"] = body
            record = repo.save_calc_record(
                session, endpoint="batch_price", success=True,
                params=item_params, result=body,
                batch_id=batch.id, item_index=index, commit=False,
            )
            body["record_id"] = record.id
            succeeded += 1
        except ServiceError as exc:
            payload = _error_payload(exc)
            stored_field = payload.get("field")
            # 对外响应指明是第几组：给字段加上组序号前缀，消息也标注组号；
            # 库内只存原始字段名（组序号已由 item_index 列承载）。
            payload["message"] = f"第 {index} 组：{payload['message']}"
            if stored_field and not stored_field.startswith(f"items[{index}]"):
                payload["field"] = f"items[{index}].{stored_field}"
            payload["item_index"] = index
            entry["ok"] = False
            entry["error"] = payload
            repo.save_calc_record(
                session, endpoint="batch_price", success=False,
                params=item_params or _best_effort_params(item_raw),
                error={**payload, "field": stored_field},
                batch_id=batch.id, item_index=index, commit=False,
            )
            failed += 1
        results.append(entry)

    batch.total = len(parsed.items)
    batch.succeeded = succeeded
    batch.failed = failed
    session.commit()

    return {
        "batch_id": batch.id,
        "total": batch.total,
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 历史查询
# ---------------------------------------------------------------------------

def _serialize_record(row: CalcRecord) -> dict[str, Any]:
    return {
        "record_id": row.id,
        "created_at": row.created_at.replace(tzinfo=None).isoformat() + "Z",
        "endpoint": row.endpoint,
        "success": row.success,
        "params": {
            "S": row.S, "K": row.K, "T": row.T, "r": row.r, "q": row.q,
            "sigma": row.sigma, "option_type": row.option_type,
            "market_price": row.market_price,
        },
        "result": row.result,
        "error": (
            None if row.error_code is None
            else {
                "code": row.error_code,
                "field": row.error_field,
                "message": row.error_message,
            }
        ),
        "batch_id": row.batch_id,
        "item_index": row.item_index,
    }


@router.get("/history")
def history(
    session: Session = Depends(get_session),
    endpoint: str | None = Query(None, description="price/greeks/implied_vol/batch_price"),
    option_type: str | None = Query(None, description="call/put"),
    success: bool | None = Query(None),
    batch_id: str | None = Query(None),
    start: str | None = Query(None, description="ISO-8601 起始时间（含）"),
    end: str | None = Query(None, description="ISO-8601 截止时间（含）"),
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
):
    if option_type is not None and option_type.lower() not in ("call", "put"):
        raise InvalidParameterError("option_type 只支持 call 或 put", field="option_type")
    if endpoint is not None and endpoint not in (
        "price", "greeks", "implied_vol", "batch_price"
    ):
        raise InvalidParameterError(
            "endpoint 只支持 price/greeks/implied_vol/batch_price", field="endpoint"
        )
    if limit > settings.history_max_limit:
        raise InvalidParameterError(
            f"limit 最大为 {settings.history_max_limit}", field="limit"
        )
    start_dt = repo._parse_iso(start, "start") if start else None
    end_dt = repo._parse_iso(end, "end") if end else None

    rows, total = repo.query_history(
        session,
        endpoint=endpoint,
        option_type=(option_type.lower() if option_type else None),
        success=success,
        batch_id=batch_id,
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_serialize_record(r) for r in rows],
    }


@router.get("/history/records/{record_id}")
def get_record(record_id: str, session: Session = Depends(get_session)):
    row = session.get(CalcRecord, record_id)
    if row is None:
        raise NotFoundError(f"未找到核算记录 {record_id}", field="record_id")
    return _serialize_record(row)


# ---------------------------------------------------------------------------
# 配置回显 / 预置算例
# ---------------------------------------------------------------------------

@router.get("/config")
def get_config():
    return {"tolerances_and_defaults": settings.public_view()}


_EXAMPLE = {
    "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.0,
    "q": 0.0, "sigma": 0.2, "option_type": "call",
}


@router.get("/examples/atm-one-year")
def example_atm(session: Session = Depends(get_session)):
    """预置算例：平值、一年期、20% 波动率、零利率零分红的看涨期权。

    理论价格与 0.4·S·σ·√T = 0.4×100×0.2×1 = 8.0 同量级
    （BS 精确值约 7.97）。
    """
    params = valid.validate_pricing_request(dict(_EXAMPLE))
    body = services.price_body(params)
    body["rule_of_thumb"] = {
        "formula": "0.4 * S * sigma * sqrt(T)",
        "value": 0.4 * params["S"] * params["sigma"] * params["T"] ** 0.5,
        "same_order_of_magnitude": True,
    }
    record = _record_one(session, "price", params, True, body, None)
    body["record_id"] = record.id
    return body


@router.get("/examples")
def list_examples():
    return {
        "examples": [
            {
                "name": "atm-one-year",
                "description": "平值、一年期、20% 波动率、零利率零分红看涨期权",
                "params": _EXAMPLE,
                "path": "/examples/atm-one-year",
            }
        ]
    }
