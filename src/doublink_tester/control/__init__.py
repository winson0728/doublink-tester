"""Closed-loop control for Doublink multilink — AI-assisted automatic mode switching."""

from doublink_tester.control.auto_mode_controller import (
    AutoModeController,
    ControllerConfig,
    LinkFeatures,
    ModeDecision,
)

__all__ = [
    "AutoModeController",
    "ControllerConfig",
    "LinkFeatures",
    "ModeDecision",
]
