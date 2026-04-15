"""Network profile management endpoints — dual-line ATSSS model.

Each profile specifies independent degradation for LINE A (5G) and LINE B (WiFi).
Applying a profile creates egress rules on up to 4 interfaces:
  wan_a_in (A-DL), lan_a_out (A-UL), wan_b_in (B-DL), lan_b_out (B-UL).
"""

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
    LineRuleResponse,
    NetworkProfileResponse,
)

router = APIRouter()


def _line_rule_to_response(rule) -> LineRuleResponse | None:
    """Convert a LineRuleConfig to API response model."""
    if rule is None or rule.is_clean:
        return None
    return LineRuleResponse(
        bandwidth_kbit=rule.bandwidth_kbit,
        delay_ms=rule.delay_ms,
        jitter_ms=rule.jitter_ms,
        loss_pct=rule.loss_pct,
        corrupt_pct=rule.corrupt_pct,
        duplicate_pct=rule.duplicate_pct,
        disorder_pct=rule.disorder_pct,
        has_variation=rule.variation is not None,
        has_disconnect_schedule=rule.disconnect_schedule is not None,
    )


@router.get("/network", response_model=list[NetworkProfileResponse])
async def list_network_profiles():
    """List all available dual-line ATSSS network condition profiles."""
    profiles = get_network_profiles()
    return [
        NetworkProfileResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            line_a=_line_rule_to_response(p.line_a),
            line_b=_line_rule_to_response(p.line_b),
        )
        for p in profiles.values()
    ]


@router.post("/network/apply", response_model=ApplyProfileResponse)
async def apply_network_profile(req: ApplyProfileRequest):
    """Apply a dual-line ATSSS profile — creates rules on all affected interfaces."""
    profiles = get_network_profiles()
    if req.profile_id not in profiles:
        raise HTTPException(status_code=404, detail=f"Profile '{req.profile_id}' not found")

    profile = profiles[req.profile_id]
    settings = get_settings()
    interfaces = {
        "line_a_dl": settings.interfaces.line_a_dl,
        "line_a_ul": settings.interfaces.line_a_ul,
        "line_b_dl": settings.interfaces.line_b_dl,
        "line_b_ul": settings.interfaces.line_b_ul,
    }

    rule_params_list = profile.get_rule_params(interfaces)
    if not rule_params_list:
        return ApplyProfileResponse(
            profile_id=req.profile_id,
            rule_ids=[],
            rules_created=0,
            status="clean (no rules needed)",
        )

    netemu = get_netemu_client()
    rule_ids: list[str] = []
    for params in rule_params_list:
        result = await netemu.create_rule(params)
        rule_ids.append(result["rule"]["id"])

    return ApplyProfileResponse(
        profile_id=req.profile_id,
        rule_ids=rule_ids,
        rules_created=len(rule_ids),
        status="applied",
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
