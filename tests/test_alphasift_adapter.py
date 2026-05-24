# -*- coding: utf-8 -*-
"""Tests for AlphaSift adapter behavior."""

from __future__ import annotations

import subprocess
import sys
import types

from src.extensions import ActionContext
from src.extensions.builtin.alphasift.adapter import AlphaSiftAdapter


def test_alphasift_adapter_uses_python_package_and_disables_post_analysis(monkeypatch):
    module = types.ModuleType("alphasift")
    captured = {}

    def screen(strategy, *, market, max_output, use_llm, deep_analysis):
        captured.update(
            {
                "strategy": strategy,
                "market": market,
                "max_output": max_output,
                "use_llm": use_llm,
                "deep_analysis": deep_analysis,
            }
        )
        return {
            "candidates": [{"code": "600519", "name": "贵州茅台", "score": 91}],
            "snapshot_source": "mock",
            "source_errors": [],
        }

    module.screen = screen
    module.__version__ = "0.1.0"
    monkeypatch.setitem(sys.modules, "alphasift", module)

    adapter = AlphaSiftAdapter()
    result = adapter.screen(
        {"market": "cn", "strategy": "dual_low", "max_results": 3},
        ActionContext(action_id="alphasift.screen", input={}),
    )

    assert result["available"] is True
    assert result["adapter_mode"] == "python"
    assert result["candidates"][0]["code"] == "600519"
    assert captured["strategy"] == "dual_low"
    assert captured["max_output"] == 3
    assert captured["use_llm"] is False
    assert captured["deep_analysis"] is False


def test_alphasift_adapter_passes_snapshot_source_priority_to_python_config(monkeypatch):
    module = types.ModuleType("alphasift")
    captured = {}

    def screen(strategy, *, market, max_output, use_llm, deep_analysis, config):
        captured["sources"] = config.snapshot_source_priority
        return {"picks": [{"code": "600519", "final_score": 91}]}

    module.screen = screen
    monkeypatch.setitem(sys.modules, "alphasift", module)
    monkeypatch.setattr(
        AlphaSiftAdapter,
        "_build_python_config",
        lambda self: types.SimpleNamespace(snapshot_source_priority=self.snapshot_source_priority),
    )

    result = AlphaSiftAdapter(
        snapshot_source_priority=["em_datacenter", "efinance"],
    ).screen(
        {"market": "cn", "strategy": "dual_low", "max_results": 3},
        ActionContext(action_id="alphasift.screen", input={}),
    )

    assert result["available"] is True
    assert captured["sources"] == ["em_datacenter", "efinance"]
    assert result["candidates"][0]["ranking_reason"].startswith("AlphaSift 因子筛选分")


def test_alphasift_adapter_refuses_python_screen_without_recursion_guards(monkeypatch):
    module = types.ModuleType("alphasift")
    called = {"value": False}

    def screen(strategy, *, market, max_output):
        called["value"] = True
        return {"candidates": []}

    module.screen = screen
    monkeypatch.setitem(sys.modules, "alphasift", module)

    result = AlphaSiftAdapter().screen(
        {"market": "cn", "strategy": "dual_low", "max_results": 3},
        ActionContext(action_id="alphasift.screen", input={}),
    )

    assert result["available"] is False
    assert "recursion guards" in result["reason"]
    assert called["value"] is False


def test_alphasift_adapter_cli_fallback_requires_json_and_no_post_analysis(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _path: "/usr/bin/alphasift")
    monkeypatch.setattr(AlphaSiftAdapter, "_import_python_package", lambda self: None)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env", {})
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=b'{"results":[{"symbol":"AAPL","score":88}],"snapshot_source":"cli"}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    adapter = AlphaSiftAdapter(cli_path="alphasift", cli_fallback_enabled=True)

    result = adapter.screen(
        {"market": "us", "strategy": "growth", "max_results": 2},
        ActionContext(action_id="alphasift.screen", input={}, trace_id="t1"),
    )

    assert captured["cmd"] == [
        "alphasift",
        "screen",
        "growth",
        "--market",
        "us",
        "--max-output",
        "2",
        "--json",
        "--no-llm",
        "--no-post-analysis",
    ]
    assert captured["env"]["DSA_TRACE_ID"] == "t1"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert result["adapter_mode"] == "cli"
    assert result["candidates"][0]["code"] == "AAPL"


def test_alphasift_adapter_cli_fallback_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _path: "/usr/bin/alphasift")
    monkeypatch.setattr(AlphaSiftAdapter, "_import_python_package", lambda self: None)

    result = AlphaSiftAdapter().screen({}, ActionContext(action_id="alphasift.screen", input={}))

    assert result["available"] is False
    assert result["adapter_mode"] == "unavailable"
    assert "CLI fallback is disabled" in result["reason"]


def test_alphasift_adapter_unavailable_when_package_and_cli_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _path: None)
    monkeypatch.setattr(AlphaSiftAdapter, "_import_python_package", lambda self: None)

    result = AlphaSiftAdapter().screen({}, ActionContext(action_id="alphasift.screen", input={}))

    assert result["available"] is False
    assert result["adapter_mode"] == "unavailable"


def test_alphasift_adapter_uses_http_fallback_when_configured(monkeypatch):
    monkeypatch.setattr(AlphaSiftAdapter, "_import_python_package", lambda self: None)

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [{"code": "600519", "final_score": 88}],
                "source_chain": [{"provider": "http", "status": "ok"}],
            }

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr("requests.request", fake_request)

    result = AlphaSiftAdapter(api_url="http://alphasift.local").screen(
        {"market": "cn", "strategy": "dual_low", "max_results": 2},
        ActionContext(action_id="alphasift.screen", input={}, trace_id="trace-1"),
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://alphasift.local/screen"
    assert captured["json"]["max_output"] == 2
    assert captured["json"]["deep_analysis"] is False
    assert captured["json"]["trace_id"] == "trace-1"
    assert result["adapter_mode"] == "http"
    assert result["candidates"][0]["code"] == "600519"
