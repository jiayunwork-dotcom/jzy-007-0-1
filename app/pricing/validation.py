"""请求输入校验。

校验刻意手写而不是依赖 Pydantic 的默认报错，保证错误信息
满足"带说明、指明哪个参数"的要求，并且：

* 缺字段、类型错误（含把布尔当成数值）、NaN/Infinity 都被拒；
* 未知字段一律拒绝；
* 未知方向、``option_type`` 与 ``is_call`` 互相矛盾都被拒；
* 利率、分红率允许零或负，但必须有限；
* 分红率缺省取配置中的默认值（零）。
"""
from __future__ import annotations

import math
from typing import Any

from ..config import settings
from ..errors import ContradictionError, InvalidParameterError

_COMMON_FIELDS = {"S", "K", "T", "r", "q", "option_type", "is_call"}
PRICING_FIELDS = _COMMON_FIELDS | {"sigma"}
IV_FIELDS = _COMMON_FIELDS | {"market_price"}

_DIRECTION_ALIASES = {
    "call": True, "c": True, "看涨": True, "认购": True,
    "put": False, "p": False, "看跌": False, "认沽": False,
}

_CANONICAL_FIELDS = {
    "S": "S（现货价格）",
    "K": "K（执行价）",
    "T": "T（剩余期限/年）",
    "r": "r（无风险利率）",
    "q": "q（连续分红率）",
    "sigma": "sigma（波动率）",
    "market_price": "market_price（市场价格）",
    "option_type": "option_type（看涨/看跌方向）",
    "is_call": "is_call（是否看涨）",
}


def _label(name: str) -> str:
    return _CANONICAL_FIELDS.get(name, name)


def _err(message: str, field: str) -> InvalidParameterError:
    return InvalidParameterError(message, field=field)


def _check_number(
    raw: dict[str, Any],
    name: str,
    *,
    required: bool,
    positive: bool = False,
    nonnegative: bool = False,
    finite_only: bool = False,
) -> float | None:
    if name not in raw or raw[name] is None:
        if required:
            raise _err(f"缺少必填字段 {_label(name)}", name)
        return None
    value = raw[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _err(f"字段 {_label(name)} 必须是数值，实际收到 {value!r}", name)
    fvalue = float(value)
    if not math.isfinite(fvalue):
        raise _err(f"字段 {_label(name)} 必须是有限数值，不能是 NaN 或无穷大", name)
    if positive and fvalue <= 0.0:
        raise _err(f"字段 {_label(name)} 必须为正数，实际为 {fvalue:g}", name)
    if nonnegative and fvalue < 0.0:
        raise _err(f"字段 {_label(name)} 必须为非负数，实际为 {fvalue:g}", name)
    if finite_only and not math.isfinite(fvalue):  # pragma: no cover - 前置已保证
        raise _err(f"字段 {_label(name)} 必须是有限数值", name)
    return fvalue


def _resolve_direction(raw: dict[str, Any]) -> bool:
    has_type = "option_type" in raw and raw["option_type"] is not None
    has_flag = "is_call" in raw and raw["is_call"] is not None
    if not has_type and not has_flag:
        raise _err("缺少必填字段 option_type（看涨看跌方向，取 call 或 put）",
                   "option_type")

    type_is_call: bool | None = None
    if has_type:
        raw_type = raw["option_type"]
        if isinstance(raw_type, bool) or not isinstance(raw_type, str):
            raise _err(
                f"字段 option_type 必须是字符串 call/put，实际收到 {raw_type!r}",
                "option_type",
            )
        key = raw_type.strip().lower()
        if key not in _DIRECTION_ALIASES:
            raise _err(
                f"未知的看涨看跌方向 {raw_type!r}，只支持 call/c 或 put/p",
                "option_type",
            )
        type_is_call = _DIRECTION_ALIASES[key]

    flag_is_call: bool | None = None
    if has_flag:
        raw_flag = raw["is_call"]
        if not isinstance(raw_flag, bool):
            raise _err(
                f"字段 is_call 必须是布尔值 true/false，实际收到 {raw_flag!r}",
                "is_call",
            )
        flag_is_call = raw_flag

    if type_is_call is not None and flag_is_call is not None \
            and type_is_call != flag_is_call:
        raise ContradictionError(
            f"方向字段互相矛盾：option_type={'call' if type_is_call else 'put'} "
            f"但 is_call={str(flag_is_call).lower()}，请只保留一个或保持一致",
            field="is_call",
        )
    return type_is_call if type_is_call is not None else bool(flag_is_call)


def _check_unknown_fields(raw: dict[str, Any], known: set[str]) -> None:
    for key in raw:
        if key not in known:
            raise _err(
                f"未知字段 {key!r}，支持的字段为 {sorted(known)}",
                key,
            )


def validate_contract(
    raw: dict[str, Any],
    *,
    known_fields: set[str],
    require_sigma: bool,
    require_market_price: bool,
) -> dict[str, Any]:
    """校验一份合约输入，返回规范化后的字典。"""
    if not isinstance(raw, dict):
        raise _err("请求体必须是 JSON 对象", "body")
    _check_unknown_fields(raw, known_fields)

    S = _check_number(raw, "S", required=True, positive=True)
    K = _check_number(raw, "K", required=True, positive=True)
    T = _check_number(raw, "T", required=True, nonnegative=True)
    # 利率、分红率允许零与负（负利率），只需有限。
    r = _check_number(raw, "r", required=True, finite_only=True)
    q = _check_number(raw, "q", required=False)
    if q is None:
        q = settings.default_dividend_yield

    result: dict[str, Any] = {
        "S": S, "K": K, "T": T, "r": r, "q": q,
        "is_call": _resolve_direction(raw),
    }

    if require_sigma:
        result["sigma"] = _check_number(raw, "sigma", required=True, positive=True)
    elif "sigma" in raw:  # pragma: no cover - 已被未知字段拦截
        raise _err("隐含波动率接口不应提供 sigma（sigma 是待反解的量）", "sigma")

    if require_market_price:
        price = _check_number(raw, "market_price", required=True)
        if price < 0.0:
            raise _err(
                f"字段 market_price（市场价格）必须为非负数，实际为 {price:g}",
                "market_price",
            )
        result["market_price"] = price

    return result


def validate_pricing_request(raw: dict[str, Any]) -> dict[str, Any]:
    return validate_contract(
        raw, known_fields=PRICING_FIELDS,
        require_sigma=True, require_market_price=False,
    )


def validate_iv_request(raw: dict[str, Any]) -> dict[str, Any]:
    return validate_contract(
        raw, known_fields=IV_FIELDS,
        require_sigma=False, require_market_price=True,
    )
