"""输入校验测试：缺字段、非数值、非有限、未知方向、矛盾字段、未知字段。"""
from __future__ import annotations

import json

import pytest

from app.errors import InvalidParameterError
from app.pricing import validation as v

GOOD = {"S": 100, "K": 100, "T": 1, "r": 0.03, "sigma": 0.2, "option_type": "call"}


def test_valid_request_defaults_q():
    out = v.validate_pricing_request(dict(GOOD))
    assert out["q"] == 0.0
    assert out["is_call"] is True


@pytest.mark.parametrize("field,value", [
    ("S", 0), ("S", -5), ("K", -1), ("sigma", 0), ("sigma", -0.2), ("T", -0.1),
])
def test_nonpositive_parameters_rejected(field, value):
    raw = dict(GOOD)
    raw[field] = value
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == field


def test_negative_rate_allowed_negative_q_allowed():
    raw = dict(GOOD, r=-0.02, q=-0.01)
    out = v.validate_pricing_request(raw)
    assert out["r"] == -0.02 and out["q"] == -0.01


@pytest.mark.parametrize("field", ["S", "K", "T", "r", "sigma"])
def test_missing_field(field):
    raw = dict(GOOD)
    del raw[field]
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == field


def test_missing_direction():
    raw = {k: val for k, val in GOOD.items() if k != "option_type"}
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == "option_type"


@pytest.mark.parametrize("bad", ["100", True, False, None, [100], {"x": 1}])
def test_non_numeric_values(bad):
    raw = dict(GOOD, S=bad)
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == "S"


def test_bool_is_not_number():
    raw = dict(GOOD, K=True)
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == "K"


def test_non_finite_rejected():
    raw = dict(GOOD, sigma=float("nan"))
    with pytest.raises(InvalidParameterError):
        v.validate_pricing_request(raw)
    raw = dict(GOOD, sigma=float("inf"))
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == "sigma"


def test_unknown_direction():
    raw = dict(GOOD, option_type="straddle")
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == "option_type"


def test_direction_aliases_and_case():
    for text, flag in [("call", True), ("CALL", True), ("c", True), ("put", False), ("P", False)]:
        out = v.validate_pricing_request(dict(GOOD, option_type=text))
        assert out["is_call"] is flag


def test_is_call_bool_only():
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(dict(GOOD, option_type=None, is_call="yes"))
    assert ei.value.field == "is_call"


def test_is_call_alone_accepted():
    raw = {k: val for k, val in GOOD.items() if k != "option_type"}
    raw["is_call"] = False
    assert v.validate_pricing_request(raw)["is_call"] is False


def test_contradictory_direction_fields():
    from app.errors import ContradictionError
    raw = dict(GOOD, option_type="call", is_call=False)
    with pytest.raises(ContradictionError):
        v.validate_pricing_request(raw)


def test_consistent_direction_fields_ok():
    raw = dict(GOOD, option_type="call", is_call=True)
    assert v.validate_pricing_request(raw)["is_call"] is True


def test_unknown_field_rejected():
    raw = dict(GOOD, foo=1)
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_pricing_request(raw)
    assert ei.value.field == "foo"


def test_negative_market_price_rejected():
    raw = {"S": 100, "K": 100, "T": 1, "r": 0, "market_price": -1,
           "option_type": "call"}
    with pytest.raises(InvalidParameterError) as ei:
        v.validate_iv_request(raw)
    assert ei.value.field == "market_price"


# ---- HTTP 层 -------------------------------------------------------------

def test_http_missing_field_422(client):
    r = client.post("/price", json={"K": 100, "T": 1, "r": 0,
                                    "sigma": 0.2, "option_type": "call"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_parameter" and err["field"] == "S"


def test_http_bad_json_422(client):
    r = client.post("/price", content=b"{not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_json"


def test_http_nan_rejected(client):
    r = client.post("/price",
                    content=json.dumps({**GOOD, "S": float("nan")}),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "S"


def test_http_contradiction_422(client):
    r = client.post("/price", json={**GOOD, "is_call": False})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "contradictory_fields"
