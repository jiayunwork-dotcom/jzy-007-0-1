"""输入校验：缺字段、非数值、非有限值、未知方向、矛盾方向、越界取值。"""
import pytest

from app.errors import ParamError
from app.validation import validate_iv_params, validate_price_params


def base_payload():
    return {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05,
            "sigma": 0.2, "option_type": "call"}


@pytest.mark.parametrize("field,value", [
    ("S", 0.0), ("S", -1.0),
    ("K", 0.0), ("K", -5.0),
    ("sigma", 0.0), ("sigma", -0.2),
    ("T", -0.1),
])
def test_out_of_range_values_rejected(field, value):
    payload = base_payload()
    payload[field] = value
    with pytest.raises(ParamError) as exc_info:
        validate_price_params(payload)
    assert exc_info.value.param == field
    assert exc_info.value.message


@pytest.mark.parametrize("field", ["S", "K", "T", "r", "sigma", "option_type"])
def test_missing_required_field_rejected(field):
    payload = base_payload()
    del payload[field]
    with pytest.raises(ParamError) as exc_info:
        validate_price_params(payload)
    assert exc_info.value.param == field


@pytest.mark.parametrize("field", ["S", "K", "T", "r", "sigma"])
def test_non_numeric_rejected(field):
    payload = base_payload()
    payload[field] = "abc"
    with pytest.raises(ParamError) as exc_info:
        validate_price_params(payload)
    assert exc_info.value.param == field


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_rejected(bad):
    for field in ("S", "r", "q", "sigma"):
        payload = base_payload()
        payload[field] = bad
        with pytest.raises(ParamError) as exc_info:
            validate_price_params(payload)
        assert exc_info.value.param == field


def test_bool_rejected_as_numeric():
    payload = base_payload()
    payload["S"] = True
    with pytest.raises(ParamError):
        validate_price_params(payload)


def test_unknown_option_type_rejected():
    payload = base_payload()
    payload["option_type"] = "straddle"
    with pytest.raises(ParamError) as exc_info:
        validate_price_params(payload)
    assert exc_info.value.param == "option_type"


def test_contradictory_direction_fields_rejected():
    payload = base_payload()
    payload["is_call"] = False  # option_type=call 与 is_call=false 互相覆盖
    with pytest.raises(ParamError) as exc_info:
        validate_price_params(payload)
    assert exc_info.value.param == "option_type"
    assert "矛盾" in exc_info.value.message


def test_consistent_direction_fields_accepted():
    payload = base_payload()
    payload["is_call"] = True
    assert validate_price_params(payload).option_type == "call"


def test_is_call_alone_defines_direction():
    payload = base_payload()
    del payload["option_type"]
    payload["is_call"] = False
    assert validate_price_params(payload).option_type == "put"


def test_default_dividend_is_zero():
    params = validate_price_params(base_payload())
    assert params.dividend == 0.0


def test_negative_rate_and_dividend_allowed():
    payload = base_payload()
    payload.update({"r": -0.02, "q": -0.01})
    params = validate_price_params(payload)
    assert params.rate == -0.02 and params.dividend == -0.01


def test_non_dict_payload_rejected():
    with pytest.raises(ParamError):
        validate_price_params([1, 2, 3])


def test_iv_params_require_market_price():
    payload = base_payload()
    del payload["sigma"]
    with pytest.raises(ParamError) as exc_info:
        validate_iv_params(payload)
    assert exc_info.value.param == "market_price"
    payload["market_price"] = 10.0
    params, market = validate_iv_params(payload)
    assert params.sigma is None and market == 10.0
