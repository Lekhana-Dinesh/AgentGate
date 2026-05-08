from __future__ import annotations

from enum import Enum as PythonEnum

from sqlalchemy import Enum


def _enum_values(enum_cls: type[PythonEnum]) -> list[str]:
    return [str(member.value) for member in enum_cls]


def enum_value_type(enum_cls: type[PythonEnum], **kwargs) -> Enum:
    return Enum(enum_cls, values_callable=_enum_values, **kwargs)
