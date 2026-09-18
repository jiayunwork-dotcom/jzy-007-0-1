"""结构化错误定义。

所有业务错误都抛出 :class:`ServiceError`，由统一异常处理器转成
``{"error": {"code": ..., "message": ..., "field": ..., "details": ...}}``
形式的可读响应，保证调用方拿到的永远是结构化错误而非堆栈。
"""
from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    """业务层错误基类。"""

    code = "invalid_request"
    status_code = 422

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.field is not None:
            body["field"] = self.field
        if self.details:
            body["details"] = self.details
        return {"error": body}


class InvalidParameterError(ServiceError):
    """单个输入参数不合法（类型、有限性、取值区间等）。"""

    code = "invalid_parameter"


class ContradictionError(ServiceError):
    """同一含义的字段互相矛盾，例如 ``option_type=call`` 且 ``is_call=false``。"""

    code = "contradictory_fields"


class IVInfeasibleError(ServiceError):
    """市场价格落在无套利界外（或 T=0 时内在值情形），隐含波动率不可行。"""

    code = "iv_infeasible"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)


class NotFoundError(ServiceError):
    """查询的资源不存在。"""

    code = "not_found"
    status_code = 404
