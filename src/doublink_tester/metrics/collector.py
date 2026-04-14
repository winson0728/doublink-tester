"""Prometheus metric query and push client."""

from __future__ import annotations

from typing import Any

import httpx


class PrometheusCollector:
    """Query Prometheus and push metrics via Pushgateway."""

    def __init__(self, prometheus_url: str, pushgateway_url: str | None = None):
        self._prometheus_url = prometheus_url.rstrip("/")
        self._pushgateway_url = pushgateway_url.rstrip("/") if pushgateway_url else None

    async def query_instant(self, promql: str) -> list[dict[str, Any]]:
        """Execute an instant PromQL query."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._prometheus_url}/api/v1/query", params={"query": promql})
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])

    async def query_range(
        self, promql: str, start: float, end: float, step: str = "5s"
    ) -> list[dict[str, Any]]:
        """Execute a range PromQL query."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._prometheus_url}/api/v1/query_range",
                params={"query": promql, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])

    async def push_metric(
        self, job: str, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Push a metric to Pushgateway."""
        if not self._pushgateway_url:
            return
        label_str = "\n".join(f'{k}="{v}"' for k, v in (labels or {}).items())
        body = f"# TYPE {name} gauge\n{name}{{{label_str}}} {value}\n"
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._pushgateway_url}/metrics/job/{job}", content=body)
            resp.raise_for_status()
