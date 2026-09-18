"""定价核心规则：平价闭合、到期内在值、单调性、齐次性、预置算例量级。"""
import math

import pytest

from app import config
from app.pricing import OptionParams, d1_d2, price


def make_params(**overrides) -> OptionParams:
    base = dict(spot=100.0, strike=100.0, expiry=1.0, rate=0.05,
                sigma=0.2, dividend=0.0, option_type="call")
    base.update(overrides)
    return OptionParams(**base)


CASES = [
    (100.0, 100.0, 1.0, 0.05, 0.0, 0.2),
    (80.0, 120.0, 0.5, 0.03, 0.01, 0.35),
    (100.0, 90.0, 2.0, -0.01, 0.02, 0.15),   # 负利率
    (50.0, 50.0, 0.25, 0.0, 0.0, 0.6),
    (200.0, 150.0, 1.5, 0.08, 0.04, 0.1),
]


def test_put_call_parity_closes_within_pinned_tolerance():
    for s, k, t, r, q, sig in CASES:
        call = price(make_params(spot=s, strike=k, expiry=t, rate=r,
                                 dividend=q, sigma=sig, option_type="call"))
        put = price(make_params(spot=s, strike=k, expiry=t, rate=r,
                                dividend=q, sigma=sig, option_type="put"))
        rhs = s * math.exp(-q * t) - k * math.exp(-r * t)
        assert abs((call - put) - rhs) <= config.PARITY_REL_TOL * max(1.0, abs(rhs))


def test_expiry_returns_intrinsic_value():
    # S > K：看跌为零，看涨为 S-K
    assert price(make_params(expiry=0.0, spot=120.0, option_type="call")) == 20.0
    assert price(make_params(expiry=0.0, spot=120.0, option_type="put")) == 0.0
    # S < K：看涨为零，看跌为 K-S
    assert price(make_params(expiry=0.0, spot=80.0, option_type="call")) == 0.0
    assert price(make_params(expiry=0.0, spot=80.0, option_type="put")) == 20.0
    # S == K：两边都为零
    assert price(make_params(expiry=0.0, spot=100.0, option_type="call")) == 0.0
    assert price(make_params(expiry=0.0, spot=100.0, option_type="put")) == 0.0


def test_price_increases_with_sigma_for_both_sides():
    sigmas = (0.05, 0.1, 0.2, 0.35, 0.6)
    calls = [price(make_params(sigma=s)) for s in sigmas]
    puts = [price(make_params(sigma=s, option_type="put")) for s in sigmas]
    assert all(b > a for a, b in zip(calls, calls[1:]))
    assert all(b > a for a, b in zip(puts, puts[1:]))


def test_rate_increase_raises_call_lowers_put():
    rates = (0.0, 0.02, 0.05, 0.10)
    calls = [price(make_params(rate=r)) for r in rates]
    puts = [price(make_params(rate=r, option_type="put")) for r in rates]
    assert all(b > a for a, b in zip(calls, calls[1:]))
    assert all(b < a for a, b in zip(puts, puts[1:]))


def test_atm_zero_rate_zero_dividend_call_equals_put():
    call = price(make_params(rate=0.0, dividend=0.0))
    put = price(make_params(rate=0.0, dividend=0.0, option_type="put"))
    assert call == pytest.approx(put, rel=1e-12)


def test_scaling_spot_and_strike_scales_price():
    base_call = price(make_params())
    base_put = price(make_params(option_type="put"))
    for factor in (0.5, 2.0, 7.3):
        scaled_call = price(make_params(spot=100.0 * factor, strike=100.0 * factor))
        scaled_put = price(make_params(spot=100.0 * factor, strike=100.0 * factor,
                                       option_type="put"))
        assert scaled_call == pytest.approx(factor * base_call, rel=1e-12)
        assert scaled_put == pytest.approx(factor * base_put, rel=1e-12)


def test_atm_call_matches_0_4_S_sigma_sqrtT_magnitude():
    # 平值、一年期、中等波动率、零分红：C ≈ 0.4·S·σ·√T
    call = price(make_params(rate=0.0, dividend=0.0, sigma=0.2, expiry=1.0))
    rule = 0.4 * 100.0 * 0.2 * math.sqrt(1.0)
    assert abs(call / rule - 1.0) < 0.05


def test_d1_d2_relationship_and_none_at_expiry():
    d1, d2 = d1_d2(make_params(sigma=0.3, expiry=0.5))
    assert d2 == pytest.approx(d1 - 0.3 * math.sqrt(0.5), rel=1e-12)
    assert d1_d2(make_params(expiry=0.0)) == (None, None)


def test_negative_rate_and_dividend_are_computable():
    value = price(make_params(rate=-0.02, dividend=-0.005))
    assert math.isfinite(value) and value > 0
