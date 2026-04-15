"""Failover tests — verify ATSSS switching when a link disconnects or degrades.

Uses NetEmu profiles that simulate LINE A (5G) or LINE B (WiFi) disconnect/intermittent
conditions, and verifies multilink continues traffic through the surviving link.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import allure

pytestmark = pytest.mark.asyncio(loop_scope="session")


@allure.epic("Multilink Verification")
@allure.feature("ATSSS Switching")
class TestLinkDisconnectFailover:
    """Verify multilink ATSSS switching when a link is fully disconnected."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("disconnect_profile,surviving_link", [
        ("5g_disconnect", "WiFi (LINE B)"),
        ("wifi_disconnect", "5G (LINE A)"),
    ])
    @allure.story("Link Disconnect Failover")
    async def test_failover_on_disconnect(
        self,
        disconnect_profile: str,
        surviving_link: str,
        apply_network_condition,
        set_multilink_mode,
        iperf3_runner,
    ):
        """Disconnect one link via profile, verify traffic continues via surviving link."""
        allure.dynamic.title(f"Failover — {disconnect_profile} — traffic via {surviving_link}")

        # 1. Set bonding mode (uses both links)
        await set_multilink_mode("bonding")

        # 2. Baseline throughput — both links healthy
        baseline = await iperf3_runner(protocol="tcp", duration_s=5)

        # 3. Apply disconnect profile (100% loss on one link)
        await apply_network_condition(disconnect_profile)

        # 4. Measure during failover
        during = await iperf3_runner(protocol="tcp", duration_s=10)

        allure.attach(
            json.dumps({
                "profile": disconnect_profile,
                "surviving_link": surviving_link,
                "baseline_mbps": baseline.throughput_mbps,
                "during_failover_mbps": during.throughput_mbps,
            }, indent=2),
            name=f"failover_{disconnect_profile}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # Traffic MUST continue through the surviving link
        assert during.throughput_mbps > 0, (
            f"Zero throughput during {disconnect_profile} — "
            f"ATSSS switching to {surviving_link} failed"
        )

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("mode", ["bonding", "duplicate"])
    @allure.story("Disconnect Under Different Modes")
    async def test_failover_under_mode(
        self,
        mode: str,
        set_multilink_mode,
        apply_network_condition,
        iperf3_runner,
    ):
        """Verify failover works under each multilink mode."""
        allure.dynamic.title(f"Failover — {mode} mode — 5G disconnect")

        await set_multilink_mode(mode)

        # Disconnect 5G
        await apply_network_condition("5g_disconnect")

        result = await iperf3_runner(protocol="tcp", duration_s=10)

        allure.attach(
            json.dumps({
                "mode": mode,
                "throughput_mbps": result.throughput_mbps,
            }, indent=2),
            name=f"failover_{mode}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.throughput_mbps > 0, f"Zero throughput with {mode} mode after 5G disconnect"


@allure.epic("Multilink Verification")
@allure.feature("ATSSS Switching")
class TestIntermittentDisconnect:
    """Verify multilink resilience under intermittent link disconnects."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("profile_id,flapping_link", [
        ("5g_intermittent", "5G (LINE A)"),
        ("wifi_intermittent", "WiFi (LINE B)"),
    ])
    @allure.story("Intermittent Disconnect")
    async def test_intermittent_disconnect_survival(
        self,
        profile_id: str,
        flapping_link: str,
        apply_network_condition,
        set_multilink_mode,
        iperf3_runner,
    ):
        """Apply intermittent disconnect schedule, verify traffic survives flaps."""
        allure.dynamic.title(f"Intermittent disconnect — {flapping_link}")

        await set_multilink_mode("duplicate")

        # Apply intermittent profile (periodic 3s disconnects every 30s, 5 repeats)
        await apply_network_condition(profile_id)

        # Run long enough to cover at least 2 disconnect cycles
        result = await iperf3_runner(protocol="tcp", duration_s=20, parallel=2)

        allure.attach(
            json.dumps({
                "profile": profile_id,
                "flapping_link": flapping_link,
                "throughput_mbps": result.throughput_mbps,
                "loss_pct": result.loss_pct,
            }, indent=2),
            name=f"intermittent_{profile_id}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # iperf3 should complete and have reasonable throughput
        assert result.throughput_mbps > 0, (
            f"No throughput during intermittent disconnect of {flapping_link}"
        )

    @pytest.mark.degradation
    @pytest.mark.slow
    @allure.story("Scheduled Disconnect via API")
    async def test_scheduled_disconnect_via_api(
        self,
        set_multilink_mode,
        netemu_client,
        settings,
    ):
        """Use NetEmu scheduled disconnect API directly during iperf3."""
        from doublink_tester.traffic.iperf3 import Iperf3Generator

        allure.dynamic.title("Scheduled disconnect via NetEmu API during iperf3")

        await set_multilink_mode("duplicate")

        gen = Iperf3Generator(server_host=settings.iperf3_server)
        target = f"{settings.iperf3_server}:5201"

        # Start 20-second iperf3
        await gen.start(target=target, duration_s=20, protocol="tcp", parallel=2)

        # Schedule a 3-second disconnect on LINE A DL at second 5
        await asyncio.sleep(5)
        await netemu_client.schedule_disconnect(
            settings.interfaces.line_a_dl, duration_s=3.0
        )

        # Wait for iperf3 to complete
        result = await gen.wait()

        allure.attach(
            json.dumps({
                "throughput_mbps": result.throughput_mbps,
                "duration_s": result.ended_at - result.started_at,
            }, indent=2),
            name="scheduled_disconnect_api.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.throughput_mbps > 0, (
            "iperf3 produced no throughput during scheduled disconnect test"
        )


@allure.epic("Multilink Verification")
@allure.feature("ATSSS Switching")
class TestRecoveryAfterDisconnect:
    """Verify throughput recovers after link reconnects."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @allure.story("Recovery After Disconnect")
    async def test_recovery_after_5g_disconnect(
        self,
        apply_network_condition,
        netemu_client,
        set_multilink_mode,
        iperf3_runner,
        settings,
    ):
        """Disconnect 5G, measure, clear rules, measure again — throughput should recover."""
        allure.dynamic.title("Recovery after 5G disconnect")

        await set_multilink_mode("bonding")

        # 1. Disconnect 5G
        rule_ids = await apply_network_condition("5g_disconnect")
        during = await iperf3_runner(protocol="tcp", duration_s=5)

        # 2. Reconnect by clearing rules
        for rule_id in rule_ids:
            await netemu_client.clear_rule(rule_id)
        await asyncio.sleep(settings.timeouts.network_settle_s)

        # 3. Measure after recovery
        after = await iperf3_runner(protocol="tcp", duration_s=5)

        allure.attach(
            json.dumps({
                "during_disconnect_mbps": during.throughput_mbps,
                "after_recovery_mbps": after.throughput_mbps,
            }, indent=2),
            name="recovery_after_disconnect.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # Throughput should improve after reconnect (both links available again)
        assert after.throughput_mbps >= during.throughput_mbps, (
            f"Recovery {after.throughput_mbps:.2f} Mbps should be >= "
            f"during disconnect {during.throughput_mbps:.2f} Mbps"
        )
