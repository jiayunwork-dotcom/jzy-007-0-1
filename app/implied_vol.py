"""隐含波动率反解：无套利界检验 + 二分法求解。

理论价格关于 sigma 单调递增，二分法必然收敛；
解出后按钉死的相对容差 IV_ROUNDTRIP_REL_TOL 验证代回闭合。
"""
from __future__ import annotations

import math
from typing import Tuple

from . import config
from .errors import InfeasibleError
from .pricing import OptionParams, price


def no_arbitrage_bounds(p: OptionParams) -> Tuple[float, float]:
    """返回 (下界, 上界)：
    看涨 [max(S·e^-qT - K·e^-rT, 0), S·e^-qT]；
    看跌 [max(K·e^-rT - S·e^-qT, 0), K·e^-rT]。
    """
    df_q = math.exp(-p.dividend * p.expiry)
    df_r = math.exp(-p.rate * p.expiry)
    if p.option_type == "call":
        return max(p.spot * df_q - p.strike * df_r, 0.0), p.spot * df_q
    return max(p.strike * df_r - p.spot * df_q, 0.0), p.strike * df_r


def implied_vol(p: OptionParams, market_price: float) -> float:
    """反解使理论价格等于 market_price 的波动率。不可行时抛 InfeasibleError。"""
    if p.expiry == 0:
        raise InfeasibleError(
            "剩余期限为零时理论价格恒等于内在价值，隐含波动率无定义"
        )

    lower, upper = no_arbitrage_bounds(p)
    bound_tol = config.BOUND_REL_TOL * max(1.0, abs(market_price))
    if market_price < lower - bound_tol or market_price > upper + bound_tol:
        raise InfeasibleError(
            f"市场价格 {market_price} 落在无套利界 [{lower:.10g}, {upper:.10g}] 之外，"
            "无法反解隐含波动率"
        )

    # 求解目标比对外承诺的闭合容差再紧两个数量级，保证代回必闭合
    solve_tol = config.IV_ROUNDTRIP_REL_TOL * max(1.0, abs(market_price)) * 1e-2

    def gap(sigma: float) -> float:
        return price(p.with_sigma(sigma)) - market_price

    lo, hi = config.IV_MIN_SIGMA, config.IV_MAX_SIGMA
    if abs(gap(lo)) <= solve_tol:
        return lo
    f_hi = gap(hi)
    while f_hi < 0.0 and hi < config.IV_MAX_SIGMA_CAP:
        hi *= 2.0
        f_hi = gap(hi)
    if f_hi < 0.0:
        raise InfeasibleError(
            f"波动率取到上限 {hi} 时理论价格仍低于市场价格，判定不可行"
        )

    mid = lo
    for _ in range(config.IV_MAX_ITER):
        mid = 0.5 * (lo + hi)
        f_mid = gap(mid)
        if abs(f_mid) <= solve_tol:
            return mid
        if f_mid > 0.0:
            hi = mid
        else:
            lo = mid

    # 迭代耗尽后的兜底校验：仍满足钉死容差则接受，否则明确判不可行
    mid = 0.5 * (lo + hi)
    if abs(gap(mid)) <= config.IV_ROUNDTRIP_REL_TOL * max(1.0, abs(market_price)):
        return mid
    raise InfeasibleError("二分求解未能在钉死容差内收敛，判定不可行")
