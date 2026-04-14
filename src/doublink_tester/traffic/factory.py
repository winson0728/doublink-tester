"""Factory for creating traffic generator instances from profiles."""

from __future__ import annotations

from typing import Any

from doublink_tester.models import TrafficProfile
from doublink_tester.traffic.base import TrafficGenerator
from doublink_tester.traffic.fortio import FortioGenerator
from doublink_tester.traffic.iperf3 import Iperf3Generator
from doublink_tester.traffic.sipp import SippGenerator


_REGISTRY: dict[str, type] = {
    "iperf3": Iperf3Generator,
    "fortio": FortioGenerator,
    "sipp": SippGenerator,
}


def create_generator(generator_type: str, **kwargs: Any) -> TrafficGenerator:
    """Create a traffic generator by type name."""
    cls = _REGISTRY.get(generator_type)
    if cls is None:
        raise ValueError(f"Unknown traffic generator: {generator_type!r}. Available: {list(_REGISTRY)}")
    return cls(**kwargs)


def from_profile(profile: TrafficProfile) -> TrafficGenerator:
    """Create a traffic generator from a TrafficProfile config."""
    # Extract constructor-level kwargs (e.g. server_host for iperf3)
    init_kwargs: dict[str, Any] = {}
    if profile.generator == "iperf3":
        if "server_host" in profile.parameters:
            init_kwargs["server_host"] = profile.parameters["server_host"]
        if "server_port" in profile.parameters:
            init_kwargs["server_port"] = profile.parameters["server_port"]
    return create_generator(profile.generator, **init_kwargs)
