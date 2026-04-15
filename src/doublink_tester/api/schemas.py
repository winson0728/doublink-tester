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


# ── Network profiles (dual-line ATSSS) ────────────────────────────


class LineRuleResponse(BaseModel):
    """Degradation parameters for a single line."""
    bandwidth_kbit: int = 0
    delay_ms: float = 0
    jitter_ms: float = 0
    loss_pct: float = 0
    corrupt_pct: float = 0
    duplicate_pct: float = 0
    disorder_pct: float = 0
    has_variation: bool = False
    has_disconnect_schedule: bool = False


class NetworkProfileResponse(BaseModel):
    """ATSSS dual-line network condition profile."""
    id: str
    name: str
    description: str = ""
    line_a: LineRuleResponse | None = None
    line_b: LineRuleResponse | None = None


class ApplyProfileRequest(BaseModel):
    """Apply a dual-line profile — creates rules on all affected interfaces."""
    profile_id: str


class ApplyProfileResponse(BaseModel):
    """Result of applying a dual-line profile."""
    profile_id: str
    rule_ids: list[str] = []
    rules_created: int = 0
    status: str = "applied"


class ClearProfileResponse(BaseModel):
    cleared: bool
    rule_id: str


# ── Multilink modes ───────────────────────────────────────────────


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
