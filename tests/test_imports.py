"""Verify every module can be imported without errors.

Catches missing dependencies, syntax errors, and broken top-level code.
"""

import importlib

import pytest

MODULES = [
    "agent.main",
    "agent.wallet_tracker",
    "agent.token_intel",
    "agent.execution",
    "agent.exit_manager",
    "agent.ct_motion",
    "agent.crawlers",
    "agent.learning",
    "agent.alerts",
    "agent.health",
    "agent.cli",
    "config.settings",
    "db",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_import(module_name: str):
    mod = importlib.import_module(module_name)
    assert mod is not None
