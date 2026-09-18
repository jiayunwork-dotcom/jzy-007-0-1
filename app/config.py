"""全局配置：钉死的数值容差与默认参数。

所有容差集中在此定义，/config 接口直接回显本模块内容，
测试也以本模块为基准做闭合校验，避免“两处各写一份容差”漂移。
"""
import os

# 缺省连续分红率
DEFAULT_Q = 0.0

# 看涨看跌平价闭合的相对容差（钉死）
PARITY_REL_TOL = 1e-9

# 隐含波动率代回定价后必须闭合的相对容差（钉死）
IV_ROUNDTRIP_REL_TOL = 1e-6

# 无套利界判断的相对容差（钉死）
BOUND_REL_TOL = 1e-9

# 隐含波动率二分求解参数
IV_MIN_SIGMA = 1e-9
IV_MAX_SIGMA = 10.0
IV_MAX_SIGMA_CAP = 100.0   # 极端情形下允许扩张到的上限
IV_MAX_ITER = 200

# 持久化连接串：缺省本地 SQLite，Docker Compose 下注入 PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bs_pricing.db")
