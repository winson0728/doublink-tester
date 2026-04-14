"""Request/response Pydantic schemas for the Control API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str] = {}


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, bool] = {}


class ApplyProfileRequest(BaseModel):
    profile_id: str
    interface: str
    direction: str = "egress"


class ApplyProfileResponse(BaseModel):
    rule_id: str
    profile_id: str
    interface: str
    status: str


class ClearProfileResponse(BaseModel):
    cleared: bool
    rule_id: str


class NetworkProfileResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    bandwidth_kbit: int = 0
    delay_ms: float = 0
    jitter_ms: float = 0
    loss_pct: float = 0
    corrupt_pct: float = 0
    duplicate_pct: float = 0
    disorder_pct: float = 0
    direction: str = "egress"


class SetModeRequest(BaseModel):
    mode: str
    parameters: dict[str, Any] | None = None


class SetModeResponse(BaseModel):
    mode: str
    switched: bool
    detail: str = ""


class ModeResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    parameters: dict[str, Any] = {}


class CurrentModeResponse(BaseModel):
    mode: str
    parameters: dict[str, Any] = {}
