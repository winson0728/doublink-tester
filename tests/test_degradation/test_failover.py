"""Failover tests — verify traffic survives link disconnect and reconnect."""

from __future__ import annotations

import asyncio
import json

import pytest
import allure

pytestmark = pytest.mark.asyncio(loop_scope="session")


@allure.epic("Multilink Verification")
@allure.feature("Failover")
class TestLinkFailover:
    """Verify multilink failover when a link is disconnected."""

    @pytest.mark.degradation
    @pytest.mark.slow
    @pytest.mark.parametrize("mode", ["bonding", "duplicate"])
    @allure.story("Link Disconnect Failover")
    async def test_failover_on_disconnect(
        self,
        mode: str,
        set_multilink_mode,
        netemu_client,
        iperf3_runner,
        settings,
    ):
        """Disconnect primary link, verify traffic continues via secondary."""
        allure.dynamic.title(f"Failover — {mode} mode — disconnect primary")

        await set_multilink_mode(mode)

        # 1. Baseline throughput
        baseline = await iperf3_runner(protocol="tcp", duration_s=5)

        # 2. Disconnect primary link
        await netemu_client.disconnect(settings.interfaces.primary)
        await asyncio.sleep(settings.timeouts.network_settle_s)

        # 3. Measure during failover
        during = await iperf3_runner(protocol="tcp", duration_s=10)

        # 4. Reconnect
        await netemu_client.reconnect(settings.interfaces.primary)
        await asyncio.sleep(settings.timeouts.network_settle_s)

        # 5. Post-recovery
        after = await iperf3_runner(protocol="tcp", duration_s=5)

        allure.attach(
            json.dumps({
                "mode": mode,
                "baseline_mbps": baseline.throughput_mbps,
                "during_failover_mbps": during.throughput_mbps,
                "after_recovery_mbps": after.throughput_mbps,
            }, indent=2),
            name=f"failover_{mode}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # Traffic should continue during failover (at reduced rate)
        assert during.throughput_mbps > 0, "Zero throughput during failover"

    @pytest.mark.degradation
    @pytest.mark.slow
    @allure.story("Scheduled Disconnect")
    async def test_scheduled_disconnect_survival(
        self,
        set_multilink_mode,
        netemu_client,
        settings,
    ):
        """Use NetEmu scheduled disconnect, run iperf3 concurrently."""
        from doublink_tester.traffic.iperf3 import Iperf3Generator

        allure.dynamic.title("Scheduled disconnect during iperf3")

        await set_multilink_mode("duplicate")

        gen = Iperf3Generator(server_host=settings.iperf3_server)
        target = f"{settings.iperf3_server}:5201"

        # Start 20-second iperf3
        await gen.start(target=target, duration_s=20, protocol="tcp", parallel=2)

        # Schedule a 3-second disconnect at second 5
        await asyncio.sleep(5)
        await netemu_client.schedule_disconnect(settings.interfaces.primary, duration_s=3.0)

        # Wait for iperf3 to complete
        result = await gen.wait()

        allure.attach(
            json.dumps({
                "throughput_mbps": result.throughput_mbps,
                "duration_s": result.ended_at - result.started_at,
            }, indent=2),
            name="scheduled_disconnect.json",
            attachment_type=allure.attachment_type.JSON,
        )

        assert result.throughput_mbps > 0, "iperf3 produced no throughput during scheduled disconnect test"
