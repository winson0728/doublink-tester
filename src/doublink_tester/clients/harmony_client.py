"""Async client for the Harmony 5G management API."""

from __future__ import annotations

from typing import Any

import httpx


class HarmonyClient:
    """Async HTTP client for the Harmony 5G API at /api/v1."""

    def __init__(
        self,
        base_url: str = "https://10.22.101.191/api/v1",
        api_key: str = "",
        timeout: float = 10.0,
        verify_ssl: bool = False,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HarmonyClient:
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            verify=self._verify_ssl,
            headers={
                "X-API-KEY": self._api_key,
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("HarmonyClient must be used as an async context manager")
        return self._http

    async def get_active_client_count(self, range_hours: int = 24) -> dict[str, Any]:
        resp = await self._client.get(f"/usage/clients/active/count?range={range_hours}")
        resp.raise_for_status()
        return resp.json()

    async def get_5g_subscribers(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/mgmt/5gc/clients/5G")
        resp.raise_for_status()
        return resp.json()

    async def get_subscriber_details(self, imsi: str) -> dict[str, Any]:
        resp = await self._client.get(f"/nb/cht/subscriber/{imsi}")
        resp.raise_for_status()
        return resp.json()

    async def get_system_alarms(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/nb/cht/alarm")
        resp.raise_for_status()
        return resp.json()

    async def get_nf_status(self) -> dict[str, Any]:
        resp = await self._client.get("/nb/cht/nf/status")
        resp.raise_for_status()
        return resp.json()

    async def get_gnb_statistics(self, range_hours: int = 24) -> dict[str, Any]:
        resp = await self._client.get(f"/usage/gnbs?range={range_hours}")
        resp.raise_for_status()
        return resp.json()
