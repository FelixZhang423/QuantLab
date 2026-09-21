from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from custom_bt.ai_research.memory import ExperimentStore
from custom_bt.ai_research.prompts import TOOL_WHITELIST
from custom_bt.ai_research.tools import validate_candidate_expression
from custom_bt.canonical_expression import normalize_expression
from custom_bt.platform_jobs import create_platform_job, run_platform_job


_LONG_JOB_TO_OPERATION = {
    "create_factor_generation_job": "generate_factors",
    "create_factor_backtest_job": "backtest_factors",
    "create_composition_job": "compose_factors",
}


class AIToolExecutor:
    """Execute a guarded AI research tool plan against local platform tools."""

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        context: Mapping[str, Any],
        store: ExperimentStore,
        session_dir: str | Path,
        project_root: str | Path = ".",
        candidates: Sequence[Mapping[str, Any]] | None = None,
        execute_long_jobs: bool = False,
    ) -> None:
        self.config = dict(config)
        self.context = dict(context)
        self.store = store
        self.session_dir = Path(session_dir).resolve()
        self.project_root = Path(project_root).resolve()
        self.candidates = [dict(item) for item in (candidates or [])]
        self.candidates_by_id = {
            str(item.get("candidate_id")): item
            for item in self.candidates
            if item.get("candidate_id") is not None
        }
        self.execute_long_jobs = bool(execute_long_jobs)

    def execute_plan(self, tool_plan: Mapping[str, Any]) -> dict[str, Any]:
        calls = self._tool_calls(tool_plan)
        max_tool_calls = int(self.config.get("agent", {}).get("max_tool_calls_per_round", 8))
        requested_max = int(tool_plan.get("max_tool_calls") or max_tool_calls)
        limit = min(max_tool_calls, requested_max)
        if len(calls) > limit:
            raise ValueError(f"tool plan exceeds max_tool_calls: {len(calls)} > {limit}")

        results: list[dict[str, Any]] = []
        for index, call in enumerate(calls, start=1):
            result = self._execute_call(index, call)
            results.append(result)
            self.store.append_jsonl(self.session_dir / "tool_results.jsonl", result)

        summary = {
            "tool_call_count": len(results),
            "created_job_count": sum(1 for item in results if item.get("job_dir")),
            "finished_job_count": sum(1 for item in results if item.get("status") == "finished"),
            "failed_tool_call_count": sum(1 for item in results if item.get("status") in {"failed", "rejected"}),
            "execute_long_jobs": self.execute_long_jobs,
            "results": results,
        }
        self.store.write_json(self.session_dir / "tool_execution.json", summary)
        return summary

    @staticmethod
    def _tool_calls(tool_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
        calls = tool_plan.get("tool_plan", [])
        if not isinstance(calls, list):
            raise ValueError("tool_plan must contain a JSON array named tool_plan")
        return [dict(item) for item in calls]

    def _execute_call(self, index: int, call: Mapping[str, Any]) -> dict[str, Any]:
        tool_name = str(call.get("tool_name", "")).strip()
        arguments = call.get("arguments") or {}
        if not isinstance(arguments, Mapping):
            return self._result(index, tool_name, "rejected", error="tool arguments must be a JSON object")
        arguments = dict(arguments)
        if tool_name not in TOOL_WHITELIST:
            return self._result(index, tool_name, "rejected", error=f"tool is not whitelisted: {tool_name}")

        try:
            self._check_identity(arguments)
            if tool_name == "list_context":
                return self._result(index, tool_name, "ok", result=self._list_context())
            if tool_name == "validate_expression":
                return self._result(index, tool_name, "ok", result=self._validate_expression(arguments))
            if tool_name == "write_experiment_memory":
                return self._write_experiment_memory(index, tool_name, arguments)
            if tool_name == "load_saved_results":
                return self._result(index, tool_name, "ok", result=self._load_saved_results(arguments))
            if tool_name in _LONG_JOB_TO_OPERATION:
                payload = self._platform_payload(tool_name, arguments)
                return self._create_or_run_job(index, tool_name, _LONG_JOB_TO_OPERATION[tool_name], payload)
        except Exception as exc:
            return self._result(index, tool_name, "failed", error=f"{type(exc).__name__}: {exc}")
        return self._result(index, tool_name, "rejected", error=f"unsupported tool: {tool_name}")

    @staticmethod
    def _result(
        index: int,
        tool_name: str,
        status: str,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
        job_dir: str | None = None,
        run_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "call_index": index,
            "tool_name": tool_name,
            "status": status,
        }
        if result is not None:
            payload["result"] = dict(result)
        if error:
            payload["error"] = error
        if job_dir:
            payload["job_dir"] = job_dir
        if run_result is not None:
            payload["run_result"] = dict(run_result)
        return payload

    def _check_identity(self, arguments: Mapping[str, Any]) -> None:
        identity = self.context.get("identity_lock", {}) or {}
        for key in ("pool_id", "source_signature"):
            expected = str(identity.get(key) or "").strip()
            actual = str(arguments.get(key) or "").strip()
            if expected and actual and actual != expected:
                raise ValueError(f"{key} does not match identity_lock")

    def _list_context(self) -> dict[str, Any]:
        fields = self.context.get("master_store", {}).get("fields", [])
        operators = self.context.get("operators", [])
        return {
            "identity_lock": dict(self.context.get("identity_lock", {}) or {}),
            "selected_pool": dict(self.context.get("selected_pool", {}) or {}),
            "field_count": len(fields),
            "operator_count": len(operators),
            "recent_factor_run_count": len(self.context.get("recent_factor_runs", []) or []),
            "saved_result_count": len(self.context.get("saved_results", []) or []),
        }

    def _validate_expression(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        candidate = self._candidate_from_arguments(arguments)
        if candidate is None:
            candidate = {
                "candidate_id": str(arguments.get("candidate_id") or "ad_hoc"),
                "expression": str(arguments.get("expression") or ""),
            }
        return validate_candidate_expression(candidate, self.context)

    def _write_experiment_memory(
        self,
        index: int,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        memory_name = str(arguments.get("memory_name") or "reflections")
        payload = arguments.get("payload")
        if not isinstance(payload, Mapping):
            payload = {key: value for key, value in arguments.items() if key not in {"memory_name", "pool_id", "source_signature"}}
        path = self.store.append_memory(memory_name, dict(payload))
        return self._result(index, tool_name, "ok", result={"memory_path": str(path)})

    def _platform_payload(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool_name == "create_factor_generation_job":
            return self._generation_payload(arguments)
        if tool_name == "create_factor_backtest_job":
            return self._backtest_payload(arguments)
        if tool_name == "create_composition_job":
            return self._composition_payload(arguments)
        raise ValueError(f"unsupported platform tool: {tool_name}")

    def _create_or_run_job(
        self,
        index: int,
        tool_name: str,
        operation: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        job_dir = create_platform_job(self._path("jobs_root", "jobs"), operation, payload)
        if not self.execute_long_jobs:
            return self._result(index, tool_name, "created", job_dir=str(job_dir), result={"operation": operation})
        run_result = run_platform_job(job_dir)
        return self._result(
            index,
            tool_name,
            "finished",
            job_dir=str(job_dir),
            result={"operation": operation},
            run_result=run_result,
        )

    def _generation_payload(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        defaults = self.config.get("research_defaults", {}) or {}
        fields = self._validated_fields(arguments.get("fields") or self.context.get("master_store", {}).get("fields", []))
        if "close" not in fields:
            fields = ["close", *fields]
        generation_config = dict(arguments.get("generation_config") or {})
        if "target_factor_count" in arguments:
            generation_config["target_factor_count"] = int(arguments["target_factor_count"])
        if "max_attempts" in arguments:
            generation_config["max_attempts"] = int(arguments["max_attempts"])
        quality = dict(generation_config.get("quality") or {})
        gates = self.config.get("quality_gates", {}) or {}
        if gates.get("min_coverage") is not None:
            quality.setdefault("min_coverage", gates.get("min_coverage"))
        if gates.get("min_valid_ic") is not None:
            quality.setdefault("min_valid_ic", gates.get("min_valid_ic"))
        if gates.get("min_icir") is not None:
            quality.setdefault("min_icir", gates.get("min_icir"))
        if quality:
            generation_config["quality"] = quality

        return {
            "master_store": str(self._path("master_store", "data_cache/master")),
            "pools_root": str(self._path("pools_root", "data_cache/pools")),
            "pool_id": self._pool_id(arguments),
            "runtime_root": str(self._path("runtime_root", "data_cache/factor_runtime")),
            "factor_runs_root": str(self._path("factor_runs_root", "factor_runs")),
            "fields": fields,
            "splits": dict(arguments.get("splits") or self._splits(defaults)),
            "max_backtrack_days": int(arguments.get("max_backtrack_days") or 100),
            "target_horizon": int(arguments.get("target_horizon") or defaults.get("target_horizon", 20)),
            "max_future_days": int(arguments.get("max_future_days") or defaults.get("target_horizon", 20)),
            "generation_config": generation_config,
        }

    def _backtest_payload(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        factor_run_dir = arguments.get("factor_run_dir")
        if not factor_run_dir:
            factor_run_dir = self._materialize_candidate_factor_run(arguments)
        return {
            "master_store": str(self._path("master_store", "data_cache/master")),
            "pools_root": str(self._path("pools_root", "data_cache/pools")),
            "factor_run_dir": str(Path(factor_run_dir).expanduser().resolve()),
            "outputs_root": str(self._path("saved_results_root", "outputs/saved_backtests")),
            "backtest_config": dict(arguments.get("backtest_config") or self._backtest_config()),
            "expected_pool_id": self._pool_id(arguments),
        }

    def _composition_payload(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        factor_run_dirs = list(arguments.get("factor_run_dirs") or [])
        if not factor_run_dirs and arguments.get("factor_run_dir"):
            factor_run_dirs = [arguments.get("factor_run_dir")]
        if not factor_run_dirs and arguments.get("candidate_ids"):
            factor_run_dirs = [self._materialize_candidate_factor_run(arguments)]
        if not factor_run_dirs:
            raise ValueError("create_composition_job requires factor_run_dirs or candidate_ids")
        return {
            "master_store": str(self._path("master_store", "data_cache/master")),
            "pools_root": str(self._path("pools_root", "data_cache/pools")),
            "pool_id": self._pool_id(arguments),
            "factor_run_dirs": [str(Path(item).expanduser().resolve()) for item in factor_run_dirs],
            "outputs_root": str(self._path("saved_results_root", "outputs/saved_backtests")),
            "backtest_config": dict(arguments.get("backtest_config") or self._backtest_config()),
            "selection_metric": str(arguments.get("selection_metric") or "score"),
            "min_score": arguments.get("min_score"),
            "min_ic": arguments.get("min_ic"),
            "min_rank_ic": arguments.get("min_rank_ic"),
            "min_coverage": arguments.get("min_coverage"),
            "min_backtest_sharpe": arguments.get("min_backtest_sharpe"),
            "mutual_ic_threshold": float(arguments.get("mutual_ic_threshold") or 0.99),
            "sweep_sizes": arguments.get("sweep_sizes"),
            "max_factors": int(arguments.get("max_factors") or 100),
            "target_horizon": int(arguments.get("target_horizon") or self.config.get("research_defaults", {}).get("target_horizon", 20)),
        }

    def _materialize_candidate_factor_run(self, arguments: Mapping[str, Any]) -> Path:
        selected = self._selected_candidates(arguments.get("candidate_ids"))
        if not selected:
            raise ValueError("no valid candidates available for factor run materialization")
        pool_id = self._pool_id(arguments)
        source_signature = self._source_signature(arguments)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "session": self.session_dir.name,
                    "pool_id": pool_id,
                    "source_signature": source_signature,
                    "candidates": [
                        {
                            "candidate_id": item.get("candidate_id"),
                            "expression": item.get("expression"),
                        }
                        for item in selected
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:10]
        run_id = str(arguments.get("factor_run_id") or f"ai_{self.session_dir.name}_{digest}")
        factor_run_dir = self._path("factor_runs_root", "factor_runs") / run_id
        factor_run_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for item in selected:
            expression = normalize_expression(str(item.get("expression") or ""))
            rows.append(
                {
                    "candidate_id": item.get("candidate_id"),
                    "hypothesis_id": item.get("hypothesis_id", ""),
                    "expression": expression,
                    "canonical_expression": expression,
                    "backtest_expression": expression,
                    "accepted": True,
                    "reason": "ai_research_candidate",
                    "pool_id": pool_id,
                    "source_signature": source_signature,
                    "runtime_id": "ai_research_session",
                    "rationale": item.get("rationale", ""),
                    "expected_direction": item.get("expected_direction", "unknown"),
                }
            )
        with (factor_run_dir / "accepted_factors.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        manifest = {
            "run_id": run_id,
            "factor_run_dir": str(factor_run_dir),
            "pool_id": pool_id,
            "source_signature": source_signature,
            "runtime_id": "ai_research_session",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "accepted_count": len(rows),
            "attempts": len(rows),
            "target_reached": True,
            "attempts_exhausted": False,
            "ai_research_session": self.session_dir.name,
        }
        (factor_run_dir / "factor_run.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self.store.write_json(self.session_dir / "materialized_factor_run.json", manifest)
        return factor_run_dir

    def _selected_candidates(self, candidate_ids: Any) -> list[dict[str, Any]]:
        requested = [str(item) for item in candidate_ids] if isinstance(candidate_ids, list) else []
        selected = []
        for candidate in self.candidates:
            if requested and str(candidate.get("candidate_id")) not in requested:
                continue
            validation = candidate.get("validation") or {}
            if validation.get("status") != "valid":
                continue
            selected.append(dict(candidate))
        return selected

    def _candidate_from_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
        candidate_id = str(arguments.get("candidate_id") or "").strip()
        if candidate_id and candidate_id in self.candidates_by_id:
            return dict(self.candidates_by_id[candidate_id])
        return None

    def _load_saved_results(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        root = self._path("saved_results_root", "outputs/saved_backtests")
        pool_id = str(arguments.get("pool_id") or self.context.get("identity_lock", {}).get("pool_id") or "").strip()
        result_type = str(arguments.get("result_type") or "").strip()
        limit = int(arguments.get("limit") or 20)
        results: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        for manifest_path in sorted(root.glob("**/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if pool_id and str(manifest.get("pool_id") or "") != pool_id:
                continue
            if result_type and str(manifest.get("result_type") or "") != result_type:
                continue
            compact = dict(manifest)
            compact["manifest_path"] = str(manifest_path)
            results.append(compact)
            summaries.extend(self._read_summary_rows(manifest_path.parent))
            if len(results) >= limit:
                break
        return {
            "result_count": len(results),
            "results": results,
            "summaries": summaries[:limit],
        }

    @staticmethod
    def _read_summary_rows(directory: Path) -> list[dict[str, Any]]:
        for name in ("factor_backtest_summary.csv", "composition_run_summary.csv", "summary.csv"):
            path = directory / name
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                return [dict(row) for row in csv.DictReader(fh)]
        summary_json = directory / "summary.json"
        if summary_json.exists():
            try:
                return [json.loads(summary_json.read_text(encoding="utf-8"))]
            except json.JSONDecodeError:
                return []
        return []

    def _validated_fields(self, fields: Any) -> list[str]:
        allowed = {str(item) for item in self.context.get("master_store", {}).get("fields", [])}
        selected = list(dict.fromkeys(str(item) for item in (fields or [])))
        unknown = [item for item in selected if allowed and item not in allowed]
        if unknown:
            raise ValueError("fields are not in context whitelist: " + ", ".join(unknown))
        return selected

    def _splits(self, defaults: Mapping[str, Any]) -> dict[str, dict[str, str]]:
        return {
            "train": {"cache_start": str(defaults.get("train_start", "")), "cache_end": str(defaults.get("train_end", ""))},
            "valid": {"cache_start": str(defaults.get("valid_start", "")), "cache_end": str(defaults.get("valid_end", ""))},
            "test": {"cache_start": str(defaults.get("test_start", "")), "cache_end": str(defaults.get("test_end", ""))},
        }

    def _backtest_config(self) -> dict[str, Any]:
        configured = self.config.get("backtest") or {}
        if configured:
            return dict(configured)
        master = self.context.get("master_store", {}) or {}
        defaults = self.config.get("research_defaults", {}) or {}
        return {
            "start_date": str(master.get("date_min") or defaults.get("test_start") or defaults.get("train_start") or "2021-01-01"),
            "end_date": str(master.get("date_max") or defaults.get("test_end") or defaults.get("train_end") or "2026-12-31"),
            "top_k": 50,
            "rebalance_freq": "1D",
            "price": "next_open",
            "initial_cash": 100000000,
            "buy_cost": 0.0015,
            "sell_cost": 0.0015,
            "slippage": 0.0005,
            "min_cost": 5,
            "max_weight_per_stock": 0.02,
            "exclude_limit_up_buy": True,
            "exclude_limit_down_sell": True,
        }

    def _pool_id(self, arguments: Mapping[str, Any]) -> str:
        return str(
            arguments.get("pool_id")
            or self.context.get("identity_lock", {}).get("pool_id")
            or self.config.get("research_defaults", {}).get("pool_id")
            or ""
        ).strip()

    def _source_signature(self, arguments: Mapping[str, Any]) -> str:
        return str(
            arguments.get("source_signature")
            or self.context.get("identity_lock", {}).get("source_signature")
            or self.context.get("master_store", {}).get("source_signature")
            or ""
        ).strip()

    def _path(self, key: str, default: str) -> Path:
        raw = self.config.get("paths", {}).get(key, default)
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.project_root / path).resolve()
