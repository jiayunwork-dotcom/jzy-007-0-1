"""业务编排：把校验后的参数喂给数值内核，并组装对外响应。

这一层不碰 HTTP，只处理"算什么、返回什么字段"，便于在测试中直接复用。
"""
from __future__ import annotations

from typing import Any

from .config import settings
from .pricing import black_scholes as bs
from .pricing import greeks as gk
from .pricing import implied_vol as ivm
from .pricing.black_scholes import BSParams


def make_params(v: dict[str, Any], sigma: float) -> BSParams:
    return BSParams(
        S=v["S"], K=v["K"], T=v["T"], r=v["r"], q=v["q"],
        sigma=sigma, is_call=v["is_call"],
    )


def echo_params(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "S": v["S"], "K": v["K"], "T": v["T"], "r": v["r"], "q": v["q"],
        "option_type": "call" if v["is_call"] else "put",
    }


def price_body(v: dict[str, Any]) -> dict[str, Any]:
    params = make_params(v, v["sigma"])
    res = bs.price(params)
    return {
        **echo_params(v),
        "sigma": v["sigma"],
        "price": res.price,
        "d1": res.d1,
        "d2": res.d2,
        "intrinsic": res.intrinsic,
        "expired": res.expired,
    }


def greeks_body(v: dict[str, Any]) -> dict[str, Any]:
    params = make_params(v, v["sigma"])
    res = gk.greeks(params)
    price_res = bs.price(params)
    return {
        **echo_params(v),
        "sigma": v["sigma"],
        "price": price_res.price,
        "d1": res.d1,
        "d2": res.d2,
        "expired": res.expired,
        "greeks": {
            "delta": res.delta,
            "gamma": res.gamma,
            "vega": res.vega,
            "theta": res.theta,
            "rho": res.rho,
            "conventions": {
                "vega": "波动率 +1 个百分点(0.01) 对应的价格变化",
                "theta": "日历时间每日损耗（按 365 天/年），Hull 口径",
                "rho": "利率 +1 个百分点(0.01) 对应的价格变化",
            },
        },
    }


def iv_body(v: dict[str, Any]) -> dict[str, Any]:
    market_price = v["market_price"]
    result = ivm.implied_volatility(
        S=v["S"], K=v["K"], T=v["T"], r=v["r"], q=v["q"],
        is_call=v["is_call"], market_price=market_price,
    )
    # 代回定价接口，验证在钉死容差内闭合。
    back = bs.price(make_params(v, result.implied_vol))
    abs_err = abs(back.price - market_price)
    rel_err = abs_err / max(abs(market_price), 1e-300)
    within = rel_err <= settings.iv_roundtrip_rel_tol or abs_err <= 1e-10
    return {
        **echo_params(v),
        "market_price": market_price,
        "implied_vol": result.implied_vol,
        "iterations": result.iterations,
        "converged": result.converged,
        "at_bound": result.at_bound,
        "arbitrage_bounds": {
            "lower": result.lower_bound,
            "upper": result.upper_bound,
        },
        "roundtrip": {
            "reconstructed_price": back.price,
            "absolute_error": abs_err,
            "relative_error": rel_err,
            "rel_tol": settings.iv_roundtrip_rel_tol,
            "within_tol": within,
        },
    }
