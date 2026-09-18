"""定价核算规则测试（直连数值内核 + HTTP）。"""
from __future__ import annotations

import math

import pytest

from app.config import settings
from app.pricing import black_scholes as bs
from app.pricing import greeks as gk


def mk(S, K, T, r, q, sigma, is_call):
    return bs.BSParams(S=S, K=K, T=T, r=r, q=q, sigma=sigma, is_call=is_call)


def call_put(S, K, T, r=0.03, q=0.01, sigma=0.25):
    c = bs.price(mk(S, K, T, r, q, sigma, True)).price
    p = bs.price(mk(S, K, T, r, q, sigma, False)).price
    return c, p


@pytest.mark.parametrize("S,K,T,r,q,sigma", [
    (100, 100, 1.0, 0.03, 0.01, 0.25),
    (42, 40, 0.5, 0.10, 0.00, 0.20),
    (50, 60, 2.0, -0.02, 0.00, 0.40),
    (100, 90, 0.25, 0.05, 0.03, 0.15),
    (10, 10, 0.01, 0.0, 0.0, 0.5),
])
def test_put_call_parity_closes(S, K, T, r, q, sigma):
    """C - P = S·e^-qT - K·e^-rT，在钉死相对容差内闭合。"""
    c = bs.price(mk(S, K, T, r, q, sigma, True)).price
    p = bs.price(mk(S, K, T, r, q, sigma, False)).price
    rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
    residual = abs((c - p) - rhs)
    scale = max(abs(c - p), abs(rhs), 1.0)
    assert residual / scale <= settings.parity_rel_tol


def test_reference_hull_value():
    """Hull《期权期货及其他衍生产品》经典算例：S=42,K=40,T=0.5,r=10%,σ=20%。"""
    c = bs.price(mk(42, 40, 0.5, 0.10, 0.0, 0.20, True)).price
    assert c == pytest.approx(4.759422, rel=1e-5)


def test_expired_call_intrinsic():
    res = bs.price(mk(110, 100, 0.0, 0.05, 0.0, 0.3, True))
    assert res.expired is True
    assert res.price == 10.0
    assert res.d1 is None and res.d2 is None


def test_expired_put_zero_when_above_strike():
    res = bs.price(mk(110, 100, 0.0, 0.05, 0.0, 0.3, False))
    assert res.price == 0.0


def test_expired_call_zero_when_below_strike():
    assert bs.price(mk(90, 100, 0.0, 0.05, 0.0, 0.3, True)).price == 0.0


def test_expired_put_intrinsic_below_strike():
    assert bs.price(mk(90, 100, 0.0, 0.05, 0.0, 0.3, False)).price == 10.0


@pytest.mark.parametrize("is_call", [True, False])
def test_higher_vol_raises_both_prices(is_call):
    """只把波动率加大，看涨与看跌价格都必须上升。"""
    p1 = bs.price(mk(100, 100, 1, 0.03, 0.01, 0.15, is_call)).price
    p2 = bs.price(mk(100, 100, 1, 0.03, 0.01, 0.35, is_call)).price
    p3 = bs.price(mk(100, 100, 1, 0.03, 0.01, 0.80, is_call)).price
    assert p1 < p2 < p3


@pytest.mark.parametrize("q", [0.0, 0.02])
def test_higher_rate_call_up_put_down(q):
    """只把利率加大：看涨上升，看跌下降。"""
    c_lo = bs.price(mk(100, 100, 1, 0.00, q, 0.25, True)).price
    c_hi = bs.price(mk(100, 100, 1, 0.10, q, 0.25, True)).price
    p_lo = bs.price(mk(100, 100, 1, 0.00, q, 0.25, False)).price
    p_hi = bs.price(mk(100, 100, 1, 0.10, q, 0.25, False)).price
    assert c_hi > c_lo
    assert p_hi < p_lo


def test_atm_zero_rates_call_equals_put():
    c = bs.price(mk(100, 100, 1, 0.0, 0.0, 0.3, True)).price
    p = bs.price(mk(100, 100, 1, 0.0, 0.0, 0.3, False)).price
    assert c == pytest.approx(p, abs=1e-12)


def test_negative_rates_accepted():
    c = bs.price(mk(100, 100, 1, -0.01, -0.02, 0.25, True)).price
    assert math.isfinite(c) and c > 0


@pytest.mark.parametrize("scale", [0.01, 2.5, 137.0])
def test_spot_strike_scaling(scale):
    """S、K 同比例缩放，价格同比例缩放。"""
    base_c = bs.price(mk(100, 100, 1, 0.03, 0.01, 0.3, True)).price
    base_p = bs.price(mk(100, 100, 1, 0.03, 0.01, 0.3, False)).price
    sc_c = bs.price(mk(100 * scale, 100 * scale, 1, 0.03, 0.01, 0.3, True)).price
    sc_p = bs.price(mk(100 * scale, 100 * scale, 1, 0.03, 0.01, 0.3, False)).price
    assert sc_c / scale == pytest.approx(base_c, rel=1e-10)
    assert sc_p / scale == pytest.approx(base_p, rel=1e-10)


def test_atm_example_order_of_magnitude():
    """预置算例：平值一年期零分红，价格与 0.4·S·σ·√T 同量级。"""
    S, sigma, T = 100.0, 0.2, 1.0
    price_call = bs.price(mk(S, S, T, 0.0, 0.0, sigma, True)).price
    thumb = 0.4 * S * sigma * math.sqrt(T)
    assert 0.5 * thumb <= price_call <= 1.5 * thumb


def test_gamma_vega_identical():
    """看涨与看跌 Gamma、Vega 必须相同。"""
    gc = gk.greeks(mk(100, 100, 1, 0.03, 0.01, 0.25, True))
    gp = gk.greeks(mk(100, 100, 1, 0.03, 0.01, 0.25, False))
    assert gc.gamma == gp.gamma
    assert gc.vega == gp.vega
    assert gc.gamma > 0 and gc.vega > 0


def test_delta_bounds_zero_dividend():
    """q=0：看涨 Delta ∈ [0,1]，看跌 Delta ∈ [-1,0]。"""
    for S in (1.0, 50.0, 100.0, 250.0, 10000.0):
        for T in (1 / 365, 1.0, 5.0):
            dc = gk.greeks(mk(S, 100, T, 0.03, 0.0, 0.3, True)).delta
            dp = gk.greeks(mk(S, 100, T, 0.03, 0.0, 0.3, False)).delta
            assert 0.0 - 1e-12 <= dc <= 1.0 + 1e-12
            assert -1.0 - 1e-12 <= dp <= 0.0 + 1e-12


@pytest.mark.parametrize("q", [0.0, 0.02, 0.05])
def test_delta_spots_is_discounted_growth(q):
    """对平价关系求 S 偏导：Δc - Δp = e^-qT。"""
    T = 1.5
    gc = gk.greeks(mk(100, 100, T, 0.03, q, 0.3, True))
    gp = gk.greeks(mk(100, 100, T, 0.03, q, 0.3, False))
    assert gc.delta - gp.delta == pytest.approx(math.exp(-q * T), abs=1e-12)


def test_rho_signs():
    g = gk.greeks(mk(100, 100, 1, 0.03, 0.0, 0.25, True))
    gp = gk.greeks(mk(100, 100, 1, 0.03, 0.0, 0.25, False))
    assert g.rho > 0
    assert gp.rho < 0


def test_greeks_finite_difference():
    """一阶希腊值与有限差分一致（同时校验 Theta 口径）。"""
    S, K, T, r, q, sig = 100, 100, 1.0, 0.04, 0.02, 0.3
    g = gk.greeks(mk(S, K, T, r, q, sig, True))
    h = 1e-4
    # Delta
    up = bs.price(mk(S + h, K, T, r, q, sig, True)).price
    dn = bs.price(mk(S - h, K, T, r, q, sig, True)).price
    assert g.delta == pytest.approx((up - dn) / (2 * h), abs=1e-6)
    # Gamma
    assert g.gamma == pytest.approx((up - 2 * bs.price(mk(S, K, T, r, q, sig, True)).price + dn) / h ** 2, abs=1e-5)
    # Vega：年化 ∂V/∂σ = vega/0.01
    vs_up = bs.price(mk(S, K, T, r, q, sig + h, True)).price
    vs_dn = bs.price(mk(S, K, T, r, q, sig - h, True)).price
    assert g.vega / 0.01 == pytest.approx((vs_up - vs_dn) / (2 * h), abs=1e-5)
    # Rho：年化 ∂V/∂r = rho/0.01
    r_up = bs.price(mk(S, K, T, r + h, q, sig, True)).price
    r_dn = bs.price(mk(S, K, T, r - h, q, sig, True)).price
    assert g.rho / 0.01 == pytest.approx((r_up - r_dn) / (2 * h), abs=1e-4)
    # Theta（Hull 日历时间口径 ∂V/∂t = -∂V/∂T）：每日 = -年化/365
    t_up = bs.price(mk(S, K, T + h, r, q, sig, True)).price
    t_dn = bs.price(mk(S, K, T - h, r, q, sig, True)).price
    annual_dv_dt = -(t_up - t_dn) / (2 * h)
    assert g.theta == pytest.approx(annual_dv_dt / 365.0, abs=1e-6)


def test_expired_greeks():
    gc = gk.greeks(mk(110, 100, 0.0, 0.0, 0.0, 0.2, True))
    assert gc.delta == 1.0 and gc.gamma == gc.vega == gc.theta == gc.rho == 0.0
    gp = gk.greeks(mk(90, 100, 0.0, 0.0, 0.0, 0.2, False))
    assert gp.delta == -1.0
    atm_c = gk.greeks(mk(100, 100, 0.0, 0.0, 0.0, 0.2, True))
    atm_p = gk.greeks(mk(100, 100, 0.0, 0.0, 0.0, 0.2, False))
    assert atm_c.delta == 0.5 and atm_p.delta == -0.5


# ---- HTTP 层：到期语义、算例、回显 ---------------------------------------

def test_http_expired_returns_intrinsic(client):
    r = client.post("/price", json={
        "S": 110, "K": 100, "T": 0, "r": 0, "sigma": 0.2, "option_type": "call"})
    body = r.json()
    assert r.status_code == 200
    assert body["price"] == 10.0 and body["expired"] is True
    assert body["d1"] is None


def test_http_example_endpoint(client):
    r = client.get("/examples/atm-one-year")
    assert r.status_code == 200
    body = r.json()
    assert body["price"] == pytest.approx(7.965567, rel=1e-5)
    assert body["rule_of_thumb"]["value"] == 8.0


def test_config_echoes_tolerance_and_default_q(client):
    r = client.get("/config")
    cfg = r.json()["tolerances_and_defaults"]
    assert cfg["parity_rel_tol"] == settings.parity_rel_tol
    assert cfg["iv_roundtrip_rel_tol"] == settings.iv_roundtrip_rel_tol
    assert cfg["default_dividend_yield"] == 0.0
