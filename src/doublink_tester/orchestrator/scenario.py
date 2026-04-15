"""Test scenario data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestScenario:
    """Describes a complete test scenario to be executed by the orchestrator.

    Network conditions are applied as dual-line ATSSS profiles — the orchestrator
    uses settings.interfaces to derive the 4 interface names automatically.
    """

    name: str
    mode: str
    network_condition: str
    traffic_profile: str
    duration_s: int = 30
    settle_time_s: float = 5.0
    assertions: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)
