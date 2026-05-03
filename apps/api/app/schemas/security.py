from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KeyPurposeStatusResponse(BaseModel):
    purpose: str
    provider: str
    active_key_ref: str | None = None
    active_key_version: str | None = None
    configured_key_refs: list[str] = Field(default_factory=list)
    status: Literal["ready", "degraded", "unconfigured"]
    warnings: list[str] = Field(default_factory=list)


class KeyStatusResponse(BaseModel):
    provider: str
    purposes: list[KeyPurposeStatusResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
