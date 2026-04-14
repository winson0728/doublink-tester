"""Test run orchestrator — coordinates network, multilink, traffic, and metrics."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from doublink_tester.clients.multilink_client import MultilinkClient
from doublink_tester.clients.netemu_client import NetEmuClient
from doublink_tester.config import load_network_profiles
from doublink_tester.metrics.annotator import GrafanaAnnotator
from doublink_tester.metrics.sampler import MetricSampler
from doublink_tester.models import TestVerdict
from doublink_tester.orchestrator.result import TestRunResult
from doublink_tester.orchestrator.scenario import TestScenario
from doublink_tester.traffic.factory import from_profile as traffic_from_profile
from doublink_tester.config import load_traffic_profiles

logger = logging.getLogger(__name__)


class TestRunOrchestrator:
    """Coordinates network conditions, multilink state, traffic, and metrics for a test scenario."""

    def __init__(
        self,
        netemu: NetEmuClient,
        multilink: MultilinkClient,
        sampler: MetricSampler,
        annotator: GrafanaAnnotator | None = None,
    ):
        self._netemu = netemu
        self._multilink = multilink
        self._sampler = sampler
        self._annotator = annotator

    async def execute_scenario(self, scenario: TestScenario) -> TestRunResult:
        """Execute a complete test scenario.

        Flow:
        1. Annotate test start in Grafana
        2. Set multilink mode
        3. Apply network condition via NetEmu
        4. Start metric sampler
        5. Run traffic generator
        6. Collect results
        7. Clear network conditions
        8. Annotate test end
        """
        result = TestRunResult(scenario_name=scenario.name, started_at=time.time())
        rule_id: str | None = None

        try:
            # 1. Annotate start
            annotation_id = 0
            if self._annotator:
                annotation_id = await self._annotator.annotate_test_start(
                    scenario.name, {"mode": scenario.mode, "condition": scenario.network_condition}
                )

            # 2. Set multilink mode
            try:
                await self._multilink.set_mode(scenario.mode, scenario.extra_params.get("mode_params"))
            except NotImplementedError:
                logger.warning("Multilink mode setting skipped — API not implemented")

            # 3. Apply network condition
            profiles = {p.id: p for p in load_network_profiles()}
            if scenario.network_condition in profiles:
                profile = profiles[scenario.network_condition]
                params = profile.to_rule_params(scenario.interface)
                rule_result = await self._netemu.create_rule(params)
                rule_id = rule_result.get("rule", {}).get("id")
                await asyncio.sleep(scenario.settle_time_s)

            # 4. Start metric sampler
            await self._sampler.start()

            # 5. Run traffic generator
            traffic_profiles = {t.id: t for t in load_traffic_profiles()}
            if scenario.traffic_profile in traffic_profiles:
                tp = traffic_profiles[scenario.traffic_profile]
                gen = traffic_from_profile(tp)
                traffic_result = await gen.run(
                    scenario.extra_params.get("target", "localhost"),
                    scenario.duration_s,
                    protocol=tp.protocol,
                    **tp.parameters,
                )
                result.traffic_result = traffic_result

            # 6. Collect metric snapshots
            result.snapshots = await self._sampler.stop()

            # 7. Evaluate verdict
            result.verdict = self._evaluate_verdict(result, scenario.assertions)

        except Exception as e:
            logger.error("Scenario '%s' failed: %s", scenario.name, e)
            result.errors.append(str(e))
            result.verdict = TestVerdict.FAIL
        finally:
            # 8. Cleanup: clear network condition
            if rule_id:
                try:
                    await self._netemu.clear_rule(rule_id)
                except Exception:
                    pass

            result.ended_at = time.time()

            # 9. Annotate end
            if self._annotator and annotation_id:
                await self._annotator.annotate_test_end(annotation_id, result.verdict.value)

        return result

    def _evaluate_verdict(self, result: TestRunResult, assertions: dict[str, Any]) -> TestVerdict:
        """Evaluate pass/fail based on assertion thresholds."""
        if not assertions or result.traffic_result is None:
            return TestVerdict.PASS

        tr = result.traffic_result
        for key, threshold in assertions.items():
            if key == "min_throughput_mbps" and tr.throughput_mbps < threshold:
                return TestVerdict.FAIL
            if key == "max_loss_pct" and tr.loss_pct > threshold:
                return TestVerdict.FAIL
            if key == "min_success_rate" and tr.success_rate < threshold:
                return TestVerdict.FAIL
            if key == "max_latency_p95_ms" and tr.latency_p95_ms > threshold:
                return TestVerdict.FAIL
            if key == "max_jitter_ms" and tr.jitter_ms > threshold:
                return TestVerdict.FAIL

        return TestVerdict.PASS
