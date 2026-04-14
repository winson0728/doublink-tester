"""Async client for the Multilink Server API.

Endpoints:
  GET  /api/v1/agents/{agent_id}/mode  — get current mode
  PUT  /api/v1/agents/{agent_id}/mode  — set mode  {"mode": int}

Mode values:
  0 = real-time
  3 = bonding
  4 = duplicate
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Mapping from mode name → numeric API value
MODE_NAME_TO_VALUE: dict[str, int] = {
    "real_time": 0,
    "bonding": 3,
    "duplicate": 4,
}

# Reverse mapping
MODE_VALUE_TO_NAME: dict[int, str] = {v: k for k, v in MODE_NAME_TO_VALUE.items()}


class MultilinkClient:
    """Async HTTP client for the Multilink Server control API.

    API base: http://192.168.101.100:30008
    Agent ID: obtained from config or passed per-call.
    """

    def __init__(
        self,
        base_url: str = "http://192.168.101.100:30008",
        agent_id: str = "100000018",
        timeout: float = 15.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> MultilinkClient:
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http:
            try:
                await self._http.aclose()
            except RuntimeError:
                pass  # event loop already closed during session teardown
            self._http = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("MultilinkClient must be used as an async context manager")
        return self._http

    def _agent_mode_url(self, agent_id: str | None = None) -> str:
        aid = agent_id or self._agent_id
        return f"/api/v1/agents/{aid}/mode"

    # ── Mode Control ────────────────────────────────────────────

    async def get_current_mode(self, agent_id: str | None = None) -> dict[str, Any]:
        """Return the current multilink operating mode.

        Returns:
            {"mode": int, "mode_name": str, "agent_id": str, "raw": dict}
        """
        url = self._agent_mode_url(agent_id)
        resp = await self._client.get(url, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        mode_val = data.get("mode", data) if isinstance(data, dict) else data
        if isinstance(mode_val, dict):
            mode_val = mode_val.get("mode", -1)
        return {
            "mode": mode_val,
            "mode_name": MODE_VALUE_TO_NAME.get(mode_val, f"unknown({mode_val})"),
            "agent_id": agent_id or self._agent_id,
            "raw": data,
        }

    async def set_mode(
        self, mode: str | int, params: dict[str, Any] | None = None, agent_id: str | None = None
    ) -> dict[str, Any]:
        """Switch the multilink operating mode.

        Args:
            mode: Mode name (e.g. "bonding") or numeric value (e.g. 3).
            params: Unused for now, kept for interface compatibility.
            agent_id: Override the default agent ID.

        Returns:
            {"mode": int, "mode_name": str, "agent_id": str, "raw": dict}
        """
        # Resolve mode to numeric value
        if isinstance(mode, str):
            mode_val = MODE_NAME_TO_VALUE.get(mode)
            if mode_val is None:
                raise ValueError(
                    f"Unknown mode name: {mode!r}. Available: {list(MODE_NAME_TO_VALUE.keys())}"
                )
        else:
            mode_val = int(mode)

        url = self._agent_mode_url(agent_id)
        resp = await self._client.put(
            url,
            json={"mode": mode_val},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        logger.info("Mode set to %d (%s) for agent %s", mode_val, MODE_VALUE_TO_NAME.get(mode_val, "unknown"), agent_id or self._agent_id)
        return {
            "mode": mode_val,
            "mode_name": MODE_VALUE_TO_NAME.get(mode_val, f"unknown({mode_val})"),
            "agent_id": agent_id or self._agent_id,
            "switched": True,
            "raw": data,
        }

    async def list_modes(self) -> list[dict[str, Any]]:
        """Return all supported multilink modes (static list)."""
        return [
            {"mode": v, "name": k, "description": desc}
            for k, v, desc in [
                ("real_time", 0, "Real-time mode — lowest latency, single best path"),
                ("bonding", 3, "Bonding mode — aggregate bandwidth across links"),
                ("duplicate", 4, "Duplicate mode — send packets on all links for redundancy"),
            ]
        ]

    # ── Link Status (via mode query) ────────────────────────────

    async def get_link_status(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Return agent mode info as link status proxy."""
        mode_info = await self.get_current_mode(agent_id)
        return [mode_info]

    async def get_statistics(self, agent_id: str | None = None) -> dict[str, Any]:
        """Return current mode as statistics."""
        return await self.get_current_mode(agent_id)
