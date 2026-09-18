"""批量定价（部分失败其余成功）与历史持久化、条件查询测试。"""
from __future__ import annotations

from app.db import models


GOOD_CALL = {"S": 100, "K": 100, "T": 1, "r": 0.03,
             "sigma": 0.2, "option_type": "call"}


def test_batch_partial_failure(client, db_session):
    items = [
        dict(GOOD_CALL),
        {**GOOD_CALL, "S": 0},                       # 非法：第 2 组
        {**GOOD_CALL, "option_type": "put", "T": 0}, # 到期看跌，合法
        {**GOOD_CALL, "sigma": -1},                  # 非法：第 4 组
        {**GOOD_CALL, "S": 120},                     # 合法
    ]
    r = client.post("/batch-price", json={"items": items})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5 and body["succeeded"] == 3 and body["failed"] == 2

    e2 = body["results"][1]
    assert e2["ok"] is False
    assert e2["error"]["field"] == "items[2].S"
    assert "第几组" in e2["error"]["message"] or e2["error"]["field"].startswith("items[2]")

    e3 = body["results"][2]
    assert e3["ok"] is True
    assert e3["result"]["price"] == 0.0  # 平值到期看跌

    # 每组（含失败组）都持久化，并挂在同一个 batch_id 下
    rows = db_session.query(models.CalcRecord).filter_by(
        batch_id=body["batch_id"]).order_by(models.CalcRecord.item_index).all()
    assert len(rows) == 5
    assert [x.item_index for x in rows] == [1, 2, 3, 4, 5]
    assert rows[1].success is False
    assert rows[1].error_field == "S"  # 库里存原始字段名，序号在 item_index
    assert rows[0].success is True
    assert rows[0].result["price"] > 0

    summary = db_session.get(models.BatchRecord, body["batch_id"])
    assert (summary.total, summary.succeeded, summary.failed) == (5, 3, 2)


def test_batch_empty_items_rejected(client):
    r = client.post("/batch-price", json={"items": []})
    # 空批量：允许提交但结果为空——这里按"可执行空作业"返回 0
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_batch_malformed_items(client):
    r = client.post("/batch-price", json={"items": "not-a-list"})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "items"


def test_batch_unknown_top_field(client):
    r = client.post("/batch-price", json={"items": [], "extra": 1})
    assert r.status_code == 422


def test_batch_non_object_element_reports_index(client, db_session):
    r = client.post("/batch-price", json={"items": [dict(GOOD_CALL), 42]})
    body = r.json()
    assert body["failed"] == 1 and body["succeeded"] == 1
    err = body["results"][1]["error"]
    assert err["field"] == "items[2]"


def test_history_persists_success_and_failure(client, db_session):
    client.post("/price", json=dict(GOOD_CALL))
    client.post("/price", json={**GOOD_CALL, "S": -1})
    client.post("/greeks", json=dict(GOOD_CALL, option_type="put"))

    r = client.get("/history")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3
    endpoints = {x["endpoint"] for x in items}
    assert endpoints == {"price", "greeks"}

    failed = [x for x in items if not x["success"]]
    assert len(failed) == 1 and failed[0]["error"]["code"] == "invalid_parameter"

    # 成功记录的结果体完整可查
    ok = [x for x in items if x["success"] and x["endpoint"] == "price"][0]
    assert ok["result"]["price"] > 0
    assert ok["params"]["S"] == 100.0


def test_history_filters(client, db_session):
    client.post("/price", json=dict(GOOD_CALL))
    client.post("/price", json=dict(GOOD_CALL, option_type="put"))
    client.post("/greeks", json=dict(GOOD_CALL))

    only_call = client.get("/history?option_type=call").json()
    assert all(x["params"]["option_type"] == "call" for x in only_call["items"])
    assert len(only_call["items"]) == 2  # price call + greeks call

    only_price = client.get("/history?endpoint=price").json()
    assert len(only_price["items"]) == 2
    assert all(x["endpoint"] == "price" for x in only_price["items"])

    only_ok = client.get("/history?success=true").json()
    assert all(x["success"] for x in only_ok["items"])
    assert only_ok["total"] == 3


def test_history_record_by_id(client):
    rid = client.post("/price", json=dict(GOOD_CALL)).json()["record_id"]
    r = client.get(f"/history/records/{rid}")
    assert r.status_code == 200
    assert r.json()["record_id"] == rid

    assert client.get("/history/records/does-not-exist").status_code == 404


def test_history_invalid_filter(client):
    assert client.get("/history?option_type=cap").status_code == 422
    assert client.get("/history?start=not-a-date").status_code == 422


def test_batch_records_queryable_by_batch_id(client):
    b = client.post("/batch-price", json={"items": [dict(GOOD_CALL)]}).json()
    r = client.get(f"/history?batch_id={b['batch_id']}")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["batch_id"] == b["batch_id"]
