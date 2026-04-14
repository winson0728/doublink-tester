"""Grafana annotation API client — marks events on dashboards."""

from __future__ import annotations

import time
from typing import Any

import httpx


class GrafanaAnnotator:
    """Create annotations on Grafana dashboards for test events."""

    def __init__(self, grafana_url: str, api_key: str):
        self._url = grafana_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def create_annotation(
        self,
        text: str,
        tags: list[str] | None = None,
        time_ms: int | None = None,
        time_end_ms: int | None = None,
        dashboard_uid: str | None = None,
        panel_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a Grafana annotation."""
        payload: dict[str, Any] = {
            "text": text,
            "tags": tags or [],
            "time": time_ms or int(time.time() * 1000),
        }
        if time_end_ms:
            payload["timeEnd"] = time_end_ms
        if dashboard_uid:
            payload["dashboardUID"] = dashboard_uid
        if panel_id:
            payload["panelId"] = panel_id

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._url}/api/annotations", json=payload, headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    async def annotate_test_start(self, test_name: str, params: dict[str, Any]) -> int:
        """Annotate the start of a test run."""
        result = await self.create_annotation(
            text=f"Test START: {test_name}\nParams: {params}",
            tags=["test", "start", test_name],
        )
        return result.get("id", 0)

    async def annotate_test_end(self, annotation_id: int, verdict: str) -> None:
        """Update annotation with test end time and verdict."""
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{self._url}/api/annotations/{annotation_id}",
                json={"timeEnd": int(time.time() * 1000), "text": f"Verdict: {verdict}", "tags": ["test", "end", verdict]},
                headers=self._headers,
            )
            resp.raise_for_status()

    async def annotate_mode_switch(self, from_mode: str, to_mode: str) -> int:
        """Annotate a multilink mode switch event."""
        result = await self.create_annotation(
            text=f"Mode switch: {from_mode} → {to_mode}",
            tags=["mode_switch", from_mode, to_mode],
        )
        return result.get("id", 0)

    async def annotate_degradation(self, profile_name: str, interface: str) -> int:
        """Annotate a network degradation event."""
        result = await self.create_annotation(
            text=f"Degradation applied: {profile_name} on {interface}",
            tags=["degradation", profile_name, interface],
        )
        return result.get("id", 0)
