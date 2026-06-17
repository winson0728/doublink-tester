"""Regression tests for the AI auto mode controller.

Each scenario mirrors a real entry from the network-condition profiles /
golden-scenario matrix, asserting the controller picks the mode the test suite
proved best for that condition.  These are pure (no network) — they drive the
controller's own smoothing + decision path directly, so they run in
milliseconds and pin the algorithm to the test-result orientation.
"""

from __future__ import annotations

import pytest

from doublink_tester.models import LinkInfo
from doublink_tester.control import AutoModeController, ControllerConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def link(socket_id: int, latency_ms: float, loss_pct: float,
         weight: int = 50, tput: float = 1000.0) -> LinkInfo:
    """Build a LinkInfo sample (loss applied symmetrically from/to)."""
    return LinkInfo(
        socket_id=socket_id, address="", latency_ms=latency_ms,
        latency_min_ms=latency_ms, latency_max_ms=latency_ms, jitter_ms=5.0,
        latency_diff_ms=0.0, loss_from_pct=loss_pct, loss_to_pct=loss_pct,
        weight=weight, inbound_throughput=tput, outbound_throughput=tput,
    )


def feed(samples: list[list[LinkInfo]], start_mode: str = "bonding"):
    """Drive the controller's smoothing + decision over a sample sequence.

    Returns the final ModeDecision. Uses the controller's own
    _extract_features + decide (the pure logic path) — no event loop needed.
    """
    ctrl = AutoModeController(fetch=None, actuate=None,
                             config=ControllerConfig(), current_mode=start_mode)
    decision = None
    for links in samples:
        feats = ctrl._extract_features(links)
        decision = ctrl.decide(feats)
        # emulate tick()'s state commit (dwell is time-based; ignore it here)
        if decision.mode != ctrl.current_mode:
            ctrl.current_mode = decision.mode
            decision.switched = True
    return decision, ctrl


def steady(links: list[LinkInfo], n: int = 8) -> list[list[LinkInfo]]:
    return [links for _ in range(n)]


# ── Scenario table — condition → expected mode (oriented by test results) ─────

@pytest.mark.parametrize("label, samples, expected", [
    # Both links healthy & comparable → aggregate (golden A1/A2)
    ("clean_controlled",
     steady([link(0, 25, 0.1), link(1, 10, 0.1)]), "bonding"),
    ("symmetric_mild_loss_0.3pct",
     steady([link(0, 20, 0.3), link(1, 20, 0.3)]), "bonding"),

    # One link steadily degraded (escapable) → steer to the good one (steering tests)
    ("5g_degraded_moderate_1.5pct",
     steady([link(0, 60, 1.5), link(1, 10, 0.1)]), "real_time"),
    ("5g_high_latency_100ms",
     steady([link(0, 100, 0.2), link(1, 10, 0.2)]), "real_time"),

    # Loss at/above the C1 boundary, or both links lossy → replicate
    ("golden_c1_loss_protection_2pct",
     steady([link(0, 30, 2.0), link(1, 10, 0.2)]), "duplicate"),
    ("congested_recoverable_1pct_both",
     steady([link(0, 80, 1.0), link(1, 80, 1.0)]), "duplicate"),

    # Fully dead link → single-path failover (real_time on survivor)
    ("hard_failover_5g_dead",
     steady([link(0, 1500, 100.0, weight=0, tput=0.0), link(1, 10, 0.1)]), "real_time"),
])
def test_mode_selection(label, samples, expected):
    decision, _ = feed(samples)
    assert decision.mode == expected, (
        f"[{label}] expected {expected}, got {decision.mode} "
        f"(scores={ {k: round(v, 2) for k, v in decision.scores.items()} }; "
        f"reason={decision.reason})"
    )


def test_c2_burst_loss_selects_duplicate():
    """Golden C2 — 5G loss alternates 0↔10 %: volatility → replicate."""
    samples = [[link(0, 30, 10.0 if i % 2 == 0 else 0.0), link(1, 10, 0.1)]
               for i in range(8)]
    decision, _ = feed(samples)
    assert decision.mode == "duplicate", decision.reason


def test_b2_intermittent_flap_selects_duplicate():
    """Golden B2 — 5G drops out periodically (loss→100): flap → replicate."""
    samples = []
    for i in range(8):
        up = i % 2 == 0
        samples.append([
            link(0, 30 if up else 1500, 0.1 if up else 100.0,
                 weight=50 if up else 0, tput=1000.0 if up else 0.0),
            link(1, 10, 0.1),
        ])
    decision, _ = feed(samples)
    assert decision.mode == "duplicate", decision.reason


def test_transient_spike_does_not_flap():
    """A single isolated loss spike must NOT change the mode (anti-oscillation)."""
    healthy = [link(0, 25, 0.1), link(1, 10, 0.1)]
    spike = [link(0, 25, 8.0), link(1, 10, 0.1)]
    samples = [healthy] * 3 + [spike] + [healthy] * 5
    decision, _ = feed(samples)
    assert decision.mode == "bonding", (
        f"transient spike flapped the mode to {decision.mode}: {decision.reason}"
    )


def test_sustained_change_switches_after_confirmation():
    """A sustained asymmetric degradation must switch — but only after the
    confirmation window (not on the first sample)."""
    ctrl = AutoModeController(fetch=None, actuate=None,
                             config=ControllerConfig(), current_mode="bonding")
    sustained = [link(0, 60, 1.5), link(1, 10, 0.1)]
    modes = []
    for _ in range(5):
        feats = ctrl._extract_features(sustained)
        d = ctrl.decide(feats)
        modes.append(d.mode)
        ctrl.current_mode = d.mode
    # Held bonding through the confirmation window, then switched to real_time
    assert modes[0] == "bonding"
    assert modes[-1] == "real_time"
    assert modes.count("real_time") <= ControllerConfig().confirm_samples + 1


def test_no_telemetry_holds_current_mode():
    """Empty link list (API hiccup) must never change the mode."""
    ctrl = AutoModeController(fetch=None, actuate=None, current_mode="bonding")
    d = ctrl.decide([])
    assert d.mode == "bonding" and not d.switched
