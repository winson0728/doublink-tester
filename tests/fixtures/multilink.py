"""Multilink mode fixtures — set/restore multilink operating modes."""

from __future__ import annotations

import logging

import pytest_asyncio

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def set_multilink_mode(multilink_client, multilink_modes):
    """Factory fixture: set a multilink mode and restore the original on teardown.

    Usage::

        async def test_something(set_multilink_mode):
            await set_multilink_mode("bonding")
            # ... test logic ...
            # original mode is restored after the test
    """
    original_mode: dict | None = None

    try:
        original_mode = await multilink_client.get_current_mode()
    except Exception:
        logger.warning("Could not fetch current multilink mode — restore on teardown will be skipped")

    async def _set(mode_id: str) -> dict:
        """Set mode by name (real_time, bonding, duplicate)."""
        return await multilink_client.set_mode(mode_id)

    yield _set

    # Teardown: restore original mode using the numeric value
    if original_mode is not None:
        try:
            await multilink_client.set_mode(original_mode.get("mode", 0))
        except Exception:
            logger.warning("Failed to restore original multilink mode")
