"""iperf3 traffic generator — TCP/UDP/SCTP throughput, loss, jitter testing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from doublink_tester.models import TrafficResult

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

        cmd = ["iperf3", "-c", host, "-p", port, "-t", str(duration_s), "-J"]  # JSON output
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

    async def run(self, target: str, duration_s: int, **kwargs: Any) -> TrafficResult:
        await self.start(target, duration_s, **kwargs)
        return await self.wait()

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

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
        protocol = "udp" if "sum" in end and "jitter_ms" in end.get("sum", {}) else "tcp"

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
            )

        # TCP
        sent = end.get("sum_sent", {})
        received = end.get("sum_received", {})
        return TrafficResult(
            generator="iperf3",
            protocol="tcp",
            throughput_mbps=received.get("bits_per_second", 0) / 1_000_000,
            raw_output=raw,
            started_at=self._started_at,
            ended_at=ended_at,
        )
