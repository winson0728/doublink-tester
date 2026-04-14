"""Network condition fixtures — apply/clear network degradation profiles via NetEmu."""

from __future__ import annotations

import asyncio

import pytest_asyncio


@pytest_asyncio.fixture(loop_scope="session")
async def apply_network_condition(netemu_client, network_profiles, settings):
    """Factory fixture: apply a network condition profile and auto-clear on teardown.

    Usage::

        async def test_something(apply_network_condition):
            rule_id = await apply_network_condition("moderate_loss")
            # ... test logic ...
            # rule is automatically cleared after the test
    """
    created_rule_ids: list[str] = []

    async def _apply(profile_id: str, interface: str | None = None) -> str:
        profile = network_profiles[profile_id]
        iface = interface or settings.interfaces.primary
        params = profile.to_rule_params(iface)
        result = await netemu_client.create_rule(params)
        rule_id = result["rule"]["id"]
        created_rule_ids.append(rule_id)
        # Wait for network condition to settle
        await asyncio.sleep(settings.timeouts.network_settle_s)
        return rule_id

    yield _apply

    # Teardown: clear all rules created during this test
    for rule_id in created_rule_ids:
        try:
            await netemu_client.clear_rule(rule_id)
        except Exception:
            pass  # Best-effort cleanup


@pytest_asyncio.fixture(loop_scope="session")
async def clean_network(netemu_client):
    """Ensure a clean network state before and after test — clears all active rules."""
    rules = await netemu_client.list_rules()
    for rule in rules:
        try:
            await netemu_client.clear_rule(rule["id"])
        except Exception:
            pass

    yield

    rules = await netemu_client.list_rules()
    for rule in rules:
        try:
            await netemu_client.clear_rule(rule["id"])
        except Exception:
            pass
