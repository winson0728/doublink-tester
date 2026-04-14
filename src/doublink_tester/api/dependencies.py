"""Shared dependency injection — manages client lifecycles for the Control API."""

from __future__ import annotations

from doublink_tester.config import load_settings, load_network_profiles, load_multilink_modes
from doublink_tester.clients.netemu_client import NetEmuClient
from doublink_tester.clients.multilink_client import MultilinkClient

_settings = None
_netemu_client: NetEmuClient | None = None
_multilink_client: MultilinkClient | None = None
_network_profiles: dict | None = None
_multilink_modes: dict | None = None


async def init_clients() -> None:
    """Initialize all shared clients on application startup."""
    global _settings, _netemu_client, _multilink_client, _network_profiles, _multilink_modes

    _settings = load_settings()
    _network_profiles = {p.id: p for p in load_network_profiles()}
    _multilink_modes = {m.id: m for m in load_multilink_modes()}

    _netemu_client = NetEmuClient(_settings.netemu_url)
    await _netemu_client.__aenter__()

    _multilink_client = MultilinkClient(_settings.multilink_url, agent_id=_settings.multilink_agent_id)
    await _multilink_client.__aenter__()


async def shutdown_clients() -> None:
    """Clean up all shared clients on application shutdown."""
    global _netemu_client, _multilink_client

    if _netemu_client:
        await _netemu_client.__aexit__(None, None, None)
        _netemu_client = None
    if _multilink_client:
        await _multilink_client.__aexit__(None, None, None)
        _multilink_client = None


def get_settings():
    return _settings


def get_netemu_client() -> NetEmuClient:
    if _netemu_client is None:
        raise RuntimeError("NetEmuClient not initialized")
    return _netemu_client


def get_multilink_client() -> MultilinkClient:
    if _multilink_client is None:
        raise RuntimeError("MultilinkClient not initialized")
    return _multilink_client


def get_network_profiles() -> dict:
    if _network_profiles is None:
        raise RuntimeError("Network profiles not loaded")
    return _network_profiles


def get_multilink_modes() -> dict:
    if _multilink_modes is None:
        raise RuntimeError("Multilink modes not loaded")
    return _multilink_modes
