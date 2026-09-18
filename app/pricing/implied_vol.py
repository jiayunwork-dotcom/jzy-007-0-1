"""从市场价格反解 Black-Scholes 隐含波动率。

无套利界（T>0）：

* 看涨： ``max(S·e^-qT − K·e^-rT, 0) ≤ C ≤ S·e^-qT``
* 看跌： ``max(K·e^-rT − S·e^-qT, 0) ≤ P ≤ K·e^-rT``

界外市价一律返回 :class:`IVInfeasibleError`，不给出无意义的波动率；
T=0 时隐含波动率无定义，同样按不可行处理。
T>0 且市价恰好等于下界时，极限解就是 0，直接返回 0 并标注命中下界。

求解使用带括号搜索的二分法：解始终被夹在单调的 BS 价格函数之间，
每一步都保证根不被抛出括号，且不依赖任何第三方数值库。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import settings
from ..errors import IVInfeasibleError
from . import black_scholes as bs

_BOUND_REL_EPS = 1e-10


@dataclass(frozen=True)
class IVResult:
    implied_vol: float
    iterations: int
    converged: bool
    at_bound: bool
    lower_bound: float
    upper_bound: float


def arbitrage_bounds(p: bs.BSParams) -> tuple[float, float]:
    """返回 (下界, 上界)。仅对 T>0 有意义。"""
    sdisc = p.S * p.df_q
    kdisc = p.K * p.df_r
    if p.is_call:
        return max(sdisc - kdisc, 0.0), sdisc
    return max(kdisc - sdisc, 0.0), kdisc


def implied_volatility(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    is_call: bool,
    market_price: float,
) -> IVResult:
    if T == 0.0:
        # 到期时任意波动率都给出同一个内在价值，IV 无定义。
        raise IVInfeasibleError(
            "期限为零时隐含波动率无定义（期权价值恒为内在价值）",
            details={"reason": "expired", "market_price": market_price},
        )

    base = bs.BSParams(S=S, K=K, T=T, r=r, q=q, sigma=1.0, is_call=is_call)
    lower, upper = arbitrage_bounds(base)
    scale = max(abs(upper), abs(lower), S, K, 1.0)
    eps = _BOUND_REL_EPS * scale

    if market_price < lower - eps:
        raise IVInfeasibleError(
            f"市场价格 {market_price:g} 低于无套利下界 {lower:g}，隐含波动率不可行",
            details={
                "reason": "below_lower_bound",
                "market_price": market_price,
                "lower_bound": lower,
                "upper_bound": upper,
            },
        )
    if market_price > upper + eps:
        raise IVInfeasibleError(
            f"市场价格 {market_price:g} 高于无套利上界 {upper:g}，隐含波动率不可行",
            details={
                "reason": "above_upper_bound",
                "market_price": market_price,
                "lower_bound": lower,
                "upper_bound": upper,
            },
        )

    # 贴近/恰好等于下界：波动率的极限解为 0。
    if market_price <= lower + eps:
        return IVResult(0.0, iterations=0, converged=True, at_bound=True,
                        lower_bound=lower, upper_bound=upper)

    target = min(market_price, upper)

    def model_price(sigma: float) -> float:
        return bs.price(bs.BSParams(
            S=S, K=K, T=T, r=r, q=q, sigma=sigma, is_call=is_call
        )).price

    # 括号搜索：从极小波动率开始倍增，直到模型价格覆盖目标市价。
    lo, hi = 0.0, 1e-6
    while model_price(hi) < target:
        if hi >= settings.iv_upper_bound:
            raise IVInfeasibleError(
                f"市场价格 {market_price:g} 超出波动率搜索上界 "
                f"{settings.iv_upper_bound:g} 对应的理论价格，隐含波动率不可行",
                details={
                    "reason": "above_upper_bound",
                    "market_price": market_price,
                    "lower_bound": lower,
                    "upper_bound": upper,
                },
            )
        lo, hi = hi, min(hi * 2.0, settings.iv_upper_bound)

    # 下界为 0 且目标价极低时，真正的根可能远小于初始括号 hi，
    # 这里先向下二分细化，把 hi 压到模型价刚好超过目标的尺度。
    while hi > 0.0:
        mid = 0.5 * (lo + hi)
        if model_price(mid) < target:
            lo = mid
            break
        hi = mid

    # 二分：BS 价格关于 σ 严格单调（Vega>0），括号始终夹住根。
    iterations = 0
    # 极低市价时模型价会在浮点下触平到 0，纯相对容差无法达成，
    # 因此收敛判据用"相对容差 + 极小绝对容差"，与代回闭合口径一致。
    price_tol = settings.iv_solve_rel_tol * abs(target) + 1e-12
    for i in range(1, settings.iv_max_iter + 1):
        iterations = i
        mid = 0.5 * (lo + hi)
        diff = model_price(mid) - target
        if abs(diff) <= price_tol:
            lo = hi = mid
            break
        if mid == lo or mid == hi:
            # 括号已压到浮点可分辨的极限
            break
        if diff < 0.0:
            lo = mid
        else:
            hi = mid

    sigma_star = 0.5 * (lo + hi)
    check = model_price(sigma_star)
    abs_err = abs(check - target)
    rel_err = abs_err / max(abs(target), 1e-300)
    if not math.isfinite(rel_err) or (
        rel_err > settings.iv_roundtrip_rel_tol and abs_err > 1e-10
    ):
        raise IVInfeasibleError(
            "隐含波动率求解未能在钉死容差内收敛",
            details={
                "reason": "no_convergence",
                "market_price": market_price,
                "reconstructed_price": check,
                "relative_error": rel_err,
            },
        )

    return IVResult(sigma_star, iterations=iterations, converged=True,
                    at_bound=False, lower_bound=lower, upper_bound=upper)
