"""Test result models for the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from doublink_tester.models import TrafficResult, TestVerdict
from doublink_tester.metrics.sampler import TestSnapshot


@dataclass
class TestRunResult:
    """Result of a single test scenario execution."""

    scenario_name: str
    verdict: TestVerdict = TestVerdict.SKIPPED
    traffic_result: TrafficResult | None = None
    snapshots: list[TestSnapshot] = field(default_factory=list)
    mode_switch_duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
