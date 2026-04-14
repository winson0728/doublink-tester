"""Network degradation tests — verify NetEmu integration and data plane impact."""

from __future__ import annotations

import pytest
import allure


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestNetworkConditionApplied:
    """Verify that network conditions are correctly applied via NetEmu."""

    @pytest.mark.asyncio
    @pytest.mark.degradation
    @pytest.mark.parametrize("condition", [
        "clean",
        "moderate_loss",
        "high_latency",
        "congested",
        "4g_weak_signal",
    ])
    @allure.story("Apply Network Condition")
    async def test_network_condition_applied(
        self,
        condition: str,
        apply_network_condition,
        netemu_client,
        settings,
    ):
        """Verify that the specified network condition is applied to the interface."""
        allure.dynamic.title(f"Apply condition: {condition}")

        rule_id = await apply_network_condition(condition, settings.interfaces.primary)

        # Verify the rule exists and is active
        rules = await netemu_client.list_rules()
        active = [r for r in rules if r["id"] == rule_id]
        assert len(active) == 1, f"Rule {rule_id} not found in active rules"
        assert active[0]["status"] in ("active", "active_varied"), (
            f"Rule status is {active[0]['status']}, expected active"
        )

    @pytest.mark.asyncio
    @pytest.mark.degradation
    @allure.story("Apply and Clear Network Condition")
    async def test_condition_clear_restores_clean(
        self,
        apply_network_condition,
        netemu_client,
        settings,
    ):
        """Verify that clearing a rule restores clean network state."""
        rule_id = await apply_network_condition("moderate_loss", settings.interfaces.primary)

        # Manually clear (fixture will also clear on teardown)
        await netemu_client.clear_rule(rule_id)

        rule = await netemu_client.get_rule(rule_id)
        assert rule["status"] == "cleared"


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestDegradationWithVariation:
    """Verify network conditions with dynamic variation."""

    @pytest.mark.asyncio
    @pytest.mark.degradation
    @allure.story("Dynamic Variation")
    async def test_asymmetric_variation_applied(
        self,
        apply_network_condition,
        netemu_client,
        settings,
    ):
        """Verify that a profile with variation gets periodic parameter changes."""
        rule_id = await apply_network_condition("asymmetric_degraded", settings.interfaces.primary)

        rule = await netemu_client.get_rule(rule_id)
        assert rule["variation_enabled"] is True
        assert rule["status"] in ("active", "active_varied")


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestDisconnectSchedule:
    """Verify intermittent disconnect functionality."""

    @pytest.mark.asyncio
    @pytest.mark.degradation
    @allure.story("Intermittent Disconnect")
    async def test_disconnect_schedule_applied(
        self,
        apply_network_condition,
        netemu_client,
        settings,
    ):
        """Verify that disconnect schedule is configured on the rule."""
        rule_id = await apply_network_condition("intermittent_disconnect", settings.interfaces.primary)

        rule = await netemu_client.get_rule(rule_id)
        assert rule.get("disconnect_schedule") is not None
        assert rule["disconnect_schedule"]["enabled"] is True
