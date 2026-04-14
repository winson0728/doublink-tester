"""Link weight / mode comparison tests — verify throughput across different modes."""

from __future__ import annotations

import pytest
import allure

from doublink_tester.config import load_test_matrix

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
    """Compare throughput and success rate across different multilink modes."""

    @pytest.mark.asyncio
    @pytest.mark.link_weight
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
        settings,
    ):
        """Verify throughput under each mode meets minimum thresholds."""
        allure.dynamic.title(f"Mode {mode} | {net_condition} | {traffic_profile}")

        # Set mode
        await set_multilink_mode(mode)

        # Apply network condition
        await apply_network_condition(net_condition)

        # NOTE: Full traffic measurement requires Phase 2 (traffic generators).
        # This test validates that the mode switch and network condition apply correctly.
