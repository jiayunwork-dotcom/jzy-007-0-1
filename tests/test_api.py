"""HTTP 接口行为：正常核算、结构化错误、批量部分失败、预置算例。"""
import json
import math

import pytest

from app import config


def price_payload(**overrides):
    payload = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
               "sigma": 0.2, "option_type": "call"}
    payload.update(overrides)
    return payload


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["db"] == "ok"


def test_config_echoes_tolerances_and_default_dividend(client):
    body = client.get("/config").json()
    assert body["default_dividend_yield"] == config.DEFAULT_Q
    assert body["parity_rel_tol"] == config.PARITY_REL_TOL
    assert body["iv_roundtrip_rel_tol"] == config.IV_ROUNDTRIP_REL_TOL
    assert body["bound_rel_tol"] == config.BOUND_REL_TOL


def test_price_returns_price_and_d1_d2(client):
    resp = client.post("/price", json=price_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["price"] == pytest.approx(10.4506, abs=1e-3)
    assert body["d1"] is not None and body["d2"] is not None
    assert body["d2"] == pytest.approx(body["d1"] - 0.2)


def test_price_at_expiry_returns_intrinsic(client):
    resp = client.post("/price", json=price_payload(S=120.0, T=0.0))
    body = resp.json()
    assert body["price"] == 20.0
    assert body["d1"] is None and body["d2"] is None
    resp = client.post("/price", json=price_payload(S=120.0, T=0.0, option_type="put"))
    assert resp.json()["price"] == 0.0


def test_price_rejects_invalid_sigma_with_readable_error(client):
    resp = client.post("/price", json=price_payload(sigma=-0.2))
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["param"] == "sigma"
    assert detail["message"]


def test_price_rejects_missing_field(client):
    payload = price_payload()
    del payload["K"]
    resp = client.post("/price", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "K"


def test_price_rejects_non_numeric(client):
    resp = client.post("/price", json=price_payload(S="一百"))
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "S"


def test_price_rejects_non_finite(client):
    # JSON 规范外的 NaN/Infinity 需要手工序列化注入
    body = json.dumps(price_payload(r=float("nan")))
    resp = client.post("/price", content=body,
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "r"


def test_price_rejects_unknown_option_type(client):
    resp = client.post("/price", json=price_payload(option_type="binary"))
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "option_type"


def test_price_rejects_contradictory_direction_fields(client):
    resp = client.post("/price", json=price_payload(is_call=False))
    assert resp.status_code == 400
    assert "矛盾" in resp.json()["detail"]["message"]


def test_price_accepts_is_call_only(client):
    payload = price_payload()
    del payload["option_type"]
    resp = client.post("/price", json={**payload, "is_call": False})
    assert resp.status_code == 200
    assert resp.json()["params"]["option_type"] == "put"


def test_greeks_endpoint(client):
    call = client.post("/greeks", json=price_payload()).json()
    put = client.post("/greeks", json=price_payload(option_type="put")).json()
    for key in ("delta", "gamma", "vega", "theta", "rho"):
        assert key in call
    assert call["gamma"] == pytest.approx(put["gamma"], rel=1e-12)
    assert call["vega"] == pytest.approx(put["vega"], rel=1e-12)
    assert 0.0 <= call["delta"] <= 1.0
    assert -1.0 <= put["delta"] <= 0.0
    assert call["delta"] - put["delta"] == pytest.approx(1.0, rel=1e-12)
    assert call["rho"] > 0.0 and put["rho"] < 0.0


def test_greeks_rejected_at_expiry(client):
    resp = client.post("/greeks", json=price_payload(T=0.0))
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "T"


def test_implied_vol_roundtrip(client):
    market = client.post("/price", json=price_payload(sigma=0.25)).json()["price"]
    payload = price_payload()
    del payload["sigma"]
    payload["market_price"] = market
    body = client.post("/implied-vol", json=payload).json()
    assert body["status"] == "ok"
    assert body["implied_vol"] == pytest.approx(0.25, rel=1e-4)
    assert body["roundtrip_price"] == pytest.approx(
        market, rel=config.IV_ROUNDTRIP_REL_TOL
    )


def test_implied_vol_out_of_bounds_returns_infeasible(client):
    payload = price_payload()
    del payload["sigma"]
    payload["market_price"] = 150.0  # 高于上界 S·e^-qT = 100
    body = client.post("/implied-vol", json=payload).json()
    assert body["status"] == "infeasible"
    assert "implied_vol" not in body
    assert body["no_arbitrage_bounds"]["upper"] == pytest.approx(100.0)


def test_implied_vol_zero_expiry_infeasible(client):
    payload = price_payload(T=0.0, S=120.0)
    del payload["sigma"]
    payload["market_price"] = 20.0  # 恰等于内在价值
    body = client.post("/implied-vol", json=payload).json()
    assert body["status"] == "infeasible"


def test_batch_partial_failure_others_succeed(client):
    items = [
        price_payload(S=100.0),
        price_payload(sigma=-1.0),          # 非法：sigma 非正
        price_payload(S=120.0, option_type="put"),
        {"S": 100.0},                        # 非法：缺字段
    ]
    resp = client.post("/batch/price", json={"items": items})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["index"] for r in results] == [0, 1, 2, 3]
    assert results[0]["status"] == "ok" and results[0]["price"] > 0
    assert results[1]["status"] == "error" and results[1]["param"] == "sigma"
    assert results[2]["status"] == "ok"
    assert results[3]["status"] == "error" and results[3]["param"]


def test_batch_rejects_malformed_request(client):
    resp = client.post("/batch/price", json={"items": "not-a-list"})
    assert resp.status_code == 400
    resp = client.post("/batch/price", json={"items": []})
    assert resp.status_code == 400


def test_example_preset_case(client):
    body = client.get("/example").json()
    assert body["params"]["q"] == 0.0
    assert body["params"]["T"] == 1.0
    # 看涨价格与 0.4·S·σ·√T 同量级
    assert abs(body["ratio"] - 1.0) < 0.05
    # 平值且 r=q=0：看涨必须等于看跌
    assert body["call_price"] == pytest.approx(body["put_price"], rel=1e-9)


def test_malformed_json_body(client):
    resp = client.post("/price", content="{not json",
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "malformed_request"
