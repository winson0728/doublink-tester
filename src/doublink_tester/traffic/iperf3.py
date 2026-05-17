"""iperf3 traffic generator — TCP/UDP/SCTP throughput, loss, jitter testing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from doublink_tester.models import TrafficResult, TrafficTimepoint

logger = logging.getLogger(__name__)


class Iperf3Generator:
    """Wraps the iperf3 CLI for network performance testing."""

    def __init__(self, server_host: str = "localhost", server_port: int = 5201):
        self._server_host = server_host
        self._server_port = server_port
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float = 0

    @property
    def name(self) -> str:
        return "iperf3"

    def _build_command(
        self,
        target: str,
        duration_s: int,
        protocol: str = "tcp",
        bandwidth: str | None = None,
        parallel: int = 1,
        reverse: bool = False,
    ) -> list[str]:
        host, _, port = target.partition(":")
        port = port or str(self._server_port)

        # -i 3: report intervals every 3 s (aligns with link sampling cadence) —
        # for long-duration runs (3-5 min) this cuts TrafficTimepoint count by ~3x
        # and proportionally reduces matplotlib rendering + Allure attachment size.
        cmd = ["iperf3", "-c", host, "-p", port, "-t", str(duration_s), "-i", "3", "-J"]
        if protocol == "udp":
            cmd.append("-u")
            if bandwidth:
                cmd.extend(["-b", bandwidth])
        elif protocol == "sctp":
            cmd.append("--sctp")
        if parallel > 1:
            cmd.extend(["-P", str(parallel)])
        if reverse:
            cmd.append("-R")
        return cmd

    async def start(self, target: str, duration_s: int, **kwargs: Any) -> None:
        cmd = self._build_command(target, duration_s, **kwargs)
        logger.info("Starting iperf3: %s", " ".join(cmd))
        self._started_at = time.time()
        self._process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()

    async def wait(self) -> TrafficResult:
        if self._process is None:
            raise RuntimeError("iperf3 not started")
        stdout, stderr = await self._process.communicate()
        ended_at = time.time()
        raw = stdout.decode("utf-8", errors="replace")
        if stderr:
            logger.warning("iperf3 stderr: %s", stderr.decode("utf-8", errors="replace"))
        return self._parse_json_output(raw, ended_at)

    async def run(
        self,
        target: str,
        duration_s: int,
        retries: int = 3,
        retry_delay_s: float = 8.0,
        **kwargs: Any,
    ) -> TrafficResult:
        """Run iperf3 with retry logic for transient errors.

        Retries on: server busy, connection refused, connection reset, no route to host,
        or any JSON-parse failure (protocol == "unknown") — all of which indicate the
        server was temporarily unavailable rather than a real measurement failure.
        """
        last_result: TrafficResult | None = None
        for attempt in range(1, retries + 1):
            await self.start(target, duration_s, **kwargs)
            result = await self.wait()

            # Classify transient vs real errors when throughput is zero.
            # "server is busy"       — iperf3 server occupied by another client
            # "Connection refused"   — server process crashed / port not open yet
            # "unable to connect"    — server unreachable (covers both refused & timeout)
            # "Connection reset"     — session torn mid-flight by a mode switch
            # "No route to host"     — routing gap during multilink state change
            # protocol == "unknown"  — iperf3 produced non-JSON output (any crash/error)
            if result.throughput_mbps == 0:
                raw = result.raw_output or ""
                is_transient = (
                    "server is busy" in raw
                    or "Connection refused" in raw
                    or "unable to connect" in raw
                    or "Connection reset" in raw
                    or "unable to send control message" in raw
                    or "No route to host" in raw
                    or "Network is unreachable" in raw
                    or result.protocol == "unknown"
                )
            else:
                is_transient = False

            if not is_transient or attempt == retries:
                return result

            logger.warning(
                "iperf3 transient error (attempt %d/%d), retrying in %.0fs ...",
                attempt, retries, retry_delay_s,
            )
            last_result = result
            await asyncio.sleep(retry_delay_s)

        return last_result or result  # type: ignore[possibly-undefined]

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _parse_timeseries(self, intervals: list[dict], protocol: str) -> list[TrafficTimepoint]:
        """Parse iperf3 per-second interval data into TrafficTimepoint list.

        Skips 'omitted' warm-up intervals that iperf3 marks as not counted.
        """
        points: list[TrafficTimepoint] = []
        for interval in intervals:
            s = interval.get("sum", {})
            if s.get("omitted", False):
                continue
            points.append(TrafficTimepoint(
                t_start=s.get("start", 0.0),
                t_end=s.get("end", 0.0),
                throughput_mbps=s.get("bits_per_second", 0) / 1_000_000,
                loss_pct=s.get("lost_percent", 0.0),
                jitter_ms=s.get("jitter_ms", 0.0),
            ))
        return points

    def _parse_json_output(self, raw: str, ended_at: float) -> TrafficResult:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Failed to parse iperf3 JSON output")
            return TrafficResult(
                generator="iperf3", protocol="unknown", raw_output=raw,
                started_at=self._started_at, ended_at=ended_at,
            )

        end = data.get("end", {})
        intervals = data.get("intervals", [])
        protocol = "udp" if "sum" in end and "jitter_ms" in end.get("sum", {}) else "tcp"
        timeseries = self._parse_timeseries(intervals, protocol)

        if protocol == "udp":
            summary = end.get("sum", {})
            return TrafficResult(
                generator="iperf3",
                protocol="udp",
                throughput_mbps=summary.get("bits_per_second", 0) / 1_000_000,
                loss_pct=summary.get("lost_percent", 0),
                jitter_ms=summary.get("jitter_ms", 0),
                raw_output=raw,
                started_at=self._started_at,
                ended_at=ended_at,
                timeseries=timeseries,
            )

        # TCP
        received = end.get("sum_received", {})
        return TrafficResult(
            generator="iperf3",
            protocol="tcp",
            throughput_mbps=received.get("bits_per_second", 0) / 1_000_000,
            raw_output=raw,
            started_at=self._started_at,
            ended_at=ended_at,
            timeseries=timeseries,
        )
