# -*- coding: utf-8 -*-
"""AlphaSift adapter for the built-in candidate discovery extension."""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from src.extensions.action_spec import ActionContext, ExtensionErrorCode

logger = logging.getLogger("dsa.extensions.alphasift.adapter")


class AlphaSiftAdapter:
    """Adapter that prefers the AlphaSift Python package and falls back to CLI screen JSON."""

    def __init__(
        self,
        *,
        cli_path: str = "alphasift",
        api_url: str = "",
        cli_fallback_enabled: bool = False,
        snapshot_source_priority: Optional[List[str]] = None,
        stdout_max_bytes: int = 10 * 1024 * 1024,
        stderr_max_bytes: int = 1024 * 1024,
        http_timeout_seconds: float = 30.0,
    ):
        self.cli_path = cli_path or "alphasift"
        self.api_url = (api_url or "").strip().rstrip("/")
        self.cli_fallback_enabled = bool(cli_fallback_enabled)
        self.snapshot_source_priority = list(snapshot_source_priority or [])
        self.stdout_max_bytes = int(stdout_max_bytes)
        self.stderr_max_bytes = int(stderr_max_bytes)
        self.http_timeout_seconds = float(http_timeout_seconds)

    def healthcheck(self) -> Dict[str, Any]:
        """Return adapter availability without throwing."""
        module = self._import_python_package()
        if module is not None:
            return {
                "available": True,
                "adapter_mode": "python",
                "version": str(getattr(module, "__version__", "")),
                "reason": "",
            }

        cli_available = self.cli_fallback_enabled and shutil.which(self.cli_path) is not None
        if cli_available:
            return {
                "available": True,
                "adapter_mode": "cli",
                "version": "",
                "reason": "",
            }
        if self.api_url:
            return self._healthcheck_http()

        reason = (
            "AlphaSift Python package was not found and CLI fallback is disabled."
            if not self.cli_fallback_enabled
            else "AlphaSift Python package and CLI were not found."
        )
        return {
            "available": False,
            "adapter_mode": "unavailable",
            "version": "",
            "reason": reason,
        }

    def list_strategies(self) -> Dict[str, Any]:
        """List strategies from the Python package only."""
        module = self._import_python_package()
        if module is None:
            if self.api_url:
                return self._list_strategies_http()
            return self._unavailable("list_strategies requires the AlphaSift Python package or HTTP adapter.")

        func = self._resolve_callable(
            module,
            [
                ("alphasift", "list_strategies"),
                ("alphasift.strategies", "list_strategies"),
                ("alphasift.strategies", "get_strategies"),
            ],
        )
        if func is None:
            return self._unavailable("AlphaSift package does not expose list_strategies().")

        try:
            raw = func()
        except Exception as exc:
            logger.warning("AlphaSift list_strategies failed: %s", exc, exc_info=True)
            return {
                "available": False,
                "adapter_mode": "python",
                "error_code": ExtensionErrorCode.DEPENDENCY_FAILED.value,
                "reason": str(exc)[:240],
                "strategies": [],
            }

        return {
            "available": True,
            "adapter_mode": "python",
            "strategies": self._normalize_strategies(raw),
        }

    def screen(self, payload: Dict[str, Any], context: ActionContext) -> Dict[str, Any]:
        """Run candidate screening and return normalized candidates plus source metadata."""
        payload = dict(payload or {})
        dry_run = bool(context.dry_run or payload.get("dry_run", False))
        health = self.healthcheck()
        if dry_run:
            return {**health, "candidates": [], "source_chain": [], "source_errors": []}

        module = self._import_python_package()
        if module is not None:
            result = self._screen_python(module, payload, context)
            if result.get("available", True):
                return result
            if result.get("error_code") != ExtensionErrorCode.PLUGIN_UNAVAILABLE.value:
                return result

        if self.cli_fallback_enabled and shutil.which(self.cli_path):
            return self._screen_cli(payload, context)

        if self.api_url:
            return self._screen_http(payload, context)

        if self.cli_fallback_enabled:
            return self._unavailable("AlphaSift is not installed. Install the Python package or expose the CLI on PATH.")
        return self._unavailable(
            "AlphaSift Python package is not installed, CLI fallback is disabled, and no HTTP adapter is configured."
        )

    def _screen_python(self, module: Any, payload: Dict[str, Any], context: ActionContext) -> Dict[str, Any]:
        func = self._resolve_callable(
            module,
            [
                ("alphasift", "screen"),
                ("alphasift.screening", "screen"),
                ("alphasift.api", "screen"),
            ],
        )
        if func is None:
            return self._unavailable("AlphaSift package does not expose screen().")

        max_results = int(payload.get("max_results") or 20)
        kwargs = {
            "market": payload.get("market", "cn"),
            "strategy": payload.get("strategy", "dual_low"),
            "max_results": max_results,
            "max_output": max_results,
            "limit": max_results,
            "use_llm": bool(payload.get("use_llm", False)),
            "post_analyzers": [],
            "deep_analysis": False,
            "trace_id": context.trace_id,
            "traceparent": context.traceparent,
            "call_depth": context.call_depth + 1,
        }
        alpha_config = self._build_python_config()
        if alpha_config is not None:
            kwargs["config"] = alpha_config
        kwargs, guard_error = self._filter_guarded_kwargs(
            func,
            kwargs,
            guard_kwargs={"post_analyzers", "deep_analysis"},
        )
        if guard_error:
            return guard_error

        try:
            raw = func(**kwargs)
        except Exception as exc:
            logger.warning("AlphaSift package screen failed: %s", exc, exc_info=True)
            return {
                "available": False,
                "adapter_mode": "python",
                "error_code": ExtensionErrorCode.DEPENDENCY_FAILED.value,
                "reason": str(exc)[:240],
                "candidates": [],
                "source_chain": [],
                "source_errors": [{"provider": "alphasift-python", "error": str(exc)[:240]}],
            }

        return self._normalize_screen_result(raw, adapter_mode="python")

    def _screen_cli(self, payload: Dict[str, Any], context: ActionContext) -> Dict[str, Any]:
        market = str(payload.get("market") or "cn")
        strategy = str(payload.get("strategy") or "dual_low")
        max_results = str(int(payload.get("max_results") or 20))
        cmd = [
            self.cli_path,
            "screen",
            strategy,
            "--market",
            market,
            "--max-output",
            max_results,
            "--json",
            "--no-llm",
            "--no-post-analysis",
        ]
        env = {
            "DSA_TRACE_ID": context.trace_id,
            "DSA_TRACEPARENT": context.traceparent,
            "DSA_CALL_DEPTH": str(context.call_depth + 1),
        }
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=False,
                timeout=float(context.budget.get("timeout_seconds") or 300),
                env=self._subprocess_env(env),
            )
        except Exception as exc:
            logger.warning("AlphaSift CLI screen failed: %s", exc, exc_info=True)
            return {
                "available": False,
                "adapter_mode": "cli",
                "error_code": ExtensionErrorCode.DEPENDENCY_FAILED.value,
                "reason": str(exc)[:240],
                "candidates": [],
                "source_chain": [],
                "source_errors": [{"provider": "alphasift-cli", "error": str(exc)[:240]}],
            }

        if len(proc.stdout or b"") > self.stdout_max_bytes or len(proc.stderr or b"") > self.stderr_max_bytes:
            return {
                "available": False,
                "adapter_mode": "cli",
                "error_code": ExtensionErrorCode.OUTPUT_TOO_LARGE.value,
                "reason": "AlphaSift CLI output exceeded configured limits.",
                "candidates": [],
                "source_chain": [],
                "source_errors": [],
            }

        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            return {
                "available": False,
                "adapter_mode": "cli",
                "error_code": ExtensionErrorCode.DEPENDENCY_FAILED.value,
                "reason": stderr[:240] or f"AlphaSift CLI exited with {proc.returncode}",
                "candidates": [],
                "source_chain": [],
                "source_errors": [{"provider": "alphasift-cli", "error": stderr[:240]}],
            }

        try:
            raw = json.loads((proc.stdout or b"{}").decode("utf-8"))
        except ValueError as exc:
            return {
                "available": False,
                "adapter_mode": "cli",
                "error_code": ExtensionErrorCode.DEPENDENCY_FAILED.value,
                "reason": f"AlphaSift CLI did not return valid JSON: {exc}",
                "candidates": [],
                "source_chain": [],
                "source_errors": [{"provider": "alphasift-cli", "error": str(exc)[:240]}],
            }

        return self._normalize_screen_result(raw, adapter_mode="cli")

    def _healthcheck_http(self) -> Dict[str, Any]:
        for path in ("/health", "/api/health"):
            data, error = self._request_json("GET", path)
            if error is None:
                return {
                    "available": bool(data.get("available", data.get("status") != "unavailable")),
                    "adapter_mode": "http",
                    "version": str(data.get("version", "")),
                    "reason": str(data.get("reason", "")),
                }
        return self._unavailable(f"AlphaSift HTTP service is unavailable: {error}")

    def _list_strategies_http(self) -> Dict[str, Any]:
        for path in ("/strategies", "/api/strategies"):
            data, error = self._request_json("GET", path)
            if error is None:
                return {
                    "available": True,
                    "adapter_mode": "http",
                    "strategies": self._normalize_strategies(data),
                }
        return self._unavailable(f"AlphaSift HTTP strategies endpoint is unavailable: {error}")

    def _screen_http(self, payload: Dict[str, Any], context: ActionContext) -> Dict[str, Any]:
        request_payload = dict(payload or {})
        request_payload.setdefault("use_llm", False)
        request_payload.setdefault("deep_analysis", False)
        request_payload.setdefault("trace_id", context.trace_id)
        request_payload.setdefault("traceparent", context.traceparent)
        request_payload.setdefault("call_depth", context.call_depth + 1)
        if "max_results" in request_payload and "max_output" not in request_payload:
            request_payload["max_output"] = request_payload["max_results"]

        for path in ("/screen", "/api/screen"):
            data, error = self._request_json("POST", path, json_payload=request_payload)
            if error is None:
                return self._normalize_screen_result(data, adapter_mode="http")
        return self._unavailable(f"AlphaSift HTTP screen endpoint is unavailable: {error}")

    def _normalize_screen_result(self, raw: Any, *, adapter_mode: str) -> Dict[str, Any]:
        data = self._to_plain_data(raw)
        candidates_raw = self._extract_candidates(data)
        candidates = [
            self._normalize_candidate(item, index + 1)
            for index, item in enumerate(candidates_raw)
        ]
        source_chain = self._normalize_source_chain(data)
        source_errors = self._normalize_source_errors(data)
        degradation = self._normalize_string_list(self._pick(data, "degradation", "degradations", "warnings"))
        warnings = self._normalize_string_list(self._pick(data, "warnings"))
        if not source_chain:
            source_chain = [{"provider": f"alphasift-{adapter_mode}", "status": "ok"}]
        return {
            "available": True,
            "adapter_mode": adapter_mode,
            "candidates": candidates,
            "candidate_count": len(candidates),
            "source_chain": source_chain,
            "source_errors": source_errors,
            "degradation": degradation,
            "warnings": warnings,
            "raw_summary": self._summarize_raw(data),
        }

    def _extract_candidates(self, data: Any) -> List[Any]:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ("candidates", "results", "items", "picks", "stocks"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    def _normalize_candidate(self, raw: Any, rank: int) -> Dict[str, Any]:
        item = self._to_plain_data(raw)
        if not isinstance(item, dict):
            item = {"code": str(item)}
        code = self._first_text(item, "code", "symbol", "ticker", "stock_code")
        score = self._first_number(item, "score", "final_score", "screen_score", "total_score", "confidence")
        tags = self._normalize_string_list(item.get("tags") or item.get("labels"))
        if not tags:
            tags = self._candidate_factor_tags(item)
        ranking_reason = self._first_text(item, "ranking_reason", "reason", "summary")
        if not ranking_reason:
            ranking_reason = self._fallback_ranking_reason(item, score)
        risk_summary = self._first_text(item, "risk_summary", "risk", "risk_reason")
        if not risk_summary:
            risk_summary = self._fallback_risk_summary(item)
        return {
            "rank": int(item.get("rank") or rank),
            "code": code,
            "name": self._first_text(item, "name", "stock_name", "display_name"),
            "market": self._first_text(item, "market", "exchange"),
            "score": score,
            "strategy": self._first_text(item, "strategy", "strategy_id"),
            "tags": tags,
            "ranking_reason": ranking_reason,
            "risk_summary": risk_summary,
            "raw": item,
        }

    def _normalize_strategies(self, raw: Any) -> List[Dict[str, Any]]:
        data = self._to_plain_data(raw)
        if isinstance(data, dict):
            values = data.get("strategies") or data.get("items") or data.values()
        else:
            values = data if isinstance(data, list) else []
        strategies = []
        for item in values:
            plain = self._to_plain_data(item)
            if isinstance(plain, str):
                strategies.append({"id": plain, "name": plain, "description": ""})
            elif isinstance(plain, dict):
                strategy_id = self._first_text(plain, "id", "name", "key")
                if strategy_id:
                    strategies.append(
                        {
                            "id": strategy_id,
                            "name": self._first_text(plain, "display_name", "title", "name") or strategy_id,
                            "description": self._first_text(plain, "description", "summary"),
                        }
                    )
        return strategies

    def _normalize_source_chain(self, data: Any) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        raw = data.get("source_chain") or data.get("snapshot_source") or data.get("sources") or []
        if isinstance(raw, str):
            return [{"provider": raw, "status": "ok", "fallback_from": None}]
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [item if isinstance(item, dict) else {"provider": str(item), "status": "ok"} for item in raw]
        return []

    def _normalize_source_errors(self, data: Any) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        raw = data.get("source_errors") or []
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [item if isinstance(item, dict) else {"error": str(item)} for item in raw]
        if raw:
            return [{"error": str(raw)}]
        return []

    def _summarize_raw(self, data: Any) -> str:
        if isinstance(data, dict):
            for key in ("summary", "message", "run_id"):
                value = data.get(key)
                if value:
                    return str(value)[:300]
        return ""

    def _import_python_package(self) -> Optional[Any]:
        try:
            return importlib.import_module("alphasift")
        except Exception:
            return None

    def _resolve_callable(self, module: Any, candidates: Iterable[Tuple[str, str]]) -> Optional[Any]:
        for module_name, attr_name in candidates:
            try:
                target_module = module if module_name == "alphasift" else importlib.import_module(module_name)
            except Exception:
                continue
            func = getattr(target_module, attr_name, None)
            if callable(func):
                return func
        return None

    def _build_python_config(self) -> Optional[Any]:
        """Build AlphaSift's own Config when DSA needs to pass runtime hints."""
        if not self.snapshot_source_priority:
            return None
        try:
            from alphasift.config import Config as AlphaSiftConfig

            config = AlphaSiftConfig.from_env()
            config.snapshot_source_priority = list(self.snapshot_source_priority)
            return config
        except Exception as exc:
            logger.warning("Failed to build AlphaSift Python config override: %s", exc)
            return None

    def _filter_kwargs(self, func: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return kwargs
        if any(param.kind == param.VAR_KEYWORD for param in signature.parameters.values()):
            return kwargs
        return {key: value for key, value in kwargs.items() if key in signature.parameters}

    def _filter_guarded_kwargs(
        self,
        func: Any,
        kwargs: Dict[str, Any],
        *,
        guard_kwargs: set[str],
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return {}, self._dependency_failed("AlphaSift screen() signature cannot be inspected for recursion guards.")

        accepts_kwargs = any(param.kind == param.VAR_KEYWORD for param in signature.parameters.values())
        if accepts_kwargs:
            return kwargs, None

        accepted = set(signature.parameters)
        accepted_guards = sorted(guard_kwargs & accepted)
        if not accepted_guards:
            return {}, self._dependency_failed(
                "AlphaSift screen() does not accept recursion guards: "
                + ", ".join(sorted(guard_kwargs))
            )
        return {key: value for key, value in kwargs.items() if key in accepted}, None

    def _subprocess_env(self, trace_env: Dict[str, str]) -> Dict[str, str]:
        allowed_names = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ"}
        env = {
            key: value
            for key, value in os.environ.items()
            if key in allowed_names or key.startswith("LC_")
        }
        env.update({key: value for key, value in trace_env.items() if value})
        return env

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        if not self.api_url:
            return {}, "ALPHASIFT_API_URL is empty"
        url = urljoin(f"{self.api_url}/", path.lstrip("/"))
        try:
            response = requests.request(
                method,
                url,
                json=json_payload,
                timeout=self.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {}, "AlphaSift HTTP response must be a JSON object"
            return payload, None
        except Exception as exc:
            return {}, str(exc)[:240]

    def _to_plain_data(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "model_dump") and callable(value.model_dump):
            return value.model_dump()
        if hasattr(value, "dict") and callable(value.dict):
            return value.dict()
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return value.to_dict()
        if isinstance(value, (list, tuple)):
            return [self._to_plain_data(item) for item in value]
        if isinstance(value, dict):
            return {key: self._to_plain_data(item) for key, item in value.items()}
        return value

    def _pick(self, data: Any, *keys: str) -> Any:
        if not isinstance(data, dict):
            return None
        for key in keys:
            if key in data:
                return data[key]
        return None

    def _first_text(self, item: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _first_number(self, item: Dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            value = item.get(key)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _candidate_factor_tags(self, item: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        pe_ratio = self._first_number(item, "pe_ratio", "pe")
        pb_ratio = self._first_number(item, "pb_ratio", "pb")
        change_pct = self._first_number(item, "change_pct")
        if pe_ratio is not None:
            tags.append(f"PE {pe_ratio:.1f}")
        if pb_ratio is not None:
            tags.append(f"PB {pb_ratio:.2f}")
        if change_pct is not None:
            tags.append(f"涨跌幅 {change_pct:.2f}%")
        status = self._first_text(item, "deep_analysis_status")
        if status and status != "not_requested":
            tags.append(f"DSA {status}")
        return tags[:4]

    def _fallback_ranking_reason(self, item: Dict[str, Any], score: Optional[float]) -> str:
        score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "--"
        price = self._first_number(item, "price")
        pe_ratio = self._first_number(item, "pe_ratio", "pe")
        pb_ratio = self._first_number(item, "pb_ratio", "pb")
        factors = []
        if price is not None:
            factors.append(f"价格 {price:.2f}")
        if pe_ratio is not None:
            factors.append(f"PE {pe_ratio:.1f}")
        if pb_ratio is not None:
            factors.append(f"PB {pb_ratio:.2f}")
        suffix = f"，{'，'.join(factors)}" if factors else ""
        return f"AlphaSift 因子筛选分 {score_text}{suffix}。"

    def _fallback_risk_summary(self, item: Dict[str, Any]) -> str:
        risk_flags = self._normalize_string_list(item.get("deep_analysis_risk_flags"))
        if risk_flags:
            return "；".join(risk_flags[:3])
        change_pct = self._first_number(item, "change_pct")
        if change_pct is not None and abs(change_pct) >= 7:
            return "当日波动较大，需结合成交量和仓位控制复核。"
        return "未执行 DSA 深度分析，当前仅代表候选筛选结果。"

    def _normalize_string_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return [str(value)] if str(value) else []

    def _unavailable(self, reason: str) -> Dict[str, Any]:
        return {
            "available": False,
            "adapter_mode": "unavailable",
            "error_code": ExtensionErrorCode.PLUGIN_UNAVAILABLE.value,
            "reason": reason,
            "candidates": [],
            "source_chain": [],
            "source_errors": [],
        }

    def _dependency_failed(self, reason: str) -> Dict[str, Any]:
        return {
            "available": False,
            "adapter_mode": "python",
            "error_code": ExtensionErrorCode.DEPENDENCY_FAILED.value,
            "reason": reason,
            "candidates": [],
            "source_chain": [],
            "source_errors": [{"provider": "alphasift-python", "error": reason}],
        }
