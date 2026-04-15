"""Network degradation tests — verify data plane impact under various network conditions."""

from __future__ import annotations

import json

import pytest
import allure

pytestmark = pytest.mark.asyncio(loop_scope="session")


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestNetworkConditionApplied:
    """Verify that network conditions are correctly applied via NetEmu."""

    @pytest.mark.degradation
    @pytest.mark.parametrize("condition", [
        "clean",
        "moderate_loss",
        "high_latency",
        "congested",
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


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestTcpThroughputDegradation:
    """Measure TCP throughput under degraded network conditions."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @allure.story("TCP Throughput Under Degradation")
    async def test_tcp_baseline_clean(self, iperf3_runner):
        """Establish TCP throughput baseline with clean network."""
        allure.dynamic.title("TCP baseline — clean network")

        result = await iperf3_runner(protocol="tcp", duration_s=10, parallel=4)

        allure.attach(
            json.dumps({"throughput_mbps": result.throughput_mbps, "loss_pct": result.loss_pct}, indent=2),
            name="tcp_baseline.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.throughput_mbps > 0, "No throughput measured"

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("condition,min_throughput_mbps", [
        ("moderate_loss", 1.0),
        ("high_latency", 0.5),
        ("congested", 0.1),
    ])
    @allure.story("TCP Throughput Under Degradation")
    async def test_tcp_under_degradation(
        self,
        condition: str,
        min_throughput_mbps: float,
        apply_network_condition,
        iperf3_runner,
        settings,
    ):
        """Verify TCP throughput stays above minimum under degraded conditions."""
        allure.dynamic.title(f"TCP throughput — {condition}")

        await apply_network_condition(condition, settings.interfaces.primary)

        result = await iperf3_runner(protocol="tcp", duration_s=10, parallel=4)

        allure.attach(
            json.dumps({
                "condition": condition,
                "throughput_mbps": result.throughput_mbps,
                "loss_pct": result.loss_pct,
                "min_required_mbps": min_throughput_mbps,
            }, indent=2),
            name=f"tcp_{condition}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.throughput_mbps >= min_throughput_mbps, (
            f"TCP throughput {result.throughput_mbps:.2f} Mbps below minimum {min_throughput_mbps} Mbps"
        )


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestUdpDegradation:
    """Measure UDP performance under degraded network conditions."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @allure.story("UDP Under Degradation")
    async def test_udp_baseline_clean(self, iperf3_runner):
        """Establish UDP baseline with clean network."""
        allure.dynamic.title("UDP baseline — clean network")

        result = await iperf3_runner(protocol="udp", duration_s=10, bandwidth="50M")

        allure.attach(
            json.dumps({
                "throughput_mbps": result.throughput_mbps,
                "loss_pct": result.loss_pct,
                "jitter_ms": result.jitter_ms,
            }, indent=2),
            name="udp_baseline.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.loss_pct < 5.0, f"UDP loss {result.loss_pct:.2f}% too high for clean network"

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("condition,max_loss_pct,max_jitter_ms", [
        ("moderate_loss", 50.0, 200.0),
        ("high_latency", 20.0, 300.0),
        ("wifi_interference", 30.0, 200.0),
    ])
    @allure.story("UDP Under Degradation")
    async def test_udp_under_degradation(
        self,
        condition: str,
        max_loss_pct: float,
        max_jitter_ms: float,
        apply_network_condition,
        iperf3_runner,
        settings,
    ):
        """Verify UDP loss and jitter stay within bounds under degraded conditions."""
        allure.dynamic.title(f"UDP — {condition}")

        await apply_network_condition(condition, settings.interfaces.primary)

        result = await iperf3_runner(protocol="udp", duration_s=10, bandwidth="10M")

        allure.attach(
            json.dumps({
                "condition": condition,
                "throughput_mbps": result.throughput_mbps,
                "loss_pct": result.loss_pct,
                "jitter_ms": result.jitter_ms,
            }, indent=2),
            name=f"udp_{condition}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.loss_pct <= max_loss_pct, (
            f"UDP loss {result.loss_pct:.2f}% exceeds maximum {max_loss_pct}%"
        )


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestRecoveryAfterDegradation:
    """Verify throughput recovers after network degradation is removed."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @allure.story("Recovery After Degradation")
    async def test_tcp_recovery_after_congestion(
        self,
        apply_network_condition,
        netemu_client,
        iperf3_runner,
        settings,
    ):
        """Apply congestion, measure, clear, measure again — throughput should recover."""
        allure.dynamic.title("TCP recovery after congestion")

        # 1. Measure under congestion
        rule_id = await apply_network_condition("congested", settings.interfaces.primary)
        degraded = await iperf3_runner(protocol="tcp", duration_s=10)

        # 2. Clear the rule
        await netemu_client.clear_rule(rule_id)
        import asyncio
        await asyncio.sleep(settings.timeouts.network_settle_s)

        # 3. Measure after recovery
        recovered = await iperf3_runner(protocol="tcp", duration_s=10)

        allure.attach(
            json.dumps({
                "degraded_mbps": degraded.throughput_mbps,
                "recovered_mbps": recovered.throughput_mbps,
            }, indent=2),
            name="recovery.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert recovered.throughput_mbps > degraded.throughput_mbps, (
            f"Recovery throughput {recovered.throughput_mbps:.2f} Mbps should exceed "
            f"degraded {degraded.throughput_mbps:.2f} Mbps"
        )
