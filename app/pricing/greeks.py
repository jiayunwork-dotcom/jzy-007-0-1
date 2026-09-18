"""一阶希腊值。

口径说明（以年计）：

* Delta   = ∂V/∂S
* Gamma   = ∂²V/∂S²（看涨看跌相同）
* Vega    = ∂V/∂σ，按"波动率变动 1 个百分点（0.01）"计价
* Theta   = ∂V/∂t（日历时间），按"每日"计价，与 Hull 教材口径一致：
            多头平值期权 Theta 为负
* Rho     = ∂V/∂r，按"利率变动 1 个百分点（0.01）"计价

T=0 到期时：Delta 取行权收益对现货的次梯度（平值取 ±0.5），
Gamma/Vega/Theta/Rho 均为 0。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import black_scholes as bs
from .dist import cdf, pdf

_DAYS_PER_YEAR = 365.0
_VEGA_PER_POINT = 0.01
_RHO_PER_POINT = 0.01


@dataclass(frozen=True)
class GreeksResult:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    d1: float | None
    d2: float | None
    expired: bool


def greeks(p: bs.BSParams) -> GreeksResult:
    if p.T == 0.0:
        if p.is_call:
            delta = 1.0 if p.S > p.K else (0.0 if p.S < p.K else 0.5)
        else:
            delta = -1.0 if p.S < p.K else (0.0 if p.S > p.K else -0.5)
        return GreeksResult(delta=delta, gamma=0.0, vega=0.0, theta=0.0,
                            rho=0.0, d1=None, d2=None, expired=True)

    d1, d2 = bs.d1_d2(p.S, p.K, p.T, p.r, p.q, p.sigma)
    sqrt_t = math.sqrt(p.T)
    phi_d1 = pdf(d1)

    # Gamma、Vega 与方向无关
    gamma = p.df_q * phi_d1 / (p.S * p.sigma * sqrt_t)
    vega_year = p.S * p.df_q * phi_d1 * sqrt_t
    vega = vega_year * _VEGA_PER_POINT

    if p.is_call:
        delta = p.df_q * cdf(d1)
        theta_year = (
            -(p.S * p.df_q * phi_d1 * p.sigma) / (2.0 * sqrt_t)
            - p.r * p.K * p.df_r * cdf(d2)
            + p.q * p.S * p.df_q * cdf(d1)
        )
        rho_year = p.K * p.T * p.df_r * cdf(d2)
    else:
        delta = -p.df_q * cdf(-d1)
        theta_year = (
            -(p.S * p.df_q * phi_d1 * p.sigma) / (2.0 * sqrt_t)
            + p.r * p.K * p.df_r * cdf(-d2)
            - p.q * p.S * p.df_q * cdf(-d1)
        )
        rho_year = -p.K * p.T * p.df_r * cdf(-d2)

    return GreeksResult(
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta_year / _DAYS_PER_YEAR,
        rho=rho_year * _RHO_PER_POINT,
        d1=d1,
        d2=d2,
        expired=False,
    )
