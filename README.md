# Black-Scholes 欧式期权定价核算服务

纯服务端的数值定价组件：上游提交合约参数，服务返回理论价格、d1/d2 与一阶希腊值，
并能从市场价格反解隐含波动率。不涉及下单、持仓、账户体系或任何前端页面。

## 快速开始

### Docker Compose（一键构建并启动服务与其依赖）

```bash
docker compose up --build
```

会启动两个服务：`api`（FastAPI，端口 8000）与 `db`（PostgreSQL 16，持久化核算记录）。
服务就绪后访问 http://localhost:8000/docs 查看交互式接口文档。

### 本地运行（SQLite，无外部依赖）

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

### 运行测试

```bash
pytest -q                 # 本地
docker compose run --rm api pytest -q   # 容器内（测试自动切换到临时 SQLite）
```

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/price` | 单张定价：返回理论价格与 d1/d2 |
| POST | `/greeks` | 同一组参数返回价格、d1/d2 与 Delta/Gamma/Vega/Theta/Rho |
| POST | `/implied-vol` | 由市场价格反解隐含波动率 |
| POST | `/batch/price` | 批量定价，单组非法不影响其余各组 |
| GET | `/history` | 历史核算记录条件查询 |
| GET | `/config` | 回显当前钉死的容差与默认分红率 |
| GET | `/example` | 预置算例（平值、一年期、中等波动率、零分红） |
| GET | `/health` | 运行状态，供监控采集 |

### 定价 `/price`

```bash
curl -X POST localhost:8000/price -H 'Content-Type: application/json' -d '{
  "S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.2, "option_type": "call"
}'
```

```json
{"status": "ok", "price": 10.4506, "d1": 0.35, "d2": 0.15,
 "params": {"S": 100, "K": 100, "T": 1.0, "r": 0.05, "q": 0.0, "sigma": 0.2, "option_type": "call"}}
```

- `q`（连续分红率）可选，缺省为 0；`r` 与 `q` 允许为零或负（负利率场景），但必须有限。
- `T == 0` 时不套用未到期公式，直接返回内在价值（d1/d2 返回 null）。
- 方向也可写成 `"is_call": true/false`；若与 `option_type` 同时给出且互相矛盾，返回 400。

### 隐含波动率 `/implied-vol`

```bash
curl -X POST localhost:8000/implied-vol -H 'Content-Type: application/json' -d '{
  "S": 100, "K": 100, "T": 1.0, "r": 0.05, "market_price": 10.4506, "option_type": "call"
}'
```

解出的波动率代回定价后，在钉死的相对容差（默认 1e-6）内回到原市价。
市价落在无套利界外（看涨 `[max(S·e^-qT − K·e^-rT, 0), S·e^-qT]`，看跌对称）、
或期限为零时，返回 `{"status": "infeasible", "reason": ...}`，绝不给出无意义的波动率。

### 批量定价 `/batch/price`

```bash
curl -X POST localhost:8000/batch/price -H 'Content-Type: application/json' -d '{
  "items": [
    {"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0.2, "option_type": "call"},
    {"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": -1, "option_type": "call"}
  ]
}'
```

每组结果带 `index`；非法组返回 `status: "error"` 及出问题的 `param` 与可读 `message`，其余各组照常返回。

### 历史查询 `/history`

```
GET /history?endpoint=price&option_type=call&status=ok&limit=50&offset=0
GET /history?batch_id=<id>
```

每次核算请求与结果（含失败与不可行留痕）都会持久化，可按接口、方向、状态、批次过滤。

## 错误模型

非法输入（缺字段、非数值、NaN/无穷、未知方向、方向字段矛盾、S/K/σ 非正、T 为负）
一律返回 HTTP 400 与结构化说明，绝不静默算出看似正常的错误数：

```json
{"detail": {"error": "invalid_parameter", "param": "sigma", "message": "波动率必须为正数，收到 -0.2"}}
```

## 数值约定

- Vega 为波动率变动 1.00 对应的价格变动；Theta 为每自然年；Rho 为利率变动 1.00。
- 看涨与看跌共用同一 Gamma、Vega；`Delta_call − Delta_put = e^(−qT)`。
- 钉死的容差集中在 `app/config.py` 并经 `/config` 回显：
  平价闭合 1e-9、隐含波动率代回 1e-6、无套利界判定 1e-9（均为相对容差）。

## 代码结构

```
app/
  config.py       # 钉死的容差与默认配置
  pricing.py      # d1/d2、理论价格、到期内在价值
  greeks.py       # Delta/Gamma/Vega/Theta/Rho
  implied_vol.py  # 无套利界检验 + 二分反解
  validation.py   # 输入校验，结构化 ParamError
  db.py           # 引擎、会话、记录表
  repository.py   # 记录写入与条件查询
  main.py         # FastAPI 接口装配
tests/            # 82 个自动化测试，覆盖全部核算规则
```
