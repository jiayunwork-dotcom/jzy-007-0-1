# Black–Scholes 欧式期权定价核算服务

纯服务端数值定价组件：上游提交合约参数，返回欧式期权理论价格、`d1`/`d2`、
一阶希腊值（Delta / Gamma / Vega / Theta / Rho），并可由市场价格反解隐含波动率。
支持批量定价，每次核算请求与结果都持久化，可按条件查询历史。

不涉及下单、持仓、账户或前端页面。

## 快速开始

```bash
# 方式一：Docker Compose（服务 + PostgreSQL，一键启动）
docker compose up --build
# 服务监听 http://localhost:8000 ，交互式文档 http://localhost:8000/docs

# 方式二：本地直接运行（默认使用 /data 下的 SQLite，无需外部依赖）
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康/就绪探针（供监控采集）：

* `GET /health`：进程存活；
* `GET /ready`：就绪，同时探测数据库连通性（异常返回 503）。

## 代码结构

```
app/
├── config.py                 # 容差、默认分红率、数据库等配置（可用环境变量覆盖）
├── errors.py                 # 结构化业务错误
├── services.py               # 业务编排（不依赖 HTTP，测试可直接调用）
├── main.py                   # FastAPI 入口、中间件、统一异常处理、生命周期
├── pricing/
│   ├── dist.py               # 标准正态 CDF/PDF（基于 erf，无第三方数值库）
│   ├── black_scholes.py      # BS 定价（含 T=0 内在值与极限分支）
│   ├── greeks.py             # 一阶希腊值
│   ├── implied_vol.py        # 隐含波动率（无套利界检查 + 括号二分法）
│   └── validation.py         # 手写输入校验（可读、带字段名的错误）
├── api/
│   ├── schemas.py            # 最外层 JSON 结构模型
│   └── routes.py             # HTTP 路由
└── db/
    ├── session.py            # 引擎、会话、建表、连通性探测
    ├── models.py             # ORM 模型（calc_records / batch_records）
    └── repository.py         # 持久化与条件查询
tests/                        # 自动化测试（94 个用例）
```

## 接口

所有错误统一形如 `{"error": {"code", "message", "field", "details"}}`，
HTTP 状态码 422（参数类）/ 404（记录不存在）/ 503（未就绪）。

### 1. 定价 `POST /price`

请求：`S` 现货、`K` 执行价、`T` 剩余期限（年）、`r` 无风险利率、
`sigma` 波动率、方向（`option_type` 取 `call/put`，或布尔字段 `is_call`）；
`q` 连续分红率可选，缺省为 0。

```json
{"S": 42, "K": 40, "T": 0.5, "r": 0.1, "q": 0.0, "sigma": 0.2, "option_type": "call"}
```

返回：`price`、`d1`、`d2`、`intrinsic`、`expired`。
**`T = 0` 时不再套用未到期公式**，直接返回内在价值，`d1/d2` 为 `null`。

### 2. 希腊值 `POST /greeks`

入参与定价相同。返回价格、`d1/d2` 与：

| 希腊值 | 口径 |
|---|---|
| delta | ∂V/∂S |
| gamma | ∂²V/∂S²（看涨看跌相同） |
| vega | 波动率 +1 个百分点（0.01）对应的价格变化（看涨看跌相同） |
| theta | 日历时间每日损耗（365 天/年，Hull 口径，多头平值为负） |
| rho | 利率 +1 个百分点（0.01）对应的价格变化（看涨正、看跌负） |

恒等式：`Δcall − Δput = e^(−qT)`（对看涨看跌平价求现货偏导）。

### 3. 隐含波动率 `POST /implied-vol`

入参为除 `sigma` 外的全部合约参数加 `market_price`。服务：

1. 先做**无套利界**检查——看涨
   `max(S·e^(−qT) − K·e^(−rT), 0) ≤ C ≤ S·e^(−qT)`，看跌对称
   （下界 `max(K·e^(−rT) − S·e^(−qT), 0)`，上界 `K·e^(−rT)`）；
   界外市价返回 `iv_infeasible`，不给出无意义的波动率；
2. `T = 0` 时 IV 无定义（即使市价等于内在价值），同样返回不可行；
3. 括号二分法求解，结果代回定价，响应中 `roundtrip.within_tol`
   标明是否在钉死容差（默认相对 1e-8）内回到市价。

### 4. 批量定价 `POST /batch-price`

```json
{"items": [ {…合约1…}, {…合约2…} ]}
```

逐组独立计算：某组非法时错误带 `items[第N组].字段名` 与组号说明，
其余各组照常返回。每组（含失败组）都持久化到同一 `batch_id` 下。

### 5. 历史查询

* `GET /history`：支持 `endpoint`、`option_type`、`success`、`batch_id`、
  `start`/`end`（ISO-8601）、`limit`/`offset` 过滤；
* `GET /history/records/{record_id}`：取单条（响应头里也带 `record_id`）。

### 6. 配置回显与预置算例

* `GET /config`：回显平价/IV 闭合容差、IV 搜索参数与默认分红率；
* `GET /examples/atm-one-year`：平值、一年期、σ=20%、零利率零分红看涨，
  精确价 ≈ 7.9656，与经验式 `0.4·S·σ·√T = 8.0` 同量级；
* `GET /examples`：算例列表。

## 核算规则（由自动化测试钉死）

* 看涨看跌平价：`C − P = S·e^(−qT) − K·e^(−rT)`（相对容差 1e-9）；
* `T = 0`：看涨 `max(S−K,0)`、看跌 `max(K−S,0)`；
* 仅波动率升高 → 看涨、看跌价格都升高；仅利率升高 → 看涨升、看跌降；
* `S = K` 且 `r = q = 0` 时看涨价 = 看跌价；
* 看涨/看跌 Gamma 相同、Vega 相同；Rho 看涨为正、看跌为负；
* S、K 同比例缩放 → 价格同比例缩放，IV 不变；
* 非法输入（缺字段、非数值、NaN/Infinity、未知方向、
  `option_type` 与 `is_call` 互相矛盾、未知字段）一律结构化拒绝；
  `r`、`q` 允许零或负（负利率），但必须有限。

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest
```

覆盖：平价闭合、到期内在值、波动率/利率比较静态、平值零利率两边相等、
Gamma/Vega 相同、希腊值有限差分校验、IV 代回闭合与界外不可行、
非法参数拒绝、批量部分失败其余成功、历史持久化与条件查询、
以及 40+ 并发请求下的结果隔离与历史不乱序。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:////data/bs_pricing.db` | 数据库连接串（compose 中为 PostgreSQL） |
| `BS_PARITY_REL_TOL` | `1e-9` | 平价闭合相对容差 |
| `BS_IV_ROUNDTRIP_REL_TOL` | `1e-8` | IV 代回闭合相对容差 |
| `BS_IV_SOLVE_REL_TOL` | `1e-12` | 二分法收敛容差 |
| `BS_IV_UPPER_BOUND` | `10.0` | 反解波动率上界（1000%） |
| `BS_DEFAULT_DIVIDEND_YIELD` | `0.0` | 默认连续分红率 |
| `BS_HISTORY_MAX_LIMIT` | `500` | 历史查询单页上限 |
