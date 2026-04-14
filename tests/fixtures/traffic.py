"""Traffic generator fixtures — create, run, and auto-cleanup traffic generators."""

from __future__ import annotations

import logging
from typing import Any

import pytest
import pytest_asyncio

from doublink_tester.models import TrafficResult
from doublink_tester.traffic.iperf3 import Iperf3Generator
from doublink_tester.traffic.factory import from_profile

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def iperf3_runner(settings):
    """Factory fixture: run iperf3 tests against the configured server.

    Usage::

        async def test_throughput(iperf3_runner):
            result = await iperf3_runner(protocol="tcp", duration_s=10)
            assert result.throughput_mbps > 1.0
    """
    generators: list[Iperf3Generator] = []

    async def _run(
        protocol: str = "tcp",
        duration_s: int = 10,
        bandwidth: str | None = None,
        parallel: int = 1,
        reverse: bool = False,
        server: str | None = None,
        port: int = 5201,
    ) -> TrafficResult:
        host = server or settings.iperf3_server
        target = f"{host}:{port}"
        gen = Iperf3Generator(server_host=host, server_port=port)
        generators.append(gen)
        return await gen.run(
            target=target,
            duration_s=duration_s,
            protocol=protocol,
            bandwidth=bandwidth,
            parallel=parallel,
            reverse=reverse,
        )

    yield _run

    # Teardown: stop any still-running generators
    for gen in generators:
        if gen.is_running():
            try:
                await gen.stop()
            except Exception:
                logger.warning("Failed to stop iperf3 generator during teardown")


@pytest_asyncio.fixture
async def traffic_runner(settings, traffic_profiles):
    """Factory fixture: run traffic from a named profile.

    Usage::

        async def test_tcp(traffic_runner):
            result = await traffic_runner("tcp_throughput")
            assert result.throughput_mbps > 1.0
    """
    generators = []

    async def _run(profile_id: str, server: str | None = None, **overrides: Any) -> TrafficResult:
        profile = traffic_profiles[profile_id]
        gen = from_profile(profile)
        generators.append(gen)

        # Determine target
        if profile.generator == "iperf3":
            host = server or settings.iperf3_server
            target = f"{host}:5201"
        else:
            host = server or settings.test_server
            target = host

        # Merge profile parameters with overrides
        kwargs = dict(profile.parameters)
        kwargs.update(overrides)

        return await gen.run(target=target, duration_s=profile.duration_s, **kwargs)

    yield _run

    for gen in generators:
        if gen.is_running():
            try:
                await gen.stop()
            except Exception:
                logger.warning("Failed to stop traffic generator during teardown")
