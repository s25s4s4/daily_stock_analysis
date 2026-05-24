# -*- coding: utf-8 -*-
"""Tests for AlphaSift built-in actions."""

from __future__ import annotations

from types import SimpleNamespace

from src.extensions import ActionContext, ActionResult, ExtensionStatus
from src.extensions.builtin.alphasift.actions import build_alphasift_actions


class FakeAdapter:
    def healthcheck(self):
        return {"available": True, "adapter_mode": "python", "reason": ""}

    def list_strategies(self):
        return {"available": True, "adapter_mode": "python", "strategies": [{"id": "dual_low"}]}

    def screen(self, _payload, _context):
        return {
            "available": True,
            "adapter_mode": "python",
            "candidates": [{"code": "600519", "score": 90}],
            "source_chain": [{"provider": "mock", "status": "ok"}],
            "source_errors": [],
            "degradation": [],
            "warnings": [],
        }


def _action(actions, action_id):
    return next(action for action in actions if action.id == action_id)


def test_alphasift_screen_action_maps_source_chain():
    config = SimpleNamespace(
        extensions_alphasift_enabled=True,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
    )
    actions = build_alphasift_actions(config, adapter=FakeAdapter())
    action = _action(actions, "alphasift.screen")
    context = ActionContext(
        action_id=action.id,
        input={"market": "cn", "strategy": "dual_low"},
        run_id="run_test",
    )

    result = action.handler(context)

    assert result.status == ExtensionStatus.COMPLETED.value
    assert result.result["candidate_count"] == 1
    assert result.source_chain == [{"provider": "mock", "status": "ok"}]
    assert action.mode == "async"


def test_alphasift_disabled_returns_plugin_disabled():
    config = SimpleNamespace(
        extensions_alphasift_enabled=False,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
    )
    action = _action(build_alphasift_actions(config, adapter=FakeAdapter()), "alphasift.screen")
    context = ActionContext(action_id=action.id, input={}, run_id="run_test")

    result = action.handler(context)

    assert result.status == ExtensionStatus.UNAVAILABLE.value
    assert result.error_code == "E_PLUGIN_DISABLED"


def test_alphasift_disabled_import_does_not_require_confirmation_metadata():
    config = SimpleNamespace(
        extensions_alphasift_enabled=False,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
    )
    action = _action(build_alphasift_actions(config, adapter=FakeAdapter()), "alphasift.import_picks_to_watchlist")
    context = ActionContext(action_id=action.id, input={"candidates": [{"code": "600519"}]}, run_id="run_test")

    result = action.handler(context)

    assert action.requires_confirmation is False
    assert result.status == ExtensionStatus.UNAVAILABLE.value
    assert result.error_code == "E_PLUGIN_DISABLED"


def test_alphasift_enabled_high_risk_actions_require_confirmation_metadata():
    config = SimpleNamespace(
        extensions_alphasift_enabled=True,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
    )
    actions = build_alphasift_actions(config, adapter=FakeAdapter())

    assert _action(actions, "alphasift.import_picks_to_watchlist").requires_confirmation is True
    assert _action(actions, "alphasift.analyze_top_picks").requires_confirmation is True


def test_alphasift_actions_use_declared_timeout_and_permissions():
    config = SimpleNamespace(
        extensions_alphasift_enabled=True,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
        extensions_alphasift_timeout_seconds=90,
    )
    actions = build_alphasift_actions(config, adapter=FakeAdapter())

    screen = _action(actions, "alphasift.screen")
    import_picks = _action(actions, "alphasift.import_picks_to_watchlist")

    assert screen.timeout_seconds == 90
    assert screen.permissions == ["candidate_discovery"]
    assert import_picks.permissions == ["watchlist.write"]


def test_alphasift_analyze_top_picks_routes_through_dsa_action(monkeypatch):
    config = SimpleNamespace(
        extensions_alphasift_enabled=True,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
    )
    calls = []

    class FakeRuntime:
        def execute(self, action_id, payload, context):
            calls.append((action_id, payload, context))
            return ActionResult(
                run_id="run_core",
                action_id=action_id,
                status=ExtensionStatus.COMPLETED.value,
                result={
                    "tasks": [
                        {
                            "task_id": "task-1",
                            "stock_code": "600519.SH",
                            "report_type": "detailed",
                        }
                    ],
                    "duplicates": [],
                },
            )

    monkeypatch.setattr("src.extensions.service.get_extension_service", lambda: SimpleNamespace(runtime=FakeRuntime()))
    action = _action(build_alphasift_actions(config, adapter=FakeAdapter()), "alphasift.analyze_top_picks")

    result = action.handler(
        ActionContext(
            action_id=action.id,
            input={"candidates": [{"code": "600519"}], "top_n": 1},
            run_id="run_parent",
        )
    )

    assert calls[0][0] == "dsa.analyze_stock"
    assert calls[0][1]["stock_codes"] == ["600519"]
    assert calls[0][2].caller == "system"
    assert result.result["core_run_id"] == "run_core"


def test_alphasift_import_picks_routes_through_stock_pool_action(monkeypatch):
    config = SimpleNamespace(
        extensions_alphasift_enabled=True,
        alphasift_cli_path="alphasift",
        extensions_cli_stdout_max_bytes=1024 * 1024,
        extensions_cli_stderr_max_bytes=1024,
    )
    calls = []

    class FakeRuntime:
        def execute(self, action_id, payload, context):
            calls.append((action_id, payload, context))
            return ActionResult(
                run_id="run_core",
                action_id=action_id,
                status=ExtensionStatus.COMPLETED.value,
                result={"imported": ["600519.SH"], "stock_list": ["600519.SH"]},
            )

    monkeypatch.setattr("src.extensions.service.get_extension_service", lambda: SimpleNamespace(runtime=FakeRuntime()))
    action = _action(build_alphasift_actions(config, adapter=FakeAdapter()), "alphasift.import_picks_to_watchlist")

    result = action.handler(
        ActionContext(
            action_id=action.id,
            input={"candidates": [{"code": "600519"}]},
            run_id="run_parent",
        )
    )

    assert calls[0][0] == "stock_pool.import"
    assert calls[0][1] == {"stock_codes": ["600519"], "merge": True}
    assert calls[0][2].caller == "system"
    assert result.result["core_run_id"] == "run_core"
