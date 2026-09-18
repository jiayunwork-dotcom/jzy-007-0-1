"""FastAPI 应用入口。

* 中间件统一读取并缓存 JSON 请求体（Python 的 json 默认接受
  NaN/Infinity，随后由手写校验按"非有限值"拒绝）；
* 统一异常处理器保证任何错误都以结构化 JSON 返回，绝不泄漏堆栈；
* 启动时建表。
"""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .api.routes import router
from .db.session import init_db, ping
from .errors import ServiceError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Black-Scholes 欧式期权定价核算服务",
    version="1.0.0",
    description=(
        "纯服务端数值定价组件：欧式期权理论价格、一阶希腊值、"
        "隐含波动率反解、批量定价与历史查询。"
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def parse_json_body(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            raw = await request.body()
            if raw:
                request.state.json_body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return JSONResponse(
                status_code=422,
                content={"error": {
                    "code": "invalid_json",
                    "message": f"请求体不是合法的 JSON：{exc.msg}",
                    "field": "body",
                }},
            )
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-process-ms"] = f"{(time.perf_counter() - start) * 1000:.3f}"
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content=exc.to_body())


@app.exception_handler(ValidationError)
async def pydantic_error_handler(_request: Request, exc: ValidationError):
    # schema 层兜底（理论上手写校验已覆盖所有路径）
    first = exc.errors()[0] if exc.errors() else {}
    return JSONResponse(
        status_code=422,
        content={"error": {
            "code": "invalid_parameter",
            "message": f"请求参数不合法：{first.get('msg', '校验失败')}",
            "field": ".".join(str(x) for x in first.get("loc", [])) or None,
        }},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {
            "code": "internal_error",
            "message": f"服务内部错误：{type(exc).__name__}",
        }},
    )


@app.get("/health")
def health():
    """存活探针。"""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """就绪探针：同时探测数据库连通性。"""
    db_ok = True
    try:
        ping()
    except Exception:
        db_ok = False
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": "ok" if db_ok else "degraded", "database": db_ok},
    )


app.include_router(router)
