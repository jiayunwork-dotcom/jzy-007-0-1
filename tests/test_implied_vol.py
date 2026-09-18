"""隐含波动率：代回闭合、界外不可行、到期不可行、缩放不变。"""
import math
from dataclasses import replace

import pytest

from app import config
from app.errors import InfeasibleError
from app.implied_vol import implied_vol, no_arbitrage_bounds
from app.pricing import OptionParams, price


def make_params(**overrides) -> OptionParams:
    base = dict(spot=100.0, strike=100.0, expiry=1.0, rate=0.05,
                sigma=0.2, dividend=0.0, option_type="call")
    base.update(overrides)
    return OptionParams(**base)


SOLVE_CASES = [
    (100.0, 100.0, 1.0, 0.05, 0.0, 0.25, "call"),
    (100.0, 100.0, 1.0, 0.05, 0.0, 0.25, "put"),
    (80.0, 120.0, 0.5, 0.03, 0.01, 0.4, "call"),
    (150.0, 100.0, 2.0, -0.01, 0.02, 0.15, "put"),
    (100.0, 100.0, 0.75, 0.0, 0.0, 0.6, "call"),
]


@pytest.mark.parametrize("s,k,t,r,q,sig,ot", SOLVE_CASES)
def test_implied_vol_roundtrip_closes_within_pinned_tolerance(s, k, t, r, q, sig, ot):
    params = make_params(spot=s, strike=k, expiry=t, rate=r,
                         dividend=q, sigma=sig, option_type=ot)
    market = price(params)
    iv = implied_vol(replace(params, sigma=None), market)
    # 代回定价接口必须在钉死的相对容差内回到原市价
    back = price(params.with_sigma(iv))
    assert abs(back - market) <= config.IV_ROUNDTRIP_REL_TOL * max(1.0, abs(market))
    assert iv == pytest.approx(sig, rel=1e-4)


def test_market_above_call_upper_bound_infeasible():
    params = replace(make_params(), sigma=None)
    _, upper = no_arbitrage_bounds(params)
    with pytest.raises(InfeasibleError):
        implied_vol(params, upper + 1.0)


def test_market_below_call_lower_bound_infeasible():
    params = replace(make_params(), sigma=None)
    lower, _ = no_arbitrage_bounds(params)
    with pytest.raises(InfeasibleError):
        implied_vol(params, lower - 1.0)


def test_market_outside_put_bounds_infeasible():
    params = replace(make_params(option_type="put"), sigma=None)
    lower, upper = no_arbitrage_bounds(params)
    assert upper == pytest.approx(100.0 * math.exp(-0.05))
    with pytest.raises(InfeasibleError):
        implied_vol(params, upper + 0.5)
    with pytest.raises(InfeasibleError):
        implied_vol(params, lower - 0.5)


def test_negative_market_price_infeasible():
    params = replace(make_params(), sigma=None)
    with pytest.raises(InfeasibleError):
        implied_vol(params, -0.01)


def test_zero_expiry_with_intrinsic_market_price_infeasible():
    # 期限为零且市价恰等于内在价值：隐含波动率无定义
    params = replace(make_params(expiry=0.0, spot=120.0), sigma=None)
    with pytest.raises(InfeasibleError):
        implied_vol(params, 20.0)


def test_implied_vol_invariant_under_scaling():
    params = make_params(sigma=0.3)
    market = price(params)
    iv1 = implied_vol(replace(params, sigma=None), market)
    scaled = make_params(spot=200.0, strike=200.0, sigma=0.3)
    iv2 = implied_vol(replace(scaled, sigma=None), 2.0 * market)
    assert iv1 == pytest.approx(iv2, rel=1e-6)
