"""Black-Scholes 欧式期权定价核心。

约定：

* ``S`` 标的现货，``K`` 执行价，``T`` 剩余期限（年），``r`` 无风险利率，
  ``q`` 连续分红率，``sigma`` 波动率；``is_call=True`` 为看涨。
* 贴现因子：利率贴现 ``df_r = exp(-rT)``，分红贴现 ``df_q = exp(-qT)``。
* 参数合法性由 :mod:`app.pricing.validation` 负责，本模块假定入参合法。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .dist import cdf

_EPS_T = 1e-12


@dataclass(frozen=True)
class BSParams:
    S: float
    K: float
    T: float
    r: float
    q: float
    sigma: float
    is_call: bool

    @property
    def df_r(self) -> float:
        return math.exp(-self.r * self.T)

    @property
    def df_q(self) -> float:
        return math.exp(-self.q * self.T)


@dataclass(frozen=True)
class PriceResult:
    price: float
    d1: float | None
    d2: float | None
    intrinsic: float
    expired: bool


def intrinsic_value(S: float, K: float, is_call: bool) -> float:
    """内在价值：看涨 max(S-K,0)，看跌 max(K-S,0)。"""
    return max(S - K, 0.0) if is_call else max(K - S, 0.0)


def d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    """Black-Scholes 的 d1、d2。调用方需保证 T>0 且 sigma>0。"""
    var = sigma * sigma
    d1 = (math.log(S / K) + (r - q + 0.5 * var) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def price(p: BSParams) -> PriceResult:
    """计算欧式期权理论价格。

    T=0（精确为零）时直接返回内在价值，不套用未到期公式；
    对 T 极小（>0）的情形走极限价格，避免 d1 数值溢出。
    """
    intrinsic = intrinsic_value(p.S, p.K, p.is_call)

    if p.T == 0.0:
        return PriceResult(price=intrinsic, d1=None, d2=None,
                           intrinsic=intrinsic, expired=True)

    # T 极小或波动率趋零时，BS 极限 = 远期价格里的行权相关项，
    # 直接算 d1 会溢出，改由贴现内在值给出，d1/d2 置空。
    if p.T <= _EPS_T or p.sigma * math.sqrt(p.T) <= 1e-10:
        forward_intrinsic = max(p.S * p.df_q - p.K * p.df_r, 0.0) if p.is_call \
            else max(p.K * p.df_r - p.S * p.df_q, 0.0)
        return PriceResult(price=forward_intrinsic, d1=None, d2=None,
                           intrinsic=intrinsic, expired=False)

    d1, d2 = d1_d2(p.S, p.K, p.T, p.r, p.q, p.sigma)
    if p.is_call:
        value = p.S * p.df_q * cdf(d1) - p.K * p.df_r * cdf(d2)
    else:
        value = p.K * p.df_r * cdf(-d2) - p.S * p.df_q * cdf(-d1)
    return PriceResult(price=value, d1=d1, d2=d2,
                       intrinsic=intrinsic, expired=False)
