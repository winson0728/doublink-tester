"""FastAPI application factory for the Doublink Tester Control API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from doublink_tester.api.dependencies import init_clients, shutdown_clients
from doublink_tester.api.routers import health, profiles, modes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_clients()
    yield
    await shutdown_clients()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Doublink Tester Control API",
        description="REST API for controlling multilink tests, network profiles, and modes",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
    app.include_router(modes.router, prefix="/modes", tags=["modes"])

    return app
