"""Chart generation for Allure test reports.

Four entry points:

* ``generate_single_chart(result, ...)``
      Single iperf3 run throughput timeline.
* ``generate_combined_chart(results, ...)``
      Multiple iperf3 runs stitched end-to-end with event markers.
* ``generate_traffic_link_chart(result, link_samples, ...)``
      **Primary chart**: iperf3 throughput + concurrent link quality sampling
      (latency / weight / loss per link) on a shared time axis.  Use this to
      correlate algorithm decisions (weight shifts) with measured throughput.
* ``generate_link_snapshot_chart(links, ...)``
      Static 3-bar snapshot of current link quality — used for before/after views.

matplotlib is an optional dev dependency.  If it is not installed the functions
return empty bytes and tests continue to run normally.
"""

from __future__ import annotations

import io
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doublink_tester.models import LinkInfo, TrafficResult

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


# ── Line colours: LINE A (5G) = blue, LINE B (WiFi) = green ───────────────────
_LINK_COLORS = {0: "#1565C0", 1: "#2E7D32"}   # socket_id → colour
_LINK_COLORS_LIGHT = {0: "#90CAF9", 1: "#A5D6A7"}


def generate_traffic_link_chart(
    result: "TrafficResult",
    link_samples: "list[tuple[float, list[LinkInfo]]]",
    title: str = "",
    events: list[tuple[float, str]] | None = None,
) -> bytes:
    """Generate a combined iperf3-throughput + link-quality time-series chart.

    Produces a **3-panel figure** with a shared time axis so you can directly
    see how ATSSS algorithm decisions (weight shifts, latency changes) correlate
    with observed throughput:

    Panel 1 (tall) — Throughput (Mbps, left Y) overlaid with ATSSS weight per
                     link (right Y, dashed).  A drop or rise in weight shows
                     exactly when the algorithm favoured or penalised a path.

    Panel 2        — RTT (ms) per link sampled every ~1 s.  Rising latency on
                     one link should precede a weight reduction.

    Panel 3        — Packet loss % per link (inbound solid, outbound dotted).

    All three panels share the X axis and display the same event markers.

    Args:
        result:       TrafficResult from iperf3 (must have non-empty timeseries).
        link_samples: List of ``(t_elapsed_s, [LinkInfo, ...])`` tuples collected
                      concurrently with the iperf3 run (typically at 1 Hz).
        title:        Optional chart title.
        events:       Mode-switch / network-change markers: ``[(t_s, label), ...]``.

    Returns:
        PNG bytes, or ``b""`` if matplotlib unavailable or no iperf3 data.
    """
    if not _HAS_MPL or not result.timeseries:
        return b""

    # Fall back to the simple chart when no link data was collected
    if not link_samples:
        return generate_single_chart(result, title=title, events=events)

    events = events or []

    # ── iperf3 time-series ─────────────────────────────────────────────────────
    pts = result.timeseries
    tp_times = [p.t_start for p in pts]
    tp_vals  = [p.throughput_mbps for p in pts]
    has_udp_loss = any(p.loss_pct > 0 for p in pts)

    # ── Link samples → per-socket time-series dict ─────────────────────────────
    # lts[socket_id] = {"t": [...], "latency": [...], "weight": [...], ...}
    lts: dict[int, dict] = defaultdict(
        lambda: {"t": [], "latency": [], "weight": [], "loss_from": [], "loss_to": [], "name": ""}
    )
    for t, links in link_samples:
        for lnk in links:
            d = lts[lnk.socket_id]
            d["t"].append(t)
            d["latency"].append(lnk.latency_ms)
            d["weight"].append(lnk.weight)
            d["loss_from"].append(lnk.loss_from_pct)
            d["loss_to"].append(lnk.loss_to_pct)
            if not d["name"]:
                d["name"] = lnk.line_name

    # ── Figure layout: 3 rows, shared X ───────────────────────────────────────
    fig, axes = plt.subplots(
        3, 1,
        figsize=(13, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.8, 1.4]},
    )
    fig.subplots_adjust(hspace=0.06)
    ax_tp, ax_lat, ax_loss = axes

    # ── Panel 1: Throughput (left Y) + ATSSS Weight (right Y) ─────────────────
    tp_col = "#1565C0"
    ax_tp.fill_between(tp_times, tp_vals, alpha=0.12, color=tp_col)
    ax_tp.plot(tp_times, tp_vals, color=tp_col, linewidth=1.8,
               label=f"{result.protocol.upper()} Throughput")
    avg = sum(tp_vals) / len(tp_vals)
    ax_tp.axhline(y=avg, color=tp_col, linestyle=":", linewidth=1.0, alpha=_AVG_COLOR_ALPHA)
    ax_tp.text(tp_times[-1] * 0.98, avg * 1.02, f"avg {avg:.1f} Mbps",
               color=tp_col, fontsize=7, ha="right", va="bottom", alpha=0.8)

    # UDP loss on left axis secondary
    if has_udp_loss:
        ax_udp_loss = ax_tp.twinx()
        udp_losses = [p.loss_pct for p in pts]
        ax_udp_loss.plot(tp_times, udp_losses, color=_LOSS_COLOR, linewidth=1.0,
                         linestyle=":", alpha=0.7, label="UDP Loss %")
        ax_udp_loss.set_ylabel("UDP Loss (%)", color=_LOSS_COLOR, fontsize=8)
        ax_udp_loss.tick_params(axis="y", labelcolor=_LOSS_COLOR, labelsize=7)
        ax_udp_loss.set_ylim(bottom=0)

    _style_ax(ax_tp, "Throughput (Mbps)", tp_col)

    # ATSSS weight overlay on right Y (only if we have link data)
    ax_wt = ax_tp.twinx()
    if has_udp_loss:
        # Offset the weight axis spine to avoid overlap with UDP loss axis
        ax_wt.spines["right"].set_position(("outward", 55))
    for sid in sorted(lts.keys()):
        d = lts[sid]
        c = _LINK_COLORS.get(sid, _PHASE_COLORS[sid % len(_PHASE_COLORS)])
        ax_wt.plot(d["t"], d["weight"], color=c, linewidth=1.5, linestyle="--",
                   alpha=0.80, label=f'{d["name"]} weight')
        # Mark weight change points with small markers
        for i in range(1, len(d["weight"])):
            if d["weight"][i] != d["weight"][i - 1]:
                ax_wt.axvline(x=d["t"][i], color=c, linewidth=0.6,
                               linestyle=":", alpha=0.35, zorder=2)
    ax_wt.set_ylabel("ATSSS Weight →", color="#555", fontsize=8)
    ax_wt.tick_params(axis="y", labelcolor="#555", labelsize=7)
    ax_wt.set_ylim(bottom=0)
    ax_wt.yaxis.set_major_formatter(mticker.FormatStrFormatter("%g"))

    # Combined legend for Panel 1
    h1, lb1 = ax_tp.get_legend_handles_labels()
    h2, lb2 = ax_wt.get_legend_handles_labels()
    if has_udp_loss:
        h3, lb3 = ax_udp_loss.get_legend_handles_labels()
        h1, lb1 = h1 + h3, lb1 + lb3
    ax_tp.legend(h1 + h2, lb1 + lb2, loc="upper left", fontsize=7.5, framealpha=0.8)

    _draw_events(ax_tp, events)

    # ── Panel 2: RTT per link ─────────────────────────────────────────────────
    for sid in sorted(lts.keys()):
        d = lts[sid]
        c = _LINK_COLORS.get(sid, _PHASE_COLORS[sid % len(_PHASE_COLORS)])
        cl = _LINK_COLORS_LIGHT.get(sid, c)
        ax_lat.plot(d["t"], d["latency"], color=c, linewidth=1.6,
                    label=d["name"], alpha=0.9, zorder=4)
        ax_lat.fill_between(d["t"], d["latency"], alpha=0.08, color=c)
    _style_ax(ax_lat, "RTT (ms)", "#333")
    ax_lat.legend(loc="upper right", fontsize=7.5, framealpha=0.8)
    _draw_events(ax_lat, events)

    # ── Panel 3: Packet loss per link ─────────────────────────────────────────
    any_loss = any(
        max(d["loss_from"] + d["loss_to"], default=0) > 0
        for d in lts.values()
    )
    for sid in sorted(lts.keys()):
        d = lts[sid]
        c = _LINK_COLORS.get(sid, _PHASE_COLORS[sid % len(_PHASE_COLORS)])
        ax_loss.plot(d["t"], d["loss_from"], color=c, linewidth=1.4,
                     label=f'{d["name"]} inbound', alpha=0.85, zorder=4)
        ax_loss.plot(d["t"], d["loss_to"], color=c, linewidth=0.9,
                     linestyle=":", label=f'{d["name"]} outbound', alpha=0.60, zorder=3)
    _style_ax(ax_loss, "Link Loss (%)", "#333")
    ax_loss.set_xlabel("Time (s)")
    ax_loss.legend(loc="upper right", fontsize=7, ncol=2, framealpha=0.8)
    _draw_events(ax_loss, events)

    # ── Annotation: sample count ───────────────────────────────────────────────
    n_samples = len(link_samples)
    fig.text(
        0.99, 0.005,
        f"link samples: {n_samples}  |  iperf3 intervals: {len(pts)}",
        ha="right", va="bottom", fontsize=6.5, color="#999",
    )

    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold", y=1.005)

    fig.tight_layout()
    return _png(fig)


def generate_link_snapshot_chart(
    links: "list[LinkInfo]",
    title: str = "",
) -> bytes:
    """Generate a PNG bar chart summarising real-time multilink link quality.

    Produces a 3-panel horizontal figure:
      • Panel 1 — Latency (current / min–max range) per link
      • Panel 2 — Packet loss (inbound + outbound) per link
      • Panel 3 — ATSSS traffic weight per link

    Each panel shows LINE_A (5G) in blue and LINE_B (WiFi) in green.

    Args:
        links: List of :class:`LinkInfo` objects (from ``MultilinkClient.get_links()``).
               Typically 2 entries (LINE_A and LINE_B).
        title: Optional chart title shown at the top.

    Returns:
        PNG image bytes, or ``b""`` if matplotlib unavailable or no link data.
    """
    if not _HAS_MPL or not links:
        return b""

    # ── Colour per link (matches LINE_A=blue, LINE_B=green convention) ─────────
    link_colors = ["#1E88E5", "#43A047", "#FB8C00", "#8E24AA", "#E53935"]
    names = [lnk.line_name for lnk in links]
    colors = [link_colors[i % len(link_colors)] for i in range(len(links))]

    x = list(range(len(links)))
    bar_w = 0.5

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.5))

    # ── Panel 1: Latency ───────────────────────────────────────────────────────
    ax_lat = axes[0]
    lats = [lnk.latency_ms for lnk in links]
    errs_lo = [max(0.0, lnk.latency_ms - lnk.latency_min_ms) for lnk in links]
    errs_hi = [max(0.0, lnk.latency_max_ms - lnk.latency_ms) for lnk in links]

    bars = ax_lat.bar(x, lats, width=bar_w, color=colors, alpha=0.85, zorder=3)
    ax_lat.errorbar(
        x, lats,
        yerr=[errs_lo, errs_hi],
        fmt="none", color="#555", capsize=4, linewidth=1.2, zorder=4,
    )
    for bar, val in zip(bars, lats):
        ax_lat.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + max(errs_hi) * 0.05,
            f"{val:.1f}", ha="center", va="bottom", fontsize=8, fontweight="bold",
        )
    ax_lat.set_title("Latency (ms)", fontsize=9, fontweight="bold")
    ax_lat.set_xticks(x)
    ax_lat.set_xticklabels(names, fontsize=7.5, rotation=10, ha="right")
    ax_lat.set_ylim(bottom=0)
    ax_lat.grid(True, axis="y", alpha=0.25, linestyle="--")
    ax_lat.set_ylabel("ms")

    # ── Panel 2: Loss ─────────────────────────────────────────────────────────
    ax_loss = axes[1]
    loss_from = [lnk.loss_from_pct for lnk in links]
    loss_to = [lnk.loss_to_pct for lnk in links]
    x_from = [xi - bar_w / 4 for xi in x]
    x_to   = [xi + bar_w / 4 for xi in x]

    b_from = ax_loss.bar(x_from, loss_from, width=bar_w / 2, color=colors,
                         alpha=0.6, label="Inbound", zorder=3)
    b_to   = ax_loss.bar(x_to,   loss_to,   width=bar_w / 2, color=colors,
                         alpha=0.9, label="Outbound", hatch="//", zorder=3)

    for bars_grp in (b_from, b_to):
        for bar in bars_grp:
            h = bar.get_height()
            if h > 0:
                ax_loss.text(
                    bar.get_x() + bar.get_width() / 2, h,
                    f"{h:.1f}%", ha="center", va="bottom", fontsize=7,
                )

    ax_loss.set_title("Packet Loss (%)", fontsize=9, fontweight="bold")
    ax_loss.set_xticks(x)
    ax_loss.set_xticklabels(names, fontsize=7.5, rotation=10, ha="right")
    ax_loss.set_ylim(bottom=0)
    ax_loss.grid(True, axis="y", alpha=0.25, linestyle="--")
    ax_loss.set_ylabel("%")
    ax_loss.legend(fontsize=7, loc="upper right")

    # ── Panel 3: Weight ───────────────────────────────────────────────────────
    ax_wt = axes[2]
    weights = [lnk.weight for lnk in links]
    total_w = sum(weights) or 1
    pct_w = [w / total_w * 100 for w in weights]

    bars_w = ax_wt.bar(x, weights, width=bar_w, color=colors, alpha=0.85, zorder=3)
    for bar, w, pct in zip(bars_w, weights, pct_w):
        ax_wt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(weights, default=1) * 0.02,
            f"{w}\n({pct:.0f}%)",
            ha="center", va="bottom", fontsize=8, fontweight="bold",
        )
    ax_wt.set_title("ATSSS Weight", fontsize=9, fontweight="bold")
    ax_wt.set_xticks(x)
    ax_wt.set_xticklabels(names, fontsize=7.5, rotation=10, ha="right")
    ax_wt.set_ylim(bottom=0, top=max(weights, default=1) * 1.3)
    ax_wt.grid(True, axis="y", alpha=0.25, linestyle="--")
    ax_wt.set_ylabel("Weight")

    # ── Jitter annotation (light text below title) ────────────────────────────
    jitter_txt = "  |  ".join(f"{lnk.line_name}: jitter {lnk.jitter_ms:.1f}ms" for lnk in links)
    fig.text(0.5, 0.01, jitter_txt, ha="center", fontsize=7, color="#666")

    if title:
        fig.suptitle(title, fontsize=10, fontweight="bold", y=1.02)

    fig.tight_layout()
    return _png(fig)
