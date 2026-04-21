"""
Doublink ATSSS Test Runner — Web UI
=====================================
啟動方式：
    cd ~/doublink-tester
    PYTHONPATH=src python3 scripts/run_ui.py

預設 port：9080
存取：http://192.168.105.210:9080/
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

# ── 路徑設定 ──────────────────────────────────────────────────────
PROJ_DIR  = Path(__file__).parent.parent
RESULTS_DIR = PROJ_DIR / "allure-results"
REPORTS_DIR = PROJ_DIR / "reports"
REPORT_SCRIPT = PROJ_DIR / "scripts" / "generate_test_report.py"

# ── 測項清單 ──────────────────────────────────────────────────────
TESTS = [
    # ── Group A ──────────────────────────────────────────────────
    {"id":"A-01","group":"A","name":"real_time → bonding（clean）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[realtime_to_bonding_clean_tcp]"},
    {"id":"A-02","group":"A","name":"bonding → duplicate（mild loss）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[bonding_to_duplicate_symm_loss_http]"},
    {"id":"A-03","group":"A","name":"duplicate → real_time（mild latency）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[duplicate_to_realtime_symm_latency_tcp]"},
    {"id":"A-04","group":"A","name":"real_time → duplicate（congested UDP）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[realtime_to_duplicate_congested_udp]"},
    {"id":"A-05","group":"A","name":"bonding → real_time（5G 間歇，SIP）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[bonding_to_realtime_5g_intermittent_sip]"},
    {"id":"A-06","group":"A","name":"bonding → duplicate（5G 劣化）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[bonding_to_duplicate_5g_degraded_tcp]"},
    {"id":"A-07","group":"A","name":"API 切換：bonding → duplicate",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeBasicSwitch::test_mode_switch_api[bonding-duplicate]"},
    {"id":"A-08","group":"A","name":"API 切換：duplicate → real_time",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeBasicSwitch::test_mode_switch_api[duplicate-real_time]"},
    {"id":"A-09","group":"A","name":"API 切換：real_time → bonding",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeBasicSwitch::test_mode_switch_api[real_time-bonding]"},
    {"id":"A-10","group":"A","name":"負載中切換（bonding → duplicate）",
     "node":"tests/test_mode_switching/test_mode_transitions.py::TestModeSwitchUnderLoad::test_switch_during_iperf3"},

    # ── Group B — Profile 驗證 ───────────────────────────────────
    {"id":"B-01","group":"B","name":"Profile 套用：clean_controlled",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[clean_controlled-4]"},
    {"id":"B-02","group":"B","name":"Profile 套用：symmetric_mild_loss",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[symmetric_mild_loss-4]"},
    {"id":"B-03","group":"B","name":"Profile 套用：symmetric_mild_latency",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[symmetric_mild_latency-4]"},
    {"id":"B-04","group":"B","name":"Profile 套用：5g_degraded_moderate",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[5g_degraded_moderate-4]"},
    {"id":"B-05","group":"B","name":"Profile 套用：wifi_degraded_moderate",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_network_condition_applied[wifi_degraded_moderate-4]"},
    {"id":"B-06","group":"B","name":"規則清除後恢復乾淨狀態",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestNetworkConditionApplied::test_condition_clear_restores_clean"},
    {"id":"B-07","group":"B","name":"WiFi 干擾動態變化 variation",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestDegradationWithVariation::test_wifi_interference_variation"},
    {"id":"B-08","group":"B","name":"雙線動態變化 both_varied",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestDegradationWithVariation::test_both_varied"},
    {"id":"B-09","group":"B","name":"5G 週期斷線排程驗證",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestDisconnectSchedule::test_disconnect_schedule_applied[5g_intermittent_visible]"},
    {"id":"B-10","group":"B","name":"WiFi 週期斷線排程驗證",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestDisconnectSchedule::test_disconnect_schedule_applied[wifi_intermittent_visible]"},

    # ── Group B — TCP 基準 ───────────────────────────────────────
    {"id":"B-11","group":"B","name":"TCP 基準 [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_baseline_clean[real_time]"},
    {"id":"B-12","group":"B","name":"TCP 基準 [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_baseline_clean[bonding]"},
    {"id":"B-13","group":"B","name":"TCP 基準 [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_baseline_clean[duplicate]"},

    # ── Group B — TCP 劣化 ───────────────────────────────────────
    {"id":"B-14","group":"B","name":"TCP symmetric_mild_loss [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_loss-2.0-real_time]"},
    {"id":"B-15","group":"B","name":"TCP symmetric_mild_loss [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_loss-2.0-bonding]"},
    {"id":"B-16","group":"B","name":"TCP symmetric_mild_loss [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_loss-2.0-duplicate]"},
    {"id":"B-17","group":"B","name":"TCP symmetric_mild_latency [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_latency-1.0-real_time]"},
    {"id":"B-18","group":"B","name":"TCP symmetric_mild_latency [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_latency-1.0-bonding]"},
    {"id":"B-19","group":"B","name":"TCP symmetric_mild_latency [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[symmetric_mild_latency-1.0-duplicate]"},
    {"id":"B-20","group":"B","name":"TCP congested_recoverable [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[congested_recoverable-0.5-real_time]"},
    {"id":"B-21","group":"B","name":"TCP congested_recoverable [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[congested_recoverable-0.5-bonding]"},
    {"id":"B-22","group":"B","name":"TCP congested_recoverable [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[congested_recoverable-0.5-duplicate]"},
    {"id":"B-23","group":"B","name":"TCP 5g_degraded_moderate [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[5g_degraded_moderate-1.0-real_time]"},
    {"id":"B-24","group":"B","name":"TCP 5g_degraded_moderate [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[5g_degraded_moderate-1.0-bonding]"},
    {"id":"B-25","group":"B","name":"TCP 5g_degraded_moderate [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[5g_degraded_moderate-1.0-duplicate]"},
    {"id":"B-26","group":"B","name":"TCP wifi_degraded_moderate [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[wifi_degraded_moderate-1.0-real_time]"},
    {"id":"B-27","group":"B","name":"TCP wifi_degraded_moderate [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[wifi_degraded_moderate-1.0-bonding]"},
    {"id":"B-28","group":"B","name":"TCP wifi_degraded_moderate [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[wifi_degraded_moderate-1.0-duplicate]"},
    {"id":"B-29","group":"B","name":"TCP asymmetric_mixed_moderate [real_time]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[asymmetric_mixed_moderate-1.0-real_time]"},
    {"id":"B-30","group":"B","name":"TCP asymmetric_mixed_moderate [bonding]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[asymmetric_mixed_moderate-1.0-bonding]"},
    {"id":"B-31","group":"B","name":"TCP asymmetric_mixed_moderate [duplicate]",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestTcpThroughputDegradation::test_tcp_under_degradation[asymmetric_mixed_moderate-1.0-duplicate]"},

    # ── Group B — UDP ────────────────────────────────────────────
    {"id":"B-32","group":"B","name":"UDP 基準（clean）",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_baseline_clean"},
    {"id":"B-33","group":"B","name":"UDP symmetric_mild_loss",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[symmetric_mild_loss-10.0-100.0]"},
    {"id":"B-34","group":"B","name":"UDP symmetric_mild_latency",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[symmetric_mild_latency-60.0-200.0]"},
    {"id":"B-35","group":"B","name":"UDP wifi_interference_moderate",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[wifi_interference_moderate-10.0-100.0]"},
    {"id":"B-36","group":"B","name":"UDP asymmetric_mixed_moderate",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestUdpDegradation::test_udp_under_degradation[asymmetric_mixed_moderate-10.0-200.0]"},

    # ── Group B — Steering ───────────────────────────────────────
    {"id":"B-37","group":"B","name":"Steering：5G 劣化 → 導向 WiFi",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[5g_degraded_moderate-5G degraded, WiFi healthy \u2014 expect steering to WiFi]"},
    {"id":"B-38","group":"B","name":"Steering：WiFi 劣化 → 導向 5G",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[wifi_degraded_moderate-WiFi degraded, 5G healthy \u2014 expect steering to 5G]"},
    {"id":"B-39","group":"B","name":"Steering：5G 高延遲 → 導向 WiFi",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[5g_high_latency_moderate-5G high latency, WiFi normal \u2014 expect latency-aware steering]"},
    {"id":"B-40","group":"B","name":"Steering：WiFi 高延遲 → 導向 5G",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestSteeringBehaviour::test_steering_maintains_throughput[wifi_high_latency_moderate-WiFi high latency, 5G normal \u2014 expect latency-aware steering]"},

    # ── Group B — Recovery & Failover ───────────────────────────
    {"id":"B-41","group":"B","name":"劣化後恢復：congested → clean",
     "node":"tests/test_degradation/test_throughput_degradation.py::TestRecoveryAfterDegradation::test_tcp_recovery_after_congestion"},
    {"id":"B-42","group":"B","name":"Failover：5G 斷線 → WiFi 存活",
     "node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_on_disconnect[5g_disconnect_visible-WiFi (LINE B)]"},
    {"id":"B-43","group":"B","name":"Failover：WiFi 斷線 → 5G 存活",
     "node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_on_disconnect[wifi_disconnect_visible-5G (LINE A)]"},
    {"id":"B-44","group":"B","name":"Failover：bonding 模式下 5G 斷線",
     "node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_under_mode[bonding]"},
    {"id":"B-45","group":"B","name":"Failover：duplicate 模式下 5G 斷線",
     "node":"tests/test_degradation/test_failover.py::TestLinkDisconnectFailover::test_failover_under_mode[duplicate]"},
    {"id":"B-46","group":"B","name":"間歇斷線：5G 每 15s 斷 2s",
     "node":"tests/test_degradation/test_failover.py::TestIntermittentDisconnect::test_intermittent_disconnect_survival[5g_intermittent_visible-5G (LINE A)]"},
    {"id":"B-47","group":"B","name":"間歇斷線：WiFi 每 15s 斷 2s",
     "node":"tests/test_degradation/test_failover.py::TestIntermittentDisconnect::test_intermittent_disconnect_survival[wifi_intermittent_visible-WiFi (LINE B)]"},
    {"id":"B-48","group":"B","name":"API 排程斷線（LINE A，3s）",
     "node":"tests/test_degradation/test_failover.py::TestIntermittentDisconnect::test_scheduled_disconnect_via_api"},
    {"id":"B-49","group":"B","name":"5G 斷線後恢復驗證",
     "node":"tests/test_degradation/test_failover.py::TestRecoveryAfterDisconnect::test_recovery_after_5g_disconnect"},

    # ── Group C ──────────────────────────────────────────────────
    {"id":"C-01","group":"C","name":"均衡頻寬聚合（5G+WiFi 各 60M）",
     "node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestBondingAggregation::test_balanced_aggregation"},
    {"id":"C-02","group":"C","name":"加權聚合（5G 80M + WiFi 40M）",
     "node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestBondingAggregation::test_weighted_aggregation"},
    {"id":"C-03","group":"C","name":"硬切換 Session 持續性（5G 週期斷線）",
     "node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestFailoverContinuity::test_hard_failover_session_continuity"},
    {"id":"C-04","group":"C","name":"間歇抖動長時間穩定性（60s）",
     "node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestFailoverContinuity::test_intermittent_flap_stability"},
    {"id":"C-05","group":"C","name":"丟包保護：duplicate vs bonding（5G 2% loss）",
     "node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestDuplicateReliability::test_loss_protection_duplicate_vs_bonding"},
    {"id":"C-06","group":"C","name":"突發丟包韌性（0~10% 浮動）",
     "node":"tests/test_golden_scenarios/test_golden_scenarios.py::TestDuplicateReliability::test_burst_loss_resilience"},

    # ── Group D ──────────────────────────────────────────────────
    {"id":"D-01","group":"D","name":"模式效能：bonding clean TCP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_clean_tcp]"},
    {"id":"D-02","group":"D","name":"模式效能：duplicate clean TCP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[duplicate_clean_tcp]"},
    {"id":"D-03","group":"D","name":"模式效能：real_time clean TCP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[realtime_clean_tcp]"},
    {"id":"D-04","group":"D","name":"模式效能：bonding symmetric_loss HTTP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_symmetric_loss_http]"},
    {"id":"D-05","group":"D","name":"模式效能：duplicate symmetric_loss HTTP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[duplicate_symmetric_loss_http]"},
    {"id":"D-06","group":"D","name":"模式效能：bonding 5G 劣化 TCP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_5g_degraded_tcp]"},
    {"id":"D-07","group":"D","name":"模式效能：bonding WiFi 劣化 TCP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeComparison::test_mode_performance[bonding_wifi_degraded_tcp]"},
    {"id":"D-08","group":"D","name":"三模式基準比較 TCP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeBaselineComparison::test_all_modes_baseline_tcp"},
    {"id":"D-09","group":"D","name":"三模式基準比較 UDP",
     "node":"tests/test_link_weight/test_weight_distribution.py::TestModeBaselineComparison::test_all_modes_baseline_udp"},
]

NODE_TO_ID = {t["node"]: t["id"] for t in TESTS}

# ── 執行狀態管理 ─────────────────────────────────────────────────
runs: dict[str, dict] = {}
current_run_id: str | None = None

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


# ══════════════════════════════════════════════════════════════════
app = FastAPI(title="Doublink Test Runner")

# ── pytest 非同步執行 ─────────────────────────────────────────────
async def run_pytest_task(run_id: str, nodes: list[str]):
    global current_run_id
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJ_DIR/'src'}:{env.get('PYTHONPATH','')}"

    cmd = [
        "python3", "-m", "pytest", *nodes,
        "-v", "--timeout=900", "--tb=short",
        f"--alluredir={RESULTS_DIR}",
        "--color=no",
    ]
    run = runs[run_id]
    run["cmd"] = " ".join(cmd[:6]) + f" ... ({len(nodes)} tests)"
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

            # parse per-test results
            m = re.search(r"::(test_\S+)\s+(PASSED|FAILED|ERROR)", line)
            if m:
                short_name = m.group(1)
                status = m.group(2)
                # find test id
                tid = None
                for t in TESTS:
                    if short_name in t["node"]:
                        tid = t["id"]
                        break
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
        run["status"] = "done"
        run["end"] = datetime.now().isoformat(timespec="seconds")
        current_run_id = None


# ── API routes ───────────────────────────────────────────────────
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

    # validate ids
    valid_ids = {t["id"] for t in TESTS}
    bad = [i for i in req.test_ids if i not in valid_ids]
    if bad:
        raise HTTPException(400, f"Unknown test IDs: {bad}")

    nodes = [t["node"] for t in TESTS if t["id"] in req.test_ids]
    run_id = uuid.uuid4().hex[:8]
    current_run_id = run_id
    runs[run_id] = {
        "status": "running", "lines": [], "results": {},
        "passed": 0, "failed": 0,
        "test_ids": req.test_ids, "process": None,
    }
    asyncio.create_task(run_pytest_task(run_id, nodes))
    return {"run_id": run_id, "count": len(nodes)}

@app.get("/api/stream/{run_id}")
async def stream_output(run_id: str):
    if run_id not in runs:
        raise HTTPException(404, "Run not found")

    async def generator():
        sent = 0
        while True:
            run = runs[run_id]
            lines = run["lines"]
            for line in lines[sent:]:
                payload = json.dumps({"line": line})
                yield f"data: {payload}\n\n"
            sent = len(lines)
            if run["status"] == "done":
                final = json.dumps({
                    "done": True,
                    "passed": run["passed"],
                    "failed": run["failed"],
                    "results": run["results"],
                    "exit_code": run.get("exit_code", -1),
                })
                yield f"data: {final}\n\n"
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})

@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    if run_id not in runs:
        raise HTTPException(404)
    r = runs[run_id]
    return {k: v for k, v in r.items() if k not in ("lines", "process")}

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

@app.post("/api/report/{run_id}")
async def generate_report(run_id: str):
    """Generate Word report from latest allure-results."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out = REPORTS_DIR / f"doublink_test_report_{today}.docx"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJ_DIR/'src'}:{env.get('PYTHONPATH','')}"
    result = subprocess.run(
        ["python3", str(REPORT_SCRIPT), str(RESULTS_DIR), str(out)],
        capture_output=True, text=True, env=env, cwd=str(PROJ_DIR)
    )
    if result.returncode != 0:
        raise HTTPException(500, result.stderr[:500])
    # copy to allure-report for download
    allure_report = PROJ_DIR / "allure-report"
    if allure_report.exists():
        import shutil
        shutil.copy(out, allure_report / out.name)
        shutil.copy(out, allure_report / "doublink_test_report_latest.docx")
    return {"ok": True, "file": out.name, "download": f"http://192.168.105.210:8888/{out.name}"}

@app.get("/api/current")
async def current_run():
    return {"run_id": current_run_id}


# ══════════════════════════════════════════════════════════════════
# HTML UI
# ══════════════════════════════════════════════════════════════════
GROUP_META = {
    "A": {"label": "Group A — 模式切換 Mode Switching", "color": "#4A90D9", "count": 10},
    "B": {"label": "Group B — 網路劣化驗證 Degradation",  "color": "#E07B39", "count": 49},
    "C": {"label": "Group C — 黃金場景 Golden Scenarios", "color": "#6BAE6A", "count": 6},
    "D": {"label": "Group D — 連結效能比較 Link Weight",  "color": "#9B6BD9", "count": 9},
}

HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doublink ATSSS Test Runner</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --card: #21253a;
    --border: #2e3349; --text: #e2e8f0; --muted: #8892b0;
    --accent: #4A90D9; --pass: #4ade80; --fail: #f87171;
    --warn: #fbbf24; --running: #60a5fa;
    --A: #4A90D9; --B: #E07B39; --C: #6BAE6A; --D: #9B6BD9;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 13px; height: 100vh; display: flex; flex-direction: column; }

  /* ── Header ── */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 10px 18px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  header h1 { font-size: 16px; font-weight: 700; color: var(--accent); }
  header .sub { font-size: 11px; color: var(--muted); }
  .badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; background: var(--card); border: 1px solid var(--border); }
  .badge.running { color: var(--running); border-color: var(--running); animation: pulse 1.5s infinite; }
  .badge.idle { color: var(--muted); }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.5; } }

  /* ── Layout ── */
  .main { display: flex; flex: 1; overflow: hidden; }

  /* ── Left panel ── */
  .left { width: 380px; min-width: 320px; display: flex; flex-direction: column; border-right: 1px solid var(--border); }
  .panel-header { background: var(--surface); padding: 10px 14px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  .panel-header .sel-count { margin-left: auto; font-size: 11px; color: var(--accent); font-weight: 600; }
  .test-list { flex: 1; overflow-y: auto; padding: 8px; }

  /* ── Group ── */
  .group-block { margin-bottom: 6px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .group-hdr { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--card); cursor: pointer; user-select: none; }
  .group-hdr:hover { background: var(--surface); }
  .group-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .group-label { font-weight: 600; font-size: 12px; flex: 1; }
  .group-cnt { font-size: 11px; color: var(--muted); }
  .group-chevron { font-size: 10px; color: var(--muted); transition: transform .2s; }
  .group-block.collapsed .group-chevron { transform: rotate(-90deg); }
  .group-block.collapsed .group-tests { display: none; }
  .group-cb { accent-color: var(--accent); width: 14px; height: 14px; cursor: pointer; }

  /* ── Test items ── */
  .group-tests { padding: 4px 8px 8px; }
  .test-item { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 5px; cursor: pointer; }
  .test-item:hover { background: var(--card); }
  .test-item.result-pass { background: rgba(74,222,128,.08); }
  .test-item.result-fail { background: rgba(248,113,113,.1); }
  .test-cb { accent-color: var(--accent); width: 13px; height: 13px; cursor: pointer; }
  .test-id { font-family: monospace; font-size: 11px; color: var(--muted); min-width: 38px; }
  .test-name { flex: 1; font-size: 12px; }
  .test-icon { font-size: 13px; }

  /* ── Toolbar ── */
  .toolbar { padding: 10px 14px; border-top: 1px solid var(--border); background: var(--surface); display: flex; gap: 8px; flex-shrink: 0; }
  .btn { padding: 7px 14px; border-radius: 6px; border: none; cursor: pointer; font-size: 12px; font-weight: 600; transition: opacity .15s; }
  .btn:hover { opacity: .85; }
  .btn:disabled { opacity: .4; cursor: not-allowed; }
  .btn-run { background: var(--accent); color: #fff; flex: 1; }
  .btn-stop { background: var(--fail); color: #fff; }
  .btn-sm { background: var(--card); color: var(--text); border: 1px solid var(--border); font-size: 11px; padding: 5px 10px; }

  /* ── Right panel ── */
  .right { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .right-tabs { display: flex; background: var(--surface); border-bottom: 1px solid var(--border); flex-shrink: 0; }
  .tab { padding: 10px 18px; cursor: pointer; font-size: 12px; font-weight: 600; color: var(--muted); border-bottom: 2px solid transparent; }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-pane { display: none; flex: 1; overflow: hidden; }
  .tab-pane.active { display: flex; flex-direction: column; }

  /* ── Terminal ── */
  #terminal { flex: 1; overflow-y: auto; padding: 12px 16px; font-family: 'Consolas', 'Monaco', monospace; font-size: 12px; line-height: 1.6; background: #0a0c10; }
  #terminal .line { white-space: pre-wrap; word-break: break-all; }
  #terminal .line.pass { color: var(--pass); }
  #terminal .line.fail { color: var(--fail); }
  #terminal .line.warn { color: var(--warn); }
  #terminal .line.info { color: var(--running); }
  #terminal .line.dim  { color: #4a5568; }

  /* ── Results pane ── */
  #results-pane { flex: 1; overflow-y: auto; padding: 16px; }
  .summary-bar { display: flex; gap: 16px; margin-bottom: 16px; }
  .summary-card { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 18px; text-align: center; }
  .summary-card .val { font-size: 28px; font-weight: 700; }
  .summary-card .lbl { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .summary-card.pass .val { color: var(--pass); }
  .summary-card.fail .val { color: var(--fail); }
  .summary-card.total .val { color: var(--accent); }
  .result-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .result-table th { background: var(--card); color: var(--muted); font-weight: 600; padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
  .result-table td { padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .result-table tr:hover td { background: var(--card); }
  .result-table tr.pass td:first-child { border-left: 3px solid var(--pass); }
  .result-table tr.fail td:first-child { border-left: 3px solid var(--fail); }
  .result-table tr.pending td { color: var(--muted); }
  .chip { padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 700; }
  .chip.A { background: rgba(74,144,217,.15); color: var(--A); }
  .chip.B { background: rgba(224,123,57,.15); color: var(--B); }
  .chip.C { background: rgba(107,174,106,.15); color: var(--C); }
  .chip.D { background: rgba(155,107,217,.15); color: var(--D); }
  .status-pass { color: var(--pass); font-weight: 700; }
  .status-fail { color: var(--fail); font-weight: 700; }
  .status-pend { color: var(--muted); }

  /* ── Report bar ── */
  .report-bar { padding: 10px 14px; border-top: 1px solid var(--border); background: var(--surface); display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
  .report-bar .msg { font-size: 11px; color: var(--muted); flex: 1; }
  .progress { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; margin-bottom: 4px; }
  .progress-bar { height: 100%; background: var(--accent); width: 0%; transition: width .3s; }
  .info-msg { font-size: 11px; padding: 6px 10px; background: var(--card); border-radius: 6px; color: var(--muted); }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>

<header>
  <h1>🔬 Doublink ATSSS Test Runner</h1>
  <span class="sub">192.168.105.210</span>
  <span class="badge idle" id="status-badge">● 閒置</span>
</header>

<div class="main">
  <!-- ══ LEFT: Test Selection ══ -->
  <div class="left">
    <div class="panel-header">
      <button class="btn btn-sm" onclick="selectAll()">全選</button>
      <button class="btn btn-sm" onclick="clearAll()">清除</button>
      <span class="sel-count" id="sel-count">已選 0 項</span>
    </div>
    <div class="test-list" id="test-list"></div>
    <div class="toolbar">
      <button class="btn btn-run" id="btn-run" onclick="startRun()">▶ 執行選取測項</button>
      <button class="btn btn-stop" id="btn-stop" onclick="stopRun()" style="display:none">■ 停止</button>
    </div>
  </div>

  <!-- ══ RIGHT: Output + Results ══ -->
  <div class="right">
    <div class="right-tabs">
      <div class="tab active" onclick="switchTab('terminal')">📟 執行輸出</div>
      <div class="tab" onclick="switchTab('results')">📊 測試結果</div>
    </div>

    <!-- Terminal tab -->
    <div class="tab-pane active" id="tab-terminal">
      <div id="terminal"><span class="line dim">等待執行...</span></div>
      <div class="report-bar">
        <div style="flex:1">
          <div class="progress"><div class="progress-bar" id="prog-bar"></div></div>
          <span class="msg" id="prog-msg">尚未執行</span>
        </div>
      </div>
    </div>

    <!-- Results tab -->
    <div class="tab-pane" id="tab-results">
      <div id="results-pane">
        <div class="summary-bar">
          <div class="summary-card total"><div class="val" id="r-total">—</div><div class="lbl">總測項</div></div>
          <div class="summary-card pass"><div class="val" id="r-pass">—</div><div class="lbl">PASS ✅</div></div>
          <div class="summary-card fail"><div class="val" id="r-fail">—</div><div class="lbl">FAIL ❌</div></div>
        </div>
        <table class="result-table">
          <thead><tr><th>Test ID</th><th>群組</th><th>測項名稱</th><th>狀態</th></tr></thead>
          <tbody id="result-tbody"></tbody>
        </table>
      </div>
      <div class="report-bar">
        <span class="msg" id="report-msg">執行完成後可生成 Word 報告</span>
        <button class="btn btn-sm" id="btn-report" onclick="generateReport()" disabled>📄 生成 Word 報告</button>
        <a id="report-link" href="#" style="display:none" class="btn btn-sm" target="_blank">⬇ 下載報告</a>
      </div>
    </div>
  </div>
</div>

<script>
const TESTS = __TESTS_JSON__;
const GROUP_META = __GROUP_META_JSON__;

let selected = new Set();
let currentRunId = null;
let runDone = false;
let lastRunId = null;

// ── Build test list ─────────────────────────────────────────────
function buildTestList() {
  const container = document.getElementById('test-list');
  const groups = {};
  TESTS.forEach(t => {
    if (!groups[t.group]) groups[t.group] = [];
    groups[t.group].push(t);
  });

  Object.keys(groups).sort().forEach(g => {
    const meta = GROUP_META[g];
    const block = document.createElement('div');
    block.className = 'group-block';
    block.id = `grp-${g}`;

    const hdr = document.createElement('div');
    hdr.className = 'group-hdr';
    hdr.innerHTML = `
      <input type="checkbox" class="group-cb" id="gcb-${g}" onclick="toggleGroup('${g}',this.checked)">
      <span class="group-dot" style="background:var(--${g})"></span>
      <span class="group-label">${meta.label}</span>
      <span class="group-cnt">${groups[g].length} 項</span>
      <span class="group-chevron">▼</span>`;
    hdr.addEventListener('click', e => {
      if (e.target.type === 'checkbox') return;
      block.classList.toggle('collapsed');
    });

    const items = document.createElement('div');
    items.className = 'group-tests';
    groups[g].forEach(t => {
      const row = document.createElement('div');
      row.className = 'test-item';
      row.id = `item-${t.id}`;
      row.innerHTML = `
        <input type="checkbox" class="test-cb" id="cb-${t.id}" onchange="toggleTest('${t.id}',this.checked)">
        <span class="test-id">${t.id}</span>
        <span class="test-name">${t.name}</span>
        <span class="test-icon" id="icon-${t.id}"></span>`;
      row.addEventListener('click', e => {
        if (e.target.type === 'checkbox') return;
        const cb = document.getElementById(`cb-${t.id}`);
        cb.checked = !cb.checked;
        toggleTest(t.id, cb.checked);
      });
      items.appendChild(row);
    });

    block.appendChild(hdr);
    block.appendChild(items);
    container.appendChild(block);
  });
  updateSelCount();
}

function toggleTest(id, checked) {
  if (checked) selected.add(id); else selected.delete(id);
  updateGroupCb(TESTS.find(t=>t.id===id).group);
  updateSelCount();
}

function toggleGroup(g, checked) {
  TESTS.filter(t=>t.group===g).forEach(t => {
    selected[checked?'add':'delete'](t.id);
    const cb = document.getElementById(`cb-${t.id}`);
    if (cb) cb.checked = checked;
  });
  updateSelCount();
}

function updateGroupCb(g) {
  const groupTests = TESTS.filter(t=>t.group===g);
  const selCount = groupTests.filter(t=>selected.has(t.id)).length;
  const cb = document.getElementById(`gcb-${g}`);
  if (!cb) return;
  cb.indeterminate = selCount > 0 && selCount < groupTests.length;
  cb.checked = selCount === groupTests.length;
}

function selectAll() {
  TESTS.forEach(t => { selected.add(t.id); const cb=document.getElementById(`cb-${t.id}`); if(cb) cb.checked=true; });
  ['A','B','C','D'].forEach(g => updateGroupCb(g));
  updateSelCount();
}
function clearAll() {
  TESTS.forEach(t => { selected.delete(t.id); const cb=document.getElementById(`cb-${t.id}`); if(cb) cb.checked=false; });
  ['A','B','C','D'].forEach(g => updateGroupCb(g));
  updateSelCount();
}
function updateSelCount() {
  const n = selected.size;
  document.getElementById('sel-count').textContent = `已選 ${n} 項`;
  document.getElementById('btn-run').textContent = `▶ 執行選取測項 (${n})`;
  document.getElementById('btn-run').disabled = n === 0;
}

// ── Run ─────────────────────────────────────────────────────────
async function startRun() {
  if (selected.size === 0) return;
  const ids = [...selected];

  // clear terminal
  const term = document.getElementById('terminal');
  term.innerHTML = '';
  runDone = false;

  // init result table
  initResultTable(ids);

  // update UI
  setRunning(true);

  const res = await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({test_ids: ids})
  });
  if (!res.ok) {
    const err = await res.json();
    appendLine(`[ERROR] ${err.detail}`, 'fail');
    setRunning(false);
    return;
  }
  const {run_id, count} = await res.json();
  currentRunId = run_id;
  lastRunId = run_id;
  appendLine(`▶ 開始執行 ${count} 個測項 (run: ${run_id})`, 'info');

  // stream
  const sse = new EventSource(`/api/stream/${run_id}`);
  sse.onmessage = e => {
    const data = JSON.parse(e.data);
    if (data.done) {
      sse.close();
      onRunDone(data);
    } else if (data.line !== undefined) {
      const line = data.line;
      let cls = '';
      if (/PASSED/.test(line)) cls = 'pass';
      else if (/FAILED|ERROR/.test(line)) cls = 'fail';
      else if (/WARNING|warn/.test(line)) cls = 'warn';
      else if (/^\s*={3,}/.test(line)) cls = 'info';
      else if (/^\s*$/.test(line)) cls = 'dim';
      appendLine(line, cls);

      // update result icons live
      const m = line.match(/::(test_\S+)\s+(PASSED|FAILED|ERROR)/);
      if (m) {
        const name = m[1], status = m[2];
        const t = TESTS.find(t => t.node.includes(name));
        if (t) updateResultIcon(t.id, status);
      }
    }
  };
  sse.onerror = () => { sse.close(); setRunning(false); };
}

function onRunDone(data) {
  runDone = true;
  setRunning(false);
  const total = data.passed + data.failed;
  document.getElementById('r-total').textContent = total;
  document.getElementById('r-pass').textContent = data.passed;
  document.getElementById('r-fail').textContent = data.failed;
  document.getElementById('prog-bar').style.width = '100%';
  document.getElementById('prog-bar').style.background = data.failed > 0 ? 'var(--fail)' : 'var(--pass)';
  const msg = data.exit_code === 0
    ? `✅ 全部通過 ${data.passed}/${total}`
    : `❌ ${data.failed} 項失敗，${data.passed} 項通過，共 ${total} 項`;
  document.getElementById('prog-msg').textContent = msg;
  document.getElementById('btn-report').disabled = false;

  // update remaining pending rows
  Object.entries(data.results).forEach(([tid, st]) => updateResultIcon(tid, st));

  appendLine('', '');
  appendLine(`═══════ 執行完成：${data.passed} PASSED  ${data.failed} FAILED ═══════`, data.failed>0?'fail':'pass');
  switchTab('results');
}

async function stopRun() {
  if (!currentRunId) return;
  await fetch(`/api/stop/${currentRunId}`, {method:'POST'});
  setRunning(false);
  appendLine('[STOPPED]', 'warn');
}

// ── Result table ─────────────────────────────────────────────────
function initResultTable(ids) {
  const tbody = document.getElementById('result-tbody');
  tbody.innerHTML = '';
  document.getElementById('r-total').textContent = ids.length;
  document.getElementById('r-pass').textContent = '0';
  document.getElementById('r-fail').textContent = '0';
  ids.forEach(id => {
    const t = TESTS.find(t=>t.id===id);
    if (!t) return;
    const tr = document.createElement('tr');
    tr.id = `row-${id}`;
    tr.className = 'pending';
    tr.innerHTML = `
      <td><b>${id}</b></td>
      <td><span class="chip ${t.group}">${t.group}</span></td>
      <td>${t.name}</td>
      <td class="status-pend" id="st-${id}">— 等待中</td>`;
    tbody.appendChild(tr);
  });
  document.getElementById('report-link').style.display = 'none';
  document.getElementById('btn-report').disabled = true;
}

let passCount = 0, failCount = 0;
function updateResultIcon(tid, status) {
  const icon = document.getElementById(`icon-${tid}`);
  const stCell = document.getElementById(`st-${tid}`);
  const row = document.getElementById(`row-${tid}`);
  const item = document.getElementById(`item-${tid}`);
  if (!icon && !stCell) return;

  if (status === 'PASSED') {
    if (icon) icon.textContent = '✅';
    if (stCell) { stCell.textContent = '✅ PASSED'; stCell.className = 'status-pass'; }
    if (row) row.className = 'pass';
    if (item) item.className = 'test-item result-pass';
  } else {
    if (icon) icon.textContent = '❌';
    if (stCell) { stCell.textContent = '❌ FAILED'; stCell.className = 'status-fail'; }
    if (row) row.className = 'fail';
    if (item) item.className = 'test-item result-fail';
  }

  // update progress
  const sel = selected.size;
  const done = document.querySelectorAll('#result-tbody tr:not(.pending)').length;
  if (sel > 0) {
    document.getElementById('prog-bar').style.width = `${(done/sel*100).toFixed(0)}%`;
    document.getElementById('prog-msg').textContent = `執行中：${done}/${sel}`;
  }
}

// ── Generate Report ──────────────────────────────────────────────
async function generateReport() {
  if (!lastRunId) return;
  document.getElementById('btn-report').disabled = true;
  document.getElementById('report-msg').textContent = '⏳ 生成報告中...';
  const res = await fetch(`/api/report/${lastRunId}`, {method:'POST'});
  if (res.ok) {
    const data = await res.json();
    document.getElementById('report-msg').textContent = `✅ 報告已生成：${data.file}`;
    const link = document.getElementById('report-link');
    link.href = data.download;
    link.textContent = `⬇ 下載 ${data.file}`;
    link.style.display = 'inline-block';
  } else {
    document.getElementById('report-msg').textContent = '❌ 報告生成失敗';
  }
  document.getElementById('btn-report').disabled = false;
}

// ── UI helpers ───────────────────────────────────────────────────
function appendLine(text, cls) {
  const term = document.getElementById('terminal');
  const span = document.createElement('div');
  span.className = `line ${cls}`;
  span.textContent = text;
  term.appendChild(span);
  term.scrollTop = term.scrollHeight;
}

function setRunning(running) {
  const badge = document.getElementById('status-badge');
  const btnRun = document.getElementById('btn-run');
  const btnStop = document.getElementById('btn-stop');
  if (running) {
    badge.textContent = '● 執行中'; badge.className = 'badge running';
    btnRun.style.display = 'none'; btnStop.style.display = 'block';
  } else {
    badge.textContent = '● 閒置'; badge.className = 'badge idle';
    btnRun.style.display = 'block'; btnStop.style.display = 'none';
    currentRunId = null;
  }
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    const panes = ['terminal','results'];
    t.classList.toggle('active', panes[i] === name);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${name}`);
  });
}

// ── Init ─────────────────────────────────────────────────────────
buildTestList();
updateSelCount();
</script>
</body>
</html>"""


def build_html() -> str:
    tests_json = json.dumps(TESTS, ensure_ascii=False)
    group_meta_json = json.dumps(GROUP_META, ensure_ascii=False)
    return (HTML
            .replace("__TESTS_JSON__", tests_json)
            .replace("__GROUP_META_JSON__", group_meta_json))


GROUP_META = {
    "A": {"label": "Group A — 模式切換 Mode Switching", "color": "#4A90D9", "count": 10},
    "B": {"label": "Group B — 網路劣化驗證 Degradation",  "color": "#E07B39", "count": 49},
    "C": {"label": "Group C — 黃金場景 Golden Scenarios", "color": "#6BAE6A", "count": 6},
    "D": {"label": "Group D — 連結效能比較 Link Weight",  "color": "#9B6BD9", "count": 9},
}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(build_html())


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9080
    print(f"\n  Doublink Test Runner UI")
    print(f"  http://192.168.105.210:{port}/\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
