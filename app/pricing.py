"""Black-Scholes 定价核心：d1/d2、理论价格、到期内在价值。

约定：
- 连续复利无风险利率 r、连续分红率 q，期限 T 以年为单位；
- T == 0 时不套用未到期公式，直接返回内在价值；
- 本模块不做输入校验，假定参数已经过 validation 模块规范化。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional, Tuple

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_SQRT_2 = math.sqrt(2.0)


def norm_cdf(x: float) -> float:
    """标准正态累积分布。math.erf 是奇函数，故 N(x)+N(-x) 恒等于 1，
    这保证了看涨看跌平价在机器精度内闭合。"""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


@dataclass(frozen=True)
class OptionParams:
    """规范化后的合约参数。sigma 在隐含波动率场景下为 None。"""

    spot: float
    strike: float
    expiry: float
    rate: float
    sigma: Optional[float]
    dividend: float = 0.0
    option_type: str = "call"  # "call" | "put"

    def with_sigma(self, sigma: float) -> "OptionParams":
        return replace(self, sigma=sigma)


def intrinsic_value(option_type: str, spot: float, strike: float) -> float:
    if option_type == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def d1_d2(p: OptionParams) -> Tuple[Optional[float], Optional[float]]:
    """到期日（T==0）时 d1/d2 无定义，返回 (None, None)。"""
    if p.expiry == 0:
        return None, None
    vol_sqrt_t = p.sigma * math.sqrt(p.expiry)
    d1 = (
        math.log(p.spot / p.strike)
        + (p.rate - p.dividend + 0.5 * p.sigma * p.sigma) * p.expiry
    ) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def price(p: OptionParams) -> float:
    """欧式期权理论价格。T==0 时直接返回内在价值。"""
    if p.expiry == 0:
        return intrinsic_value(p.option_type, p.spot, p.strike)
    d1, d2 = d1_d2(p)
    df_q = math.exp(-p.dividend * p.expiry)  # 分红贴现因子
    df_r = math.exp(-p.rate * p.expiry)      # 利率贴现因子
    if p.option_type == "call":
        return p.spot * df_q * norm_cdf(d1) - p.strike * df_r * norm_cdf(d2)
    return p.strike * df_r * norm_cdf(-d2) - p.spot * df_q * norm_cdf(-d1)
