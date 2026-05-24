# -*- coding: utf-8 -*-
"""Tests for ExtensionService singleton lifecycle."""

from __future__ import annotations

from types import SimpleNamespace

from src.extensions.service import get_extension_service, reset_extension_service


def _config(**overrides):
    payload = {
        "extensions_enabled": True,
        "extensions_autoload_builtin": True,
        "extensions_alphasift_enabled": False,
        "max_action_call_depth": 3,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_extension_service_reuses_runtime_until_config_signature_changes():
    reset_extension_service()
    first = get_extension_service(_config())
    second = get_extension_service(_config())
    changed = get_extension_service(_config(extensions_alphasift_enabled=True))

    assert second is first
    assert changed is not first

    reset_extension_service()


def test_extension_service_enabled_action_view_hides_disabled_plugins_and_internal_actions():
    reset_extension_service()
    disabled = get_extension_service(_config(extensions_alphasift_enabled=False))

    assert disabled.list_actions(enabled_only=True, include_internal=False) == []
    assert disabled.catalog.get("dsa.analyze_stock") is not None
    assert disabled.get_plugin("alphasift") is not None
    assert disabled.plugin_to_dict(disabled.get_plugin("alphasift"))["status"] == "disabled"

    enabled = get_extension_service(_config(extensions_alphasift_enabled=True), refresh=True)
    exposed = enabled.list_actions(enabled_only=True, include_internal=False)

    assert {action.id for action in exposed} == {
        "alphasift.healthcheck",
        "alphasift.list_strategies",
        "alphasift.screen",
        "alphasift.analyze_top_picks",
        "alphasift.import_picks_to_watchlist",
    }
    assert enabled.plugin_to_dict(enabled.get_plugin("alphasift"))["status"] == "enabled"

    reset_extension_service()
