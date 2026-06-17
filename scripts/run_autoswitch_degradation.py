#!/usr/bin/env python3
"""Auto-switch vs fixed-mode comparison over Group B (network degradation).

Runs AFTER the daily test. With NetEmu's variation seeded (NETEMU_VARIATION_SEED),
each condition replays the IDENTICAL impairment, so comparing the AutoModeController
against fixed modes is fair.

For every degradation condition it measures iperf3 throughput/loss under each mode
in --modes (default: real_time, bonding, duplicate, AUTO) and writes a side-by-side
JSON + Markdown report.

  PYTHONPATH=src python3 scripts/run_autoswitch_degradation.py \
      --duration 120 --report reports/autoswitch_$(date +%F).md

The existing pytest framework, fixtures and config are untouched — this is a
standalone harness.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from doublink_tester.config import load_network_profiles, load_settings
from doublink_tester.clients.netemu_client import NetEmuClient
from doublink_tester.clients.multilink_client import MultilinkClient
from doublink_tester.traffic.iperf3 import Iperf3Generator
from doublink_tester.control import AutoModeController, ControllerConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("autoswitch_ab")

# ── Group B — network degradation conditions ────────────────────────────────
# The core degradation set exercised by tests/test_degradation/. Override with
# --conditions. These are the regimes where auto-switch should differ from fixed.
DEFAULT_CONDITIONS = [
    "clean_controlled",          # baseline
    "symmetric_mild_loss",       # symmetric loss
    "5g_degraded_moderate",      # asymmetric → expect steering
    "wifi_degraded_moderate",    # asymmetric → expect steering
    "5g_high_latency_moderate",  # latency-driven steering
    "congested_recoverable",     # both lossy → expect redundant
    "wifi_interference_moderate",# variation (now deterministic via seed)
]

INACTIVE = {"cleared", "deleted", "error"}


def _interfaces(settings) -> dict[str, str]:
    i = settings.interfaces
    return {"line_a_dl": i.line_a_dl, "line_a_ul": i.line_a_ul,
            "line_b_dl": i.line_b_dl, "line_b_ul": i.line_b_ul}


async def _clear_all(netemu) -> None:
    try:
        rules = await netemu.list_rules()
    except Exception as e:
        logger.warning("list_rules failed: %s", e)
        return
    for r in rules:
        if r.get("status", "") in INACTIVE:
            continue
        try:
            await netemu.clear_rule(r["id"])
        except Exception:
            pass


async def _apply(netemu, profile, settings) -> None:
    for params in profile.get_rule_params(_interfaces(settings)):
        await netemu.create_rule(params)
    await asyncio.sleep(settings.timeouts.network_settle_s)


async def _measure(multilink, settings, mode: str, duration: int, cfg: ControllerConfig):
    """Run one iperf3 measurement under `mode` (a fixed mode name or 'AUTO')."""
    gen = Iperf3Generator(server_host=settings.iperf3_server)
    target = f"{settings.iperf3_server}:5201"

    if mode == "AUTO":
        switches: list[tuple[float, str]] = []
        t0 = time.monotonic()

        async def counting_actuate(new_mode: str):
            switches.append((round(time.monotonic() - t0, 1), new_mode))
            return await multilink.set_mode(new_mode)

        # Seed the controller with the link state's current mode if known
        ctrl = AutoModeController(
            fetch=multilink.get_links, actuate=counting_actuate,
            config=cfg, current_mode="bonding",
        )
        stop = asyncio.Event()
        loop_task = asyncio.create_task(ctrl.run(stop=stop))
        try:
            result = await gen.run(target=target, duration_s=duration, protocol="tcp", parallel=4)
        finally:
            stop.set()
            try:
                await asyncio.wait_for(loop_task, timeout=5)
            except asyncio.TimeoutError:
                loop_task.cancel()
        return {
            "throughput_mbps": round(result.throughput_mbps, 2),
            "loss_pct": round(result.loss_pct, 3),
            "final_mode": ctrl.current_mode,
            "switch_count": len(switches),
            "switches": switches,
        }
    else:
        await multilink.set_mode(mode)
        result = await gen.run(target=target, duration_s=duration, protocol="tcp", parallel=4)
        return {
            "throughput_mbps": round(result.throughput_mbps, 2),
            "loss_pct": round(result.loss_pct, 3),
        }


async def run(args) -> dict:
    settings = load_settings()
    profiles = {p.id: p for p in load_network_profiles()}
    conditions = args.conditions or DEFAULT_CONDITIONS
    modes = args.modes
    cfg = ControllerConfig()

    rows = []
    async with NetEmuClient(settings.netemu_url) as netemu, \
               MultilinkClient(settings.multilink_url, agent_id=settings.multilink_agent_id) as multilink:
        for cond in conditions:
            if cond not in profiles:
                logger.warning("skip unknown condition %s", cond)
                continue
            row = {"condition": cond, "results": {}}
            for mode in modes:
                try:
                    await _clear_all(netemu)
                    await _apply(netemu, profiles[cond], settings)   # same seed → same impairment
                    logger.info("[%s] mode=%s measuring %ds ...", cond, mode, args.duration)
                    row["results"][mode] = await _measure(multilink, settings, mode, args.duration, cfg)
                    settle = getattr(settings.timeouts, "iperf3_settle_s", 3)
                    await asyncio.sleep(settle)
                except Exception as e:
                    logger.exception("[%s] mode=%s failed: %s", cond, mode, e)
                    row["results"][mode] = {"error": str(e)}
            rows.append(row)
            logger.info("[%s] done: %s", cond,
                        {m: row["results"][m].get("throughput_mbps") for m in modes})
        await _clear_all(netemu)

    return {"seed_env": "NETEMU_VARIATION_SEED", "duration_s": args.duration,
            "modes": modes, "conditions": conditions, "rows": rows,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def write_markdown(data: dict, path: Path) -> None:
    modes = data["modes"]
    fixed = [m for m in modes if m != "AUTO"]
    lines = [
        "# Auto-switch vs Fixed — Group B (Network Degradation)",
        "",
        f"Generated: {data['generated_at']}  |  iperf3 {data['duration_s']}s TCP  |  "
        f"variation seed: NETEMU_VARIATION_SEED (identical impairment per condition)",
        "",
        "| Condition | " + " | ".join(modes) + " | AUTO mode | switches | AUTO vs best fixed |",
        "|" + "---|" * (len(modes) + 4),
    ]
    for row in data["rows"]:
        res = row["results"]
        cells = []
        best_fixed = None
        for m in modes:
            r = res.get(m, {})
            tp = r.get("throughput_mbps")
            cells.append(f"{tp:.1f}" if isinstance(tp, (int, float)) else "ERR")
            if m in fixed and isinstance(tp, (int, float)):
                best_fixed = tp if best_fixed is None else max(best_fixed, tp)
        auto = res.get("AUTO", {})
        auto_tp = auto.get("throughput_mbps")
        auto_mode = auto.get("final_mode", "-")
        sw = auto.get("switch_count", "-")
        if isinstance(auto_tp, (int, float)) and best_fixed:
            delta = f"{(auto_tp - best_fixed):+.1f} ({(auto_tp/best_fixed - 1)*100:+.0f}%)"
        else:
            delta = "-"
        lines.append(f"| {row['condition']} | " + " | ".join(cells) +
                     f" | {auto_mode} | {sw} | {delta} |")
    lines += ["", "_AUTO vs best fixed: positive = auto matched/beat the best fixed mode "
              "under the identical (seeded) impairment._", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-switch vs fixed comparison (Group B degradation)")
    ap.add_argument("--duration", type=int, default=120, help="iperf3 seconds per measurement")
    ap.add_argument("--modes", nargs="+", default=["real_time", "bonding", "duplicate", "AUTO"])
    ap.add_argument("--conditions", nargs="+", default=None, help="override condition list")
    ap.add_argument("--output", type=Path, default=Path("reports/autoswitch_degradation.json"))
    ap.add_argument("--report", type=Path, default=Path("reports/autoswitch_degradation.md"))
    args = ap.parse_args()

    data = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_markdown(data, args.report)
    logger.info("Wrote %s and %s", args.output, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
