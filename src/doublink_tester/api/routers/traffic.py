"""Traffic control router — start/stop iperf3 tests and retrieve results."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from doublink_tester.api.dependencies import get_settings
from doublink_tester.traffic.iperf3 import Iperf3Generator
from doublink_tester.traffic.factory import from_profile
from doublink_tester.config import load_traffic_profiles
from doublink_tester.models import TrafficResult

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory store for running/completed jobs
_jobs: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task] = {}


# ── Schemas ──────────────────────────────────────────────────

class Iperf3Request(BaseModel):
    server: str | None = None
    port: int = 5201
    protocol: str = "tcp"
    duration_s: int = 10
    bandwidth: str | None = None
    parallel: int = 1
    reverse: bool = False


class ProfileRunRequest(BaseModel):
    profile_id: str
    server: str | None = None


class TrafficJobResponse(BaseModel):
    job_id: str
    status: str
    generator: str = ""
    protocol: str = ""


class TrafficResultResponse(BaseModel):
    job_id: str
    status: str
    generator: str = ""
    protocol: str = ""
    throughput_mbps: float = 0.0
    loss_pct: float = 0.0
    latency_avg_ms: float = 0.0
    jitter_ms: float = 0.0
    success_rate: float = 1.0
    duration_s: float = 0.0
    error: str = ""


# ── Helpers ──────────────────────────────────────────────────

def _result_to_response(job_id: str, job: dict[str, Any]) -> TrafficResultResponse:
    result: TrafficResult | None = job.get("result")
    if result is None:
        return TrafficResultResponse(
            job_id=job_id,
            status=job["status"],
            generator=job.get("generator", ""),
            protocol=job.get("protocol", ""),
            error=job.get("error", ""),
        )
    return TrafficResultResponse(
        job_id=job_id,
        status=job["status"],
        generator=result.generator,
        protocol=result.protocol,
        throughput_mbps=result.throughput_mbps,
        loss_pct=result.loss_pct,
        latency_avg_ms=result.latency_avg_ms,
        jitter_ms=result.jitter_ms,
        success_rate=result.success_rate,
        duration_s=result.ended_at - result.started_at if result.ended_at else 0,
    )


async def _run_job(job_id: str, gen: Any, target: str, duration_s: int, **kwargs: Any) -> None:
    try:
        result = await gen.run(target=target, duration_s=duration_s, **kwargs)
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["result"] = result
    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
        logger.exception("Traffic job %s failed", job_id)


# ── Endpoints ────────────────────────────────────────────────

@router.get("/profiles")
async def list_traffic_profiles():
    """List available traffic profiles."""
    profiles = load_traffic_profiles()
    return [
        {"id": p.id, "generator": p.generator, "protocol": p.protocol, "duration_s": p.duration_s}
        for p in profiles
    ]


@router.post("/iperf3", response_model=TrafficJobResponse)
async def start_iperf3(req: Iperf3Request):
    """Start an iperf3 traffic test (runs in background, poll for result)."""
    settings = get_settings()
    host = req.server or settings.iperf3_server
    target = f"{host}:{req.port}"

    job_id = str(uuid.uuid4())[:8]
    gen = Iperf3Generator(server_host=host, server_port=req.port)
    _jobs[job_id] = {"status": "running", "generator": "iperf3", "protocol": req.protocol}

    task = asyncio.create_task(
        _run_job(
            job_id, gen, target, req.duration_s,
            protocol=req.protocol, bandwidth=req.bandwidth,
            parallel=req.parallel, reverse=req.reverse,
        )
    )
    _tasks[job_id] = task

    return TrafficJobResponse(job_id=job_id, status="running", generator="iperf3", protocol=req.protocol)


@router.post("/run", response_model=TrafficJobResponse)
async def start_profile_run(req: ProfileRunRequest):
    """Start a traffic test from a named profile (runs in background)."""
    settings = get_settings()
    profiles = {p.id: p for p in load_traffic_profiles()}
    profile = profiles.get(req.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {req.profile_id!r} not found")

    gen = from_profile(profile)
    if profile.generator == "iperf3":
        host = req.server or settings.iperf3_server
        target = f"{host}:5201"
    else:
        host = req.server or settings.test_server
        target = host

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "running", "generator": profile.generator, "protocol": profile.protocol}

    task = asyncio.create_task(
        _run_job(job_id, gen, target, profile.duration_s, **profile.parameters)
    )
    _tasks[job_id] = task

    return TrafficJobResponse(job_id=job_id, status="running", generator=profile.generator, protocol=profile.protocol)


@router.get("/jobs/{job_id}", response_model=TrafficResultResponse)
async def get_job_result(job_id: str):
    """Get the status/result of a traffic job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return _result_to_response(job_id, job)


@router.get("/jobs")
async def list_jobs():
    """List all traffic jobs."""
    return [
        {"job_id": jid, "status": j["status"], "generator": j.get("generator", ""), "protocol": j.get("protocol", "")}
        for jid, j in _jobs.items()
    ]


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running traffic job."""
    task = _tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        _jobs[job_id]["status"] = "cancelled"
        return {"job_id": job_id, "cancelled": True}
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return {"job_id": job_id, "cancelled": False, "status": job["status"]}
