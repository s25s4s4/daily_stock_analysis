# -*- coding: utf-8 -*-
"""ActionSpec builders for the built-in AlphaSift extension."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from data_provider.base import canonical_stock_code

from src.extensions.action_spec import ActionContext, ActionResult, ActionSpec, ExtensionErrorCode, ExtensionStatus
from src.extensions.builtin.alphasift.adapter import AlphaSiftAdapter
from src.extensions.builtin.alphasift import schemas
from src.extensions.manifests import PluginManifest
from src.extensions.run_envelope import input_hash, new_run_id

PLUGIN_ID = "alphasift"
PLUGIN_VERSION = "0.1.0"


def get_alphasift_manifest() -> PluginManifest:
    """Return the built-in AlphaSift manifest."""
    manifest_path = Path(__file__).with_name("plugin.yaml")
    if manifest_path.is_file():
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict):
            return PluginManifest.from_dict(payload)

    return PluginManifest.from_dict(
        {
            "id": PLUGIN_ID,
            "name": "AlphaSift",
            "version": PLUGIN_VERSION,
            "kind": "builtin",
            "description": "Candidate discovery and strategy screening via local AlphaSift.",
            "requires": ["alphasift>=0.1.0"],
            "permissions": ["candidate_discovery", "watchlist.write", "analysis.submit"],
            "supported_markets": ["cn"],
            "installation_hints": [
                "python -m pip install -e /path/to/alphasift",
                "如需 CLI fallback，先核对 alphasift screen --help 后设置 EXTENSIONS_ALPHASIFT_CLI_FALLBACK_ENABLED=true",
            ],
            "setup_doc_url": "docs/alphasift-integration.md",
            "default_enabled": False,
            "actions": [
                {"id": "alphasift.healthcheck", "name": "Healthcheck"},
                {"id": "alphasift.list_strategies", "name": "List strategies"},
                {"id": "alphasift.screen", "name": "Screen candidates"},
                {"id": "alphasift.analyze_top_picks", "name": "Analyze top picks"},
                {"id": "alphasift.import_picks_to_watchlist", "name": "Import picks to watchlist"},
            ],
            "skills": ["alphasift_candidate_discovery"],
            "ui_contributions": [],
        }
    )


def build_alphasift_actions(config=None, adapter: Optional[AlphaSiftAdapter] = None) -> List[ActionSpec]:
    """Build AlphaSift action specs using runtime config."""
    if config is None:
        from src.config import get_config

        config = get_config()

    plugin_enabled = bool(getattr(config, "extensions_alphasift_enabled", False))
    timeout_seconds = int(getattr(config, "extensions_alphasift_timeout_seconds", 180) or 180)
    adapter = adapter or AlphaSiftAdapter(
        cli_path=getattr(config, "alphasift_cli_path", "alphasift"),
        api_url=getattr(config, "alphasift_api_url", ""),
        cli_fallback_enabled=getattr(config, "extensions_alphasift_cli_fallback_enabled", False),
        snapshot_source_priority=getattr(config, "extensions_alphasift_snapshot_source_priority", []),
        stdout_max_bytes=getattr(config, "extensions_cli_stdout_max_bytes", 10 * 1024 * 1024),
        stderr_max_bytes=getattr(config, "extensions_cli_stderr_max_bytes", 1024 * 1024),
        http_timeout_seconds=min(float(timeout_seconds), 60.0),
    )
    metadata = {"plugin_version": PLUGIN_VERSION, "business_category": "candidate_discovery"}

    def _healthcheck(context: ActionContext) -> ActionResult:
        health = adapter.healthcheck()
        if not plugin_enabled:
            health["enabled"] = False
            return _result(
                context,
                ExtensionStatus.UNAVAILABLE.value,
                health,
                error_code=ExtensionErrorCode.PLUGIN_DISABLED.value,
            )
        status = ExtensionStatus.COMPLETED.value if health.get("available") else ExtensionStatus.UNAVAILABLE.value
        return _result(
            context,
            status,
            {**health, "enabled": True},
            error_code=None if health.get("available") else ExtensionErrorCode.PLUGIN_UNAVAILABLE.value,
        )

    def _list_strategies(context: ActionContext) -> ActionResult:
        if not plugin_enabled:
            return _disabled(context)
        payload = adapter.list_strategies()
        status = ExtensionStatus.COMPLETED.value if payload.get("available") else ExtensionStatus.UNAVAILABLE.value
        return _result(
            context,
            status,
            payload,
            error_code=payload.get("error_code") if not payload.get("available") else None,
        )

    def _screen(context: ActionContext) -> ActionResult:
        if not plugin_enabled:
            return _disabled(context)
        payload = adapter.screen(context.input, context)
        available = bool(payload.get("available"))
        degradation = payload.get("degradation") or []
        status = ExtensionStatus.COMPLETED.value if available else ExtensionStatus.UNAVAILABLE.value
        if available and degradation:
            status = ExtensionStatus.PARTIAL.value
        result = {
            "adapter_mode": payload.get("adapter_mode", "unavailable"),
            "candidates": payload.get("candidates", []),
            "candidate_count": len(payload.get("candidates", []) or []),
            "raw_summary": payload.get("raw_summary", ""),
        }
        return _result(
            context,
            status,
            result,
            warnings=payload.get("warnings") or [],
            degradation=degradation,
            source_chain=payload.get("source_chain") or [],
            source_errors=payload.get("source_errors") or [],
            error_code=payload.get("error_code") if not available else None,
            diagnostics={"reason": payload.get("reason", "")} if payload.get("reason") else {},
        )

    def _analyze_top_picks(context: ActionContext) -> ActionResult:
        if not plugin_enabled:
            return _disabled(context)
        candidates = _candidate_items(context.input)
        top_n = max(1, min(int(context.input.get("top_n") or 5), 20))
        selected = candidates[:top_n]
        if not selected:
            return _result(
                context,
                ExtensionStatus.FAILED.value,
                {"tasks": []},
                error_code=ExtensionErrorCode.INPUT_INVALID.value,
                diagnostics={"reason": "No candidates provided."},
            )

        child_payload = {
            "stock_codes": [candidate["code"] for candidate in selected if candidate.get("code")],
            "report_type": str(context.input.get("report_type") or "detailed"),
            "original_query": f"alphasift:{context.run_id}",
            "selection_source": "import",
            "notify": bool(context.input.get("notify", False)),
        }
        child_result = _execute_internal_action(
            "dsa.analyze_stock",
            child_payload,
            parent=context,
            budget={"max_items": top_n},
        )
        child_payload_result = child_result.result if isinstance(child_result.result, dict) else {}
        tasks = child_payload_result.get("tasks") if isinstance(child_payload_result, dict) else []
        duplicates = child_payload_result.get("duplicates") if isinstance(child_payload_result, dict) else []
        if isinstance(tasks, list):
            _link_analysis_tasks(context, tasks)
        if child_result.status not in (ExtensionStatus.COMPLETED.value, ExtensionStatus.PARTIAL.value):
            return _result(
                context,
                child_result.status,
                {"tasks": tasks if isinstance(tasks, list) else [], "duplicates": duplicates if isinstance(duplicates, list) else []},
                error_code=child_result.error_code,
                diagnostics=child_result.diagnostics,
            )
        return _result(
            context,
            child_result.status,
            {
                "tasks": tasks if isinstance(tasks, list) else [],
                "duplicates": duplicates if isinstance(duplicates, list) else [],
                "core_run_id": child_result.run_id,
            },
        )

    def _import_picks(context: ActionContext) -> ActionResult:
        if not plugin_enabled:
            return _disabled(context)
        candidates = _candidate_items(context.input)
        codes = [candidate["code"] for candidate in candidates if candidate.get("code")]
        if not codes:
            return _result(
                context,
                ExtensionStatus.FAILED.value,
                {"imported": [], "stock_list": []},
                error_code=ExtensionErrorCode.INPUT_INVALID.value,
                diagnostics={"reason": "No valid candidate codes provided."},
            )

        merge = bool(context.input.get("merge", True))
        child_payload = {"stock_codes": codes, "merge": merge}
        child_result = _execute_internal_action(
            "stock_pool.import",
            child_payload,
            parent=context,
            budget={"max_items": len(codes)},
        )
        child_payload_result = child_result.result if isinstance(child_result.result, dict) else {}
        if child_result.status != ExtensionStatus.COMPLETED.value:
            return _result(
                context,
                child_result.status,
                {
                    "imported": child_payload_result.get("imported", []),
                    "stock_list": child_payload_result.get("stock_list", []),
                },
                error_code=child_result.error_code,
                diagnostics=child_result.diagnostics,
            )
        _link_watchlist_update(context, codes, merge)
        return _result(
            context,
            ExtensionStatus.COMPLETED.value,
            {
                "imported": child_payload_result.get("imported", codes),
                "stock_list": child_payload_result.get("stock_list", []),
                "core_run_id": child_result.run_id,
            },
        )

    return [
        ActionSpec(
            id="alphasift.healthcheck",
            plugin_id=PLUGIN_ID,
            name="AlphaSift Healthcheck",
            description="Check whether AlphaSift is available locally.",
            category="candidate_discovery",
            mode="sync",
            input_schema=schemas.HEALTHCHECK_INPUT_SCHEMA,
            handler=_healthcheck,
            permissions=["candidate_discovery"],
            supported_callers=["web", "agent", "bot", "cli", "scheduler", "system", "mcp"],
            dedupe_strategy="none",
            concurrency_limit=2,
            metadata=metadata,
        ),
        ActionSpec(
            id="alphasift.list_strategies",
            plugin_id=PLUGIN_ID,
            name="List AlphaSift Strategies",
            description="List AlphaSift screening strategies from the Python package.",
            category="candidate_discovery",
            mode="sync",
            input_schema=schemas.LIST_STRATEGIES_INPUT_SCHEMA,
            handler=_list_strategies,
            permissions=["candidate_discovery"],
            supported_callers=["web", "agent", "bot", "cli", "system", "mcp"],
            dedupe_strategy="none",
            concurrency_limit=2,
            metadata=metadata,
        ),
        ActionSpec(
            id="alphasift.screen",
            plugin_id=PLUGIN_ID,
            name="Screen AlphaSift Candidates",
            description="Run AlphaSift candidate discovery with DSA recursion disabled.",
            category="candidate_discovery",
            mode="async",
            input_schema=schemas.SCREEN_INPUT_SCHEMA,
            handler=_screen,
            permissions=["candidate_discovery"],
            supported_callers=["web", "agent", "bot", "cli", "scheduler", "system", "mcp"],
            dedupe_strategy="input_hash",
            concurrency_limit=1,
            cancel_capability="pending_only",
            timeout_seconds=timeout_seconds,
            metadata=metadata,
        ),
        ActionSpec(
            id="alphasift.analyze_top_picks",
            plugin_id=PLUGIN_ID,
            name="Analyze AlphaSift Top Picks",
            description="Submit DSA analysis tasks for selected AlphaSift candidates.",
            category="candidate_discovery",
            mode="sync",
            input_schema=schemas.ANALYZE_TOP_PICKS_INPUT_SCHEMA,
            handler=_analyze_top_picks,
            permissions=["analysis.submit"],
            supported_callers=["web", "cli", "bot", "system"],
            requires_confirmation=plugin_enabled,
            confirmation_scope="analysis.submit",
            dedupe_strategy="none",
            concurrency_limit=1,
            metadata=metadata,
        ),
        ActionSpec(
            id="alphasift.import_picks_to_watchlist",
            plugin_id=PLUGIN_ID,
            name="Import AlphaSift Picks to Watchlist",
            description="Merge AlphaSift candidate codes into STOCK_LIST.",
            category="candidate_discovery",
            mode="sync",
            input_schema=schemas.IMPORT_PICKS_INPUT_SCHEMA,
            handler=_import_picks,
            permissions=["watchlist.write"],
            supported_callers=["web", "cli", "bot", "system"],
            requires_confirmation=plugin_enabled,
            confirmation_scope="watchlist.write",
            dedupe_strategy="none",
            concurrency_limit=1,
            metadata=metadata,
        ),
    ]


def _disabled(context: ActionContext) -> ActionResult:
    return _result(
        context,
        ExtensionStatus.UNAVAILABLE.value,
        {"available": False, "enabled": False, "reason": "AlphaSift extension is disabled."},
        error_code=ExtensionErrorCode.PLUGIN_DISABLED.value,
    )


def _result(
    context: ActionContext,
    status: str,
    result: Dict[str, Any],
    *,
    warnings: Optional[List[str]] = None,
    degradation: Optional[List[str]] = None,
    source_chain: Optional[List[Dict[str, Any]]] = None,
    source_errors: Optional[List[Dict[str, Any]]] = None,
    error_code: Optional[str] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> ActionResult:
    now = datetime.now()
    return ActionResult(
        run_id=context.run_id,
        action_id=context.action_id,
        status=status,
        result=result,
        warnings=warnings or [],
        degradation=degradation or [],
        source_chain=source_chain or [],
        source_errors=source_errors or [],
        error_code=error_code,
        diagnostics=diagnostics or {},
        created_at=now,
        updated_at=now,
    )


def _candidate_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_items = payload.get("candidates") if isinstance(payload, dict) else []
    items = raw_items if isinstance(raw_items, list) else []
    normalized: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = canonical_stock_code(str(item.get("code") or item.get("symbol") or "").strip())
        if not code:
            continue
        normalized.append({**item, "code": code})
    return normalized


def _execute_internal_action(
    action_id: str,
    payload: Dict[str, Any],
    *,
    parent: ActionContext,
    budget: Optional[Dict[str, Any]] = None,
) -> ActionResult:
    from src.extensions.service import get_extension_service

    child_context = ActionContext(
        action_id=action_id,
        input=payload,
        caller="system",
        trace_id=parent.trace_id,
        traceparent=parent.traceparent,
        session_id=parent.session_id,
        request_id=parent.request_id,
        dry_run=parent.dry_run,
        call_depth=parent.call_depth + 1,
        budget=dict(budget or {}),
        context={**parent.context, "parent_run_id": parent.run_id},
        input_hash=input_hash(payload),
        run_id=new_run_id(),
    )
    return get_extension_service().runtime.execute(action_id, payload, context=child_context)


def _link_analysis_tasks(context: ActionContext, tasks) -> None:
    """Reserve audit backlink wiring for the persistent run-store phase."""
    return None


def _link_watchlist_update(context: ActionContext, codes: List[str], merge: bool) -> None:
    """Reserve audit backlink wiring for the persistent run-store phase."""
    return None
