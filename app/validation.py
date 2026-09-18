"""输入校验：把松散 JSON 负载规范化为 OptionParams。

所有非法输入（缺字段、非数值、非有限值、未知方向、方向字段互相矛盾、
取值越界）都抛出携带参数名与可读说明的 ParamError，绝不静默算出错误结果。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from . import config
from .errors import ParamError
from .pricing import OptionParams

_OPTION_TYPE_ALIASES = {
    "call": "call", "c": "call",
    "put": "put", "p": "put",
}


def _require_object(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ParamError("body", "请求体必须是 JSON 对象")
    return payload


def _number(payload: Dict[str, Any], name: str, *,
            required: bool = True, default: Optional[float] = None) -> Optional[float]:
    if name not in payload or payload[name] is None:
        if required:
            raise ParamError(name, f"缺少必填参数 {name}")
        return default
    value = payload[name]
    # bool 是 int 的子类，必须显式排除，避免 true/false 被当成 1/0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParamError(name, f"参数 {name} 必须是数值，收到的是 {value!r}")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise ParamError(name, f"参数 {name} 必须是有限数值，不能为 NaN 或无穷大")
    return value


def _option_type(payload: Dict[str, Any]) -> str:
    """方向支持 option_type（call/put）与 is_call（布尔）两种写法；
    两者同时给出且互相矛盾时拒绝。"""
    raw_type = payload.get("option_type")
    is_call = payload.get("is_call")
    if raw_type is None and is_call is None:
        raise ParamError(
            "option_type",
            "缺少看涨/看跌方向：请提供 option_type（call/put）或 is_call（true/false）",
        )

    resolved: Optional[str] = None
    if raw_type is not None:
        if not isinstance(raw_type, str):
            raise ParamError("option_type", f"option_type 必须是字符串，收到 {raw_type!r}")
        norm = raw_type.strip().lower()
        if norm not in _OPTION_TYPE_ALIASES:
            raise ParamError(
                "option_type", f"未知的期权方向 {raw_type!r}，仅支持 call/put"
            )
        resolved = _OPTION_TYPE_ALIASES[norm]

    if is_call is not None:
        if not isinstance(is_call, bool):
            raise ParamError("is_call", f"is_call 必须是布尔值，收到 {is_call!r}")
        implied = "call" if is_call else "put"
        if resolved is not None and resolved != implied:
            raise ParamError(
                "option_type",
                f"方向字段互相矛盾：option_type={raw_type!r} 与 is_call={is_call} 不一致",
            )
        resolved = implied
    return resolved


def _validate_common(payload: Dict[str, Any]) -> Dict[str, float]:
    spot = _number(payload, "S")
    strike = _number(payload, "K")
    expiry = _number(payload, "T")
    rate = _number(payload, "r")
    dividend = _number(payload, "q", required=False, default=config.DEFAULT_Q)

    if spot <= 0:
        raise ParamError("S", f"现货价格必须为正数，收到 {spot}")
    if strike <= 0:
        raise ParamError("K", f"执行价必须为正数，收到 {strike}")
    if expiry < 0:
        raise ParamError("T", f"剩余期限不能为负，收到 {expiry}")
    # rate / dividend 允许为零或负（负利率场景），_number 已保证有限
    return {
        "spot": spot, "strike": strike, "expiry": expiry,
        "rate": rate, "dividend": dividend,
    }


def validate_price_params(payload: Any) -> OptionParams:
    """定价/希腊值请求：sigma 必填且必须为正。"""
    payload = _require_object(payload)
    option_type = _option_type(payload)
    common = _validate_common(payload)
    sigma = _number(payload, "sigma")
    if sigma <= 0:
        raise ParamError("sigma", f"波动率必须为正数，收到 {sigma}")
    return OptionParams(sigma=sigma, option_type=option_type, **common)


def validate_iv_params(payload: Any) -> Tuple[OptionParams, float]:
    """隐含波动率请求：不需要 sigma，额外要求有限的 market_price。"""
    payload = _require_object(payload)
    option_type = _option_type(payload)
    common = _validate_common(payload)
    market_price = _number(payload, "market_price")
    return OptionParams(sigma=None, option_type=option_type, **common), market_price
