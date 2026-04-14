"""Fortio traffic generator — HTTP/gRPC QPS, latency distribution, success rate."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from doublink_tester.models import TrafficResult

logger = logging.getLogger(__name__)


class FortioGenerator:
    """Wraps the fortio CLI for HTTP/gRPC load testing."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float = 0

    @property
    def name(self) -> str:
        return "fortio"

    def _build_command(
        self,
        target: str,
        duration_s: int,
        qps: int = 0,
        connections: int = 8,
        protocol: str = "http",
        payload_size: int = 0,
    ) -> list[str]:
        cmd = [
            "fortio", "load",
            "-json", "-",  # JSON output to stdout
            "-qps", str(qps),
            "-c", str(connections),
            "-t", f"{duration_s}s",
        ]
        if protocol == "grpc":
            cmd.extend(["-grpc", "-payload-size", str(payload_size)])
        cmd.append(target)
        return cmd

    async def start(self, target: str, duration_s: int, **kwargs: Any) -> None:
        cmd = self._build_command(target, duration_s, **kwargs)
        logger.info("Starting fortio: %s", " ".join(cmd))
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
            raise RuntimeError("fortio not started")
        stdout, stderr = await self._process.communicate()
        ended_at = time.time()
        raw = stdout.decode("utf-8", errors="replace")
        if stderr:
            logger.debug("fortio stderr: %s", stderr.decode("utf-8", errors="replace"))
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
            logger.error("Failed to parse fortio JSON output")
            return TrafficResult(
                generator="fortio", protocol="http", raw_output=raw,
                started_at=self._started_at, ended_at=ended_at,
            )

        duration = data.get("ActualDuration", 0) / 1_000_000_000  # ns → s
        qps = data.get("ActualQPS", 0)

        # Latency percentiles (in seconds → ms)
        dh = data.get("DurationHistogram", {})
        percentiles = {p["Percentile"]: p["Value"] * 1000 for p in dh.get("Percentiles", [])}
        avg_ms = dh.get("Avg", 0) * 1000

        # Status code counts
        ret_codes = data.get("RetCodes", {})
        total = sum(ret_codes.values()) if ret_codes else 0
        ok_count = ret_codes.get("200", 0) + ret_codes.get("0", 0)  # 0 is gRPC OK
        success_rate = ok_count / total if total > 0 else 0.0

        return TrafficResult(
            generator="fortio",
            protocol="grpc" if data.get("Destination", "").startswith("grpc") else "http",
            qps=qps,
            latency_avg_ms=avg_ms,
            latency_p95_ms=percentiles.get(95, 0),
            latency_p99_ms=percentiles.get(99, 0),
            success_rate=success_rate,
            raw_output=raw,
            started_at=self._started_at,
            ended_at=ended_at,
        )
