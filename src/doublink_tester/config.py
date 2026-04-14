"""Configuration loader — reads YAML config and returns Pydantic-validated settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from doublink_tester.models import (
    DisconnectScheduleConfig,
    MultilinkModeConfig,
    NetworkConditionProfile,
    TrafficProfile,
    VariationConfig,
)

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} placeholders with environment variable values."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_key = value[2:-1]
        return os.environ.get(env_key, value)
    return value


class TimeoutSettings(BaseModel):
    traffic_start_s: int = 10
    mode_switch_s: int = 15
    network_settle_s: int = 5
    metric_sample_interval_s: float = 2.0


class InterfaceSettings(BaseModel):
    primary: str = "eth0"
    secondary: str = "eth1"


class DoublinkSettings(BaseModel):
    netemu_url: str = "http://192.168.105.115:8080"
    multilink_url: str = "http://192.168.101.100:30008"
    multilink_agent_id: str = "100000018"
    test_server: str = "192.168.105.103"
    iperf3_server: str = "192.168.101.101"
    harmony_url: str = "https://10.22.101.191/api/v1"
    harmony_api_key: str = ""
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3000"
    grafana_api_key: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8090, ge=1, le=65535)
    results_dir: str = "./allure-results"
    interfaces: InterfaceSettings = InterfaceSettings()
    timeouts: TimeoutSettings = TimeoutSettings()


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: str | Path | None = None) -> DoublinkSettings:
    """Load global settings from config/settings.yaml."""
    config_path = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
    data = _load_yaml(config_path / "settings.yaml")
    raw = data.get("doublink", {})

    # Resolve environment variable placeholders in string values
    for key, value in raw.items():
        if isinstance(value, str):
            raw[key] = _resolve_env_vars(value)

    return DoublinkSettings(**raw)


def _parse_variation(raw: dict[str, Any] | None) -> VariationConfig | None:
    if raw is None:
        return None
    return VariationConfig(**raw)


def _parse_disconnect_schedule(raw: dict[str, Any] | None) -> DisconnectScheduleConfig | None:
    if raw is None:
        return None
    return DisconnectScheduleConfig(**raw)


def load_network_profiles(config_dir: str | Path | None = None) -> list[NetworkConditionProfile]:
    """Load network condition profiles from config/profiles/network_conditions.yaml."""
    config_path = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
    data = _load_yaml(config_path / "profiles" / "network_conditions.yaml")
    profiles = []
    for entry in data.get("profiles", []):
        variation = _parse_variation(entry.pop("variation", None))
        disconnect = _parse_disconnect_schedule(entry.pop("disconnect_schedule", None))
        profiles.append(NetworkConditionProfile(**entry, variation=variation, disconnect_schedule=disconnect))
    return profiles


def load_multilink_modes(config_dir: str | Path | None = None) -> list[MultilinkModeConfig]:
    """Load multilink mode configurations from config/profiles/multilink_modes.yaml."""
    config_path = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
    data = _load_yaml(config_path / "profiles" / "multilink_modes.yaml")
    return [MultilinkModeConfig(**entry) for entry in data.get("modes", [])]


def load_traffic_profiles(config_dir: str | Path | None = None) -> list[TrafficProfile]:
    """Load traffic generation profiles from config/profiles/traffic_profiles.yaml."""
    config_path = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
    data = _load_yaml(config_path / "profiles" / "traffic_profiles.yaml")
    return [TrafficProfile(**entry) for entry in data.get("profiles", [])]


def load_test_matrix(matrix_name: str, config_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Load a test parameter matrix from config/test_matrices/{matrix_name}.yaml."""
    config_path = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
    data = _load_yaml(config_path / "test_matrices" / f"{matrix_name}.yaml")
    return data.get("matrix", [])
