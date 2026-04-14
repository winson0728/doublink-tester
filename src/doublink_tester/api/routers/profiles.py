"""Network profile management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from doublink_tester.api.dependencies import (
    get_netemu_client,
    get_network_profiles,
    get_settings,
)
from doublink_tester.api.schemas import (
    ApplyProfileRequest,
    ApplyProfileResponse,
    ClearProfileResponse,
    NetworkProfileResponse,
)

router = APIRouter()


@router.get("/network", response_model=list[NetworkProfileResponse])
async def list_network_profiles():
    """List all available network condition profiles."""
    profiles = get_network_profiles()
    return [
        NetworkProfileResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            bandwidth_kbit=p.bandwidth_kbit,
            delay_ms=p.delay_ms,
            jitter_ms=p.jitter_ms,
            loss_pct=p.loss_pct,
            corrupt_pct=p.corrupt_pct,
            duplicate_pct=p.duplicate_pct,
            disorder_pct=p.disorder_pct,
            direction=p.direction,
        )
        for p in profiles.values()
    ]


@router.post("/network/apply", response_model=ApplyProfileResponse)
async def apply_network_profile(req: ApplyProfileRequest):
    """Apply a network condition profile to an interface via NetEmu."""
    profiles = get_network_profiles()
    if req.profile_id not in profiles:
        raise HTTPException(status_code=404, detail=f"Profile '{req.profile_id}' not found")

    profile = profiles[req.profile_id]
    params = profile.to_rule_params(req.interface)
    if req.direction != "egress":
        params.direction = req.direction

    netemu = get_netemu_client()
    result = await netemu.create_rule(params)

    rule = result.get("rule", {})
    return ApplyProfileResponse(
        rule_id=rule.get("id", ""),
        profile_id=req.profile_id,
        interface=req.interface,
        status=rule.get("status", "unknown"),
    )


@router.delete("/network/{rule_id}", response_model=ClearProfileResponse)
async def clear_network_profile(rule_id: str):
    """Clear (remove) a network condition rule from an interface."""
    netemu = get_netemu_client()
    try:
        await netemu.clear_rule(rule_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found or already cleared: {e}")
    return ClearProfileResponse(cleared=True, rule_id=rule_id)


@router.get("/netemu", response_model=list[dict])
async def list_netemu_profiles():
    """List built-in and custom profiles from the NetEmu server."""
    netemu = get_netemu_client()
    return await netemu.list_profiles()


@router.get("/netemu/active", response_model=list[dict])
async def list_active_rules():
    """List all currently active network emulation rules on NetEmu."""
    netemu = get_netemu_client()
    return await netemu.list_rules()
