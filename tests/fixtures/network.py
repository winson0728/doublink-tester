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

# Rule statuses that are already inactive — no need to clear them again
_INACTIVE_STATUSES = {"cleared", "deleted", "error"}


def _interfaces_dict(settings) -> dict[str, str]:
    """Build the interfaces mapping expected by NetworkConditionProfile.get_rule_params()."""
    ifaces = settings.interfaces
    return {
        "line_a_dl": ifaces.line_a_dl,
        "line_a_ul": ifaces.line_a_ul,
        "line_b_dl": ifaces.line_b_dl,
        "line_b_ul": ifaces.line_b_ul,
    }


async def _clear_all_active_rules(netemu_client) -> int:
    """Clear every active rule on NetEmu. Returns the number of rules cleared.

    This is called both by clean_network (autouse guard) and by _apply() before
    installing a new profile — so dirty state left by manual clear_rule() calls
    inside individual tests never leaks to the next test.
    """
    try:
        rules = await netemu_client.list_rules()
    except Exception as e:
        logger.warning("clear_all_active_rules: failed to list rules: %s", e)
        return 0

    cleared = 0
    for rule in rules:
        status = rule.get("status", "")
        if status in _INACTIVE_STATUSES:
            continue
        try:
            await netemu_client.clear_rule(rule["id"])
            cleared += 1
            logger.debug("Cleared rule %s (was %s)", rule["id"], status)
        except Exception as e:
            logger.warning("Failed to clear rule %s (status=%s): %s", rule["id"], status, e)

    return cleared


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def clean_network(netemu_client):
    """Autouse guard: ensure a clean network state before and after every test.

    Runs for ALL tests in the session. Clears all active NetEmu rules before the
    test begins, so leftover conditions from a previous test (or a failed teardown)
    cannot affect this test's baseline.

    The post-test teardown clears rules again as belt-and-suspenders, complementing
    apply_network_condition's own teardown.
    """
    n = await _clear_all_active_rules(netemu_client)
    if n:
        logger.info("clean_network [setup]: cleared %d leftover rule(s) before test", n)

    yield

    n = await _clear_all_active_rules(netemu_client)
    if n:
        logger.info("clean_network [teardown]: cleared %d rule(s) after test", n)


@pytest_asyncio.fixture(loop_scope="session")
async def apply_network_condition(netemu_client, network_profiles, settings):
    """Factory fixture: apply a dual-line network condition profile and auto-clear on teardown.

    Creates egress rules on all affected interfaces (up to 4: A-DL, A-UL, B-DL, B-UL).
    Returns a list of created rule_ids so tests can inspect individual rules.

    Before installing a new profile this fixture clears ALL active NetEmu rules —
    not just the ones it tracked — to handle the case where a test manually called
    netemu_client.clear_rule() (which would desync the internal tracking list).

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

        # Clear ALL active rules — not just the ones we tracked.
        # This handles the desync that occurs when a test calls
        # netemu_client.clear_rule() directly (those IDs stay in
        # created_rule_ids but are already gone from NetEmu, so a
        # targeted clear would silently fail and leave stale state).
        n = await _clear_all_active_rules(netemu_client)
        if n:
            logger.debug("apply(%s): cleared %d pre-existing rule(s)", profile_id, n)
        created_rule_ids.clear()

        profile = network_profiles[profile_id]
        interfaces = _interfaces_dict(settings)
        rule_params_list = profile.get_rule_params(interfaces)

        if not rule_params_list:
            # Clean profile — no rules to create
            logger.debug("apply(%s): clean profile, no rules created", profile_id)
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

    # Teardown: clear rules created during this test.
    # clean_network's autouse teardown will also run as a safety net.
    for rule_id in created_rule_ids:
        try:
            await netemu_client.clear_rule(rule_id)
        except Exception as e:
            logger.warning("Teardown: failed to clear rule %s: %s", rule_id, e)
