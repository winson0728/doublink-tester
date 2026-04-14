"""Mode switching tests — verify multilink mode transitions under various conditions."""

from __future__ import annotations

import json

import pytest
import allure

from doublink_tester.config import load_test_matrix


_matrix = load_test_matrix("mode_switching")
_transition_params = [
    pytest.param(
        entry["from_mode"],
        entry["to_mode"],
        entry["network_condition"],
        entry["traffic"],
        entry["assertions"],
        id=entry["id"],
    )
    for entry in _matrix
]


@allure.epic("Multilink Verification")
@allure.feature("Mode Switching")
class TestModeTransitions:
    """Verify traffic continuity during multilink mode transitions."""

    @pytest.mark.asyncio
    @pytest.mark.mode_switching
    @pytest.mark.parametrize(
        "from_mode, to_mode, net_condition, traffic_profile, assertions",
        _transition_params,
    )
    @allure.story("Mode Transition Under Traffic")
    async def test_mode_switch_continuity(
        self,
        from_mode: str,
        to_mode: str,
        net_condition: str,
        traffic_profile: str,
        assertions: dict,
        set_multilink_mode,
        apply_network_condition,
        settings,
    ):
        """Verify that switching from one mode to another does not excessively interrupt traffic."""
        allure.dynamic.title(f"Switch {from_mode} → {to_mode} | {net_condition} | {traffic_profile}")

        # 1. Set initial mode
        await set_multilink_mode(from_mode)

        # 2. Apply network condition
        await apply_network_condition(net_condition)

        # 3. Switch mode
        result = await set_multilink_mode(to_mode)

        # 4. Attach result for reporting
        allure.attach(
            json.dumps({"from": from_mode, "to": to_mode, "result": result, "assertions": assertions}, indent=2),
            name="switch_result.json",
            attachment_type=allure.attachment_type.JSON,
        )

        # NOTE: Full traffic-during-switch testing requires Phase 2 (traffic generators).
        # This test currently validates that the mode switch API call succeeds.
