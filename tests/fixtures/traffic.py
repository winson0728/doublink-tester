"""Traffic generator fixtures — create, run, and auto-cleanup traffic generators.

Every iperf3 run automatically:
  1. Polls the Doublink /links API every second **concurrently** with the iperf3
     measurement, collecting per-link latency, jitter, loss, and ATSSS weight.
  2. Stitches the iperf3 per-second throughput together with the link samples
     into a single 3-panel chart:
       Panel 1 — Throughput (Mbps) overlaid with ATSSS weight per link (right Y)
       Panel 2 — RTT (ms) per link
       Panel 3 — Packet loss % per link
  The combined chart is attached to the current Allure test step automatically.

For multi-phase tests (e.g. mode-switching) use ``attach_combined_chart()`` to
stitch multiple results into one timeline with vertical markers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import allure
import pytest_asyncio

from doublink_tester.models import TrafficResult
from doublink_tester.traffic.iperf3 import Iperf3Generator
from doublink_tester.traffic.factory import from_profile
from doublink_tester.metrics.chart import (
    generate_combined_chart,
    generate_single_chart,
    generate_traffic_link_chart,
)

logger = logging.getLogger(__name__)

# How often to poll the /links API during iperf3 runs (seconds)
_LINK_POLL_INTERVAL = 1.0


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
                 points on the stitched timeline.
        title:   Chart title shown at the top of the PNG.
        name:    Allure attachment filename.
    """
    chart_bytes = generate_combined_chart(results, events=events, title=title)
    _attach_chart(chart_bytes, name)


# ── Link poller ────────────────────────────────────────────────────────────────

async def _poll_links_task(
    multilink_client,
    t0: float,
    stop_event: asyncio.Event,
    samples: list,          # list of (t_elapsed, [LinkInfo, ...])
) -> None:
    """Background task: poll /links API at 1 Hz until stop_event is set.

    Samples are appended to *samples* as ``(t_elapsed_seconds, [LinkInfo, ...])``.
    All errors are silently logged so a broken API never fails an iperf3 test.
    """
    while not stop_event.is_set():
        try:
            links = await multilink_client.get_links()
            t_elapsed = time.monotonic() - t0
            samples.append((t_elapsed, links))
        except Exception as exc:
            logger.debug("link poller: API call failed — %s", exc)
        # Sleep _LINK_POLL_INTERVAL, but wake immediately if stop_event fires
        try:
            await asyncio.wait_for(
                asyncio.shield(stop_event.wait()),
                timeout=_LINK_POLL_INTERVAL,
            )
            break  # stop_event was set during sleep
        except asyncio.TimeoutError:
            pass  # interval elapsed — poll again


# ── iperf3_runner fixture ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="session")
async def iperf3_runner(settings, multilink_client):
    """Factory fixture: run iperf3 while concurrently sampling link quality.

    **Automatic combined chart**: while iperf3 measures throughput, a background
    task polls ``GET /api/v1/agents/{id}/links`` every second.  After the run the
    fixture generates a 3-panel PNG chart:

      Panel 1 — Throughput (Mbps, left Y) + ATSSS weight per link (right Y, dashed)
                 A weight shift shows exactly when the algorithm re-routed traffic.
      Panel 2 — RTT per link — rising latency should precede a weight reduction.
      Panel 3 — Packet loss % per link (inbound solid, outbound dotted).

    The chart is attached to the Allure report automatically; no test code changes
    are needed.

    A post-run cooldown (``settings.timeouts.iperf3_settle_s``, default 3 s) lets
    the iperf3 server release its connection before the next test.

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

        # ── Concurrent link sampling + iperf3 ─────────────────────────────────
        link_samples: list = []
        stop_event = asyncio.Event()
        t0 = time.monotonic()

        poll_task = asyncio.create_task(
            _poll_links_task(multilink_client, t0, stop_event, link_samples)
        )
        try:
            result = await gen.run(
                target=target,
                duration_s=duration_s,
                protocol=protocol,
                bandwidth=bandwidth,
                parallel=parallel,
                reverse=reverse,
            )
        finally:
            stop_event.set()
            try:
                await asyncio.wait_for(poll_task, timeout=3.0)
            except asyncio.TimeoutError:
                poll_task.cancel()

        # ── Chart: combined throughput + link quality ──────────────────────────
        _run_counter[0] += 1
        title = chart_title or f"iperf3 {protocol.upper()} — {duration_s}s"
        chart_name = f"traffic_{protocol}_{_run_counter[0]:02d}.png"

        chart_bytes = generate_traffic_link_chart(
            result,
            link_samples,
            title=title,
            events=chart_events,
        )
        _attach_chart(chart_bytes, chart_name)

        logger.info(
            "iperf3 [%02d] %s %ds → %.1f Mbps  (link samples: %d)",
            _run_counter[0], protocol.upper(), duration_s,
            result.throughput_mbps, len(link_samples),
        )

        # ── Post-run cooldown ──────────────────────────────────────────────────
        settle = getattr(settings.timeouts, "iperf3_settle_s", 3)
        if settle > 0:
            await asyncio.sleep(settle)

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
