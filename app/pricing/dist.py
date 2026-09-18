"""标准正态分布工具（零第三方数值依赖）。

分布函数用标准 erf 实现，密度函数直接给闭式。
"""
from __future__ import annotations

import math


def pdf(x: float) -> float:
    """标准正态概率密度函数 φ(x)。"""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def cdf(x: float) -> float:
    """标准正态累积分布函数 N(x)。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
