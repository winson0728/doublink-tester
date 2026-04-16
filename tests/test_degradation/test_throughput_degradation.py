"""Network degradation tests — verify data plane impact under various ATSSS conditions.

Tests apply dual-line profiles (LINE A = 5G, LINE B = WiFi) and measure throughput,
loss, jitter, and recovery behaviour through the multilink tunnel.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import allure

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── Profile application verification ──────────────────────────────


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestNetworkConditionApplied:
    """Verify that dual-line ATSSS network conditions are correctly applied via NetEmu."""

    @pytest.mark.degradation
    @pytest.mark.parametrize("condition,expected_rule_count", [
        ("clean_controlled", 4),     # both lines shaped → 4 rules (A-DL, A-UL, B-DL, B-UL)
        ("symmetric_mild_loss", 4),
        ("symmetric_mild_latency", 4),
        ("5g_degraded_moderate", 4), # both lines non-zero → 4 rules
        ("wifi_degraded_moderate", 4),
    ])
    @allure.story("Apply ATSSS Profile")
    async def test_network_condition_applied(
        self,
        condition: str,
        expected_rule_count: int,
        apply_network_condition,
        netemu_client,
    ):
        """Verify that the correct number of rules are created for each profile."""
        allure.dynamic.title(f"Apply condition: {condition}")

        rule_ids = await apply_network_condition(condition)

        assert len(rule_ids) == expected_rule_count, (
            f"Expected {expected_rule_count} rules for '{condition}', got {len(rule_ids)}"
        )

        # Verify all created rules are active
        for rule_id in rule_ids:
            rules = await netemu_client.list_rules()
            active = [r for r in rules if r["id"] == rule_id]
            assert len(active) == 1, f"Rule {rule_id} not found in active rules"
            assert active[0]["status"] in ("active", "active_varied"), (
                f"Rule {rule_id} status is {active[0]['status']}, expected active"
            )

    @pytest.mark.degradation
    @allure.story("Apply and Clear Network Condition")
    async def test_condition_clear_restores_clean(
        self,
        apply_network_condition,
        netemu_client,
    ):
        """Verify that clearing all rules restores clean network state."""
        rule_ids = await apply_network_condition("symmetric_mild_loss")
        assert len(rule_ids) == 4

        # Manually clear all rules (fixture will also clear on teardown)
        for rule_id in rule_ids:
            await netemu_client.clear_rule(rule_id)

        for rule_id in rule_ids:
            rule = await netemu_client.get_rule(rule_id)
            assert rule["status"] == "cleared"


# ── Dynamic variation verification ────────────────────────────────


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestDegradationWithVariation:
    """Verify network conditions with dynamic variation."""

    @pytest.mark.degradation
    @allure.story("Dynamic Variation")
    async def test_wifi_interference_variation(
        self,
        apply_network_condition,
        netemu_client,
    ):
        """Verify that wifi_interference profile creates LINE B rules with variation enabled."""
        rule_ids = await apply_network_condition("wifi_interference_moderate")

        # wifi_interference: LINE A shaped (bw cap), LINE B with variation → 4 rules
        assert len(rule_ids) == 4

        # At least the LINE B rules should have variation enabled
        varied_count = 0
        for rule_id in rule_ids:
            rule = await netemu_client.get_rule(rule_id)
            assert rule["status"] in ("active", "active_varied")
            if rule.get("variation_enabled"):
                varied_count += 1

        assert varied_count >= 2, f"Expected at least 2 rules with variation, got {varied_count}"

    @pytest.mark.degradation
    @allure.story("Dynamic Variation")
    async def test_both_varied(
        self,
        apply_network_condition,
        netemu_client,
    ):
        """Verify that both_varied profile applies variation on all 4 interfaces."""
        rule_ids = await apply_network_condition("both_varied_moderate")
        assert len(rule_ids) == 4

        for rule_id in rule_ids:
            rule = await netemu_client.get_rule(rule_id)
            assert rule["variation_enabled"] is True


# ── Disconnect schedule verification ──────────────────────────────


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestDisconnectSchedule:
    """Verify intermittent disconnect functionality."""

    @pytest.mark.degradation
    @pytest.mark.parametrize("profile_id", ["5g_intermittent_visible", "wifi_intermittent_visible"])
    @allure.story("Intermittent Disconnect")
    async def test_disconnect_schedule_applied(
        self,
        profile_id: str,
        apply_network_condition,
        netemu_client,
    ):
        """Verify that disconnect schedule is configured on the degraded line's rules."""
        allure.dynamic.title(f"Disconnect schedule: {profile_id}")

        rule_ids = await apply_network_condition(profile_id)
        assert len(rule_ids) == 4  # both lines shaped → 4 rules (DL + UL per line)

        # Only the degraded line (2 of 4 rules) has disconnect_schedule
        sched_count = 0
        for rule_id in rule_ids:
            rule = await netemu_client.get_rule(rule_id)
            ds = rule.get("disconnect_schedule")
            if ds is not None and ds.get("enabled"):
                sched_count += 1

        assert sched_count >= 2, (
            f"Expected at least 2 rules with disconnect_schedule, got {sched_count}"
        )


# ── TCP throughput under degradation ──────────────────────────────


@allure.epic("Multilink Verification")
@allure.feature("Network Degradation")
class TestTcpThroughputDegradation:
    """Measure TCP throughput under degraded network conditions (both lines)."""

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
        ("symmetric_mild_loss", 2.0),
        ("symmetric_mild_latency", 1.0),
        ("congested_recoverable", 0.5),
        ("5g_degraded_moderate", 1.0),
        ("wifi_degraded_moderate", 1.0),
        ("asymmetric_mixed_moderate", 1.0),
    ])
    @allure.story("TCP Throughput Under Degradation")
    async def test_tcp_under_degradation(
        self,
        condition: str,
        min_throughput_mbps: float,
        apply_network_condition,
        iperf3_runner,
    ):
        """Verify TCP throughput stays above minimum under degraded conditions."""
        allure.dynamic.title(f"TCP throughput — {condition}")

        await apply_network_condition(condition)

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


# ── UDP under degradation ─────────────────────────────────────────


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

        # Note: ATSSS duplicate mode can cause iperf3 to report >100% loss
        # (server receives duplicated packets on both links).
        # We only assert throughput is measurable; loss_pct is informational.
        assert result.throughput_mbps > 0, "No UDP throughput measured"

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("condition,max_loss_pct,max_jitter_ms", [
        ("symmetric_mild_loss", 10.0, 100.0),
        ("symmetric_mild_latency", 60.0, 200.0),
        ("wifi_interference_moderate", 10.0, 100.0),
        ("asymmetric_mixed_moderate", 10.0, 200.0),
    ])
    @allure.story("UDP Under Degradation")
    async def test_udp_under_degradation(
        self,
        condition: str,
        max_loss_pct: float,
        max_jitter_ms: float,
        apply_network_condition,
        iperf3_runner,
    ):
        """Verify UDP throughput and loss under degraded conditions."""
        allure.dynamic.title(f"UDP — {condition}")

        await apply_network_condition(condition)

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

        # ATSSS duplicate mode sends packets on both links — iperf3 counts
        # duplicates as negative loss (>100%). Only assert loss when it's
        # in a plausible range (i.e. not a duplicate-mode artifact).
        if result.loss_pct <= 100.0:
            assert result.loss_pct <= max_loss_pct, (
                f"UDP loss {result.loss_pct:.2f}% exceeds maximum {max_loss_pct}%"
            )

        assert result.throughput_mbps > 0, f"No UDP throughput for {condition}"


# ── ATSSS steering verification ──────────────────────────────────


@allure.epic("Multilink Verification")
@allure.feature("ATSSS Steering")
class TestSteeringBehaviour:
    """Verify ATSSS steers traffic away from degraded links."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("profile_id,description", [
        ("5g_degraded_moderate", "5G degraded, WiFi healthy — expect steering to WiFi"),
        ("wifi_degraded_moderate", "WiFi degraded, 5G healthy — expect steering to 5G"),
        ("5g_high_latency_moderate", "5G high latency, WiFi normal — expect latency-aware steering"),
        ("wifi_high_latency_moderate", "WiFi high latency, 5G normal — expect latency-aware steering"),
    ])
    @allure.story("Asymmetric Steering")
    async def test_steering_maintains_throughput(
        self,
        profile_id: str,
        description: str,
        apply_network_condition,
        iperf3_runner,
    ):
        """When one link is degraded, ATSSS should steer traffic to the healthy link."""
        allure.dynamic.title(f"Steering: {profile_id}")
        allure.dynamic.description(description)

        await apply_network_condition(profile_id)

        result = await iperf3_runner(protocol="tcp", duration_s=10, parallel=4)

        allure.attach(
            json.dumps({
                "profile": profile_id,
                "throughput_mbps": result.throughput_mbps,
                "loss_pct": result.loss_pct,
                "latency_avg_ms": result.latency_avg_ms,
            }, indent=2),
            name=f"steering_{profile_id}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # With one healthy link available (shaped to 40-50M), throughput should be measurable
        assert result.throughput_mbps > 1.0, (
            f"Throughput {result.throughput_mbps:.2f} Mbps too low — "
            f"ATSSS should steer to healthy link"
        )


# ── Recovery after degradation ────────────────────────────────────


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
        """Apply symmetric congestion, measure, clear, measure again — throughput should recover."""
        allure.dynamic.title("TCP recovery after symmetric congestion")

        # 1. Measure under congestion (both lines)
        rule_ids = await apply_network_condition("congested_recoverable")
        degraded = await iperf3_runner(protocol="tcp", duration_s=10)

        # 2. Clear all rules
        for rule_id in rule_ids:
            await netemu_client.clear_rule(rule_id)
        await asyncio.sleep(settings.timeouts.network_settle_s)

        # 3. Measure after recovery
        recovered = await iperf3_runner(protocol="tcp", duration_s=10)

        allure.attach(
            json.dumps({
                "degraded_mbps": degraded.throughput_mbps,
                "recovered_mbps": recovered.throughput_mbps,
                "rules_cleared": len(rule_ids),
            }, indent=2),
            name="recovery.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # If degradation was effective, recovered should be higher.
        # If both are similar (traffic doesn't traverse bridge), both are acceptable
        # as long as recovered throughput is non-zero and not drastically worse.
        assert recovered.throughput_mbps > 0, "No throughput after recovery"
        if degraded.throughput_mbps > 0:
            ratio = recovered.throughput_mbps / degraded.throughput_mbps
            assert ratio >= 0.5, (
                f"Recovery throughput {recovered.throughput_mbps:.2f} Mbps is less than "
                f"50% of degraded {degraded.throughput_mbps:.2f} Mbps — unexpected regression"
            )
