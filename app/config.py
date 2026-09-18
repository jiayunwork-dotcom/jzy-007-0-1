"""运行期配置。

容差等核算口径以这里的默认值为准（即"钉死"的容差），
但允许通过环境变量覆盖，便于部署方按自身精度要求调整。
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"环境变量 {name} 必须是有限数值")
    return value


@dataclass(frozen=True)
class Settings:
    # 看涨看跌平价（put-call parity）闭合校验使用的相对容差（仅用于服务端自检与测试）
    parity_rel_tol: float
    # 隐含波动率代回定价后与市场价对齐的相对容差（钉死）
    iv_roundtrip_rel_tol: float
    # 二分法反解波动率时判定收敛的相对价格容差
    iv_solve_rel_tol: float
    # 反解波动率时允许的波动率上界（10 即 1000%）
    iv_upper_bound: float
    # 二分法最大迭代次数
    iv_max_iter: int
    # 缺省连续分红率
    default_dividend_yield: float
    # 数据库连接串；默认使用容器内 SQLite，Docker Compose 中覆盖为 PostgreSQL
    database_url: str
    # 历史查询单页上限
    history_max_limit: int

    def public_view(self) -> dict:
        """对外回显的配置（只暴露口径相关项，不含连接串）。"""
        return {
            "parity_rel_tol": self.parity_rel_tol,
            "iv_roundtrip_rel_tol": self.iv_roundtrip_rel_tol,
            "iv_solve_rel_tol": self.iv_solve_rel_tol,
            "iv_upper_bound": self.iv_upper_bound,
            "iv_max_iter": self.iv_max_iter,
            "default_dividend_yield": self.default_dividend_yield,
            "history_max_limit": self.history_max_limit,
        }


def load_settings() -> Settings:
    url = os.getenv("DATABASE_URL", "sqlite:////data/bs_pricing.db")
    return Settings(
        parity_rel_tol=_env_float("BS_PARITY_REL_TOL", 1e-9),
        iv_roundtrip_rel_tol=_env_float("BS_IV_ROUNDTRIP_REL_TOL", 1e-8),
        iv_solve_rel_tol=_env_float("BS_IV_SOLVE_REL_TOL", 1e-12),
        iv_upper_bound=_env_float("BS_IV_UPPER_BOUND", 10.0),
        iv_max_iter=int(os.getenv("BS_IV_MAX_ITER", "120")),
        default_dividend_yield=_env_float("BS_DEFAULT_DIVIDEND_YIELD", 0.0),
        database_url=url,
        history_max_limit=int(os.getenv("BS_HISTORY_MAX_LIMIT", "500")),
    )


settings = load_settings()
