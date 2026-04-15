"""Shared domain models for doublink-tester."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MultilinkMode(str, Enum):
    REAL_TIME = "real_time"       # mode 0
    BONDING = "bonding"           # mode 3
    DUPLICATE = "duplicate"       # mode 4


class Direction(str, Enum):
    EGRESS = "egress"
    INGRESS = "ingress"
    BOTH = "both"


class TestVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


@dataclass
class VariationConfig:
    delay_range_ms: float = 0
    jitter_range_ms: float = 0
    loss_range_pct: float = 0
    bw_range_kbit: int = 0
    interval_s: int = 5


@dataclass
class DisconnectScheduleConfig:
    enabled: bool = False
    disconnect_s: float = 5.0
    interval_s: float = 30.0
    repeat: int = 0


@dataclass
class RuleCreateParams:
    """Parameters for creating a network emulation rule via NetEmu API."""

    interface: str
    label: str = ""
    direction: str = "egress"
    bandwidth_kbit: int = 0
    delay_ms: float = 0
    jitter_ms: float = 0
    loss_pct: float = 0
    corrupt_pct: float = 0
    duplicate_pct: float = 0
    disorder_pct: float = 0
    variation_enabled: bool = False
    variation: VariationConfig | None = None
    disconnect_schedule: DisconnectScheduleConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "interface": self.interface,
            "label": self.label,
            "direction": self.direction,
            "bandwidth_kbit": self.bandwidth_kbit,
            "delay_ms": self.delay_ms,
            "jitter_ms": self.jitter_ms,
            "loss_pct": self.loss_pct,
            "corrupt_pct": self.corrupt_pct,
            "duplicate_pct": self.duplicate_pct,
            "disorder_pct": self.disorder_pct,
            "variation_enabled": self.variation_enabled,
        }
        if self.variation is not None:
            d["variation"] = {
                "delay_range_ms": self.variation.delay_range_ms,
                "jitter_range_ms": self.variation.jitter_range_ms,
                "loss_range_pct": self.variation.loss_range_pct,
                "bw_range_kbit": self.variation.bw_range_kbit,
                "interval_s": self.variation.interval_s,
            }
        if self.disconnect_schedule is not None:
            d["disconnect_schedule"] = {
                "enabled": self.disconnect_schedule.enabled,
                "disconnect_s": self.disconnect_schedule.disconnect_s,
                "interval_s": self.disconnect_schedule.interval_s,
                "repeat": self.disconnect_schedule.repeat,
            }
        return d


@dataclass
class LineRuleConfig:
    """Degradation parameters for a single line (DL + UL share same params)."""

    bandwidth_kbit: int = 0
    delay_ms: float = 0
    jitter_ms: float = 0
    loss_pct: float = 0
    corrupt_pct: float = 0
    duplicate_pct: float = 0
    disorder_pct: float = 0
    variation: VariationConfig | None = None
    disconnect_schedule: DisconnectScheduleConfig | None = None

    def to_rule_params(self, interface: str, label: str = "") -> RuleCreateParams:
        return RuleCreateParams(
            interface=interface,
            label=label,
            direction="egress",
            bandwidth_kbit=self.bandwidth_kbit,
            delay_ms=self.delay_ms,
            jitter_ms=self.jitter_ms,
            loss_pct=self.loss_pct,
            corrupt_pct=self.corrupt_pct,
            duplicate_pct=self.duplicate_pct,
            disorder_pct=self.disorder_pct,
            variation_enabled=self.variation is not None,
            variation=self.variation,
            disconnect_schedule=self.disconnect_schedule,
        )

    @property
    def is_clean(self) -> bool:
        return (
            self.bandwidth_kbit == 0
            and self.delay_ms == 0
            and self.jitter_ms == 0
            and self.loss_pct == 0
            and self.corrupt_pct == 0
            and self.duplicate_pct == 0
            and self.disorder_pct == 0
            and self.variation is None
            and self.disconnect_schedule is None
        )


@dataclass
class NetworkConditionProfile:
    """Dual-line network condition profile for ATSSS testing.

    Each profile specifies degradation for LINE A (5G) and LINE B (WiFi)
    independently. The test fixture creates egress rules on all 4 interfaces:
      wan_a_in  (LINE A DL), lan_a_out (LINE A UL),
      wan_b_in  (LINE B DL), lan_b_out (LINE B UL).
    """

    id: str
    name: str
    description: str = ""
    line_a: LineRuleConfig | None = None
    line_b: LineRuleConfig | None = None

    def get_rule_params(self, interfaces: dict[str, str]) -> list[RuleCreateParams]:
        """Generate RuleCreateParams for all affected interfaces.

        Args:
            interfaces: mapping with keys line_a_dl, line_a_ul, line_b_dl, line_b_ul

        Returns:
            List of RuleCreateParams (only for non-clean lines).
        """
        rules: list[RuleCreateParams] = []
        if self.line_a is not None and not self.line_a.is_clean:
            rules.append(self.line_a.to_rule_params(
                interfaces["line_a_dl"], label=f"{self.id}:a_dl"))
            rules.append(self.line_a.to_rule_params(
                interfaces["line_a_ul"], label=f"{self.id}:a_ul"))
        if self.line_b is not None and not self.line_b.is_clean:
            rules.append(self.line_b.to_rule_params(
                interfaces["line_b_dl"], label=f"{self.id}:b_dl"))
            rules.append(self.line_b.to_rule_params(
                interfaces["line_b_ul"], label=f"{self.id}:b_ul"))
        return rules


@dataclass
class MultilinkModeConfig:
    """A multilink mode configuration, loaded from YAML config."""

    id: str
    name: str
    description: str = ""
    mode_value: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrafficProfile:
    """A traffic generation profile, loaded from YAML config."""

    id: str
    generator: str  # "iperf3" | "fortio" | "sipp"
    protocol: str  # "tcp" | "udp" | "http" | "grpc" | "sip"
    duration_s: int = 30
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrafficResult:
    """Normalized result from any traffic generator."""

    generator: str
    protocol: str
    throughput_mbps: float = 0.0
    loss_pct: float = 0.0
    latency_avg_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    jitter_ms: float = 0.0
    success_rate: float = 1.0
    qps: float = 0.0
    raw_output: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
