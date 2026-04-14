"""Root conftest — session-scoped fixtures for all tests."""

from __future__ import annotations

import pytest
import pytest_asyncio

from doublink_tester.config import (
    load_multilink_modes,
    load_network_profiles,
    load_settings,
    load_traffic_profiles,
)
from doublink_tester.clients.netemu_client import NetEmuClient
from doublink_tester.clients.multilink_client import MultilinkClient

# Register fixture modules so they are available project-wide
pytest_plugins = [
    "tests.fixtures.network",
    "tests.fixtures.multilink",
    "tests.fixtures.traffic",
]


# Use a single event loop for the entire session so session-scoped async
# fixtures don't hit "Event loop is closed" during teardown.
@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Session-scoped: live for entire test run ───────────────────

@pytest.fixture(scope="session")
def settings():
    """Load global settings once per session."""
    return load_settings()


@pytest.fixture(scope="session")
def network_profiles():
    """Load network condition profiles as a dict keyed by profile ID."""
    return {p.id: p for p in load_network_profiles()}


@pytest.fixture(scope="session")
def multilink_modes():
    """Load multilink mode configs as a dict keyed by mode ID."""
    return {m.id: m for m in load_multilink_modes()}


@pytest.fixture(scope="session")
def traffic_profiles():
    """Load traffic profiles as a dict keyed by profile ID."""
    return {t.id: t for t in load_traffic_profiles()}


@pytest_asyncio.fixture(scope="session")
async def netemu_client(settings):
    """Async NetEmu client — opened once, shared across all tests."""
    async with NetEmuClient(settings.netemu_url) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def multilink_client(settings):
    """Async Multilink client — opened once, shared across all tests."""
    async with MultilinkClient(settings.multilink_url, agent_id=settings.multilink_agent_id) as client:
        yield client
