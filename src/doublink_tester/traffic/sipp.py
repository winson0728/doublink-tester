"""SIPp traffic generator — SIP call setup, hold, continuity testing."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from typing import Any

from doublink_tester.models import TrafficResult

logger = logging.getLogger(__name__)


class SippGenerator:
    """Wraps the SIPp CLI for SIP call testing."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float = 0

    @property
    def name(self) -> str:
        return "sipp"

    def _build_command(
        self,
        target: str,
        duration_s: int,
        scenario: str = "uac",
        calls_per_second: float = 1.0,
        max_calls: int = 10,
    ) -> list[str]:
        host, _, port = target.partition(":")
        port = port or "5060"

        cmd = [
            "sipp", f"{host}:{port}",
            "-sn", scenario,
            "-r", str(calls_per_second),
            "-m", str(max_calls),
            "-timeout", str(duration_s),
            "-trace_stat",
            "-stf", "/dev/stdout",
            "-fd", "1",  # stat dump frequency 1s
            "-bg",  # suppress interactive display
        ]
        return cmd

    async def start(self, target: str, duration_s: int, **kwargs: Any) -> None:
        cmd = self._build_command(target, duration_s, **kwargs)
        logger.info("Starting sipp: %s", " ".join(cmd))
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
            raise RuntimeError("sipp not started")
        stdout, stderr = await self._process.communicate()
        ended_at = time.time()
        raw = stdout.decode("utf-8", errors="replace")
        if stderr:
            logger.debug("sipp stderr: %s", stderr.decode("utf-8", errors="replace"))
        return self._parse_stat_output(raw, ended_at)

    async def run(self, target: str, duration_s: int, **kwargs: Any) -> TrafficResult:
        await self.start(target, duration_s, **kwargs)
        return await self.wait()

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _parse_stat_output(self, raw: str, ended_at: float) -> TrafficResult:
        """Parse SIPp CSV stat output for call success/failure counts."""
        total_calls = 0
        successful_calls = 0
        failed_calls = 0

        try:
            reader = csv.DictReader(io.StringIO(raw), delimiter=";")
            for row in reader:
                total_calls = int(row.get("TotalCallCreated", 0))
                successful_calls = int(row.get("SuccessfulCall(C)", 0))
                failed_calls = int(row.get("FailedCall(C)", 0))
        except Exception:
            logger.warning("Failed to parse sipp stat output")

        success_rate = successful_calls / total_calls if total_calls > 0 else 0.0

        return TrafficResult(
            generator="sipp",
            protocol="sip",
            success_rate=success_rate,
            raw_output=raw,
            started_at=self._started_at,
            ended_at=ended_at,
        )
