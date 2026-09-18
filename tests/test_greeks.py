"""希腊值规则：看涨看跌 Gamma/Vega 相同、Delta 区间与平价偏导、Rho 符号。"""
import math

import pytest

from app.errors import ParamError
from app.greeks import greeks
from app.pricing import OptionParams


def make_params(**overrides) -> OptionParams:
    base = dict(spot=100.0, strike=100.0, expiry=1.0, rate=0.05,
                sigma=0.2, dividend=0.0, option_type="call")
    base.update(overrides)
    return OptionParams(**base)


def test_gamma_and_vega_identical_for_call_and_put():
    for q in (0.0, 0.03):
        g_call = greeks(make_params(dividend=q))
        g_put = greeks(make_params(dividend=q, option_type="put"))
        assert g_call["gamma"] == pytest.approx(g_put["gamma"], rel=1e-12)
        assert g_call["vega"] == pytest.approx(g_put["vega"], rel=1e-12)


def test_delta_bounds_when_dividend_zero():
    for spot in (60.0, 90.0, 100.0, 110.0, 150.0):
        g_call = greeks(make_params(spot=spot))
        g_put = greeks(make_params(spot=spot, option_type="put"))
        assert 0.0 <= g_call["delta"] <= 1.0
        assert -1.0 <= g_put["delta"] <= 0.0


def test_call_minus_put_delta_equals_parity_derivative():
    # ∂/∂S (C - P) = e^(-qT)
    for q, t in ((0.0, 1.0), (0.03, 0.5), (0.01, 2.0)):
        g_call = greeks(make_params(dividend=q, expiry=t))
        g_put = greeks(make_params(dividend=q, expiry=t, option_type="put"))
        assert g_call["delta"] - g_put["delta"] == pytest.approx(
            math.exp(-q * t), rel=1e-12
        )


def test_rho_signs_match_rate_comparative_statics():
    g_call = greeks(make_params(rate=0.05))
    g_put = greeks(make_params(rate=0.05, option_type="put"))
    assert g_call["rho"] > 0.0
    assert g_put["rho"] < 0.0


def test_greeks_rejected_at_expiry():
    with pytest.raises(ParamError) as exc_info:
        greeks(make_params(expiry=0.0))
    assert exc_info.value.param == "T"
