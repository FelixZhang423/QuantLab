from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from custom_bt.ai_research.schemas import ResearchSpec


SYSTEM_GUARDRAILS = """你是量化研究 Agent，不是投资顾问，也不是交易执行系统。
你只能在给定字段、给定操作符和给定工具白名单内工作。
你不能凭空创造字段或操作符。
你不能输出 Python 代码。
你不能绕过表达式校验。
你不能把单次回测结果解释为无条件投资建议。
你不能静默改变 pool_id、source_signature、时间切分、成本配置或 operator_registry_version。
如果工具数据缺失，你必须返回 review 或 blocked，不允许编造。
你必须记录失败候选、重复结构和风险。
除非明确要求输出 Markdown 报告，否则必须输出严格 JSON。
"""


TOOL_WHITELIST = [
    "list_context",
    "validate_expression",
    "write_experiment_memory",
    "create_factor_generation_job",
    "create_factor_backtest_job",
    "create_composition_job",
    "load_saved_results",
]


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _spec_payload(spec: ResearchSpec | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(spec, ResearchSpec):
        return spec.to_dict()
    return dict(spec)


def _operator_names(context: Mapping[str, Any]) -> list[str]:
    operators = context.get("operators", [])
    names: list[str] = []
    for item in operators:
        if isinstance(item, Mapping):
            name = item.get("name")
        else:
            name = item
        if name:
            names.append(str(name))
    return sorted(set(names))


def build_research_spec_prompt(
    user_intent: str,
    context: Mapping[str, Any],
    config: Mapping[str, Any],
) -> str:
    defaults = config.get("research_defaults", {})
    payload = {
        "user_intent": user_intent,
        "available_pools": [pool.get("pool_id") for pool in context.get("pools", []) if pool.get("pool_id")],
        "default_horizon": defaults.get("target_horizon", 20),
        "default_pool_id": defaults.get("pool_id", ""),
        "identity_lock": context.get("identity_lock", {}),
    }
    schema = {
        "objective": "string",
        "pool_id": "string",
        "target_horizon": 20,
        "holding_period": 20,
        "factor_style": ["string"],
        "preferred_fields": ["string"],
        "metrics": ["string"],
        "constraints": ["string"],
        "success_criteria": {},
        "identity_lock": {},
        "clarifying_questions": [],
    }
    return f"""prompt_version: ai_research_agent.v1.l1_research_spec
{SYSTEM_GUARDRAILS}

任务：把用户自然语言研究目标编译为 Research Spec。
规则：
- 如果用户没有指定股票池，使用 default_pool_id，并在 JSON 中显式写出。
- 输出必须继承 identity_lock，后续层不得静默改写。
- 只做研究任务结构化，不生成表达式。

输入：
{_json(payload)}

输出 schema，必须为严格 JSON：
{_json(schema)}
"""


def build_expression_proposal_prompt(
    spec: ResearchSpec | Mapping[str, Any],
    context: Mapping[str, Any],
    config: Mapping[str, Any],
    past_failure_memory: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    spec_payload = _spec_payload(spec)
    fields = context.get("master_store", {}).get("fields", [])
    operators = _operator_names(context)
    max_candidates = config.get("agent", {}).get("max_candidates_per_round", 30)
    payload = {
        "research_spec": spec_payload,
        "allowed_fields": fields,
        "allowed_operators": operators,
        "max_candidates": max_candidates,
        "identity_lock": context.get("identity_lock") or spec_payload.get("identity_lock", {}),
        "past_failure_memory": list(past_failure_memory or []),
    }
    schema = {
        "candidates": [
            {
                "candidate_id": "cand_001",
                "hypothesis_id": "hyp_001",
                "expression": "rank(ts_mean(volume,20))",
                "expected_direction": "positive|negative|unknown",
                "rationale": "string",
                "used_fields": ["volume"],
                "used_operators": ["rank", "ts_mean"],
                "complexity_estimate": 3,
                "risk_flags": ["string"],
            }
        ]
    }
    return f"""prompt_version: ai_research_agent.v1.l4_expression_proposal
{SYSTEM_GUARDRAILS}

任务：把研究假设转成候选因子表达式。
硬约束：
- 只能使用白名单字段 allowed_fields。
- 只能使用白名单操作符 allowed_operators。
- 不允许自然语言伪公式、Python、SQL 或不存在字段。
- 候选数量不能超过 max_candidates。
- 如果候选与 past_failure_memory 的失败模式高度相似，必须调整结构或在 risk_flags 标记。
- 输出严格 JSON 对象，不要输出解释性正文；候选列表必须放在 candidates 数组中。

输入：
{_json(payload)}

输出 schema：
{_json(schema)}
"""


def build_tool_plan_prompt(
    spec: ResearchSpec | Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
    config: Mapping[str, Any],
) -> str:
    spec_payload = _spec_payload(spec)
    max_tool_calls = config.get("agent", {}).get("max_tool_calls_per_round", 8)
    payload = {
        "research_spec": spec_payload,
        "candidates": list(candidates),
        "identity_lock": context.get("identity_lock") or spec_payload.get("identity_lock", {}),
        "tool_whitelist": TOOL_WHITELIST,
        "max_tool_calls": max_tool_calls,
        "requires_user_confirmation_for_long_jobs": True,
        "stop_after_report": True,
    }
    schema = {
        "tool_plan": [
            {
                "tool_name": "create_factor_backtest_job",
                "arguments": {"candidate_ids": ["cand_001"]},
            }
        ],
        "requires_user_confirmation": True,
        "max_tool_calls": max_tool_calls,
        "stop_after_report": True,
    }
    return f"""prompt_version: ai_research_agent.v1.l5_tool_plan
{SYSTEM_GUARDRAILS}

任务：把候选研究动作转成工具调用计划。
规则：
- 只能选择 tool_whitelist 中的工具。
- 每轮工具调用数量不得超过 max_tool_calls。
- 工具失败时记录失败原因，不能编造工具结果。
- 创建耗时后台任务必须 requires_user_confirmation=true。
- 已通过本地校验的候选如果需要研究评估，优先创建 create_factor_backtest_job，并用 candidate_ids 引用候选。
- 只有需要重新训练 PPO 生成器时才使用 create_factor_generation_job。
- 只有已有回测后的 factor_run_dirs 足够时才使用 create_composition_job。
- 生成报告后本轮停止，不继续调用工具。
- 工具参数必须携带或遵守 identity_lock。

输入：
{_json(payload)}

输出 schema，必须为严格 JSON：
{_json(schema)}
"""


def build_research_debate_prompt(
    candidate: Mapping[str, Any],
    metrics: Mapping[str, Any],
    past_memory: Sequence[Mapping[str, Any]],
) -> str:
    payload = {"candidate": dict(candidate), "metrics": dict(metrics), "past_memory": list(past_memory)}
    schema = {
        "evidence_advocate": ["string"],
        "skeptical_reviewer": ["string"],
        "risk_judge": {
            "decision": "accept|reject|review",
            "required_checks": ["string"],
        },
    }
    return f"""prompt_version: ai_research_agent.v1.l6_research_debate
{SYSTEM_GUARDRAILS}

任务：用单 Agent 的三个固定视角审查候选因子。
- Evidence Advocate：只引用已有指标和回测结果，说明支持有效性的证据。
- Skeptical Reviewer：指出样本外、重复、过拟合、换手或机制薄弱风险。
- Risk Judge：根据质量门槛裁决 accept、reject 或 review。

输入：
{_json(payload)}

输出 schema，必须为严格 JSON：
{_json(schema)}
"""


def build_audit_prompt(
    candidate: Mapping[str, Any],
    metrics: Mapping[str, Any],
    quality_gates: Mapping[str, Any],
    similar_history: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    payload = {
        "candidate": dict(candidate),
        "metrics": dict(metrics),
        "quality_gates": dict(quality_gates),
        "similar_history": list(similar_history or []),
    }
    schema = {
        "decision": "accept|reject|review",
        "reasons": ["string"],
        "risk_flags": ["string"],
        "metric_summary": {},
        "next_actions": ["string"],
    }
    return f"""prompt_version: ai_research_agent.v1.l7_audit
{SYSTEM_GUARDRAILS}

任务：审计候选因子结果，不允许只挑好看的指标。
规则：
- 样本外指标缺失时不能 accept。
- 回测、IC、RankIC、ICIR、换手、回撤和重复度都要审查。
- 如果疑似重复历史失败表达式，必须标记。

输入：
{_json(payload)}

输出 schema，必须为严格 JSON：
{_json(schema)}
"""


def build_report_prompt(
    research_spec: Mapping[str, Any],
    accepted_candidates: Sequence[Mapping[str, Any]],
    rejected_candidates: Sequence[Mapping[str, Any]],
    audit_report: Mapping[str, Any],
) -> str:
    payload = {
        "research_spec": dict(research_spec),
        "accepted_candidates": list(accepted_candidates),
        "rejected_candidates": list(rejected_candidates),
        "audit_report": dict(audit_report),
    }
    return f"""prompt_version: ai_research_agent.v1.l8_report
{SYSTEM_GUARDRAILS}

任务：把本次研究 session 输出为 Markdown 研究报告。
报告结构必须包含：
# AI 因子研究报告
## 研究目标
## 数据与股票池
## 候选生成概况
## 通过候选
## 拒绝候选与失败原因
## 回测与风险审计
## 因子组合研究结论
## 下一轮研究方向

规则：
- 必须写清股票池、时间范围、持有期和成本假设。
- 必须同时展示成功和失败。
- 推荐只能写成条件性研究结论，不能写确定性承诺。

输入：
{_json(payload)}
"""


def build_reflection_prompt(
    research_spec: Mapping[str, Any],
    accepted_candidates: Sequence[Mapping[str, Any]],
    rejected_candidates: Sequence[Mapping[str, Any]],
    audit_report: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "research_spec": dict(research_spec),
        "accepted_candidates": list(accepted_candidates),
        "rejected_candidates": list(rejected_candidates),
        "audit_report": dict(audit_report or {}),
        "memory_target": "reflections.jsonl",
    }
    schema = {
        "lessons": [
            {
                "pattern": "string",
                "outcome": "worked|failed|uncertain",
                "reason": "string",
                "reuse_when": ["string"],
                "avoid_when": ["string"],
            }
        ],
        "query_summary": "string",
    }
    return f"""prompt_version: ai_research_agent.v1.l9_reflection
{SYSTEM_GUARDRAILS}

任务：把本次研究压缩成可写入 reflections.jsonl 的反思记忆。
规则：
- 成功经验和失败经验都要写。
- 不确定结果不能写成稳定规律。
- query_summary 要便于下一轮检索相似失败或成功模式。

输入：
{_json(payload)}

输出 schema，必须为严格 JSON：
{_json(schema)}
"""
