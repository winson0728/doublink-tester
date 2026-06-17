"""AI-assisted automatic ATSSS mode controller for Doublink multilink.

Closed loop
-----------
    poll status2 (/links)  →  extract & smooth features  →  score 3 modes
        →  decide (with hysteresis)  →  actuate (PUT /mode)  →  repeat

The controller reads the Doublink ``status2`` link telemetry (per-link
throughput, latency, jitter, loss, and ATSSS weight) and automatically selects
the best operating mode:

    real_time (0)  — steer to the single lowest-latency path
    bonding   (3)  — aggregate both links for maximum throughput
    duplicate (4)  — replicate packets on both links for reliability ("redundant")

Why these regimes (derived from the 74-case nightly regression)
---------------------------------------------------------------
* **Bonding** wins when both links are healthy and comparable in capacity —
  golden scenario A1/A2 reached ~142 Mbps aggregate vs ~70 Mbps single link.
* **Real-time** wins when the links are asymmetric (one clearly better, no
  severe loss) — the steering tests (5g_degraded / wifi_degraded /
  *_high_latency) confirmed real_time steers traffic onto the healthy link.
* **Duplicate / redundant** wins when a link is lossy or unstable — golden C1
  (5G 2% loss) showed duplicate success-rate 0.98 vs bonding 0.90, and C2
  (0–10% burst loss) / B2 (intermittent flap) stayed stable only under
  duplicate.

Anti-oscillation (the key production lesson)
--------------------------------------------
The chart-interpretation guide flagged *"weight oscillating between links =
stability issue, needs smoothing"*.  This controller therefore never reacts to
a single sample.  It applies:

* **EWMA smoothing** on loss and latency,
* a **confirmation window** (a new mode must win N consecutive evaluations),
* a **minimum dwell time** after every switch, and
* a **hysteresis margin** (the incumbent mode gets a score bonus),

so a brief spike can never flap the mode.

The decision is a pure function of the smoothed features and controller state
(:meth:`AutoModeController.decide`), making it fully testable and explainable —
every switch carries a human-readable ``reason`` and the per-mode scores.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Deque

from doublink_tester.models import LinkInfo

logger = logging.getLogger(__name__)

# Mode names as understood by MultilinkClient.set_mode()
MODE_REALTIME = "real_time"
MODE_BONDING = "bonding"
MODE_REDUNDANT = "duplicate"   # a.k.a. "redundant" / replication


# ─────────────────────────────────────────────────────────────────────────────
# Configuration — defaults grounded in the test-matrix thresholds
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ControllerConfig:
    """Tunable thresholds. Defaults come straight from the regression results."""

    # Sampling / loop
    poll_interval_s: float = 3.0          # matches the 3 s link-sampling cadence
    ewma_alpha: float = 0.4               # smoothing weight for new samples
    window: int = 10                      # samples kept for volatility/flap (~30 s)

    # Loss thresholds (max of loss_from / loss_to per link), in percent
    loss_healthy_pct: float = 0.5         # below → link counts as healthy
    loss_redundant_pct: float = 2.0       # at/above → reliability at risk (C1 = 2%)
    loss_volatile_std_pct: float = 1.5    # loss std over window → burst (C2)

    # Latency / jitter thresholds, in ms
    latency_healthy_ms: float = 60.0      # clean profiles sit at 10–25 ms
    latency_high_ms: float = 100.0        # high_latency profile = 100 ms
    jitter_healthy_ms: float = 30.0

    # Bonding comparability: links bond well when capacities are within this ratio.
    # A2 bonded a 2:1 (80M/40M) split successfully → 0.5 is a safe floor.
    bonding_capacity_ratio: float = 0.5

    # Flap detection: this many active→inactive transitions in the window → flapping
    flap_transitions: int = 2

    # Hysteresis / anti-flap
    min_dwell_s: float = 20.0             # matches mode_switch_s settling time
    confirm_samples: int = 3              # 3 × 3 s = 9 s < 10 s "healthy response"
    switch_margin: float = 0.15           # candidate must beat incumbent by this

    # Safety
    redundant_is_safe_default: bool = True  # on missing/garbage telemetry, hold or go safe


# ─────────────────────────────────────────────────────────────────────────────
# Feature & decision records
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LinkFeatures:
    """Smoothed, decision-ready view of one link."""

    socket_id: int
    name: str
    loss_pct: float            # EWMA of max(loss_from, loss_to)
    loss_std_pct: float        # std of loss over the window (reporting only)
    loss_bursts: int           # # times loss CROSSED up over the line (alternation)
    latency_ms: float          # EWMA latency
    jitter_ms: float           # EWMA jitter
    weight: int                # latest ATSSS weight (algorithm's own steering)
    capacity: float            # latest throughput proxy (in+out)
    active: bool               # carrying traffic / reachable right now
    flapping: bool             # repeatedly toggling active in the window

    @property
    def health(self) -> float:
        """Composite link health in [0, 1] (1 = pristine)."""
        # Loss term — drops to 0 by loss_redundant_pct
        loss_term = _clamp(1.0 - self.loss_pct / 2.0)          # 0% →1, 2% →0
        # Latency term — 1 up to 60 ms, 0 by 100 ms
        lat_term = _clamp(1.0 - (self.latency_ms - 60.0) / 40.0)
        # Jitter term — 1 up to 30 ms, 0 by 90 ms
        jit_term = _clamp(1.0 - (self.jitter_ms - 30.0) / 60.0)
        score = 0.6 * loss_term + 0.3 * lat_term + 0.1 * jit_term
        if self.flapping or not self.active:
            score *= 0.3
        return _clamp(score)


@dataclass
class ModeDecision:
    """Output of one decision cycle."""

    mode: str
    reason: str
    scores: dict[str, float]
    switched: bool = False
    features: list[LinkFeatures] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────────────────

# A fetcher returns the current link list. Defaults to multilink_client.get_links.
LinkFetcher = Callable[[], Awaitable[list[LinkInfo]]]
# An actuator applies a mode by name. Defaults to multilink_client.set_mode.
ModeActuator = Callable[[str], Awaitable[object]]


class AutoModeController:
    """Stateful closed-loop controller.

    Usage::

        async with MultilinkClient(...) as ml:
            ctrl = AutoModeController(
                fetch=ml.get_links,
                actuate=ml.set_mode,
                config=ControllerConfig(),
                current_mode="bonding",
            )
            await ctrl.run()                # runs until cancelled

    Or drive it manually (e.g. in a test) one tick at a time::

        decision = await ctrl.tick()
    """

    def __init__(
        self,
        fetch: LinkFetcher,
        actuate: ModeActuator,
        config: ControllerConfig | None = None,
        current_mode: str = MODE_BONDING,
    ) -> None:
        self._fetch = fetch
        self._actuate = actuate
        self.cfg = config or ControllerConfig()
        self.current_mode = current_mode

        # Per-link smoothing state, keyed by socket_id
        self._loss_ewma: dict[int, float] = {}
        self._lat_ewma: dict[int, float] = {}
        self._jit_ewma: dict[int, float] = {}
        self._loss_hist: dict[int, Deque[float]] = {}
        self._active_hist: dict[int, Deque[bool]] = {}

        # Hysteresis state
        self._last_switch_t: float = 0.0
        self._pending_mode: str | None = None
        self._pending_count: int = 0

    # ── Public API ───────────────────────────────────────────────────────────

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Run the control loop until *stop* is set (or forever)."""
        logger.info("AutoModeController starting in mode=%s", self.current_mode)
        while stop is None or not stop.is_set():
            try:
                await self.tick()
            except Exception as exc:  # never let one bad poll kill the loop
                logger.warning("controller tick failed: %s", exc)
            try:
                if stop is not None:
                    await asyncio.wait_for(stop.wait(), timeout=self.cfg.poll_interval_s)
                    break
                await asyncio.sleep(self.cfg.poll_interval_s)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> ModeDecision:
        """One closed-loop iteration: poll → decide → maybe actuate."""
        links = await self._fetch()
        features = self._extract_features(links)
        decision = self.decide(features)
        if decision.mode != self.current_mode and self._dwell_elapsed():
            await self._actuate(decision.mode)
            logger.info(
                "MODE SWITCH %s → %s | %s | scores=%s",
                self.current_mode, decision.mode, decision.reason,
                {k: round(v, 2) for k, v in decision.scores.items()},
            )
            self.current_mode = decision.mode
            self._last_switch_t = time.monotonic()
            decision.switched = True
        return decision

    # ── Decision policy (pure function of features + hysteresis state) ────────

    def decide(self, features: list[LinkFeatures]) -> ModeDecision:
        """Score the three modes and return the chosen one (with hysteresis).

        This is intentionally pure & deterministic so it can be unit-tested
        against recorded link traces.
        """
        if not features:
            # No telemetry → do not change anything; stay where we are.
            return ModeDecision(self.current_mode, "no telemetry — holding",
                                {self.current_mode: 1.0}, features=features)

        scores = self._score_modes(features)

        # Raw winner before hysteresis
        candidate = max(scores, key=scores.get)
        incumbent = self.current_mode

        # Hysteresis: incumbent keeps the mode unless a candidate beats it by margin
        if candidate != incumbent:
            if scores[candidate] - scores.get(incumbent, 0.0) < self.cfg.switch_margin:
                candidate = incumbent  # not enough advantage → stay

        # Confirmation window: a real challenger must win N ticks in a row
        if candidate != incumbent:
            if self._pending_mode == candidate:
                self._pending_count += 1
            else:
                self._pending_mode = candidate
                self._pending_count = 1
            if self._pending_count < self.cfg.confirm_samples:
                reason = (f"{candidate} leading ({self._pending_count}/"
                          f"{self.cfg.confirm_samples} confirmations) — holding {incumbent}")
                return ModeDecision(incumbent, reason, scores, features=features)
        else:
            self._pending_mode = None
            self._pending_count = 0

        reason = self._explain(candidate, features, scores)
        return ModeDecision(candidate, reason, scores, features=features)

    # ── Mode scoring ─────────────────────────────────────────────────────────

    def _score_modes(self, feats: list[LinkFeatures]) -> dict[str, float]:
        """Map smoothed features → a suitability score per mode in [0, 1].

        Regime split (oriented by the regression results):

        * **REDUNDANT** when steering cannot escape the problem — loss is
          *volatile* (C2 burst), a link is *flapping* (B2), the loss is
          *severe & steady* (≥ C1's 2 %), or *both* links are lossy (no clean
          link to steer to).
        * **REAL-TIME** when the links are asymmetric but the impairment is
          steady & escapable — steer onto the better path (5g/wifi_degraded,
          *_high_latency steering tests). Steady ≤ ~1.5 % loss does NOT force
          redundancy; it steers instead.
        * **BONDING** only when *both* links are genuinely healthy & comparable
          (A1/A2 aggregation).
        """
        cfg = self.cfg
        lo = cfg.loss_redundant_pct - 0.5     # steady-loss ramp start (1.5 % by default)
        hi = cfg.loss_redundant_pct + 0.5     # steady-loss ramp end   (2.5 % by default)

        active_feats = [f for f in feats if f.active]

        # ── Reliability risk → drives REDUNDANT ──────────────────────────────
        # Steady-loss & "no clean link" only consider ACTIVE links — you cannot
        # replicate onto a dead path. A fully dead link instead drops n_active to
        # 1 and falls through to the single-path real_time fallback below.
        steady_severe = (max(_smoothstep(f.loss_pct, lo, hi) for f in active_feats)
                         if active_feats else 0.0)
        if len(active_feats) >= 2:
            min_link_loss = min(f.loss_pct for f in active_feats)
            both_lossy = _smoothstep(min_link_loss, cfg.loss_healthy_pct, cfg.loss_redundant_pct)
        else:
            both_lossy = 0.0
        # Volatility & flapping look at ALL links (they are about instability over
        # the window — a link that keeps dropping out should drive replication).
        # Volatility = loss ALTERNATING over the line (≥2 up-crossings). One
        # isolated transient (1 crossing) must not flap the mode; a steadily dead
        # link (0 crossings, always high) is handled as failover, not burst.
        volatile = max(_smoothstep(float(f.loss_bursts), 1.0, 3.0) for f in feats)
        flap = 1.0 if any(f.flapping for f in feats) else 0.0
        risk = max(steady_severe, volatile, flap, both_lossy)

        healths = [f.health for f in feats]
        min_health, max_health = min(healths), max(healths)
        asymmetry = max_health - min_health           # 0 = identical, 1 = one good/one bad
        comparability = self._capacity_comparability(feats)
        n_active = sum(1 for f in feats if f.active and not f.flapping)

        # REDUNDANT: reliability at risk.
        score_redundant = risk

        # BONDING: needs BOTH links genuinely healthy (steep gate) + comparable + low risk.
        score_bonding = _smoothstep(min_health, 0.6, 0.9) * comparability * (1.0 - risk)
        if n_active < 2:
            score_bonding *= 0.2                       # cannot aggregate a single link

        # REAL-TIME: asymmetric but escapable — steer to the better path.
        score_realtime = max(asymmetry, 0.0) * max_health * (1.0 - risk)
        if n_active < 2:
            score_realtime = max(score_realtime, 0.7 * max_health)  # single-path fallback

        return {
            MODE_REALTIME: _clamp(score_realtime),
            MODE_BONDING: _clamp(score_bonding),
            MODE_REDUNDANT: _clamp(score_redundant),
        }

    def _capacity_comparability(self, feats: list[LinkFeatures]) -> float:
        """1.0 when the two links have similar capacity, →0 when very lopsided."""
        active = [f.capacity for f in feats if f.active]
        if len(active) < 2:
            return 0.0
        hi, lo = max(active), min(active)
        if hi <= 0:
            return 0.0
        ratio = lo / hi                                 # 1.0 = identical
        # Map ratio ≥ bonding_capacity_ratio → ~1, below → falls off
        return _clamp((ratio - 0.0) / max(self.cfg.bonding_capacity_ratio, 1e-6))

    def _explain(self, mode: str, feats: list[LinkFeatures], scores: dict[str, float]) -> str:
        worst = max(feats, key=lambda f: f.loss_pct)
        if mode == MODE_REDUNDANT:
            return (f"reliability at risk — {worst.name} loss={worst.loss_pct:.1f}% "
                    f"std={worst.loss_std_pct:.1f}% flapping={worst.flapping} → replicate")
        if mode == MODE_BONDING:
            return ("both links healthy & comparable → aggregate for throughput "
                    f"(min_health={min(f.health for f in feats):.2f})")
        if mode == MODE_REALTIME:
            best = max(feats, key=lambda f: f.health)
            other = min(feats, key=lambda f: f.health)
            driver = "latency" if other.latency_ms >= self.cfg.latency_high_ms else "loss/quality"
            return (f"asymmetric links ({driver}-driven) → steer to {best.name} "
                    f"(health={best.health:.2f}, lat={best.latency_ms:.0f}ms)")
        return mode

    # ── Feature extraction & smoothing ───────────────────────────────────────

    def _extract_features(self, links: list[LinkInfo]) -> list[LinkFeatures]:
        feats: list[LinkFeatures] = []
        a = self.cfg.ewma_alpha
        for lnk in links:
            sid = lnk.socket_id
            raw_loss = max(lnk.loss_from_pct, lnk.loss_to_pct)
            capacity = lnk.inbound_throughput + lnk.outbound_throughput
            # "active" = reachable & usable RIGHT NOW. Keyed off loss/latency, NOT
            # the ATSSS weight — a real intermittent disconnect spikes loss to
            # ~100 % and times out latency, whereas a healthy standby link (which
            # real_time has parked at weight 0) must still count as available.
            active = (raw_loss < 80.0) and (0.0 <= lnk.latency_ms < 2000.0)

            # EWMA updates
            self._loss_ewma[sid] = _ewma(self._loss_ewma.get(sid), raw_loss, a)
            self._lat_ewma[sid] = _ewma(self._lat_ewma.get(sid), lnk.latency_ms, a)
            self._jit_ewma[sid] = _ewma(self._jit_ewma.get(sid), lnk.jitter_ms, a)

            # Windowed history
            lh = self._loss_hist.setdefault(sid, deque(maxlen=self.cfg.window))
            lh.append(raw_loss)
            ah = self._active_hist.setdefault(sid, deque(maxlen=self.cfg.window))
            ah.append(active)

            feats.append(LinkFeatures(
                socket_id=sid,
                name=lnk.line_name,
                loss_pct=self._loss_ewma[sid],
                loss_std_pct=_std(lh),
                loss_bursts=_count_rising_edges_num(lh, self.cfg.loss_redundant_pct),
                latency_ms=self._lat_ewma[sid],
                jitter_ms=self._jit_ewma[sid],
                weight=lnk.weight,
                capacity=capacity,
                active=active,
                flapping=_count_falling_edges(ah) >= self.cfg.flap_transitions,
            ))
        return feats

    # ── Hysteresis helpers ───────────────────────────────────────────────────

    def _dwell_elapsed(self) -> bool:
        return (time.monotonic() - self._last_switch_t) >= self.cfg.min_dwell_s


# ─────────────────────────────────────────────────────────────────────────────
# Small numeric helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _ewma(prev: float | None, new: float, alpha: float) -> float:
    return new if prev is None else (alpha * new + (1.0 - alpha) * prev)


def _std(values: Deque[float] | list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return var ** 0.5


def _smoothstep(x: float, lo: float, hi: float) -> float:
    """0 below lo, 1 above hi, smooth cubic ramp in between."""
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    t = _clamp((x - lo) / (hi - lo))
    return t * t * (3.0 - 2.0 * t)


def _count_falling_edges(flags: Deque[bool] | list[bool]) -> int:
    """Count active→inactive transitions (link going down) in the window."""
    edges = 0
    prev = None
    for f in flags:
        if prev is True and f is False:
            edges += 1
        prev = f
    return edges


def _count_rising_edges_num(values: Deque[float] | list[float], thresh: float) -> int:
    """Count times a value crosses UP through *thresh* (low→high) in the window.

    Distinguishes burstiness (loss alternating over the line, many crossings)
    from a single transient (one crossing) and from a steadily-bad link
    (zero crossings — always above the line)."""
    edges = 0
    prev = None
    for v in values:
        if prev is not None and prev < thresh <= v:
            edges += 1
        prev = v
    return edges
