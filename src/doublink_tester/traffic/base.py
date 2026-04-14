"""Traffic generator protocol — all generators must implement this interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from doublink_tester.models import TrafficResult


@runtime_checkable
class TrafficGenerator(Protocol):
    """Interface that all traffic generators implement."""

    @property
    def name(self) -> str:
        """Generator name (e.g. 'iperf3', 'fortio', 'sipp')."""
        ...

    async def start(self, target: str, duration_s: int, **kwargs: Any) -> None:
        """Start traffic generation in background."""
        ...

    async def stop(self) -> None:
        """Stop traffic generation gracefully."""
        ...

    async def wait(self) -> TrafficResult:
        """Wait for completion and return parsed results."""
        ...

    async def run(self, target: str, duration_s: int, **kwargs: Any) -> TrafficResult:
        """Start, wait, and return results (convenience method)."""
        ...

    def is_running(self) -> bool:
        """Return True if the generator is currently running."""
        ...
