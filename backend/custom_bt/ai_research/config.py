from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_AGENT_CONFIG: dict[str, Any] = {
    "agent": {
        "name": "QuantResearchAgent",
        "mode": "prompt_only",
        "default_language": "zh",
        "require_user_confirmation": True,
        "max_candidates_per_round": 30,
        "max_tool_calls_per_round": 8,
    },
    "llm": {
        "provider": "none",
        "model": "none",
        "temperature": 0.2,
        "top_p": 1.0,
        "response_format": "json",
        "timeout_seconds": 120,
    },
    "research_defaults": {
        "pool_id": "liquid_500_864dc25f",
        "target_horizon": 20,
        "holding_period": 20,
        "train_start": "2022-01-14",
        "train_end": "2024-07-26",
        "valid_start": "2024-01-25",
        "valid_end": "2025-07-28",
        "test_start": "2025-01-27",
        "test_end": "2026-06-12",
    },
    "quality_gates": {
        "min_coverage": 0.8,
        "min_valid_ic": 0.02,
        "min_valid_rank_ic": 0.02,
        "min_icir": 0.2,
        "max_turnover": 1.0,
        "require_positive_backtest": True,
    },
    "guardrails": {
        "allow_python_code": False,
        "allow_unknown_fields": False,
        "allow_unknown_operators": False,
        "allow_direct_trading": False,
        "require_identity_lock": True,
        "require_failure_memory": True,
        "require_reflection_memory": True,
        "require_audit_report": True,
        "require_tool_call_limit": True,
    },
    "paths": {
        "master_store": "data_cache/master",
        "pools_root": "data_cache/pools",
        "runtime_root": "data_cache/factor_runtime",
        "factor_runs_root": "factor_runs",
        "saved_results_root": "outputs/saved_backtests",
        "jobs_root": "jobs",
        "ai_research_root": "outputs/ai_research",
    },
}


_REQUIRED_TRUE_GUARDRAILS = (
    "require_identity_lock",
    "require_failure_memory",
    "require_reflection_memory",
    "require_audit_report",
    "require_tool_call_limit",
)
_REQUIRED_FALSE_GUARDRAILS = (
    "allow_python_code",
    "allow_unknown_fields",
    "allow_unknown_operators",
    "allow_direct_trading",
)
_MAX_TOOL_CALLS_PER_ROUND = DEFAULT_AGENT_CONFIG["agent"]["max_tool_calls_per_round"]


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_agent_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load AI research Agent config.

    `None` returns a deep copy of the provider-agnostic defaults. A YAML file is
    merged over defaults so partial local overrides do not accidentally remove
    guardrails such as identity locks or tool-loop limits.
    """

    defaults = deepcopy(DEFAULT_AGENT_CONFIG)
    if path is None:
        return defaults

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"agent config must be a mapping: {config_path}")
    config = _deep_merge(defaults, payload)
    _validate_guardrails(config)
    return config


def _validate_guardrails(config: Mapping[str, Any]) -> None:
    errors: list[str] = []
    guardrails = config.get("guardrails", {})
    agent = config.get("agent", {})

    for key in _REQUIRED_TRUE_GUARDRAILS:
        if guardrails.get(key) is not True:
            errors.append(f"guardrail {key} must remain true")
    for key in _REQUIRED_FALSE_GUARDRAILS:
        if guardrails.get(key) is not False:
            errors.append(f"guardrail {key} must remain false")

    try:
        max_tool_calls = int(agent.get("max_tool_calls_per_round", 0))
    except (TypeError, ValueError):
        errors.append("guardrail max_tool_calls_per_round must be an integer")
    else:
        if max_tool_calls < 1 or max_tool_calls > _MAX_TOOL_CALLS_PER_ROUND:
            errors.append(
                "guardrail max_tool_calls_per_round must be between "
                f"1 and {_MAX_TOOL_CALLS_PER_ROUND}"
            )

    if errors:
        raise ValueError("agent guardrail violation: " + "; ".join(errors))
