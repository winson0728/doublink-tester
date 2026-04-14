"""Health and readiness endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from doublink_tester.api.dependencies import get_netemu_client, get_multilink_client
from doublink_tester.api.schemas import HealthResponse, ReadyResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=HealthResponse)
async def health_check():
    """Basic health check — always returns OK if the API is running."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def readiness_check():
    """Readiness check — verifies connectivity to NetEmu and Multilink services."""
    checks: dict[str, bool] = {}

    # Check NetEmu connectivity
    try:
        netemu = get_netemu_client()
        await netemu.list_interfaces()
        checks["netemu"] = True
    except Exception as e:
        logger.warning("NetEmu readiness check failed: %s", e)
        checks["netemu"] = False

    # Check Multilink connectivity
    try:
        multilink = get_multilink_client()
        await multilink.get_current_mode()
        checks["multilink"] = True
    except Exception as e:
        logger.warning("Multilink readiness check failed: %s", e)
        checks["multilink"] = False

    ready = all(checks.values())
    return ReadyResponse(ready=ready, checks=checks)
