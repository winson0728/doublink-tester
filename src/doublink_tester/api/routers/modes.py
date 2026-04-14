"""Multilink mode control endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from doublink_tester.api.dependencies import get_multilink_client, get_multilink_modes
from doublink_tester.api.schemas import (
    CurrentModeResponse,
    ModeResponse,
    SetModeRequest,
    SetModeResponse,
)

router = APIRouter()


@router.get("", response_model=list[ModeResponse])
async def list_modes():
    """List all available multilink operating modes."""
    modes = get_multilink_modes()
    return [
        ModeResponse(id=m.id, name=m.name, description=m.description, parameters=m.parameters)
        for m in modes.values()
    ]


@router.get("/current", response_model=CurrentModeResponse)
async def get_current_mode():
    """Get the current multilink operating mode."""
    client = get_multilink_client()
    result = await client.get_current_mode()
    return CurrentModeResponse(
        mode=result.get("mode_name", "unknown"),
        parameters={"mode_value": result.get("mode"), "agent_id": result.get("agent_id")},
    )


@router.post("/set", response_model=SetModeResponse)
async def set_mode(req: SetModeRequest):
    """Switch the multilink operating mode.

    Accepts mode name (real_time, bonding, duplicate) or numeric value (0, 3, 4).
    """
    client = get_multilink_client()
    try:
        result = await client.set_mode(req.mode, req.parameters)
        return SetModeResponse(mode=result.get("mode_name", req.mode), switched=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
