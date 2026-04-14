"""Periodic metric sampler — collects metrics at fixed intervals during tests."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from doublink_tester.clients.netemu_client import NetEmuClient
from doublink_tester.metrics.collector import PrometheusCollector

logger = logging.getLogger(__name__)


@dataclass
class TestSnapshot:
    """Point-in-time capture of all metrics during a test."""

    timestamp: float
    network_stats: dict[str, Any] = field(default_factory=dict)
    prometheus_metrics: dict[str, float] = field(default_factory=dict)


class MetricSampler:
    """Collects metrics at fixed intervals during a test run."""

    def __init__(
        self,
        collector: PrometheusCollector,
        netemu_client: NetEmuClient,
        interval_s: float = 2.0,
    ):
        self._collector = collector
        self._netemu = netemu_client
        self._interval = interval_s
        self._task: asyncio.Task | None = None
        self._snapshots: list[TestSnapshot] = []
        self._promql_queries: list[str] = []
        self._running = False

    async def start(self, queries: list[str] | None = None) -> None:
        """Start periodic sampling."""
        self._promql_queries = queries or []
        self._snapshots = []
        self._running = True
        self._task = asyncio.create_task(self._sample_loop())

    async def stop(self) -> list[TestSnapshot]:
        """Stop sampling and return collected snapshots."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        return self._snapshots

    async def _sample_loop(self) -> None:
        while self._running:
            try:
                snapshot = TestSnapshot(timestamp=time.time())

                # Collect interface stats from NetEmu
                try:
                    interfaces = await self._netemu.list_interfaces()
                    snapshot.network_stats = {iface["name"]: iface for iface in interfaces}
                except Exception as e:
                    logger.debug("Failed to collect NetEmu stats: %s", e)

                # Collect Prometheus metrics
                for query in self._promql_queries:
                    try:
                        result = await self._collector.query_instant(query)
                        if result:
                            snapshot.prometheus_metrics[query] = float(result[0]["value"][1])
                    except Exception as e:
                        logger.debug("Failed to query Prometheus (%s): %s", query, e)

                self._snapshots.append(snapshot)
            except Exception as e:
                logger.warning("Metric sampling error: %s", e)

            await asyncio.sleep(self._interval)
