"""持久化：每次核算请求与结果入库，可按条件查询；失败请求同样留痕。"""
import pytest


def payload(**overrides):
    base = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
            "sigma": 0.2, "option_type": "call"}
    base.update(overrides)
    return base


def test_price_request_and_result_persisted(client):
    body = client.post("/price", json=payload(S=111.0)).json()
    records = client.get("/history", params={"endpoint": "price", "limit": 500}).json()
    match = [r for r in records["records"]
             if r["spot"] == 111.0 and r["status"] == "ok"]
    assert match, "定价请求未入库"
    rec = match[0]
    assert rec["price"] == pytest.approx(body["price"])
    assert rec["d1"] == pytest.approx(body["d1"])
    assert rec["option_type"] == "call"
    assert rec["sigma"] == 0.2
    assert rec["created_at"]


def test_greeks_persisted_with_all_greeks(client):
    body = client.post("/greeks", json=payload(S=112.0)).json()
    records = client.get("/history", params={"endpoint": "greeks", "limit": 500}).json()
    rec = [r for r in records["records"] if r["spot"] == 112.0][0]
    for key in ("delta", "gamma", "vega", "theta", "rho"):
        assert rec[key] == pytest.approx(body[key])


def test_implied_vol_persisted(client):
    market = client.post("/price", json=payload(sigma=0.3)).json()["price"]
    iv_payload = payload()
    del iv_payload["sigma"]
    iv_payload["market_price"] = market
    body = client.post("/implied-vol", json=iv_payload).json()
    records = client.get(
        "/history", params={"endpoint": "implied-vol", "limit": 500}
    ).json()
    rec = [r for r in records["records"]
           if r["market_price"] == pytest.approx(market)][0]
    assert rec["implied_vol"] == pytest.approx(body["implied_vol"])
    assert rec["status"] == "ok"


def test_failed_request_persisted_with_error_detail(client):
    client.post("/price", json=payload(sigma=-5.0))
    records = client.get("/history", params={"status": "error", "limit": 500}).json()
    assert any(r["error_param"] == "sigma" and r["error_message"]
               for r in records["records"])


def test_batch_items_persisted_individually(client):
    items = [payload(S=130.0), payload(sigma=-1.0), payload(S=140.0, option_type="put")]
    batch = client.post("/batch/price", json={"items": items}).json()
    records = client.get(
        "/history", params={"batch_id": batch["batch_id"], "limit": 10}
    ).json()
    assert records["total"] == 3
    by_index = {r["batch_index"]: r for r in records["records"]}
    assert by_index[0]["status"] == "ok" and by_index[0]["spot"] == 130.0
    assert by_index[1]["status"] == "error" and by_index[1]["error_param"] == "sigma"
    assert by_index[2]["status"] == "ok" and by_index[2]["option_type"] == "put"


def test_history_filters_by_option_type(client):
    client.post("/price", json=payload(S=151.0, option_type="put"))
    records = client.get(
        "/history", params={"option_type": "put", "limit": 500}
    ).json()
    assert records["records"]
    assert all(r["option_type"] == "put" for r in records["records"])
    assert any(r["spot"] == 151.0 for r in records["records"])
