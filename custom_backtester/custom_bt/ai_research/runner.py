from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from custom_bt.ai_research.config import load_agent_config
from custom_bt.ai_research.context import build_context_snapshot
from custom_bt.ai_research.llm_client import create_llm_client
from custom_bt.ai_research.memory import ExperimentStore
from custom_bt.ai_research.prompts import (
    SYSTEM_GUARDRAILS,
    build_expression_proposal_prompt,
    build_research_spec_prompt,
    build_tool_plan_prompt,
)
from custom_bt.ai_research.schemas import CandidateExpression, ResearchSpec
from custom_bt.ai_research.tool_executor import AIToolExecutor
from custom_bt.ai_research.tools import validate_candidate_expressions


class AIResearchRunner:
    """Minimal model-backed runner for AI research sessions."""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        config_path: str | Path | None = None,
        client: Any | None = None,
        project_root: str | Path = ".",
        env_path: str | Path = ".env.local",
    ):
        self.project_root = Path(project_root).resolve()
        self.config = dict(config or load_agent_config(config_path))
        self.env_path = Path(env_path)
        if not self.env_path.is_absolute():
            self.env_path = self.project_root / self.env_path
        self.client = client or create_llm_client(self.config, env_path=self.env_path)

    def create_research_spec_session(
        self,
        user_intent: str,
        session_id: str | None = None,
        pool_id: str | None = None,
    ) -> dict[str, Any]:
        context = self._build_context(pool_id=pool_id)
        prompt = build_research_spec_prompt(user_intent, context, self.config)
        llm_response = self.client.complete_json(prompt, system_prompt=SYSTEM_GUARDRAILS)
        research_spec = ResearchSpec.from_mapping(llm_response.parsed)

        store = ExperimentStore(self._path("ai_research_root"))
        session_dir = store.create_session(
            session_id or self._session_id(),
            research_spec.to_dict(),
        )
        store.write_json(session_dir / "context_snapshot.json", context)
        store.write_json(session_dir / "research_spec_prompt.json", {"prompt": prompt})
        store.write_json(session_dir / "research_spec_llm_response.json", llm_response.to_dict())

        return {
            "session_dir": session_dir,
            "research_spec": research_spec.to_dict(),
            "context_snapshot": context,
            "llm_response": llm_response.to_dict(),
        }

    def run_research_session(
        self,
        user_intent: str,
        session_id: str | None = None,
        pool_id: str | None = None,
        max_candidates: int | None = None,
        execute_tools: bool = False,
        execute_long_jobs: bool = False,
    ) -> dict[str, Any]:
        config = self._config_with_max_candidates(max_candidates)
        context = self._build_context(pool_id=pool_id)

        spec_prompt = build_research_spec_prompt(user_intent, context, config)
        spec_response = self.client.complete_json(spec_prompt, system_prompt=SYSTEM_GUARDRAILS)
        research_spec = ResearchSpec.from_mapping(spec_response.parsed)

        store = ExperimentStore(self._path("ai_research_root"))
        session_dir = store.create_session(
            session_id or self._session_id(),
            research_spec.to_dict(),
        )
        store.write_json(session_dir / "context_snapshot.json", context)
        store.write_json(session_dir / "research_spec_prompt.json", {"prompt": spec_prompt})
        store.write_json(session_dir / "research_spec_llm_response.json", spec_response.to_dict())

        expression_prompt = build_expression_proposal_prompt(
            research_spec,
            context,
            config,
            past_failure_memory=[],
        )
        expression_response = self.client.complete_json(expression_prompt, system_prompt=SYSTEM_GUARDRAILS)
        candidate_payloads = self._candidate_payloads(expression_response.parsed)
        candidates = [CandidateExpression.from_mapping(item).to_dict() for item in candidate_payloads]
        validations = validate_candidate_expressions(candidates, context)
        validation_by_id = {item["candidate_id"]: item for item in validations}
        for candidate in candidates:
            candidate["validation"] = validation_by_id.get(candidate["candidate_id"], {})
            store.append_jsonl(session_dir / "candidate_expressions.jsonl", candidate)
        for validation in validations:
            store.append_jsonl(session_dir / "validation_results.jsonl", validation)
        store.write_json(session_dir / "expression_proposal_prompt.json", {"prompt": expression_prompt})
        store.write_json(session_dir / "expression_proposal_llm_response.json", expression_response.to_dict())

        valid_candidates = [
            candidate
            for candidate in candidates
            if validation_by_id.get(candidate["candidate_id"], {}).get("status") == "valid"
        ]
        tool_prompt = build_tool_plan_prompt(research_spec, valid_candidates, context, config)
        tool_response = self.client.complete_json(tool_prompt, system_prompt=SYSTEM_GUARDRAILS)
        store.write_json(session_dir / "tool_plan_prompt.json", {"prompt": tool_prompt})
        tool_plan = self._mapping_payload(tool_response.parsed)
        store.write_json(session_dir / "tool_plan.json", tool_plan)
        store.write_json(session_dir / "tool_plan_llm_response.json", tool_response.to_dict())

        tool_execution: dict[str, Any] = {
            "tool_call_count": 0,
            "created_job_count": 0,
            "finished_job_count": 0,
            "failed_tool_call_count": 0,
            "execute_long_jobs": bool(execute_long_jobs),
            "results": [],
        }
        if execute_tools:
            executor = AIToolExecutor(
                config=config,
                context=context,
                store=store,
                session_dir=session_dir,
                project_root=self.project_root,
                candidates=valid_candidates,
                execute_long_jobs=execute_long_jobs,
            )
            tool_execution = executor.execute_plan(tool_plan)
            store.write_json(session_dir / "tool_execution.json", tool_execution)
        else:
            store.write_json(session_dir / "tool_execution.json", tool_execution)

        summary = {
            "session_id": session_dir.name,
            "candidate_count": len(candidates),
            "valid_candidate_count": len(valid_candidates),
            "invalid_candidate_count": len(candidates) - len(valid_candidates),
            "tool_call_count": len(tool_plan.get("tool_plan", [])),
            "executed_tool_call_count": int(tool_execution.get("tool_call_count", 0)),
            "created_job_count": int(tool_execution.get("created_job_count", 0)),
            "finished_job_count": int(tool_execution.get("finished_job_count", 0)),
            "failed_tool_call_count": int(tool_execution.get("failed_tool_call_count", 0)),
            "session_dir": str(session_dir),
        }
        store.write_json(session_dir / "summary.json", summary)
        report_path = session_dir / "report.md"
        report_path.write_text(
            self._local_report(user_intent, research_spec.to_dict(), candidates, validations, summary),
            encoding="utf-8",
        )
        store.append_memory(
            "reflections",
            {
                "session_id": session_dir.name,
                "objective": research_spec.objective,
                "candidate_count": len(candidates),
                "valid_candidate_count": len(valid_candidates),
            },
        )

        return {
            "session_dir": session_dir,
            "research_spec": research_spec.to_dict(),
            "candidates": candidates,
            "validations": validations,
            "tool_plan": tool_plan,
            "tool_execution": tool_execution,
            "summary": summary,
        }

    def _build_context(self, pool_id: str | None = None) -> dict[str, Any]:
        defaults = self.config.get("research_defaults", {})
        return build_context_snapshot(
            self._path("master_store"),
            self._path("pools_root"),
            self._path("factor_runs_root"),
            self._path("saved_results_root"),
            pool_id=pool_id or defaults.get("pool_id"),
        )

    def _path(self, key: str) -> Path:
        value = Path(self.config.get("paths", {}).get(key, ""))
        if value.is_absolute():
            return value
        return self.project_root / value

    def _config_with_max_candidates(self, max_candidates: int | None) -> dict[str, Any]:
        config = dict(self.config)
        config["agent"] = dict(config.get("agent", {}))
        if max_candidates is not None:
            config["agent"]["max_candidates_per_round"] = int(max_candidates)
        return config

    @staticmethod
    def _candidate_payloads(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, Mapping):
            items = payload.get("candidates", [])
        else:
            items = payload
        if not isinstance(items, list):
            raise ValueError("expression proposal response must be a JSON array or {candidates: [...]}")
        return [dict(item) for item in items]

    @staticmethod
    def _mapping_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("LLM response must be a JSON object")
        return dict(payload)

    @staticmethod
    def _local_report(
        user_intent: str,
        research_spec: Mapping[str, Any],
        candidates: list[dict[str, Any]],
        validations: list[dict[str, Any]],
        summary: Mapping[str, Any],
    ) -> str:
        lines = [
            "# AI 因子研究报告",
            "",
            "## 研究目标",
            str(user_intent),
            "",
            "## Research Spec",
            f"- objective: {research_spec.get('objective', '')}",
            f"- pool_id: {research_spec.get('pool_id', '')}",
            f"- target_horizon: {research_spec.get('target_horizon', '')}",
            "",
            "## 候选生成概况",
            f"- candidate_count: {summary.get('candidate_count', 0)}",
            f"- valid_candidate_count: {summary.get('valid_candidate_count', 0)}",
            f"- invalid_candidate_count: {summary.get('invalid_candidate_count', 0)}",
            "",
            "## 本地表达式校验",
        ]
        validation_by_id = {item["candidate_id"]: item for item in validations}
        for candidate in candidates:
            validation = validation_by_id.get(candidate.get("candidate_id"), {})
            lines.append(
                "- {candidate_id}: {status} `{expression}`".format(
                    candidate_id=candidate.get("candidate_id", ""),
                    status=validation.get("status", "unknown"),
                    expression=candidate.get("expression", ""),
                )
            )
            if validation.get("errors"):
                lines.append(f"  errors: {'; '.join(validation['errors'])}")
        lines.extend(["", "## 下一轮研究方向", "- 对 valid 候选进入回测或组合评估。"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _session_id() -> str:
        return "research_" + time.strftime("%Y%m%d_%H%M%S")
