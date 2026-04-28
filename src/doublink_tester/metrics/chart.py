"""Time-series traffic chart generation for Allure test reports.

Produces PNG charts from iperf3 per-interval data.  Two entry points:

* ``generate_single_chart(result, ...)``   — one iperf3 run
* ``generate_combined_chart(results, ...)`` — multiple runs stitched end-to-end,
  with vertical markers for mode-switch / network-change events

matplotlib is an optional dev dependency.  If it is not installed the functions
return empty bytes and tests continue to run normally.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doublink_tester.models import TrafficResult

logger = logging.getLogger(__name__)

# Colour palette for up to 5 measurement phases
_PHASE_COLORS = ["#1E88E5", "#43A047", "#FB8C00", "#8E24AA", "#E53935"]
_EVENT_COLOR = "#FF5722"
_BOUNDARY_COLOR = "#9E9E9E"
_LOSS_COLOR = "#EF5350"
_AVG_COLOR_ALPHA = 0.45

try:
    import matplotlib
    matplotlib.use("Agg")          # non-interactive — no display required
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False
    logger.debug("matplotlib not installed — traffic charts will be skipped")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _png(fig: "plt.Figure") -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _draw_events(ax: "plt.Axes", events: list[tuple[float, str]]) -> None:
    """Draw vertical dashed lines with labels for named events (e.g. mode switches)."""
    ylim = ax.get_ylim()
    y_top = ylim[1]
    for t, label in events:
        ax.axvline(x=t, color=_EVENT_COLOR, linestyle="--", linewidth=1.8, alpha=0.9, zorder=5)
        if label:
            ax.text(
                t + 0.15, y_top * 0.96, label,
                color=_EVENT_COLOR, fontsize=8, va="top", rotation=90,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor=_EVENT_COLOR, alpha=0.75),
                zorder=6,
            )


def _style_ax(ax: "plt.Axes", ylabel: str, color: str) -> None:
    ax.set_ylabel(ylabel, color=color)
    ax.tick_params(axis="y", labelcolor=color)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f"))


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_single_chart(
    result: "TrafficResult",
    title: str = "",
    events: list[tuple[float, str]] | None = None,
) -> bytes:
    """Generate a PNG chart for a single iperf3 TrafficResult.

    Args:
        result: TrafficResult with a populated ``timeseries`` list.
        title:  Optional chart title shown at the top.
        events: List of ``(t_seconds, label)`` pairs — drawn as vertical dashed
                lines.  Use these to mark when a mode switch or network condition
                change occurred during the measurement.

    Returns:
        PNG image bytes, or ``b""`` if matplotlib is unavailable or the result
        contains no per-interval data.
    """
    if not _HAS_MPL or not result.timeseries:
        return b""

    events = events or []
    pts = result.timeseries
    times = [p.t_start for p in pts]
    tps = [p.throughput_mbps for p in pts]
    has_loss = any(p.loss_pct > 0 for p in pts)

    color = _PHASE_COLORS[0]
    fig, ax1 = plt.subplots(figsize=(12, 4))

    ax1.fill_between(times, tps, alpha=0.13, color=color)
    ax1.plot(times, tps, color=color, linewidth=1.8,
             label=f"{result.protocol.upper()} Throughput")

    # Average throughput reference line
    avg = sum(tps) / len(tps)
    ax1.axhline(y=avg, color=color, linestyle=":", linewidth=1.0, alpha=_AVG_COLOR_ALPHA)
    ax1.text(times[-1] * 0.98, avg * 1.02, f"avg {avg:.1f} Mbps",
             color=color, fontsize=7, ha="right", va="bottom", alpha=0.7)

    _style_ax(ax1, "Throughput (Mbps)", color)
    ax1.set_xlabel("Time (s)")

    # Secondary Y axis: loss % (UDP)
    if has_loss:
        ax2 = ax1.twinx()
        losses = [p.loss_pct for p in pts]
        ax2.plot(times, losses, color=_LOSS_COLOR, linewidth=1.2, linestyle=":",
                 alpha=0.8, label="Loss %")
        ax2.set_ylabel("Loss (%)", color=_LOSS_COLOR)
        ax2.tick_params(axis="y", labelcolor=_LOSS_COLOR)
        ax2.set_ylim(bottom=0)
        l1, lb1 = ax1.get_legend_handles_labels()
        l2, lb2 = ax2.get_legend_handles_labels()
        ax1.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8)
    else:
        ax1.legend(loc="upper left", fontsize=8)

    _draw_events(ax1, events)

    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold")

    fig.tight_layout()
    return _png(fig)


def generate_combined_chart(
    results: list[tuple[str, "TrafficResult"]],
    events: list[tuple[float, str]] | None = None,
    title: str = "",
) -> bytes:
    """Generate a combined PNG chart from multiple TrafficResults stitched in time.

    Each phase is plotted in a distinct colour.  Phase boundaries (the gap between
    consecutive measurements) are shown as thin grey vertical lines.  User-supplied
    ``events`` are shown as bold dashed orange lines — ideal for marking the exact
    moment a mode switch or network condition change occurred.

    The stitched time axis is cumulative: Phase 1 occupies t=0..D1, Phase 2
    occupies t=D1..D1+D2, etc., so the chart reads left-to-right as a continuous
    timeline.

    Args:
        results: List of ``(phase_label, TrafficResult)`` tuples in chronological
                 order.
        events:  List of ``(t_stitched_seconds, label)`` pairs.  ``t_stitched``
                 uses the same cumulative time axis as the chart.  Typically you
                 pass the cumulative duration of Phase 1 to mark the switch point.
        title:   Optional chart title.

    Returns:
        PNG image bytes, or ``b""`` if matplotlib unavailable or no data.
    """
    if not _HAS_MPL or not results:
        return b""

    events = events or []

    # ── Build stitched time series ─────────────────────────────────────────────
    # phase_segments: list of (label, color, [(t, mbps, loss_pct)])
    phase_segments: list[tuple[str, str, list[tuple[float, float, float]]]] = []
    phase_boundaries: list[float] = []   # cumulative t at each phase end
    offset = 0.0

    for idx, (label, result) in enumerate(results):
        color = _PHASE_COLORS[idx % len(_PHASE_COLORS)]
        pts = result.timeseries
        if pts:
            seg = [(offset + p.t_start, p.throughput_mbps, p.loss_pct) for p in pts]
            duration = pts[-1].t_end
        else:
            # No timeseries — represent as a single zero-duration point
            seg = []
            duration = max(result.ended_at - result.started_at, 0)

        phase_segments.append((label, color, seg))
        offset += duration
        if idx < len(results) - 1:
            phase_boundaries.append(offset)

    all_pts = [pt for _, _, seg in phase_segments for pt in seg]
    if not all_pts:
        return b""

    has_loss = any(pt[2] > 0 for pt in all_pts)

    # ── Plot ──────────────────────────────────────────────────────────────────
    fig, ax1 = plt.subplots(figsize=(14, 4))

    for label, color, seg in phase_segments:
        if not seg:
            continue
        times_p = [pt[0] for pt in seg]
        tps_p = [pt[1] for pt in seg]
        ax1.fill_between(times_p, tps_p, alpha=0.12, color=color)
        ax1.plot(times_p, tps_p, color=color, linewidth=1.8, label=label)

        avg = sum(tps_p) / len(tps_p)
        ax1.axhline(y=avg, color=color, linestyle=":", linewidth=0.9, alpha=_AVG_COLOR_ALPHA)

    _style_ax(ax1, "Throughput (Mbps)", "#333333")
    ax1.set_xlabel("Time (s)")

    # Loss % secondary axis (UDP)
    if has_loss:
        ax2 = ax1.twinx()
        loss_t = [pt[0] for pt in all_pts if pt[2] > 0]
        loss_v = [pt[2] for pt in all_pts if pt[2] > 0]
        ax2.plot(loss_t, loss_v, color=_LOSS_COLOR, linewidth=1.0,
                 linestyle=":", alpha=0.75, label="Loss %")
        ax2.set_ylabel("Loss (%)", color=_LOSS_COLOR)
        ax2.tick_params(axis="y", labelcolor=_LOSS_COLOR)
        ax2.set_ylim(bottom=0)
        l1, lb1 = ax1.get_legend_handles_labels()
        l2, lb2 = ax2.get_legend_handles_labels()
        ax1.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8)
    else:
        ax1.legend(loc="upper left", fontsize=8)

    # Phase boundary lines (light grey)
    for t_b in phase_boundaries:
        ax1.axvline(x=t_b, color=_BOUNDARY_COLOR, linestyle="-",
                    linewidth=0.7, alpha=0.45, zorder=3)

    # User event markers (mode switches, network changes)
    _draw_events(ax1, events)

    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold")

    fig.tight_layout()
    return _png(fig)
