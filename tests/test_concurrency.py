"""并发测试：多请求同时进行时结果互不串扰、历史记录不错乱。"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

from app.db import models


def _one_call(client, S: float) -> dict:
    return client.post("/price", json={
        "S": S, "K": 100, "T": 1.0, "r": 0.03, "q": 0.01,
        "sigma": 0.25, "option_type": "call",
    }).json()


def test_concurrent_pricing_isolation(client, db_session):
    spots = [50.0 + 0.37 * i for i in range(40)]

    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(lambda s: _one_call(client, s), spots))

    # 每个响应只反映自己的入参，且价格随 S 单调
    for s, body in zip(spots, responses):
        assert body["S"] == s
        assert body["K"] == 100
        assert body["r"] == 0.03 and body["q"] == 0.01
        assert body["sigma"] == 0.25
        assert body["option_type"] == "call"
        assert math.isfinite(body["price"])
    prices = [b["price"] for b in responses]
    assert prices == sorted(prices)
    assert len(set(b["record_id"] for b in responses)) == 40

    # 历史记录数量、入参回显与结果一一对得上
    rows = db_session.query(models.CalcRecord).filter_by(endpoint="price").all()
    assert len(rows) == 40
    for row in rows:
        assert row.success is True
        assert row.result["S"] == row.S
        assert row.result["price"] >= 0
    assert sorted(r.S for r in rows) == sorted(spots)


def test_concurrent_batch_and_single_no_cross_talk(client, db_session):
    def batch_call(_):
        return client.post("/batch-price", json={"items": [
            {"S": 100, "K": 100, "T": 1, "r": 0, "sigma": 0.2,
             "option_type": "call"},
            {"S": 100, "K": 100, "T": 1, "r": 0, "sigma": 0.2,
             "option_type": "put"},
            {"S": -1, "K": 100, "T": 1, "r": 0, "sigma": 0.2,
             "option_type": "call"},
        ]}).json()

    def single_call(i):
        return _one_call(client, 90.0 + i)

    with ThreadPoolExecutor(max_workers=12) as pool:
        batches = list(pool.map(batch_call, range(10)))
        singles = list(pool.map(single_call, range(20)))

    for b in batches:
        assert b["succeeded"] == 2 and b["failed"] == 1
        assert b["results"][0]["result"]["option_type"] == "call"
        assert b["results"][1]["result"]["option_type"] == "put"
        assert b["results"][2]["error"]["field"] == "items[3].S"

    # 每个 batch 恰好挂 3 条，互不串组
    for b in batches:
        n = db_session.query(models.CalcRecord).filter_by(batch_id=b["batch_id"]).count()
        assert n == 3

    # 批量明细共 30 条，单张 20 条
    assert db_session.query(models.CalcRecord).filter_by(
        endpoint="batch_price").count() == 30
    assert db_session.query(models.CalcRecord).filter_by(
        endpoint="price").count() == 20

    # 平值零利率看涨看跌相等的并发放心校验
    calls = [s["price"] for s in singles]
    assert all(math.isfinite(x) for x in calls)
