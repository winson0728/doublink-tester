"""Network condition fixtures — apply/clear dual-line ATSSS profiles via NetEmu.

Each profile creates egress rules on up to 4 interfaces:
  wan_a_in  (LINE A DL), lan_a_out (LINE A UL),
  wan_b_in  (LINE B DL), lan_b_out (LINE B UL).
"""

from __future__ import annotations

import asyncio
import logging

import pytest_asyncio

logger = logging.getLogger(__name__)


def _interfaces_dict(settings) -> dict[str, str]:
    """Build the interfaces mapping expected by NetworkConditionProfile.get_rule_params()."""
    ifaces = settings.interfaces
    return {
        "line_a_dl": ifaces.line_a_dl,
        "line_a_ul": ifaces.line_a_ul,
        "line_b_dl": ifaces.line_b_dl,
        "line_b_ul": ifaces.line_b_ul,
    }


@pytest_asyncio.fixture(loop_scope="session")
async def apply_network_condition(netemu_client, network_profiles, settings):
    """Factory fixture: apply a dual-line network condition profile and auto-clear on teardown.

    Creates egress rules on all affected interfaces (up to 4: A-DL, A-UL, B-DL, B-UL).
    Returns a list of created rule_ids so tests can inspect individual rules.

    Usage::

        async def test_something(apply_network_condition):
            rule_ids = await apply_network_condition("symmetric_mild_loss")
            # ... test logic (rules on both lines) ...
            # all rules are automatically cleared after the test
    """
    created_rule_ids: list[str] = []

    async def _apply(profile_id: str) -> list[str]:
        if profile_id not in network_profiles:
            raise KeyError(
                f"Network profile '{profile_id}' not found. "
                f"Available: {list(network_profiles.keys())}"
            )

        # Clear any previously-created rules before applying new profile
        for old_id in list(created_rule_ids):
            try:
                await netemu_client.clear_rule(old_id)
            except Exception:
                pass
        created_rule_ids.clear()

        profile = network_profiles[profile_id]
        interfaces = _interfaces_dict(settings)
        rule_params_list = profile.get_rule_params(interfaces)

        if not rule_params_list:
            # Clean profile — no rules to create
            return []

        ids: list[str] = []
        for params in rule_params_list:
            result = await netemu_client.create_rule(params)
            rule_id = result["rule"]["id"]
            ids.append(rule_id)
            created_rule_ids.append(rule_id)
            logger.debug("Created rule %s on %s (%s)", rule_id, params.interface, params.label)

        # Wait for network condition to settle
        await asyncio.sleep(settings.timeouts.network_settle_s)
        return ids

    yield _apply

    # Teardown: clear all rules created during this test
    for rule_id in created_rule_ids:
        try:
            await netemu_client.clear_rule(rule_id)
        except Exception:
            logger.debug("Best-effort cleanup failed for rule %s", rule_id)


@pytest_asyncio.fixture(loop_scope="session")
async def clean_network(netemu_client):
    """Ensure a clean network state before and after test — clears all active rules."""

    async def _clear_all():
        rules = await netemu_client.list_rules()
        for rule in rules:
            try:
                await netemu_client.clear_rule(rule["id"])
            except Exception:
                pass

    await _clear_all()
    yield
    await _clear_all()
