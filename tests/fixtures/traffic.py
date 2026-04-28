"""Traffic generator fixtures — create, run, and auto-cleanup traffic generators.

Every iperf3 result automatically gets a per-second throughput chart attached to
the current Allure report step.  For multi-phase tests (e.g. mode-switching) use
``attach_combined_chart()`` to stitch multiple results into one timeline chart
with vertical markers at the exact switch points.
"""

from __future__ import annotations

import logging
from typing import Any

import allure
import pytest_asyncio

from doublink_tester.models import TrafficResult
from doublink_tester.traffic.iperf3 import Iperf3Generator
from doublink_tester.traffic.factory import from_profile
from doublink_tester.metrics.chart import generate_single_chart, generate_combined_chart

logger = logging.getLogger(__name__)


def _attach_chart(chart_bytes: bytes, name: str) -> None:
    """Attach a PNG chart to the current Allure test step (no-op if empty)."""
    if chart_bytes:
        allure.attach(chart_bytes, name=name, attachment_type=allure.attachment_type.PNG)


def attach_combined_chart(
    results: list[tuple[str, TrafficResult]],
    events: list[tuple[float, str]] | None = None,
    title: str = "",
    name: str = "traffic_timeline.png",
) -> None:
    """Attach a combined multi-phase traffic timeline chart to the current Allure test.

    Use this for mode-switching or multi-phase tests where you want to see all
    measurement phases on a single time axis with event markers.

    Args:
        results: Ordered list of ``(phase_label, TrafficResult)`` — e.g.
                 ``[("Bonding", result_before), ("Duplicate", result_after)]``.
        events:  List of ``(t_stitched_seconds, label)`` pairs marking switch
                 points on the stitched timeline.  Pass the cumulative duration of
                 the preceding phase(s) as ``t_stitched``.

                 Convenience: if you only have two phases and one switch, pass::

                     events=[(result_phase1_duration, "Mode Switch → Bonding")]

                 where ``result_phase1_duration`` is
                 ``result1.timeseries[-1].t_end`` (or the iperf3 duration_s).
        title:   Chart title shown at the top of the PNG.
        name:    Allure attachment filename.

    Example::

        result_rt   = await iperf3_runner(protocol="tcp", duration_s=15)
        await set_multilink_mode("bonding")
        result_bond = await iperf3_runner(protocol="tcp", duration_s=15)

        t_switch = result_rt.timeseries[-1].t_end if result_rt.timeseries else 15.0
        attach_combined_chart(
            results=[("Real-time", result_rt), ("Bonding", result_bond)],
            events=[(t_switch, "→ Bonding")],
            title="Throughput: Real-time vs Bonding",
        )
    """
    chart_bytes = generate_combined_chart(results, events=events, title=title)
    _attach_chart(chart_bytes, name)


@pytest_asyncio.fixture(loop_scope="session")
async def iperf3_runner(settings):
    """Factory fixture: run iperf3 tests against the configured server.

    After each run a per-second throughput chart is automatically attached to the
    Allure report.  For multi-phase charts use ``attach_combined_chart()``.

    Usage::

        async def test_throughput(iperf3_runner):
            result = await iperf3_runner(protocol="tcp", duration_s=10)
            assert result.throughput_mbps > 1.0
    """
    generators: list[Iperf3Generator] = []
    _run_counter = [0]

    async def _run(
        protocol: str = "tcp",
        duration_s: int = 10,
        bandwidth: str | None = None,
        parallel: int = 1,
        reverse: bool = False,
        server: str | None = None,
        port: int = 5201,
        chart_title: str = "",
        chart_events: list[tuple[float, str]] | None = None,
    ) -> TrafficResult:
        host = server or settings.iperf3_server
        target = f"{host}:{port}"
        gen = Iperf3Generator(server_host=host, server_port=port)
        generators.append(gen)
        result = await gen.run(
            target=target,
            duration_s=duration_s,
            protocol=protocol,
            bandwidth=bandwidth,
            parallel=parallel,
            reverse=reverse,
        )

        # Auto-attach per-second throughput chart to Allure
        _run_counter[0] += 1
        title = chart_title or f"iperf3 {protocol.upper()} — {duration_s}s"
        chart_name = f"traffic_{protocol}_{_run_counter[0]:02d}.png"
        chart_bytes = generate_single_chart(result, title=title, events=chart_events)
        _attach_chart(chart_bytes, chart_name)

        return result

    yield _run

    # Teardown: stop any still-running generators
    for gen in generators:
        if gen.is_running():
            try:
                await gen.stop()
            except Exception:
                logger.warning("Failed to stop iperf3 generator during teardown")


@pytest_asyncio.fixture(loop_scope="session")
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
