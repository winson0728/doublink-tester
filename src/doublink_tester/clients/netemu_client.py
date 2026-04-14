"""Async client for the Network Emulator (NetEmu) API.

Wraps all endpoints at http://<host>:8080/api/* using httpx.
Mirrors the models in netemu/backend/core/models.py.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
import websockets

from doublink_tester.models import RuleCreateParams


class NetEmuClient:
    """Async HTTP client for the NetEmu API."""

    def __init__(self, base_url: str = "http://192.168.105.115:8080", timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> NetEmuClient:
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("NetEmuClient must be used as an async context manager")
        return self._http

    # ── Interfaces ──────────────────────────────────────────────

    async def list_interfaces(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/api/interfaces")
        resp.raise_for_status()
        return resp.json()

    async def get_interface_stats(self, name: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/interfaces/{name}/stats")
        resp.raise_for_status()
        return resp.json()

    # ── Rules ───────────────────────────────────────────────────

    async def list_rules(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/api/rules")
        resp.raise_for_status()
        return resp.json()

    async def get_rule(self, rule_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/rules/{rule_id}")
        resp.raise_for_status()
        return resp.json()

    async def create_rule(self, params: RuleCreateParams) -> dict[str, Any]:
        resp = await self._client.post("/api/rules", json=params.to_dict())
        resp.raise_for_status()
        return resp.json()

    async def update_rule(self, rule_id: str, params: RuleCreateParams) -> dict[str, Any]:
        payload = params.to_dict()
        payload["id"] = rule_id
        resp = await self._client.post("/api/rules", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def clear_rule(self, rule_id: str) -> dict[str, Any]:
        resp = await self._client.post(f"/api/rules/{rule_id}/clear")
        resp.raise_for_status()
        return resp.json()

    async def delete_rule(self, rule_id: str) -> dict[str, Any]:
        resp = await self._client.delete(f"/api/rules/{rule_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Profiles ────────────────────────────────────────────────

    async def list_profiles(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/api/profiles")
        resp.raise_for_status()
        return resp.json()

    async def get_profile(self, profile_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/profiles/{profile_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Disconnect ──────────────────────────────────────────────

    async def disconnect(self, interface: str) -> dict[str, Any]:
        resp = await self._client.post("/api/rules/disconnect", json={"interface": interface, "disconnect": True})
        resp.raise_for_status()
        return resp.json()

    async def reconnect(self, interface: str) -> dict[str, Any]:
        resp = await self._client.post("/api/rules/disconnect", json={"interface": interface, "disconnect": False})
        resp.raise_for_status()
        return resp.json()

    async def schedule_disconnect(self, interface: str, duration_s: float = 5.0) -> dict[str, Any]:
        resp = await self._client.post(
            "/api/schedule/disconnect", json={"interface": interface, "duration_s": duration_s}
        )
        resp.raise_for_status()
        return resp.json()

    # ── Bridge ──────────────────────────────────────────────────

    async def get_bridge(self) -> dict[str, Any]:
        resp = await self._client.get("/api/rules/bridge")
        resp.raise_for_status()
        return resp.json()

    async def set_bridge(self, lines: list[tuple[str, str]]) -> dict[str, Any]:
        payload = {"lines": [{"uplink": up, "downlink": down} for up, down in lines]}
        resp = await self._client.post("/api/rules/bridge", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Convenience ─────────────────────────────────────────────

    async def apply_profile(
        self,
        profile_id: str,
        interface: str,
        direction: str = "egress",
    ) -> dict[str, Any]:
        """Fetch a NetEmu profile and create a rule from its parameters."""
        profile = await self.get_profile(profile_id)
        params = RuleCreateParams(
            interface=interface,
            label=f"profile:{profile_id}",
            direction=direction,
            bandwidth_kbit=profile.get("bandwidth_kbit", 0),
            delay_ms=profile.get("delay_ms", 0),
            jitter_ms=profile.get("jitter_ms", 0),
            loss_pct=profile.get("loss_pct", 0),
            corrupt_pct=profile.get("corrupt_pct", 0),
            duplicate_pct=profile.get("duplicate_pct", 0),
            disorder_pct=profile.get("disorder_pct", 0),
        )
        return await self.create_rule(params)

    # ── WebSocket Stats ─────────────────────────────────────────

    async def stream_stats(self) -> AsyncIterator[dict[str, Any]]:
        """Connect to the WebSocket stats endpoint and yield parsed messages."""
        ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        async for ws in websockets.connect(f"{ws_url}/ws/stats"):
            try:
                async for raw in ws:
                    yield json.loads(raw)
            except websockets.ConnectionClosed:
                break
