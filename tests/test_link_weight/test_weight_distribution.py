"""Mode comparison tests — compare throughput and loss across multilink modes."""

from __future__ import annotations

import json

import pytest
import allure

from doublink_tester.config import load_test_matrix

pytestmark = pytest.mark.asyncio(loop_scope="session")

_matrix = load_test_matrix("link_weight")
_params = [
    pytest.param(
        entry["mode"],
        entry["network_condition"],
        entry["traffic"],
        entry["assertions"],
        id=entry["id"],
    )
    for entry in _matrix
]


@allure.epic("Multilink Verification")
@allure.feature("Mode Comparison")
class TestModeComparison:
    """Compare throughput and loss across different multilink modes."""

    @pytest.mark.link_weight
    @pytest.mark.slow
    @pytest.mark.parametrize(
        "mode, net_condition, traffic_profile, assertions",
        _params,
    )
    @allure.story("Mode Performance Comparison")
    async def test_mode_performance(
        self,
        mode: str,
        net_condition: str,
        traffic_profile: str,
        assertions: dict,
        set_multilink_mode,
        apply_network_condition,
        iperf3_runner,
        settings,
    ):
        """Measure throughput under each mode and verify minimums."""
        allure.dynamic.title(f"Mode {mode} | {net_condition} | {traffic_profile}")

        # Set mode
        await set_multilink_mode(mode)

        # Apply network condition
        if net_condition != "clean":
            await apply_network_condition(net_condition)

        # Determine test parameters from traffic profile name
        if "udp" in traffic_profile:
            result = await iperf3_runner(protocol="udp", duration_s=10, bandwidth="50M")
        else:
            result = await iperf3_runner(protocol="tcp", duration_s=10, parallel=4)

        allure.attach(
            json.dumps({
                "mode": mode,
                "condition": net_condition,
                "traffic": traffic_profile,
                "throughput_mbps": result.throughput_mbps,
                "loss_pct": result.loss_pct,
                "jitter_ms": result.jitter_ms,
                "assertions": assertions,
            }, indent=2),
            name=f"mode_{mode}_{net_condition}.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # Check assertions from test matrix
        min_tp = assertions.get("min_throughput_mbps")
        if min_tp is not None:
            assert result.throughput_mbps >= min_tp, (
                f"Throughput {result.throughput_mbps:.2f} Mbps below minimum {min_tp} Mbps"
            )

        max_loss = assertions.get("max_loss_pct")
        if max_loss is not None:
            assert result.loss_pct <= max_loss, (
                f"Loss {result.loss_pct:.2f}% exceeds maximum {max_loss}%"
            )

        max_jitter = assertions.get("max_jitter_ms")
        if max_jitter is not None and result.jitter_ms > 0:
            assert result.jitter_ms <= max_jitter, (
                f"Jitter {result.jitter_ms:.2f} ms exceeds maximum {max_jitter} ms"
            )


@allure.epic("Multilink Verification")
@allure.feature("Mode Comparison")
class TestModeBaselineComparison:
    """Compare clean-network throughput across all modes."""

    @pytest.mark.link_weight
    @pytest.mark.slow
    @allure.story("Baseline Mode Comparison")
    async def test_all_modes_baseline_tcp(
        self,
        set_multilink_mode,
        iperf3_runner,
    ):
        """Measure TCP throughput for each mode under clean network, compare."""
        results = {}
        for mode in ["real_time", "bonding", "duplicate"]:
            await set_multilink_mode(mode)
            result = await iperf3_runner(protocol="tcp", duration_s=10, parallel=4)
            results[mode] = result.throughput_mbps

        allure.attach(
            json.dumps(results, indent=2),
            name="baseline_comparison.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # All modes should produce some throughput
        for mode, mbps in results.items():
            assert mbps > 0, f"Mode {mode} produced zero throughput"

    @pytest.mark.link_weight
    @pytest.mark.slow
    @allure.story("Baseline Mode Comparison")
    async def test_all_modes_baseline_udp(
        self,
        set_multilink_mode,
        iperf3_runner,
    ):
        """Measure UDP performance for each mode under clean network."""
        results = {}
        for mode in ["real_time", "bonding", "duplicate"]:
            await set_multilink_mode(mode)
            result = await iperf3_runner(protocol="udp", duration_s=10, bandwidth="50M")
            results[mode] = {"throughput_mbps": result.throughput_mbps, "loss_pct": result.loss_pct, "jitter_ms": result.jitter_ms}

        allure.attach(
            json.dumps(results, indent=2),
            name="udp_baseline_comparison.json",
            attachment_type=allure.attachment_type.JSON,
        )

        for mode, data in results.items():
            assert data["loss_pct"] < 10.0, f"Mode {mode} UDP loss {data['loss_pct']:.2f}% too high for clean network"
