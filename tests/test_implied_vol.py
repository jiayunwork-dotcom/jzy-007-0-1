"""隐含波动率测试：代回闭合、无套利界、缩放不变性、到期不可行。"""
from __future__ import annotations

import math

import pytest

from app.config import settings
from app.errors import IVInfeasibleError
from app.pricing import black_scholes as bs
from app.pricing import implied_vol as ivm


def mk(S, K, T, r, q, sigma, is_call):
    return bs.BSParams(S=S, K=K, T=T, r=r, q=q, sigma=sigma, is_call=is_call)


@pytest.mark.parametrize("is_call", [True, False])
@pytest.mark.parametrize("S,K,T,r,q,sigma", [
    (100, 100, 1.0, 0.03, 0.01, 0.25),
    (42, 40, 0.5, 0.10, 0.00, 0.20),
    (100, 120, 2.0, 0.02, 0.03, 0.55),
    (50, 48, 0.1, -0.01, 0.0, 0.12),
])
def test_iv_roundtrip_closes(S, K, T, r, q, sigma, is_call):
    """解出的 IV 代回定价，必须在钉死相对容差内回到市价。"""
    market = bs.price(mk(S, K, T, r, q, sigma, is_call)).price
    res = ivm.implied_volatility(S, K, T, r, q, is_call, market)
    back = bs.price(mk(S, K, T, r, q, res.implied_vol, is_call)).price
    rel = abs(back - market) / max(abs(market), 1e-300)
    assert res.converged
    assert res.implied_vol == pytest.approx(sigma, rel=1e-7)
    assert rel <= settings.iv_roundtrip_rel_tol or abs(back - market) <= 1e-10


def test_iv_below_lower_bound_infeasible():
    # 看涨下界 = S·e^-qT - K·e^-rT = 100 - 100·e^-0.05 ≈ 4.877
    with pytest.raises(IVInfeasibleError) as ei:
        ivm.implied_volatility(100, 100, 1, 0.05, 0.0, True, 1.0)
    assert ei.value.details["reason"] == "below_lower_bound"
    assert ei.value.details["lower_bound"] == pytest.approx(
        100 - 100 * math.exp(-0.05), rel=1e-10)


def test_iv_above_upper_bound_infeasible():
    with pytest.raises(IVInfeasibleError) as ei:
        ivm.implied_volatility(100, 100, 1, 0.0, 0.0, True, 100.5)
    assert ei.value.details["reason"] == "above_upper_bound"


def test_iv_put_bounds_infeasible():
    # 看跌上界 = K·e^-rT
    with pytest.raises(IVInfeasibleError) as ei:
        ivm.implied_volatility(100, 100, 1, 0.05, 0.0, False, 100.0)
    assert ei.value.details["reason"] == "above_upper_bound"
    # 看跌下界 = K·e^-rT - S·e^-qT，取 max 0
    with pytest.raises(IVInfeasibleError) as ei2:
        ivm.implied_volatility(100, 100, 1, 0.0, 0.05, False, 1.0)
    assert ei2.value.details["reason"] == "below_lower_bound"


def test_iv_expired_infeasible_even_at_intrinsic():
    """T=0 且市价等于内在价值，IV 无定义，按不可行处理。"""
    with pytest.raises(IVInfeasibleError) as ei:
        ivm.implied_volatility(110, 100, 0.0, 0.0, 0.0, True, 10.0)
    assert ei.value.details["reason"] == "expired"


def test_iv_at_lower_bound_t_positive_returns_zero():
    """T>0 市价恰好等于贴现内在值，极限解为 0，不报错。"""
    lower = 100 - 100 * math.exp(-0.05)
    res = ivm.implied_volatility(100, 100, 1, 0.05, 0.0, True, lower)
    assert res.implied_vol == 0.0
    assert res.at_bound is True


def test_iv_invariant_under_scaling():
    """S、K 同比例缩放，市价同比例缩放，IV 保持不变。"""
    market = bs.price(mk(100, 100, 1, 0.03, 0.01, 0.33, True)).price
    a = ivm.implied_volatility(100, 100, 1, 0.03, 0.01, True, market).implied_vol
    b = ivm.implied_volatility(730, 730, 1, 0.03, 0.01, True, market * 7.3).implied_vol
    assert a == pytest.approx(b, rel=1e-8)
    assert a == pytest.approx(0.33, rel=1e-7)


def test_http_iv_roundtrip(client):
    market = bs.price(mk(42, 40, 0.5, 0.1, 0.0, 0.2, True)).price
    r = client.post("/implied-vol", json={
        "S": 42, "K": 40, "T": 0.5, "r": 0.1, "market_price": market,
        "option_type": "call"})
    assert r.status_code == 200
    body = r.json()
    assert body["implied_vol"] == pytest.approx(0.2, abs=1e-7)
    assert body["roundtrip"]["within_tol"] is True


def test_http_iv_infeasible(client):
    r = client.post("/implied-vol", json={
        "S": 100, "K": 100, "T": 1, "r": 0, "market_price": 101,
        "option_type": "call"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "iv_infeasible"
    assert err["details"]["reason"] == "above_upper_bound"


def test_http_iv_sigma_field_rejected(client):
    r = client.post("/implied-vol", json={
        "S": 100, "K": 100, "T": 1, "r": 0, "sigma": 0.2,
        "market_price": 8, "option_type": "call"})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "sigma"
