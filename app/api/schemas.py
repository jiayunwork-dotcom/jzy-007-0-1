"""原始请求体模型。

数值层面的校验由 :mod:`app.pricing.validation` 负责（以拿到中文、
带字段名的可读错误），Pydantic 这里只做最外层 JSON 结构约束：

* 顶层必须是对象（批量的 items 必须是数组且元素是对象）；
* 拒绝 items 之外的未知顶层字段；
* 其余任何字段（含 NaN/Infinity 与嵌套键）原样进入手写校验。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawBody(BaseModel):
    model_config = ConfigDict(extra="allow")


class RawBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 元素类型不在这里约束：非对象元素需要在循环中按"第几组"报错，
    # 而不是让整批请求失败。
    items: list[Any] = Field(..., description="待批量定价的合约列表")

    @field_validator("items", mode="before")
    @classmethod
    def _items_must_be_list(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("items 必须是数组")
        return value
