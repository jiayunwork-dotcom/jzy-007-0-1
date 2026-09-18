"""HTTP 接口层：定价、希腊值、隐含波动率、批量定价、历史查询、配置回显、健康检查。

接口层只负责：解析负载 → 调用校验/核算 → 留痕 → 组织响应。
所有数值规则都在 pricing / greeks / implied_vol / validation 模块中。
"""
from __future__ import annotations

import math
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Body, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config
from .db import get_session, init_db
from .errors import InfeasibleError, ParamError
from .greeks import greeks
from .implied_vol import implied_vol, no_arbitrage_bounds
from .pricing import OptionParams, d1_d2, price
from .repository import query_records, record_to_dict, save_record
from .validation import validate_iv_params, validate_price_params


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Black-Scholes 欧式期权定价核算服务",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------- 错误响应

def _param_error_response(err: ParamError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "error": "invalid_parameter",
                "param": err.param,
                "message": err.message,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "error": "malformed_request",
                "message": "请求体无法解析，请检查 JSON 格式与字段类型",
                "errors": str(exc),
            }
        },
    )


# ---------------------------------------------------------------- 留痕

def _persist(
    session: Session,
    endpoint: str,
    payload: Any,
    *,
    params: Optional[OptionParams] = None,
    market_price: Optional[float] = None,
    status: str = "ok",
    error: Optional[ParamError] = None,
    batch_id: Optional[str] = None,
    batch_index: Optional[int] = None,
    **result: Any,
) -> None:
    """尽力留痕：持久化失败不影响核算结果本身。"""
    try:
        fields: Dict[str, Any] = dict(
            endpoint=endpoint, status=status,
            batch_id=batch_id, batch_index=batch_index, **result,
        )
        if params is not None:
            fields.update(
                option_type=params.option_type, spot=params.spot,
                strike=params.strike, expiry=params.expiry, rate=params.rate,
                dividend=params.dividend, sigma=params.sigma,
            )
        elif isinstance(payload, dict):
            # 参数整体非法时，仍把能识别的字段留下来便于排查
            for col, key in (("spot", "S"), ("strike", "K"), ("expiry", "T"),
                             ("rate", "r"), ("dividend", "q"), ("sigma", "sigma"),
                             ("market_price", "market_price")):
                v = payload.get(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    fields[col] = float(v)
            ot = payload.get("option_type")
            if isinstance(ot, str) and ot.strip().lower() in ("call", "put"):
                fields["option_type"] = ot.strip().lower()
        if market_price is not None:
            fields["market_price"] = market_price
        if error is not None:
            fields["error_param"] = error.param
            fields["error_message"] = error.message
        save_record(session, **fields)
    except Exception:
        session.rollback()


def _params_echo(p: OptionParams) -> Dict[str, Any]:
    return {
        "S": p.spot, "K": p.strike, "T": p.expiry, "r": p.rate,
        "q": p.dividend, "sigma": p.sigma, "option_type": p.option_type,
    }


def _price_result(params: OptionParams) -> Dict[str, Any]:
    value = price(params)
    d1, d2 = d1_d2(params)
    return {"price": value, "d1": d1, "d2": d2}


# ---------------------------------------------------------------- 核算接口

@app.post("/price")
def price_endpoint(payload: Any = Body(...), session: Session = Depends(get_session)):
    """单张定价：返回理论价格与 d1/d2。"""
    try:
        params = validate_price_params(payload)
    except ParamError as err:
        _persist(session, "price", payload, status="error", error=err)
        return _param_error_response(err)

    result = _price_result(params)
    _persist(session, "price", payload, params=params, **result)
    return {"status": "ok", **result, "params": _params_echo(params)}


@app.post("/greeks")
def greeks_endpoint(payload: Any = Body(...), session: Session = Depends(get_session)):
    """希腊值：同一组参数返回价格、d1/d2 与五个希腊值。"""
    try:
        params = validate_price_params(payload)
        greek_values = greeks(params)
    except ParamError as err:
        _persist(session, "greeks", payload, status="error", error=err)
        return _param_error_response(err)

    result = _price_result(params)
    _persist(session, "greeks", payload, params=params, **result, **greek_values)
    return {"status": "ok", **result, **greek_values, "params": _params_echo(params)}


@app.post("/implied-vol")
def implied_vol_endpoint(payload: Any = Body(...), session: Session = Depends(get_session)):
    """隐含波动率：市价落在无套利界外或期限为零时明确返回不可行。"""
    try:
        params, market_price = validate_iv_params(payload)
    except ParamError as err:
        _persist(session, "implied-vol", payload, status="error", error=err)
        return _param_error_response(err)

    try:
        iv = implied_vol(params, market_price)
    except InfeasibleError as err:
        lower, upper = no_arbitrage_bounds(params)
        _persist(session, "implied-vol", payload, params=params,
                 market_price=market_price, status="infeasible")
        return {
            "status": "infeasible",
            "reason": str(err),
            "market_price": market_price,
            "no_arbitrage_bounds": {"lower": lower, "upper": upper},
            "params": _params_echo(params),
        }

    roundtrip = price(params.with_sigma(iv))
    _persist(session, "implied-vol", payload, params=params,
             market_price=market_price, implied_vol=iv, price=roundtrip)
    return {
        "status": "ok",
        "implied_vol": iv,
        "market_price": market_price,
        "roundtrip_price": roundtrip,
        "roundtrip_rel_error": abs(roundtrip - market_price) / max(1.0, abs(market_price)),
        "params": _params_echo(params),
    }


@app.post("/batch/price")
def batch_price_endpoint(payload: Any = Body(...), session: Session = Depends(get_session)):
    """批量定价：某一组非法只影响该组，返回其序号与出问题的参数。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return _param_error_response(
            ParamError("items", "请求体必须是包含 items 数组的 JSON 对象")
        )
    items = payload["items"]
    if not items:
        return _param_error_response(ParamError("items", "items 数组不能为空"))

    batch_id = uuid.uuid4().hex
    results = []
    for index, item in enumerate(items):
        try:
            params = validate_price_params(item)
            result = _price_result(params)
            results.append({"index": index, "status": "ok", **result,
                            "params": _params_echo(params)})
            _persist(session, "batch/price", item, params=params,
                     batch_id=batch_id, batch_index=index, **result)
        except ParamError as err:
            results.append({"index": index, "status": "error",
                            "param": err.param, "message": err.message})
            _persist(session, "batch/price", item, status="error", error=err,
                     batch_id=batch_id, batch_index=index)
    return {"status": "ok", "batch_id": batch_id, "count": len(results), "results": results}


# ---------------------------------------------------------------- 查询接口

@app.get("/history")
def history_endpoint(
    endpoint: Optional[str] = Query(None, description="按接口过滤，如 price / greeks / implied-vol / batch/price"),
    option_type: Optional[str] = Query(None, description="call 或 put"),
    status: Optional[str] = Query(None, description="ok / error / infeasible"),
    batch_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """历史核算记录条件查询，按时间倒序。"""
    records, total = query_records(
        session, endpoint=endpoint, option_type=option_type,
        status=status, batch_id=batch_id, limit=limit, offset=offset,
    )
    return {
        "total": total,
        "count": len(records),
        "records": [record_to_dict(r) for r in records],
    }


@app.get("/config")
def config_endpoint():
    """回显当前钉死的容差与默认分红率配置。"""
    return {
        "default_dividend_yield": config.DEFAULT_Q,
        "parity_rel_tol": config.PARITY_REL_TOL,
        "iv_roundtrip_rel_tol": config.IV_ROUNDTRIP_REL_TOL,
        "bound_rel_tol": config.BOUND_REL_TOL,
        "iv_solver": {
            "min_sigma": config.IV_MIN_SIGMA,
            "max_sigma": config.IV_MAX_SIGMA,
            "max_iter": config.IV_MAX_ITER,
        },
    }


@app.get("/example")
def example_endpoint():
    """预置算例：平值、一年期、中等波动率、零分红、零利率。

    看涨价格应与 0.4·S·σ·√T 同量级（ATM 近似 C ≈ S·σ·√T/√(2π)）。
    """
    params = OptionParams(spot=100.0, strike=100.0, expiry=1.0, rate=0.0,
                          sigma=0.2, dividend=0.0, option_type="call")
    call_price = price(params)
    put_price = price(OptionParams(**{**params.__dict__, "option_type": "put"}))
    rule_of_thumb = 0.4 * params.spot * params.sigma * math.sqrt(params.expiry)
    return {
        "description": "平值、一年期、中等波动率、零分红算例",
        "params": _params_echo(params),
        "call_price": call_price,
        "put_price": put_price,
        "rule_of_thumb_0.4_S_sigma_sqrtT": rule_of_thumb,
        "ratio": call_price / rule_of_thumb,
    }


@app.get("/health")
def health_endpoint(session: Session = Depends(get_session)):
    """运行状态，供监控采集。"""
    try:
        session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    body = {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(status_code=200 if db_status == "ok" else 503, content=body)
