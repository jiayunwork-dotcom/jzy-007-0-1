"""一阶/二阶希腊值：Delta、Gamma、Vega、Theta、Rho。

报价约定：
- Vega 为波动率变动 1.00（即 100 个波动率点）对应的价格变动；
- Theta 为每自然年变动，Rho 为利率变动 1.00 对应的价格变动；
- 看涨与看跌共用同一 Gamma、Vega；
- T == 0 时希腊值在到期点不连续/发散，按无定义拒绝。
"""
from __future__ import annotations

import math
from typing import Dict

from .errors import ParamError
from .pricing import OptionParams, d1_d2, norm_cdf, norm_pdf


def greeks(p: OptionParams) -> Dict[str, float]:
    if p.expiry == 0:
        raise ParamError("T", "剩余期限为零（合约已到期）时希腊值无定义，仅能返回内在价值")

    d1, d2 = d1_d2(p)
    sqrt_t = math.sqrt(p.expiry)
    df_q = math.exp(-p.dividend * p.expiry)
    df_r = math.exp(-p.rate * p.expiry)
    pdf_d1 = norm_pdf(d1)

    # 看涨看跌相同的两项
    gamma = df_q * pdf_d1 / (p.spot * p.sigma * sqrt_t)
    vega = p.spot * df_q * pdf_d1 * sqrt_t

    # Theta 的公共时间衰减项
    decay = -(p.spot * df_q * pdf_d1 * p.sigma) / (2.0 * sqrt_t)

    if p.option_type == "call":
        delta = df_q * norm_cdf(d1)
        theta = (
            decay
            - p.rate * p.strike * df_r * norm_cdf(d2)
            + p.dividend * p.spot * df_q * norm_cdf(d1)
        )
        rho = p.strike * p.expiry * df_r * norm_cdf(d2)
    else:
        delta = df_q * (norm_cdf(d1) - 1.0)
        theta = (
            decay
            + p.rate * p.strike * df_r * norm_cdf(-d2)
            - p.dividend * p.spot * df_q * norm_cdf(-d1)
        )
        rho = -p.strike * p.expiry * df_r * norm_cdf(-d2)

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
    }
