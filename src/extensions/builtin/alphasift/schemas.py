# -*- coding: utf-8 -*-
"""Action schemas for the built-in AlphaSift extension."""

HEALTHCHECK_INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

LIST_STRATEGIES_INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

SCREEN_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "market": {
            "type": "string",
            "enum": ["cn"],
            "default": "cn",
            "description": "Market universe to screen.",
        },
        "strategy": {
            "type": "string",
            "default": "dual_low",
            "description": "AlphaSift strategy id.",
        },
        "max_results": {
            "type": "integer",
            "default": 20,
            "minimum": 1,
            "maximum": 200,
            "description": "Maximum candidates to keep.",
        },
        "dry_run": {
            "type": "boolean",
            "default": False,
            "description": "Validate inputs and adapter availability without running a full scan.",
        },
        "use_llm": {
            "type": "boolean",
            "default": False,
            "description": "Whether AlphaSift should use its own LLM ranking step.",
        },
    },
    "required": ["market", "strategy"],
    "additionalProperties": False,
}

ANALYZE_TOP_PICKS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["code"],
                "additionalProperties": True,
            },
            "minItems": 1,
            "maxItems": 50,
        },
        "top_n": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        "report_type": {"type": "string", "default": "detailed"},
        "notify": {"type": "boolean", "default": False},
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

IMPORT_PICKS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["code"],
                "additionalProperties": True,
            },
            "minItems": 1,
            "maxItems": 200,
        },
        "merge": {
            "type": "boolean",
            "default": True,
            "description": "Merge with the existing STOCK_LIST instead of replacing it.",
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}
