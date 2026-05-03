"""Validate config.settings behaviour under different env configurations.

Uses importlib.reload() because settings are module-level constants.
"""

import importlib
import os

import pytest


def _reload_settings(monkeypatch, env_overrides: dict):
    base = {
        "HELIUS_API_KEY": "test_key",
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
        "TELEGRAM_CHAT_ID": "999999",
        "DRY_RUN": "true",
    }
    base.update(env_overrides)

    for k in list(os.environ):
        if k in (
            "ENCRYPTION_KEY", "TRADER_WALLET_KEY",
            "TRADER_WALLET_PRIVATE_KEY", "REQUIRE_TRADING_WALLET",
        ):
            monkeypatch.delenv(k, raising=False)

    for k, v in base.items():
        monkeypatch.setenv(k, v)

    import config.settings as mod
    importlib.reload(mod)
    return mod


def test_dry_run_allows_no_wallet(monkeypatch):
    settings = _reload_settings(monkeypatch, {"DRY_RUN": "true"})
    assert settings.DRY_RUN is True
    settings.validate()


def test_live_requires_wallet(monkeypatch):
    settings = _reload_settings(monkeypatch, {"DRY_RUN": "false"})
    assert settings.DRY_RUN is False
    with pytest.raises(ValueError, match="wallet"):
        settings.validate()


def test_min_apes_below_range(monkeypatch):
    settings = _reload_settings(monkeypatch, {"MIN_APES": "1"})
    with pytest.raises(ValueError, match="MIN_APES"):
        settings.validate()


def test_min_apes_above_range(monkeypatch):
    settings = _reload_settings(monkeypatch, {"MIN_APES": "6"})
    with pytest.raises(ValueError, match="MIN_APES"):
        settings.validate()


def test_min_apes_valid(monkeypatch):
    for val in ("2", "3", "4", "5"):
        settings = _reload_settings(monkeypatch, {"MIN_APES": val})
        settings.validate()
