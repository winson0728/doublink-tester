"""
Doublink ATSSS Test Runner + Network Profile Editor — Web UI
=============================================================
啟動：  cd ~/doublink-tester && PYTHONPATH=src python3 scripts/run_ui.py
存取：  http://192.168.105.210:9080/
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import importlib.util

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# ── 路徑 / 常數 ──────────────────────────────────────────────────
PROJ_DIR      = Path(__file__).parent.parent
RESULTS_DIR   = PROJ_DIR / "allure-results"
REPORTS_DIR   = PROJ_DIR / "reports"
REPORT_SCRIPT = PROJ_DIR / "scripts" / "generate_test_report.py"
PROFILES_YAML = PROJ_DIR / "config" / "profiles" / "network_conditions.yaml"
NETEMU_URL    = "http://192.168.105.115:8080"

# ── Dynamic import: reuse parse_allure_results from generate_test_report.py ──
def _load_parse_allure():
    try:
        spec = importlib.util.spec_from_file_location("_rpt", REPORT_SCRIPT)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.parse_allure_results
    except Exception:
        return None

_parse_allure_results = _load_parse_allure()


def parse_allure_for_ui() -> dict[str, dict]:
    """Return {tid: {status, **metrics}} from current allure-results dir.
    Strips the internal 'start' timestamp before returning."""
    if _parse_allure_results is None:
        return {}
    try:
        raw = _parse_allure_results(str(RESULTS_DIR))
        return {tid: {k: v for k, v in d.items() if k != "start"} for tid, d in raw.items()}
    except Exception:
        return {}


LINE_IFACES = {
    "a_dl": "wan_a_in",
    "a_ul": "lan_a_out",
    "b_dl": "wan_b_in",
    "b_ul": "lan_b_out",
}

# ── 測項清單 (74 items) ──────────────────────────────────────────
TESTS = [
    {"id":"A-01","group":"A","name":"real_time → bonding（clean）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[realtime_to_bonding_clean_tcp]"},
    {"id":"A-02","group":"A","name":"bonding → duplicate（mild loss）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[bonding_to_duplicate_symm_loss_http]"},
    {"id":"A-03","group":"A","name":"duplicate → real_time（mild latency）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[duplicate_to_realtime_symm_latency_tcp]"},
    {"id":"A-04","group":"A","name":"real_time → duplicate（congested UDP）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[realtime_to_duplicate_congested_udp]"},
    {"id":"A-05","group":"A","name":"bonding → real_time（5G 間歇，SIP）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[bonding_to_realtime_5g_intermittent_sip]"},
    {"id":"A-06","group":"A","name":"bonding → duplicate（5G 劣化）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[bonding_to_duplicate_5g_degraded_tcp]"},
    {"id":"A-07","group":"A","name":"API 切換：bonding → duplicate","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeBasicSwitch::test_mode_switch_api[bonding-duplicate]"},
    {"id":"A-08","group":"A","name":"API 切換：duplicate → real_time","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeBasicSwitch::test_mode_switch_api[duplicate-real_time]"},
    {"id":"A-09","group":"A","name":"API 切換：real_time → bonding","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeBasicSwitch::test_mode_switch_api[real_time-bonding]"},
    {"id":"A-10","group":"A","name":"負載中切換（bonding → duplicate）","node":"tests/test_mode_switching/test_mode_transitions.py::TestModeSwitchUnderLoad::test_switch_during_iperf3"},
    {"id":"B-01","group":"B","name":"Profile 套用：clean_controlled","node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[clean_controlled-4]"},
    {"id":"B-02","group":"B","name":"Profile 套用：symmetric_mild_loss","node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[symmetric_mild_loss-4]"},
    {"id":"B-03","group":"B","name":"Profile 套用：symmetric_mild_latency","node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[symmetric_mild_latency-4]"},
    {"id":"B-04","group":"B","name":"Profile 套用：5g_degraded_moderate","node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[5g_degraded_moderate-4]"},
    {"id":"B-05","group":"B","name":"Profile 套用：wifi_degraded_moderate","node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[wifi_degraded_moderate-4]"},
    {"id":"B-06","group":"B","name":"規則清除後恢復乾淨狀態","node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_condition_clear_restores_clean"},
    {"id":"B-07","group":"B","name":"WiFi 干擾動態變化 variation","node":"tests/test_degradation/test_throughput_degradation.py::TestDegradationWithVariation::test_wifi_interference_variation"},
    {"id":"B-08","group":"B","name":"雙線動態變化 both_varied","node":"tests/test_degradation/test_throughput_degradation.py::TestDegradationWithVariation::test_both_varied"},
    {"id":"B-09","group":"B","name":"5G 週期斷線排程驗證","node":"tests/test_degradation/test_throughput_degradation.py::TestDisconnectSchedule::test_disconnect_schedule_applied[5g_intermittent_visible]"},
    {"id":"B-10","group":"B","name":"WiFi 週期斷線排程驗證","node":"tests/test_degradation/test_throughput_degradation.py::TestDisconnectSchedule::test_disconnect_schedule_applied[wifi_intermittent_visible]"},
    {"id":"B-11","group":"B","name":"TCP 基準 [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_baseline_clean[real_time]"},
    {"id":"B-12","group":"B","name":"TCP 基準 [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_baseline_clean[bonding]"},
    {"id":"B-13","group":"B","name":"TCP 基準 [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_baseline_clean[duplicate]"},
    {"id":"B-14","group":"B","name":"TCP symmetric_mild_loss [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_loss-2.0-real_time]"},
    {"id":"B-15","group":"B","name":"TCP symmetric_mild_loss [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_loss-2.0-bonding]"},
    {"id":"B-16","group":"B","name":"TCP symmetric_mild_loss [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_loss-2.0-duplicate]"},
    {"id":"B-17","group":"B","name":"TCP symmetric_mild_latency [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_latency-1.0-real_time]"},
    {"id":"B-18","group":"B","name":"TCP symmetric_mild_latency [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_latency-1.0-bonding]"},
    {"id":"B-19","group":"B","name":"TCP symmetric_mild_latency [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_latency-1.0-duplicate]"},
    {"id":"B-20","group":"B","name":"TCP congested_recoverable [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[congested_recoverable-0.5-real_time]"},
    {"id":"B-21","group":"B","name":"TCP congested_recoverable [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[congested_recoverable-0.5-bonding]"},
    {"id":"B-22","group":"B","name":"TCP congested_recoverable [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[congested_recoverable-0.5-duplicate]"},
    {"id":"B-23","group":"B","name":"TCP 5g_degraded_moderate [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[5g_degraded_moderate-1.0-real_time]"},
    {"id":"B-24","group":"B","name":"TCP 5g_degraded_moderate [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[5g_degraded_moderate-1.0-bonding]"},
    {"id":"B-25","group":"B","name":"TCP 5g_degraded_moderate [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[5g_degraded_moderate-1.0-duplicate]"},
    {"id":"B-26","group":"B","name":"TCP wifi_degraded_moderate [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[wifi_degraded_moderate-1.0-real_time]"},
    {"id":"B-27","group":"B","name":"TCP wifi_degraded_moderate [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[wifi_degraded_moderate-1.0-bonding]"},
    {"id":"B-28","group":"B","name":"TCP wifi_degraded_moderate [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[wifi_degraded_moderate-1.0-duplicate]"},
    {"id":"B-29","group":"B","name":"TCP asymmetric_mixed_moderate [real_time]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[asymmetric_mixed_moderate-1.0-real_time]"},
    {"id":"B-30","group":"B","name":"TCP asymmetric_mixed_moderate [bonding]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[asymmetric_mixed_moderate-1.0-bonding]"},
    {"id":"B-31","group":"B","name":"TCP asymmetric_mixed_moderate [duplicate]","node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[asymmetric_mixed_moderate-1.0-duplicate]"},
    {"id":"B-32","group":"B","name":"UDP 基準（clean）","node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_baseline_clean"},
    {"id":"B-33","group":"B","name":"UDP symmetric_mild_loss","node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[symmetric_mild_loss-10.0-100.0]"},
    {"id":"B-34","group":"B","name":"UDP symmetric_mild_latency","node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[symmetric_mild_latency-60.0-200.0]"},
    {"id":"B-35","group":"B","name":"UDP wifi_interference_moderate","node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[wifi_interference_moderate-10.0-100.0]"},
    {"id":"B-36","group":"B","name":"UDP asymmetric_mixed_moderate","node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[asymmetric_mixed_moderate-10.0-200.0]"},
    {"id":"B-37","group":"B","name":"Steering：5G 劣化 → WiFi","node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[5g_degraded_moderate-5G degraded, WiFi healthy \u2014 expect steering to WiFi]"},
    {"id":"B-38","group":"B","name":"Steering：WiFi 劣化 → 5G","node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[wifi_degraded_moderate-WiFi degraded, 5G healthy \u2014 expect steering to 5G]"},
    {"id":"B-39","group":"B","name":"Steering：5G 高延遲 → WiFi","node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[5g_high_latency_moderate-5G high latency, WiFi normal \u2014 expect latency-aware steering]"},
    {"id":"B-40","group":"B","name":"Steering：WiFi 高延遲 → 5G","node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[wifi_high_latency_moderate-WiFi high latency, 5G normal \u2014 expect latency-aware steering]"},
    {"id":"B-41","group":"B","name":"劣化後恢復：congested → clean","node":"tests/test_degradation/test_throughput_degradation.py::TestRecoveryAfterDegradation::test_tcp_recovery_after_congestion"},
    {"id":"B-42","group":"B","name":"Failover：5G 斷線 → WiFi","node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_on_disconnect[5g_disconnect_visible-WiFi (LINE B)]"},
    {"id":"B-43","group":"B","name":"Failover：WiFi 斷線 → 5G","node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_on_disconnect[wifi_disconnect_visible-5G (LINE A)]"},
    {"id":"B-44","group":"B","name":"Failover：bonding 下 5G 斷線","node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_under_mode[bonding]"},
    {"id":"B-45","group":"B","name":"Failover：duplicate 下 5G 斷線","node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_under_mode[duplicate]"},
    {"id":"B-46","group":"B","name":"間歇斷線：5G 每 15s 斷 2s","node":"tests/test_degradation/test_failover.py::TestIntermittentDisconnect::test_intermittent_disconnect_survival[5g_intermittent_visible-5G (LINE A)]"},
    {"id":"B-47","group":"B","name":"間歇斷線：WiFi 每 15s 斷 2s","node":"tests/test_degradation/test_failover.py::TestIntermittentDisconnect::test_intermittent_disconnect_survival[wifi_intermittent_visible-WiFi (LINE B)]"},
    {"id":"B-48","group":"B","name":"API 排程斷線（LINE A，3s）","node":"tests/test_degradation/test_failover.py::TestIntermittentDisconnect::test_scheduled_disconnect_via_api"},
    {"id":"B-49","group":"B","name":"5G 斷線後恢復驗證","node":"tests/test_degradation/test_failover.py::TestRecoveryAfterDisconnect::test_recovery_after_5g_disconnect"},
    {"id":"C-01","group":"C","name":"均衡頻寬聚合（5G+WiFi 各 60M）","node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestBondingAggregation::test_balanced_aggregation"},
    {"id":"C-02","group":"C","name":"加權聚合（5G 80M + WiFi 40M）","node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestBondingAggregation::test_weighted_aggregation"},
    {"id":"C-03","group":"C","name":"硬切換 Session 持續性","node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestFailoverContinuity::test_hard_failover_session_continuity"},
    {"id":"C-04","group":"C","name":"間歇抖動長時間穩定性（60s）","node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestFailoverContinuity::test_intermittent_flap_stability"},
    {"id":"C-05","group":"C","name":"丟包保護：duplicate vs bonding","node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestDuplicateReliability::test_loss_protection_duplicate_vs_bonding"},
    {"id":"C-06","group":"C","name":"突發丟包韌性（0~10% 浮動）","node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestDuplicateReliability::test_burst_loss_resilience"},
    {"id":"D-01","group":"D","name":"模式效能：bonding clean TCP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_clean_tcp]"},
    {"id":"D-02","group":"D","name":"模式效能：duplicate clean TCP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[duplicate_clean_tcp]"},
    {"id":"D-03","group":"D","name":"模式效能：real_time clean TCP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[realtime_clean_tcp]"},
    {"id":"D-04","group":"D","name":"模式效能：bonding symmetric_loss HTTP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_symmetric_loss_http]"},
    {"id":"D-05","group":"D","name":"模式效能：duplicate symmetric_loss HTTP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[duplicate_symmetric_loss_http]"},
    {"id":"D-06","group":"D","name":"模式效能：bonding 5G 劣化 TCP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_5g_degraded_tcp]"},
    {"id":"D-07","group":"D","name":"模式效能：bonding WiFi 劣化 TCP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_wifi_degraded_tcp]"},
    {"id":"D-08","group":"D","name":"三模式基準比較 TCP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeBaselineComparison::test_all_modes_baseline_tcp"},
    {"id":"D-09","group":"D","name":"三模式基準比較 UDP","node":"tests/test_link_weight/test_weight_distribution.py::TestModeBaselineComparison::test_all_modes_baseline_udp"},
]

GROUP_META = {
    "A": {"label":"Group A — 模式切換 Mode Switching","count":10},
    "B": {"label":"Group B — 網路劣化驗證 Degradation","count":49},
    "C": {"label":"Group C — 黃金場景 Golden Scenarios","count":6},
    "D": {"label":"Group D — 連結效能比較 Link Weight","count":9},
}

# ── Profile utilities ─────────────────────────────────────────────
def load_profiles() -> list[dict]:
    if not PROFILES_YAML.exists():
        return []
    data = yaml.safe_load(PROFILES_YAML.read_text(encoding="utf-8"))
    return data.get("profiles", []) if data else []


def save_profiles(profiles: list[dict]) -> None:
    raw = PROFILES_YAML.read_text(encoding="utf-8") if PROFILES_YAML.exists() else ""
    # Preserve header comments (everything before "profiles:")
    header = ""
    if "profiles:" in raw:
        header = raw[: raw.index("profiles:")]
    body = yaml.dump(
        {"profiles": profiles},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        indent=2,
    )
    PROFILES_YAML.write_text(header + body, encoding="utf-8")


# ── Run state ─────────────────────────────────────────────────────
runs: dict[str, dict] = {}
current_run_id: str | None = None
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


# ══════════════════════════════════════════════════════════════════
app = FastAPI(title="Doublink Test Runner")


# ── pytest task ───────────────────────────────────────────────────
async def run_pytest_task(run_id: str, nodes: list[str]):
    global current_run_id
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJ_DIR/'src'}:{env.get('PYTHONPATH','')}"
    cmd = ["python3", "-m", "pytest", *nodes, "-v", "--timeout=900",
           "--tb=short", f"--alluredir={RESULTS_DIR}", "--color=no"]
    run = runs[run_id]
    run["start"] = datetime.now().isoformat(timespec="seconds")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(PROJ_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        run["process"] = proc
        async for raw in proc.stdout:
            line = strip_ansi(raw.decode("utf-8", errors="replace")).rstrip()
            run["lines"].append(line)
            m = re.search(r"::(test_\S+)\s+(PASSED|FAILED|ERROR)", line)
            if m:
                short, status = m.group(1), m.group(2)
                tid = next((t["id"] for t in TESTS if short in t["node"]), None)
                if tid:
                    run["results"][tid] = status
                if status == "PASSED":
                    run["passed"] += 1
                elif status in ("FAILED", "ERROR"):
                    run["failed"] += 1
        await proc.wait()
        run["exit_code"] = proc.returncode
    except Exception as e:
        run["lines"].append(f"[ERROR] {e}")
        run["exit_code"] = -1
    finally:
        # Parse allure-results to get actual measured metrics
        run["metrics"] = parse_allure_for_ui()
        run["status"] = "done"
        run["end"] = datetime.now().isoformat(timespec="seconds")
        current_run_id = None


# ── Test runner routes ────────────────────────────────────────────
class RunRequest(BaseModel):
    test_ids: list[str]

@app.get("/api/tests")
async def get_tests():
    return TESTS

@app.post("/api/run")
async def start_run(req: RunRequest):
    global current_run_id
    if current_run_id and runs.get(current_run_id, {}).get("status") == "running":
        raise HTTPException(409, "Another run is already in progress")
    valid = {t["id"] for t in TESTS}
    bad = [i for i in req.test_ids if i not in valid]
    if bad:
        raise HTTPException(400, f"Unknown IDs: {bad}")
    nodes = [t["node"] for t in TESTS if t["id"] in req.test_ids]
    run_id = uuid.uuid4().hex[:8]
    current_run_id = run_id
    runs[run_id] = {"status":"running","lines":[],"results":{},"passed":0,"failed":0,"process":None}
    asyncio.create_task(run_pytest_task(run_id, nodes))
    return {"run_id": run_id, "count": len(nodes)}

@app.get("/api/stream/{run_id}")
async def stream_output(run_id: str):
    if run_id not in runs:
        raise HTTPException(404)
    async def gen():
        sent = 0
        while True:
            run = runs[run_id]
            for line in run["lines"][sent:]:
                yield f"data: {json.dumps({'line': line})}\n\n"
            sent = len(run["lines"])
            if run["status"] == "done":
                yield f"data: {json.dumps({'done':True,'passed':run['passed'],'failed':run['failed'],'results':run['results'],'metrics':run.get('metrics',{}),'exit_code':run.get('exit_code',-1)})}\n\n"
                break
            await asyncio.sleep(0.4)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.post("/api/stop/{run_id}")
async def stop_run(run_id: str):
    global current_run_id
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404)
    proc = run.get("process")
    if proc and run["status"] == "running":
        proc.terminate()
        run["status"] = "done"
        run["lines"].append("[STOPPED by user]")
        current_run_id = None
    return {"ok": True}

@app.get("/api/current")
async def current_run_info():
    return {"run_id": current_run_id}

@app.post("/api/report/{run_id}")
async def generate_report(run_id: str):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out = REPORTS_DIR / f"doublink_test_report_{today}.docx"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJ_DIR/'src'}:{env.get('PYTHONPATH','')}"
    r = subprocess.run(["python3", str(REPORT_SCRIPT), str(RESULTS_DIR), str(out)],
                       capture_output=True, text=True, env=env, cwd=str(PROJ_DIR))
    if r.returncode != 0:
        raise HTTPException(500, r.stderr[:500])
    allure_rep = PROJ_DIR / "allure-report"
    if allure_rep.exists():
        import shutil
        shutil.copy(out, allure_rep / out.name)
        shutil.copy(out, allure_rep / "doublink_test_report_latest.docx")
    return {"ok": True, "file": out.name,
            "download": f"http://192.168.105.210:8888/{out.name}"}


@app.get("/api/results")
async def get_allure_results():
    """Return current allure-results parsed metrics for all tests."""
    return parse_allure_for_ui()


# ── Profile routes ────────────────────────────────────────────────
@app.get("/api/profiles")
async def list_profiles():
    return load_profiles()

@app.get("/api/profiles/{pid}")
async def get_profile(pid: str):
    p = next((p for p in load_profiles() if p["id"] == pid), None)
    if not p:
        raise HTTPException(404, "Profile not found")
    return p

@app.post("/api/profiles")
async def create_profile(data: dict):
    profiles = load_profiles()
    if any(p["id"] == data.get("id") for p in profiles):
        raise HTTPException(409, "Profile ID already exists")
    profiles.append(data)
    save_profiles(profiles)
    return {"ok": True}

@app.put("/api/profiles/{pid}")
async def update_profile(pid: str, data: dict):
    profiles = load_profiles()
    idx = next((i for i, p in enumerate(profiles) if p["id"] == pid), None)
    if idx is None:
        raise HTTPException(404, "Profile not found")
    profiles[idx] = data
    save_profiles(profiles)
    return {"ok": True}

@app.delete("/api/profiles/{pid}")
async def delete_profile(pid: str):
    profiles = [p for p in load_profiles() if p["id"] != pid]
    save_profiles(profiles)
    return {"ok": True}

@app.post("/api/profiles/{pid}/apply")
async def apply_profile(pid: str):
    """Apply a profile to NetEmu by creating 4 rules (A-DL, A-UL, B-DL, B-UL)."""
    import httpx
    profile = next((p for p in load_profiles() if p["id"] == pid), None)
    if not profile:
        raise HTTPException(404)

    results = []
    errors = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for line_key in ("line_a", "line_b"):
            line = profile.get(line_key, {})
            suffix = "a" if line_key == "line_a" else "b"
            for dir_key in ("dl", "ul"):
                iface = LINE_IFACES[f"{suffix}_{dir_key}"]
                params: dict[str, Any] = {
                    "interface": iface,
                    "direction": "egress",
                    "bandwidth_kbit": int(line.get("bandwidth_kbit", 0)),
                    "delay_ms":       float(line.get("delay_ms", 0)),
                    "jitter_ms":      float(line.get("jitter_ms", 0)),
                    "loss_pct":       float(line.get("loss_pct", 0)),
                    "corrupt_pct":    float(line.get("corrupt_pct", 0)),
                    "duplicate_pct":  float(line.get("duplicate_pct", 0)),
                }
                if "variation" in line:
                    v = line["variation"]
                    params["variation"] = {
                        "bw_range_kbit":    int(v.get("bw_range_kbit", 0)),
                        "delay_range_ms":   float(v.get("delay_range_ms", 0)),
                        "loss_range_pct":   float(v.get("loss_range_pct", 0)),
                        "interval_s":       float(v.get("interval_s", 5)),
                    }
                if "disconnect_schedule" in line:
                    d = line["disconnect_schedule"]
                    if d.get("enabled"):
                        params["disconnect_schedule"] = {
                            "enabled":      True,
                            "disconnect_s": float(d.get("disconnect_s", 2)),
                            "interval_s":   float(d.get("interval_s", 15)),
                            "repeat":       int(d.get("repeat", 5)),
                        }
                try:
                    resp = await client.post(f"{NETEMU_URL}/api/rules", json=params)
                    rule_id = resp.json().get("id") if resp.is_success else None
                    results.append({"iface": iface, "status": resp.status_code, "rule_id": rule_id})
                except Exception as e:
                    errors.append({"iface": iface, "error": str(e)})

    return {"ok": not errors, "rules": results, "errors": errors}


# ── NetEmu routes ─────────────────────────────────────────────────
@app.get("/api/netemu/rules")
async def get_netemu_rules():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{NETEMU_URL}/api/rules")
            text = resp.text.strip()
            if not text:
                return []
            return resp.json()
    except Exception as e:
        raise HTTPException(503, f"NetEmu unreachable: {e}")

@app.delete("/api/netemu/rules")
async def clear_netemu_rules():
    import httpx
    cleared = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{NETEMU_URL}/api/rules")
            rules = r.json() if r.text.strip() else []
            for rule in rules:
                rid = rule.get("id")
                if rid:
                    await client.post(f"{NETEMU_URL}/api/rules/{rid}/clear")
                    cleared.append(rid)
    except Exception as e:
        raise HTTPException(503, str(e))
    return {"ok": True, "cleared": cleared}


# ══════════════════════════════════════════════════════════════════
# HTML
# ══════════════════════════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<title>Doublink Test Runner</title>
<style>
:root{
  --bg:#0f1117;--surface:#1a1d27;--card:#21253a;--border:#2e3349;
  --text:#e2e8f0;--muted:#8892b0;--accent:#4A90D9;
  --pass:#4ade80;--fail:#f87171;--warn:#fbbf24;--run:#60a5fa;
  --A:#4A90D9;--B:#E07B39;--C:#6BAE6A;--D:#9B6BD9;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;height:100vh;display:flex;flex-direction:column}
/* header */
header{background:var(--surface);border-bottom:1px solid var(--border);padding:10px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0}
header h1{font-size:16px;font-weight:700;color:var(--accent)}
.sub{font-size:11px;color:var(--muted)}
.badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:var(--card);border:1px solid var(--border)}
.badge.running{color:var(--run);border-color:var(--run);animation:pulse 1.5s infinite}
.badge.idle{color:var(--muted)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
/* layout */
.main{display:flex;flex:1;overflow:hidden}
/* left */
.left{width:360px;min-width:300px;display:flex;flex-direction:column;border-right:1px solid var(--border)}
.panel-hdr{background:var(--surface);padding:9px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;flex-shrink:0}
.sel-count{margin-left:auto;font-size:11px;color:var(--accent);font-weight:600}
.test-list{flex:1;overflow-y:auto;padding:8px}
/* groups */
.group-block{margin-bottom:6px;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.group-hdr{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--card);cursor:pointer;user-select:none}
.group-hdr:hover{background:var(--surface)}
.group-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.group-label{font-weight:600;font-size:12px;flex:1}
.group-cnt{font-size:11px;color:var(--muted)}
.group-chevron{font-size:10px;color:var(--muted);transition:transform .2s}
.group-block.collapsed .group-chevron{transform:rotate(-90deg)}
.group-block.collapsed .group-tests{display:none}
.group-cb{accent-color:var(--accent);width:14px;height:14px;cursor:pointer}
.group-tests{padding:4px 8px 8px}
.test-item{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:5px;cursor:pointer}
.test-item:hover{background:var(--card)}
.test-item.result-pass{background:rgba(74,222,128,.08)}
.test-item.result-fail{background:rgba(248,113,113,.1)}
.test-cb{accent-color:var(--accent);width:13px;height:13px;cursor:pointer}
.test-id{font-family:monospace;font-size:11px;color:var(--muted);min-width:38px}
.test-name{flex:1;font-size:12px}
.test-icon{font-size:13px}
/* toolbar */
.toolbar{padding:10px 14px;border-top:1px solid var(--border);background:var(--surface);display:flex;gap:8px;flex-shrink:0}
.btn{padding:7px 14px;border-radius:6px;border:none;cursor:pointer;font-size:12px;font-weight:600;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-run{background:var(--accent);color:#fff;flex:1}
.btn-stop{background:var(--fail);color:#fff}
.btn-sm{background:var(--card);color:var(--text);border:1px solid var(--border);font-size:11px;padding:5px 10px;border-radius:5px;cursor:pointer}
.btn-sm:hover{background:var(--surface)}
.btn-sm:disabled{opacity:.4;cursor:not-allowed}
/* right */
.right{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.right-tabs{display:flex;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}
.tab{padding:10px 18px;cursor:pointer;font-size:12px;font-weight:600;color:var(--muted);border-bottom:2px solid transparent;white-space:nowrap}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-pane{display:none;flex:1;overflow:hidden}
.tab-pane.active{display:flex;flex-direction:column}
/* terminal */
#terminal{flex:1;overflow-y:auto;padding:12px 16px;font-family:'Consolas','Monaco',monospace;font-size:12px;line-height:1.6;background:#0a0c10}
#terminal .line{white-space:pre-wrap;word-break:break-all}
#terminal .line.pass{color:var(--pass)}
#terminal .line.fail{color:var(--fail)}
#terminal .line.warn{color:var(--warn)}
#terminal .line.info{color:var(--run)}
#terminal .line.dim{color:#4a5568}
/* progress bar */
.prog-wrap{padding:10px 14px;border-top:1px solid var(--border);background:var(--surface);flex-shrink:0}
.progress{height:4px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:4px}
.progress-bar{height:100%;background:var(--accent);width:0%;transition:width .3s}
.prog-msg{font-size:11px;color:var(--muted)}
/* results */
#results-pane{flex:1;overflow-y:auto;padding:16px}
.summary-bar{display:flex;gap:16px;margin-bottom:16px}
.summary-card{flex:1;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;text-align:center}
.summary-card .val{font-size:28px;font-weight:700}
.summary-card .lbl{font-size:11px;color:var(--muted);margin-top:2px}
.summary-card.pass .val{color:var(--pass)}
.summary-card.fail .val{color:var(--fail)}
.summary-card.total .val{color:var(--accent)}
.result-table{width:100%;border-collapse:collapse;font-size:12px}
.result-table th{background:var(--card);color:var(--muted);font-weight:600;padding:8px 12px;text-align:left;border-bottom:1px solid var(--border)}
.result-table td{padding:7px 12px;border-bottom:1px solid var(--border)}
.result-table tr:hover td{background:var(--card)}
.result-table tr.pass td:first-child{border-left:3px solid var(--pass)}
.result-table tr.fail td:first-child{border-left:3px solid var(--fail)}
.result-table tr.pending td{color:var(--muted)}
.metric-cell{font-size:11px;color:#a0c4e8;font-family:monospace;white-space:nowrap}
.metric-cell.fail{color:#ff9999}
.metric-cell.pass{color:#9ee89e}
.chip{padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700}
.chip.A{background:rgba(74,144,217,.15);color:var(--A)}
.chip.B{background:rgba(224,123,57,.15);color:var(--B)}
.chip.C{background:rgba(107,174,106,.15);color:var(--C)}
.chip.D{background:rgba(155,107,217,.15);color:var(--D)}
.status-pass{color:var(--pass);font-weight:700}
.status-fail{color:var(--fail);font-weight:700}
.status-pend{color:var(--muted)}
.report-bar{padding:10px 14px;border-top:1px solid var(--border);background:var(--surface);display:flex;align-items:center;gap:10px;flex-shrink:0}
.report-bar .msg{font-size:11px;color:var(--muted);flex:1}
/* ═══ Profile Editor ═══ */
#tab-profiles .profiles-layout{display:flex;flex:1;overflow:hidden}
.profile-sidebar{width:260px;min-width:200px;border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0}
.sidebar-hdr{background:var(--surface);padding:9px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;flex-shrink:0}
.sidebar-hdr .ml-auto{margin-left:auto}
.profile-list{flex:1;overflow-y:auto;padding:6px}
.profile-item{padding:9px 12px;border-radius:6px;cursor:pointer;border:1px solid transparent;margin-bottom:3px}
.profile-item:hover{background:var(--card)}
.profile-item.active{background:var(--card);border-color:var(--accent)}
.profile-item .pid{font-family:monospace;font-size:11px;font-weight:700;color:var(--accent)}
.profile-item .pname{font-size:11px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* NetEmu rules */
.netemu-panel{padding:8px 12px;border-top:1px solid var(--border);flex-shrink:0;max-height:180px;overflow-y:auto}
.netemu-hdr{font-size:11px;font-weight:600;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:6px}
.rule-row{display:flex;gap:6px;padding:4px 0;font-size:11px;border-bottom:1px solid var(--border);align-items:center}
.rule-row:last-child{border-bottom:none}
.rule-iface{font-family:monospace;min-width:90px;color:var(--text)}
.rule-badge{padding:1px 6px;border-radius:8px;font-size:10px;font-weight:700}
.rule-badge.active,.rule-badge.active_varied{background:rgba(74,222,128,.15);color:var(--pass)}
.rule-badge.cleared,.rule-badge.pending{background:rgba(148,163,184,.1);color:var(--muted)}
.rule-params{color:var(--muted);font-size:10px;flex:1}
.no-rules{font-size:11px;color:var(--muted);padding:4px 0}
/* Profile editor */
.profile-editor{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
.pe-section{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px}
.pe-section-title{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px;display:flex;align-items:center;gap:6px}
.pe-section-title span{flex:1}
.line-badge{padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700}
.line-badge.a{background:rgba(74,144,217,.15);color:var(--A)}
.line-badge.b{background:rgba(107,174,106,.15);color:var(--C)}
.form-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.form-field{display:flex;flex-direction:column;gap:4px}
.form-field label{font-size:11px;color:var(--muted)}
.form-field input[type=text],.form-field input[type=number]{background:var(--surface);border:1px solid var(--border);border-radius:5px;padding:5px 8px;color:var(--text);font-size:12px;width:100%}
.form-field input:focus{outline:none;border-color:var(--accent)}
.form-field-full{grid-column:1/-1}
.toggle-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);margin-top:6px;cursor:pointer;user-select:none}
.toggle-row label{font-size:12px;cursor:pointer;flex:1}
.toggle-row input[type=checkbox]{accent-color:var(--accent);width:14px;height:14px;cursor:pointer}
.nested-params{margin-top:8px;padding:10px;background:var(--surface);border-radius:6px;border:1px solid var(--border)}
.nested-params .form-grid{grid-template-columns:repeat(4,1fr)}
.editor-actions{background:var(--surface);border-top:1px solid var(--border);padding:10px 16px;display:flex;gap:8px;flex-shrink:0;align-items:center;flex-wrap:wrap}
.editor-actions .msg{font-size:11px;flex:1;color:var(--muted)}
.btn-primary{background:var(--accent);color:#fff;padding:7px 16px;border-radius:6px;border:none;cursor:pointer;font-size:12px;font-weight:600}
.btn-primary:hover{opacity:.85}
.btn-primary:disabled{opacity:.4;cursor:not-allowed}
.btn-danger{background:var(--fail);color:#fff;padding:7px 14px;border-radius:6px;border:none;cursor:pointer;font-size:12px;font-weight:600}
.btn-danger:hover{opacity:.85}
.btn-success{background:#16a34a;color:#fff;padding:7px 14px;border-radius:6px;border:none;cursor:pointer;font-size:12px;font-weight:600}
.btn-success:hover{opacity:.85}
.empty-editor{flex:1;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:14px}
/* scrollbar */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>
<header>
  <h1>🔬 Doublink ATSSS Test Runner</h1>
  <span class="sub">192.168.105.210:9080</span>
  <span class="badge idle" id="status-badge">● 閒置</span>
</header>
<div class="main">
  <!-- ══ LEFT: Test Selection ══ -->
  <div class="left">
    <div class="panel-hdr">
      <button class="btn-sm" onclick="selectAll()">全選</button>
      <button class="btn-sm" onclick="clearAll()">清除</button>
      <span class="sel-count" id="sel-count">已選 0 項</span>
    </div>
    <div class="test-list" id="test-list"></div>
    <div class="toolbar">
      <button class="btn btn-run" id="btn-run" onclick="startRun()" disabled>▶ 執行選取測項</button>
      <button class="btn btn-stop" id="btn-stop" onclick="stopRun()" style="display:none">■ 停止</button>
    </div>
  </div>

  <!-- ══ RIGHT: Tabs ══ -->
  <div class="right">
    <div class="right-tabs">
      <div class="tab active" onclick="switchTab('terminal')">📟 執行輸出</div>
      <div class="tab" onclick="switchTab('results')">📊 測試結果</div>
      <div class="tab" onclick="switchTab('profiles');loadProfileList()">🌐 Network Profiles</div>
    </div>

    <!-- Tab: Terminal -->
    <div class="tab-pane active" id="tab-terminal">
      <div id="terminal"><span class="line dim">等待執行...</span></div>
      <div class="prog-wrap">
        <div class="progress"><div class="progress-bar" id="prog-bar"></div></div>
        <span class="prog-msg" id="prog-msg">尚未執行</span>
      </div>
    </div>

    <!-- Tab: Results -->
    <div class="tab-pane" id="tab-results">
      <div id="results-pane">
        <div class="summary-bar">
          <div class="summary-card total"><div class="val" id="r-total">—</div><div class="lbl">總測項</div></div>
          <div class="summary-card pass"><div class="val" id="r-pass">—</div><div class="lbl">PASS ✅</div></div>
          <div class="summary-card fail"><div class="val" id="r-fail">—</div><div class="lbl">FAIL ❌</div></div>
        </div>
        <table class="result-table">
          <thead><tr><th>Test ID</th><th>群組</th><th>測項名稱</th><th>狀態</th><th>實測數值</th></tr></thead>
          <tbody id="result-tbody"></tbody>
        </table>
      </div>
      <div class="report-bar">
        <span class="msg" id="report-msg">執行完成後可生成 Word 報告</span>
        <button class="btn-sm" onclick="refreshMetrics()">🔄 刷新數值</button>
        <button class="btn-sm" id="btn-report" onclick="generateReport()" disabled>📄 生成 Word 報告</button>
        <a id="report-link" href="#" style="display:none" class="btn-sm" target="_blank">⬇ 下載</a>
      </div>
    </div>

    <!-- Tab: Network Profiles -->
    <div class="tab-pane" id="tab-profiles">
      <div class="profiles-layout">

        <!-- Sidebar: Profile list + NetEmu rules -->
        <div class="profile-sidebar">
          <div class="sidebar-hdr">
            Network Profiles
            <button class="btn-sm ml-auto" onclick="newProfile()">+ 新增</button>
          </div>
          <div class="profile-list" id="profile-list">
            <div style="padding:12px;color:var(--muted);font-size:12px">載入中...</div>
          </div>
          <!-- NetEmu current rules -->
          <div class="netemu-panel">
            <div class="netemu-hdr">
              <span>NetEmu 目前規則</span>
              <button class="btn-sm" onclick="refreshRules()" style="padding:2px 8px;font-size:10px">🔄</button>
            </div>
            <div id="netemu-rules"><div class="no-rules">點 🔄 刷新</div></div>
          </div>
        </div>

        <!-- Editor -->
        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0">
          <div class="profile-editor" id="profile-editor">
            <div class="empty-editor">← 選擇 Profile 開始編輯，或點「+ 新增」建立新 Profile</div>
          </div>
          <div class="editor-actions" id="editor-actions" style="display:none">
            <span class="msg" id="editor-msg"></span>
            <button class="btn-primary" onclick="saveProfile()">💾 儲存</button>
            <button class="btn-success" onclick="applyToNetEmu()">🌐 套用到 NetEmu</button>
            <button class="btn-danger" onclick="deleteProfile()" id="btn-del-profile">🗑 刪除</button>
            <button class="btn-sm" onclick="clearAllRules()">✖ 清除所有規則</button>
          </div>
        </div>
      </div>
    </div>
  </div><!-- .right -->
</div><!-- .main -->

<script>
const TESTS = __TESTS_JSON__;
const GROUP_META = __GROUP_META_JSON__;

// ═══ TEST RUNNER ═══
let selected = new Set();
let currentRunId = null, lastRunId = null;

function buildTestList() {
  const container = document.getElementById('test-list');
  const groups = {};
  TESTS.forEach(t => { if (!groups[t.group]) groups[t.group] = []; groups[t.group].push(t); });
  Object.keys(groups).sort().forEach(g => {
    const meta = GROUP_META[g];
    const block = document.createElement('div');
    block.className = 'group-block'; block.id = `grp-${g}`;
    const hdr = document.createElement('div');
    hdr.className = 'group-hdr';
    hdr.innerHTML = `<input type="checkbox" class="group-cb" id="gcb-${g}" onclick="toggleGroup('${g}',this.checked)">
      <span class="group-dot" style="background:var(--${g})"></span>
      <span class="group-label">${meta.label}</span>
      <span class="group-cnt">${groups[g].length} 項</span>
      <span class="group-chevron">▼</span>`;
    hdr.addEventListener('click', e => { if (e.target.type === 'checkbox') return; block.classList.toggle('collapsed'); });
    const items = document.createElement('div'); items.className = 'group-tests';
    groups[g].forEach(t => {
      const row = document.createElement('div'); row.className = 'test-item'; row.id = `item-${t.id}`;
      row.innerHTML = `<input type="checkbox" class="test-cb" id="cb-${t.id}" onchange="toggleTest('${t.id}',this.checked)">
        <span class="test-id">${t.id}</span><span class="test-name">${t.name}</span>
        <span class="test-icon" id="icon-${t.id}"></span>`;
      row.addEventListener('click', e => { if (e.target.type === 'checkbox') return; const cb=document.getElementById(`cb-${t.id}`); cb.checked=!cb.checked; toggleTest(t.id, cb.checked); });
      items.appendChild(row);
    });
    block.appendChild(hdr); block.appendChild(items); container.appendChild(block);
  });
  updateSelCount();
}

function toggleTest(id, checked) {
  if (checked) selected.add(id); else selected.delete(id);
  updateGroupCb(TESTS.find(t=>t.id===id).group);
  updateSelCount();
}
function toggleGroup(g, checked) {
  TESTS.filter(t=>t.group===g).forEach(t => { selected[checked?'add':'delete'](t.id); const cb=document.getElementById(`cb-${t.id}`); if(cb) cb.checked=checked; });
  updateSelCount();
}
function updateGroupCb(g) {
  const gt = TESTS.filter(t=>t.group===g); const sc = gt.filter(t=>selected.has(t.id)).length;
  const cb = document.getElementById(`gcb-${g}`); if(!cb) return;
  cb.indeterminate = sc>0 && sc<gt.length; cb.checked = sc===gt.length;
}
function selectAll() { TESTS.forEach(t => { selected.add(t.id); const cb=document.getElementById(`cb-${t.id}`); if(cb) cb.checked=true; }); ['A','B','C','D'].forEach(g=>updateGroupCb(g)); updateSelCount(); }
function clearAll()  { TESTS.forEach(t => { selected.delete(t.id); const cb=document.getElementById(`cb-${t.id}`); if(cb) cb.checked=false; }); ['A','B','C','D'].forEach(g=>updateGroupCb(g)); updateSelCount(); }
function updateSelCount() {
  const n = selected.size;
  document.getElementById('sel-count').textContent = `已選 ${n} 項`;
  const btn = document.getElementById('btn-run');
  btn.textContent = `▶ 執行選取測項 (${n})`; btn.disabled = n===0;
}

async function startRun() {
  if (selected.size===0) return;
  const ids = [...selected];
  document.getElementById('terminal').innerHTML='';
  initResultTable(ids);
  setRunning(true);
  const res = await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({test_ids:ids})});
  if (!res.ok) { const err=await res.json(); appendLine(`[ERROR] ${err.detail}`,'fail'); setRunning(false); return; }
  const {run_id,count} = await res.json();
  currentRunId=run_id; lastRunId=run_id;
  appendLine(`▶ 開始執行 ${count} 個測項 (run: ${run_id})`,'info');
  const sse = new EventSource(`/api/stream/${run_id}`);
  sse.onmessage = e => {
    const data = JSON.parse(e.data);
    if (data.done) { sse.close(); onRunDone(data); return; }
    if (data.line!==undefined) {
      let cls='';
      if (/PASSED/.test(data.line)) cls='pass';
      else if (/FAILED|ERROR/.test(data.line)) cls='fail';
      else if (/WARNING/.test(data.line)) cls='warn';
      else if (/^={3,}/.test(data.line.trim())) cls='info';
      appendLine(data.line, cls);
      const m = data.line.match(/::(test_\S+)\s+(PASSED|FAILED|ERROR)/);
      if (m) { const t=TESTS.find(t=>t.node.includes(m[1])); if(t) updateResultIcon(t.id, m[2]); }
    }
  };
  sse.onerror = () => { sse.close(); setRunning(false); };
}

function onRunDone(data) {
  setRunning(false);
  document.getElementById('r-total').textContent = data.passed+data.failed;
  document.getElementById('r-pass').textContent  = data.passed;
  document.getElementById('r-fail').textContent  = data.failed;
  const bar = document.getElementById('prog-bar');
  bar.style.width='100%'; bar.style.background = data.failed>0?'var(--fail)':'var(--pass)';
  document.getElementById('prog-msg').textContent = data.exit_code===0 ? `✅ 全部通過 ${data.passed}/${data.passed+data.failed}` : `❌ ${data.failed} 項失敗，${data.passed} 項通過`;
  document.getElementById('btn-report').disabled = false;
  Object.entries(data.results).forEach(([tid,st])=>updateResultIcon(tid,st));
  if (data.metrics && Object.keys(data.metrics).length > 0) {
    applyMetricsToTable(data.metrics);
  }
  appendLine('',''); appendLine(`═══ 完成：${data.passed} PASSED  ${data.failed} FAILED ═══`, data.failed>0?'fail':'pass');
  switchTab('results');
}

async function stopRun() {
  if (!currentRunId) return;
  await fetch(`/api/stop/${currentRunId}`,{method:'POST'});
  setRunning(false); appendLine('[STOPPED]','warn');
}

// ── Metric formatting ─────────────────────────────────────────────
function fmtMetrics(tid, d) {
  if (!d) return '—';
  const f = v => (v != null && v !== undefined) ? parseFloat(v).toFixed(1) : '—';
  // Mode switch continuity (A-01..A-06): baseline + after_switch
  if (d.baseline_mbps != null && d.after_switch_mbps != null) {
    const pct = d.baseline_mbps > 0 ? Math.round(d.after_switch_mbps/d.baseline_mbps*100)+'%' : '—';
    return `基準 ${f(d.baseline_mbps)} → 後 ${f(d.after_switch_mbps)} Mbps (${pct})`;
  }
  // Failover disconnect (B-42, B-43): baseline + during_failover
  if (d.baseline_mbps != null && d.during_failover_mbps != null) {
    return `基準 ${f(d.baseline_mbps)} → 斷線中 ${f(d.during_failover_mbps)} Mbps`;
  }
  // Recovery (B-41): degraded + recovered
  if (d.degraded_mbps != null) {
    const ratio = d.degraded_mbps > 0 ? Math.round(d.recovered_mbps/d.degraded_mbps)+'×' : '—';
    return `劣化 ${f(d.degraded_mbps)} → 恢復 ${f(d.recovered_mbps)} Mbps (${ratio})`;
  }
  // Recovery after disconnect (B-49)
  if (d.during_disconnect_mbps != null) {
    return `斷線 ${f(d.during_disconnect_mbps)} → 恢復 ${f(d.after_recovery_mbps)} Mbps`;
  }
  // Loss protection C-05: dup vs bonding
  if (d.duplicate_throughput_mbps != null) {
    return `dup ${f(d.duplicate_throughput_mbps)} / bond ${f(d.bonding_throughput_mbps)} Mbps`;
  }
  // Mode switch under load (A-10)
  if (d.throughput_mbps != null && d.duration_s != null && d.protocol != null) {
    return `${f(d.throughput_mbps)} Mbps (${f(d.duration_s,0)}s ${d.protocol})`;
  }
  // D-08/D-09 baseline comparison: {real_time, bonding, duplicate}
  if (d.real_time != null || d.bonding != null) {
    const rt   = typeof d.real_time  === 'number' ? f(d.real_time)  : f(d.real_time?.throughput_mbps);
    const bond = typeof d.bonding    === 'number' ? f(d.bonding)    : f(d.bonding?.throughput_mbps);
    const dup  = typeof d.duplicate  === 'number' ? f(d.duplicate)  : f(d.duplicate?.throughput_mbps);
    return `rt ${rt} / bond ${bond} / dup ${dup} Mbps`;
  }
  // Generic: throughput + optional loss/jitter
  if (d.throughput_mbps != null) {
    let s = `${f(d.throughput_mbps)} Mbps`;
    if (d.loss_pct != null && Math.abs(d.loss_pct) < 200) s += ` / ${f(d.loss_pct)}% loss`;
    if (d.jitter_ms != null && d.jitter_ms > 0) s += ` / ${f(d.jitter_ms)}ms jitter`;
    if (d.min_required_mbps != null) s += ` (门槛 ≥${f(d.min_required_mbps)})`;
    return s;
  }
  return '—';
}

// ── Refresh metrics from allure-results (without re-running tests) ──
async function refreshMetrics() {
  const btn = event.currentTarget;
  btn.textContent = '⏳';
  try {
    const res = await fetch('/api/results');
    if (!res.ok) throw new Error('API error');
    const metrics = await res.json();
    applyMetricsToTable(metrics);
    btn.textContent = '🔄 刷新數值';
  } catch(e) {
    btn.textContent = '❌ 失敗';
    setTimeout(() => btn.textContent='🔄 刷新數值', 2000);
  }
}

function applyMetricsToTable(metrics) {
  Object.entries(metrics).forEach(([tid, data]) => {
    const cell = document.getElementById(`mt-${tid}`);
    if (!cell) return;
    const text = fmtMetrics(tid, data);
    cell.textContent = text;
    const status = data.status;
    cell.className = 'metric-cell' + (status==='failed' ? ' fail' : status==='passed' ? ' pass' : '');
    // Also update status icon if row is still pending
    const row = document.getElementById(`row-${tid}`);
    if (row && row.className === 'pending') {
      updateResultIcon(tid, status === 'passed' ? 'PASSED' : status === 'failed' ? 'FAILED' : null);
    }
  });
}

function initResultTable(ids) {
  const tbody = document.getElementById('result-tbody'); tbody.innerHTML='';
  document.getElementById('r-total').textContent=ids.length;
  document.getElementById('r-pass').textContent='0';
  document.getElementById('r-fail').textContent='0';
  ids.forEach(id => {
    const t=TESTS.find(t=>t.id===id); if(!t) return;
    const tr=document.createElement('tr'); tr.id=`row-${id}`; tr.className='pending';
    tr.innerHTML=`<td><b>${id}</b></td><td><span class="chip ${t.group}">${t.group}</span></td><td>${t.name}</td><td class="status-pend" id="st-${id}">— 等待中</td><td class="metric-cell" id="mt-${id}">—</td>`;
    tbody.appendChild(tr);
  });
  document.getElementById('report-link').style.display='none';
  document.getElementById('btn-report').disabled=true;
}

function updateResultIcon(tid, status) {
  const icon=document.getElementById(`icon-${tid}`);
  const stCell=document.getElementById(`st-${tid}`);
  const row=document.getElementById(`row-${tid}`);
  const item=document.getElementById(`item-${tid}`);
  if (status==='PASSED') {
    if(icon) icon.textContent='✅'; if(stCell){stCell.textContent='✅ PASSED';stCell.className='status-pass';}
    if(row) row.className='pass'; if(item) item.className='test-item result-pass';
  } else {
    if(icon) icon.textContent='❌'; if(stCell){stCell.textContent='❌ FAILED';stCell.className='status-fail';}
    if(row) row.className='fail'; if(item) item.className='test-item result-fail';
  }
  const done=document.querySelectorAll('#result-tbody tr:not(.pending)').length;
  const sel=selected.size;
  if(sel>0){document.getElementById('prog-bar').style.width=`${(done/sel*100).toFixed(0)}%`;document.getElementById('prog-msg').textContent=`執行中：${done}/${sel}`;}
}

async function generateReport() {
  if(!lastRunId) return;
  document.getElementById('btn-report').disabled=true;
  document.getElementById('report-msg').textContent='⏳ 生成報告中...';
  const res=await fetch(`/api/report/${lastRunId}`,{method:'POST'});
  if(res.ok){
    const data=await res.json();
    document.getElementById('report-msg').textContent=`✅ 報告已生成：${data.file}`;
    const link=document.getElementById('report-link');
    link.href=data.download; link.textContent=`⬇ 下載 ${data.file}`; link.style.display='inline-block';
  } else { document.getElementById('report-msg').textContent='❌ 報告生成失敗'; }
  document.getElementById('btn-report').disabled=false;
}

function appendLine(text, cls) {
  const term=document.getElementById('terminal');
  const d=document.createElement('div'); d.className=`line ${cls}`; d.textContent=text;
  term.appendChild(d); term.scrollTop=term.scrollHeight;
}
function setRunning(running) {
  const badge=document.getElementById('status-badge');
  const btnRun=document.getElementById('btn-run'); const btnStop=document.getElementById('btn-stop');
  if(running){ badge.textContent='● 執行中'; badge.className='badge running'; btnRun.style.display='none'; btnStop.style.display='block'; }
  else{ badge.textContent='● 閒置'; badge.className='badge idle'; btnRun.style.display='block'; btnStop.style.display='none'; currentRunId=null; }
}
function switchTab(name) {
  const names=['terminal','results','profiles'];
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',names[i]===name));
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.toggle('active',p.id===`tab-${name}`));
}

// ═══ PROFILE EDITOR ═══
let profiles = [], editingProfile = null, isNewProfile = false;

async function loadProfileList() {
  const res = await fetch('/api/profiles');
  profiles = await res.json();
  renderProfileList();
}

function renderProfileList() {
  const container = document.getElementById('profile-list');
  container.innerHTML = '';
  if (!profiles.length) { container.innerHTML='<div style="padding:12px;color:var(--muted);font-size:12px">無 Profile</div>'; return; }
  profiles.forEach(p => {
    const div = document.createElement('div');
    div.className = `profile-item${editingProfile?.id===p.id?' active':''}`;
    div.onclick = () => selectProfile(p.id);
    div.innerHTML = `<div class="pid">${p.id}</div><div class="pname">${p.name||''}</div>`;
    container.appendChild(div);
  });
}

function selectProfile(pid) {
  editingProfile = profiles.find(p=>p.id===pid);
  isNewProfile = false;
  if (!editingProfile) return;
  renderProfileList();
  renderEditor(editingProfile);
  document.getElementById('editor-actions').style.display='flex';
  document.getElementById('btn-del-profile').style.display='inline-block';
  setEditorMsg('');
}

function newProfile() {
  isNewProfile = true;
  editingProfile = {id:'new_profile',name:'New Profile',description:'',line_a:{bandwidth_kbit:50000,delay_ms:20,jitter_ms:0,loss_pct:0},line_b:{bandwidth_kbit:50000,delay_ms:20,jitter_ms:0,loss_pct:0}};
  renderEditor(editingProfile);
  document.getElementById('editor-actions').style.display='flex';
  document.getElementById('btn-del-profile').style.display='none';
  setEditorMsg('新 Profile（輸入 ID 後儲存）');
}

function renderEditor(p) {
  const container = document.getElementById('profile-editor');
  container.innerHTML = `
    <div class="pe-section">
      <div class="pe-section-title"><span>基本資訊</span></div>
      <div class="form-grid" style="grid-template-columns:1fr 2fr">
        <div class="form-field"><label>Profile ID</label><input type="text" id="f-id" value="${esc(p.id||'')}"></div>
        <div class="form-field"><label>名稱 (Name)</label><input type="text" id="f-name" value="${esc(p.name||'')}"></div>
        <div class="form-field form-field-full"><label>描述 (Description)</label><input type="text" id="f-desc" value="${esc(p.description||'')}"></div>
      </div>
    </div>
    ${renderLineSection('a','5G (LINE A)',p.line_a||{})}
    ${renderLineSection('b','WiFi (LINE B)',p.line_b||{})}
  `;
}

function renderLineSection(line, title, data) {
  const vr = data.variation || {};
  const ds = data.disconnect_schedule || {};
  const hasVar  = !!data.variation;
  const hasDisc = !!(data.disconnect_schedule && data.disconnect_schedule.enabled !== false);
  return `
  <div class="pe-section">
    <div class="pe-section-title">
      <span class="line-badge ${line}">${line.toUpperCase()}</span>
      <span>${title}</span>
    </div>
    <div class="form-grid">
      <div class="form-field"><label>頻寬 (kbit/s)</label><input type="number" id="f${line}-bw" value="${data.bandwidth_kbit||0}" min="0" max="10000000"></div>
      <div class="form-field"><label>延遲 Delay (ms)</label><input type="number" id="f${line}-delay" value="${data.delay_ms||0}" min="0"></div>
      <div class="form-field"><label>Jitter (ms)</label><input type="number" id="f${line}-jitter" value="${data.jitter_ms||0}" min="0"></div>
      <div class="form-field"><label>丟包 Loss (%)</label><input type="number" id="f${line}-loss" value="${data.loss_pct||0}" min="0" max="100" step="0.01"></div>
      <div class="form-field"><label>損壞 Corrupt (%)</label><input type="number" id="f${line}-corrupt" value="${data.corrupt_pct||0}" min="0" max="100" step="0.01"></div>
      <div class="form-field"><label>重複 Duplicate (%)</label><input type="number" id="f${line}-dup" value="${data.duplicate_pct||0}" min="0" max="100" step="0.01"></div>
    </div>
    <div class="toggle-row" onclick="toggleNested('${line}-var','f${line}-var-en')">
      <input type="checkbox" id="f${line}-var-en" ${hasVar?'checked':''} onclick="event.stopPropagation();toggleNested('${line}-var','f${line}-var-en')">
      <label>動態變化 (Variation)</label>
    </div>
    <div id="${line}-var" class="nested-params" style="display:${hasVar?'block':'none'}">
      <div class="form-grid" style="grid-template-columns:repeat(4,1fr)">
        <div class="form-field"><label>BW ± kbit</label><input type="number" id="f${line}-var-bw" value="${vr.bw_range_kbit||0}"></div>
        <div class="form-field"><label>Delay ± ms</label><input type="number" id="f${line}-var-delay" value="${vr.delay_range_ms||0}"></div>
        <div class="form-field"><label>Loss ± %</label><input type="number" id="f${line}-var-loss" step="0.01" value="${vr.loss_range_pct||0}"></div>
        <div class="form-field"><label>間隔 (s)</label><input type="number" id="f${line}-var-int" value="${vr.interval_s||5}"></div>
      </div>
    </div>
    <div class="toggle-row" onclick="toggleNested('${line}-disc','f${line}-disc-en')">
      <input type="checkbox" id="f${line}-disc-en" ${hasDisc?'checked':''} onclick="event.stopPropagation();toggleNested('${line}-disc','f${line}-disc-en')">
      <label>週期斷線 (Disconnect Schedule)</label>
    </div>
    <div id="${line}-disc" class="nested-params" style="display:${hasDisc?'block':'none'}">
      <div class="form-grid" style="grid-template-columns:repeat(4,1fr)">
        <div class="form-field"><label>斷線時長 (s)</label><input type="number" id="f${line}-disc-s" value="${ds.disconnect_s||2}"></div>
        <div class="form-field"><label>間隔 (s)</label><input type="number" id="f${line}-disc-int" value="${ds.interval_s||15}"></div>
        <div class="form-field"><label>重複次數</label><input type="number" id="f${line}-disc-rep" value="${ds.repeat||5}"></div>
      </div>
    </div>
  </div>`;
}

function toggleNested(id, cbId) {
  const el=document.getElementById(id); const cb=document.getElementById(cbId);
  if (el && cb) el.style.display = cb.checked ? 'block' : 'none';
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }

function gv(id){ return document.getElementById(id)?.value||''; }
function gn(id){ return parseFloat(document.getElementById(id)?.value||0)||0; }
function gc(id){ return document.getElementById(id)?.checked||false; }

function collectFormData() {
  const buildLine = (l) => {
    const d = {bandwidth_kbit:gn(`f${l}-bw`),delay_ms:gn(`f${l}-delay`),jitter_ms:gn(`f${l}-jitter`),loss_pct:gn(`f${l}-loss`)};
    const corrupt=gn(`f${l}-corrupt`); if(corrupt) d.corrupt_pct=corrupt;
    const dup=gn(`f${l}-dup`); if(dup) d.duplicate_pct=dup;
    if(gc(`f${l}-var-en`)) d.variation={bw_range_kbit:gn(`f${l}-var-bw`),delay_range_ms:gn(`f${l}-var-delay`),loss_range_pct:gn(`f${l}-var-loss`),interval_s:gn(`f${l}-var-int`)};
    if(gc(`f${l}-disc-en`)) d.disconnect_schedule={enabled:true,disconnect_s:gn(`f${l}-disc-s`),interval_s:gn(`f${l}-disc-int`),repeat:gn(`f${l}-disc-rep`)};
    return d;
  };
  return {id:gv('f-id').trim(),name:gv('f-name').trim(),description:gv('f-desc').trim(),line_a:buildLine('a'),line_b:buildLine('b')};
}

async function saveProfile() {
  const data = collectFormData();
  if (!data.id) { setEditorMsg('❌ Profile ID 不可為空'); return; }
  const pid = isNewProfile ? null : editingProfile?.id;
  const url  = pid ? `/api/profiles/${pid}` : '/api/profiles';
  const method = pid ? 'PUT' : 'POST';
  setEditorMsg('⏳ 儲存中...');
  const res = await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if (res.ok) {
    isNewProfile=false; editingProfile=data;
    await loadProfileList(); selectProfile(data.id);
    setEditorMsg('✅ 已儲存');
    document.getElementById('btn-del-profile').style.display='inline-block';
  } else { const e=await res.json(); setEditorMsg(`❌ 儲存失敗：${e.detail||''}`); }
}

async function applyToNetEmu() {
  const data = collectFormData();
  if (!data.id) { setEditorMsg('❌ 請先儲存 Profile'); return; }
  await saveProfile();
  setEditorMsg('⏳ 套用到 NetEmu...');
  const res = await fetch(`/api/profiles/${data.id}/apply`,{method:'POST'});
  if (res.ok) {
    const result=await res.json();
    const ok=result.rules.filter(r=>r.status<300).length;
    const errs=result.errors.length;
    setEditorMsg(`✅ 已建立 ${ok} 條規則${errs?`，⚠ ${errs} 個錯誤`:''}`);
    await refreshRules();
  } else { const e=await res.json(); setEditorMsg(`❌ 套用失敗：${e.detail||''}`); }
}

async function deleteProfile() {
  if (!editingProfile?.id) return;
  if (!confirm(`確定刪除 Profile「${editingProfile.id}」？`)) return;
  const res = await fetch(`/api/profiles/${editingProfile.id}`,{method:'DELETE'});
  if (res.ok) {
    editingProfile=null; isNewProfile=false;
    document.getElementById('profile-editor').innerHTML='<div class="empty-editor">Profile 已刪除</div>';
    document.getElementById('editor-actions').style.display='none';
    await loadProfileList();
  }
}

async function clearAllRules() {
  if (!confirm('確定清除 NetEmu 所有規則？')) return;
  setEditorMsg('⏳ 清除中...');
  const res = await fetch('/api/netemu/rules',{method:'DELETE'});
  if (res.ok) { const d=await res.json(); setEditorMsg(`✅ 已清除 ${d.cleared.length} 條規則`); await refreshRules(); }
  else { setEditorMsg('❌ 清除失敗'); }
}

async function refreshRules() {
  const container = document.getElementById('netemu-rules');
  try {
    const res = await fetch('/api/netemu/rules');
    if (!res.ok) { container.innerHTML='<div class="no-rules">NetEmu 無法連線</div>'; return; }
    const rules = await res.json();
    if (!rules.length) { container.innerHTML='<div class="no-rules">無 active 規則</div>'; return; }
    container.innerHTML = rules.map(r=>`
      <div class="rule-row">
        <span class="rule-iface">${r.interface||r.iface||'?'}</span>
        <span class="rule-badge ${r.status||'pending'}">${r.status||'?'}</span>
        <span class="rule-params">${r.bandwidth_kbit||0}k / ${r.delay_ms||0}ms / ${r.loss_pct||0}%</span>
      </div>`).join('');
  } catch(e) { container.innerHTML='<div class="no-rules">⚠ 連線失敗</div>'; }
}

function setEditorMsg(msg) { document.getElementById('editor-msg').textContent=msg; }

// ── Init ──
buildTestList();
</script>
</body>
</html>"""


def build_html() -> str:
    return (HTML
            .replace("__TESTS_JSON__", json.dumps(TESTS, ensure_ascii=False))
            .replace("__GROUP_META_JSON__", json.dumps(GROUP_META, ensure_ascii=False)))


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(build_html())


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9080
    print(f"\n  Doublink Test Runner  →  http://192.168.105.210:{port}/\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
