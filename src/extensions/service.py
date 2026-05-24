# -*- coding: utf-8 -*-
"""Runtime assembly helpers for the built-in Extension Runtime."""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict
from typing import Dict, List, Optional

from src.extensions.catalog import ExtensionCatalog
from src.extensions.manifests import PluginManifest
from src.extensions.runtime import ExtensionRuntime

logger = logging.getLogger("dsa.extensions.service")

_SERVICE = None
_SERVICE_SIGNATURE = None

_CONFIG_SIGNATURE_FIELDS = (
    "extensions_enabled",
    "extensions_autoload_builtin",
    "extensions_alphasift_enabled",
    "alphasift_api_url",
    "alphasift_cli_path",
    "extensions_alphasift_cli_fallback_enabled",
    "extensions_alphasift_snapshot_source_priority",
    "extensions_alphasift_timeout_seconds",
    "extensions_cli_stdout_max_bytes",
    "extensions_cli_stderr_max_bytes",
    "max_action_call_depth",
)


class ExtensionService:
    """A small facade around manifests, catalog and runtime."""

    def __init__(self, config=None):
        if config is None:
            from src.config import get_config

            config = get_config()
        self.config = config
        self.manifests: Dict[str, PluginManifest] = {}
        self.catalog = ExtensionCatalog()
        self._load_core_actions()
        self._load_builtin_extensions()
        self.runtime = ExtensionRuntime.from_config(config, self.catalog)

    def _load_core_actions(self) -> None:
        """Register internal DSA actions used by extension workflows."""
        try:
            from src.extensions.builtin.dsa import build_dsa_core_actions

            for action in build_dsa_core_actions(self.config):
                self.catalog.register(action)
        except Exception as exc:  # pragma: no cover - defensive import guard
            logger.warning("Failed to load core DSA extension actions: %s", exc, exc_info=True)

    def _load_builtin_extensions(self) -> None:
        if not getattr(self.config, "extensions_autoload_builtin", True):
            return
        try:
            from src.extensions.builtin.alphasift import build_alphasift_actions, get_alphasift_manifest

            manifest = get_alphasift_manifest()
            self.manifests[manifest.id] = manifest
            for action in build_alphasift_actions(self.config):
                self.catalog.register(action)
        except Exception as exc:  # pragma: no cover - defensive import guard
            logger.warning("Failed to load built-in AlphaSift extension: %s", exc, exc_info=True)

    def list_plugins(self) -> List[Dict[str, object]]:
        """Return manifest snapshots for all known plugins."""
        return [
            self.plugin_to_dict(manifest)
            for manifest in sorted(self.manifests.values(), key=lambda item: item.id)
        ]

    def get_plugin(self, plugin_id: str) -> Optional[PluginManifest]:
        """Return one plugin manifest by id."""
        return self.manifests.get(plugin_id)

    def list_actions(
        self,
        plugin_id: Optional[str] = None,
        *,
        enabled_only: bool = False,
        include_internal: bool = True,
    ):
        """Return action specs."""
        actions = self.catalog.list_actions(plugin_id=plugin_id)
        if not include_internal:
            actions = [
                action
                for action in actions
                if not bool(action.metadata.get("internal"))
            ]
        if enabled_only:
            actions = [
                action
                for action in actions
                if self._is_action_enabled(action)
            ]
        return actions

    def plugin_to_dict(self, manifest: PluginManifest) -> Dict[str, object]:
        """Serialize a plugin manifest plus runtime enablement state."""
        payload = asdict(manifest)
        enabled_attr = f"extensions_{manifest.id}_enabled"
        runtime_enabled = bool(getattr(self.config, "extensions_enabled", True))
        enabled = bool(getattr(self.config, enabled_attr, manifest.default_enabled))
        payload["enabled"] = enabled
        payload["runtime_enabled"] = runtime_enabled
        payload["status"] = "enabled" if runtime_enabled and enabled else "disabled"
        payload["actions"] = [
            action_to_dict(action)
            for action in self.catalog.list_actions(plugin_id=manifest.id)
        ]
        return payload

    def _is_action_enabled(self, action) -> bool:
        if bool(action.metadata.get("internal")):
            return True
        manifest = self.manifests.get(action.plugin_id)
        if manifest is None:
            return False
        runtime_enabled = bool(getattr(self.config, "extensions_enabled", True))
        enabled_attr = f"extensions_{manifest.id}_enabled"
        plugin_enabled = bool(getattr(self.config, enabled_attr, manifest.default_enabled))
        return runtime_enabled and plugin_enabled


def action_to_dict(action) -> Dict[str, object]:
    """Serialize ActionSpec without leaking handler callables."""
    return {
        "id": action.id,
        "plugin_id": action.plugin_id,
        "name": action.name,
        "description": action.description,
        "category": action.category,
        "mode": action.mode,
        "input_schema": copy.deepcopy(action.input_schema),
        "output_schema": copy.deepcopy(action.output_schema),
        "permissions": list(action.permissions),
        "supported_callers": list(action.supported_callers),
        "requires_confirmation": action.requires_confirmation,
        "confirmation_scope": action.confirmation_scope,
        "timeout_seconds": action.timeout_seconds,
        "budget_hints": copy.deepcopy(action.budget_hints),
        "concurrency_limit": action.concurrency_limit,
        "dedupe_strategy": action.dedupe_strategy,
        "cancel_capability": action.cancel_capability,
        "metadata": copy.deepcopy(action.metadata),
    }


def _config_signature(config) -> tuple:
    if config is None:
        from src.config import get_config

        config = get_config()
    return tuple((field, getattr(config, field, None)) for field in _CONFIG_SIGNATURE_FIELDS)


def get_extension_service(config=None, *, refresh: bool = False) -> ExtensionService:
    """Return the process-local ExtensionService singleton."""
    global _SERVICE, _SERVICE_SIGNATURE
    signature = _config_signature(config)
    if refresh or _SERVICE is None or signature != _SERVICE_SIGNATURE:
        if config is None:
            from src.config import get_config

            config = get_config()
        _SERVICE = ExtensionService(config)
        _SERVICE_SIGNATURE = signature
    return _SERVICE


def reset_extension_service() -> None:
    """Reset cached ExtensionService, mainly for tests and config reloads."""
    global _SERVICE, _SERVICE_SIGNATURE
    _SERVICE = None
    _SERVICE_SIGNATURE = None
