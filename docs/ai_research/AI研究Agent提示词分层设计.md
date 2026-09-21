# AI 研究 Agent 提示词分层设计

日期：2026-08-20

## 1. 为什么要分层

量化 Agent 的提示词不能写成一个“大而全”的长 prompt。原因是：

- 不同阶段的任务不同：任务澄清、字段检索、假设生成、表达式生成、审计报告不该混在一起；
- 每一层都需要不同的输出格式；
- 分层后才能版本化、测试和复盘；
- 出错时可以定位是哪一层出问题，而不是整段 prompt 玄学调参。

建议所有提示词都带版本号：

```text
prompt_version: ai_research_agent.v1.<layer>
```

## 2. 从 `提示词合集/` 抽象出的设计模式

`提示词合集/` 的原始目标偏交易分析，当前项目只参考其提示词工程结构，不复制具体交易话术。

可迁移到当前系统的模式：

- **工具优先**：先获取真实数据和上下文，再输出分析。
- **身份一致性**：在多轮提示词里锁定标的身份。当前项目应锁定 `pool_id`、`source_signature`、日期切分和操作符版本。
- **结构化抽取**：用 JSON schema 抽取决策。当前项目应抽取 Research Spec、候选表达式、工具计划和审计结论。
- **多视角辩论**：把“看涨/看跌/风控”改造成“有效性支持/风险质疑/审计裁决”。
- **反思记忆**：把过去错误注入当前任务。当前项目应注入历史失败因子、重复结构、样本外失效和高换手案例。
- **工具防死循环**：每层限制工具调用次数，工具返回后立即进入下一阶段或报告阶段。
- **兜底输出**：工具失败时输出 `review` 或 `blocked`，不能编造数据补齐。

不可迁移的内容：

- 不使用买入/持有/卖出作为主输出；
- 不要求模型给目标价；
- 不要求模型在信息不足时强行明确交易建议；
- 不使用新闻/基本面工具作为第一版核心，因为当前主数据是日频量价与技术字段。

## 3. L0：系统护栏 Prompt

用途：所有子任务共享的硬边界。

核心内容：

```text
你是量化研究 Agent，不是投资顾问，也不是交易执行系统。
你只能在给定字段、给定操作符和给定工具白名单内工作。
你不能凭空创造字段。
你不能输出 Python 代码。
你不能绕过表达式校验。
你不能把单次回测结果解释为无条件投资建议。
你不能静默改变 pool_id、source_signature、时间切分或成本配置。
如果工具数据缺失，你必须返回 review 或 blocked，不允许编造。
你必须记录失败候选和风险。
你必须输出严格 JSON，除非明确要求输出研究报告 Markdown。
```

输出要求：L0 本身不产生业务输出，只作为所有层的 system instruction。

## 4. L1：Research Spec Compiler Prompt

用途：把用户自然语言转成结构化研究任务。

输入：

```json
{
  "user_intent": "找一些适合 liquid_500 的中期量价因子，希望回撤低一点。",
  "available_pools": ["liquid_500_864dc25f"],
  "default_horizon": 20,
  "default_metrics": ["ic", "rank_ic", "icir", "annual_return", "max_drawdown", "turnover"],
  "identity_lock": {
    "source_signature": "8afffe05...",
    "default_pool_id": "liquid_500_864dc25f"
  }
}
```

输出 schema：

```json
{
  "objective": "string",
  "pool_id": "string",
  "target_horizon": 20,
  "holding_period": 20,
  "factor_style": ["string"],
  "preferred_fields": ["string"],
  "metrics": ["string"],
  "constraints": ["string"],
  "success_criteria": {
    "min_valid_ic": 0.02,
    "min_valid_rank_ic": 0.02,
    "min_icir": 0.2,
    "max_turnover": 1.0,
    "require_positive_backtest": true
  },
  "clarifying_questions": []
}
```

规则：

- 如果用户没有指定股票池，使用配置默认股票池，并在输出中显式标记；
- 如果用户没有指定持有期，使用默认 `target_horizon`；
- 如果缺失的信息会显著改变结果，写入 `clarifying_questions`；
- 输出必须携带或继承 `identity_lock`，后续不能静默更改；
- 不允许直接输出候选表达式。

## 5. L2：Context Summary Prompt

用途：把当前项目上下文压缩成模型可读事实。

输入来自 `ContextRetriever`：

```json
{
  "master_store": {
    "n_stocks": 5432,
    "date_min": "2021-06-18",
    "date_max": "2026-06-16",
    "fields": ["open", "close", "volume"]
  },
  "pools": [{"pool_id": "liquid_500_864dc25f", "n_stocks": 500}],
  "operators": [{"name": "rank", "category": "cross_section"}],
  "recent_factor_runs": [],
  "recent_failures": [],
  "identity_lock": {
    "pool_id": "liquid_500_864dc25f",
    "source_signature": "8afffe05..."
  }
}
```

输出：

```json
{
  "usable_fields": ["string"],
  "usable_operators": ["string"],
  "recommended_field_groups": {
    "price": ["open", "close", "high", "low", "vwap"],
    "volume": ["volume", "amount", "TurnoverRate"],
    "technical": ["macd", "kdj_k", "ma20"]
  },
  "warnings": ["string"]
}
```

规则：

- 只能总结上下文中真实存在的字段和操作符；
- 如果字段语义不确定，标记为 `warnings`，不能擅自解释；
- 必须保留 `identity_lock`，不得在摘要中改写；
- 不输出回测结论。

## 6. L3：Hypothesis Generator Prompt

用途：生成经济假设。

输出 schema：

```json
[
  {
    "hypothesis_id": "hyp_001",
    "mechanism": "string",
    "expected_direction": "positive|negative|unknown",
    "horizon": 20,
    "preferred_fields": ["string"],
    "preferred_operators": ["string"],
    "failure_modes": ["string"]
  }
]
```

规则：

- 每个假设必须包含机制和失败条件；
- 假设不等于事实，不能写成确定收益；
- 假设必须能被表达式和回测验证。

## 7. L4：Expression Proposer Prompt

用途：把假设转成候选表达式。

输入：

```json
{
  "research_spec": {},
  "hypotheses": [],
  "allowed_fields": [],
  "allowed_operators": [],
  "max_candidates": 30,
  "past_failure_memory": []
}
```

输出 schema：

```json
[
  {
    "candidate_id": "cand_001",
    "hypothesis_id": "hyp_001",
    "expression": "rank(ts_mean(volume, 20) / volume)",
    "expected_direction": "negative",
    "rationale": "string",
    "used_fields": ["volume"],
    "used_operators": ["rank", "ts_mean", "divide"],
    "complexity_estimate": 4
  }
]
```

硬规则：

- `used_fields` 必须是 `allowed_fields` 的子集；
- `used_operators` 必须是 `allowed_operators` 的子集；
- 表达式中不能出现未来收益、未来价格或标签字段；
- 不允许自然语言公式；
- 不允许 Python 代码；
- 不允许输出重复表达式；
- 候选数量不能超过 `max_candidates`。
- 如果候选与 `past_failure_memory` 中失败模式高度相似，必须调整结构或标记 `risk_flags`。

## 8. L5：Tool Planner Prompt

用途：把候选研究动作转成工具调用计划。

输出 schema：

```json
{
  "tool_plan": [
    {
      "tool_name": "validate_expression",
      "arguments": {
        "expression": "rank(close)"
      }
    },
    {
      "tool_name": "write_experiment_memory",
      "arguments": {
        "candidate_id": "cand_001",
        "status": "proposed"
      }
    }
  ],
  "requires_user_confirmation": true,
  "max_tool_calls": 8,
  "stop_after_report": true
}
```

工具白名单：

```text
list_context
validate_expression
write_experiment_memory
create_factor_generation_job
create_factor_backtest_job
create_composition_job
load_saved_results
```

第一版所有长耗时任务必须 `requires_user_confirmation: true`。

工具计划规则：

- 只能使用工具白名单；
- 每轮工具调用不能超过 `max_tool_calls`；
- 如果工具返回可用结果，进入审计或报告，不重复调用同一工具；
- 工具失败时记录失败原因，不能编造工具结果；
- 长耗时任务必须等待用户确认。

## 9. L6：Research Debate Prompt

用途：用单 Agent 模拟多视角研究辩论，降低单一模型自我说服。

输入：

```json
{
  "candidate": {},
  "metrics": {},
  "backtest_summary": {},
  "past_memory": []
}
```

输出 schema：

```json
{
  "evidence_advocate": ["string"],
  "skeptical_reviewer": ["string"],
  "risk_judge": {
    "decision": "accept|reject|review",
    "required_checks": ["string"]
  }
}
```

规则：

- `evidence_advocate` 只能引用已有指标和回测结果；
- `skeptical_reviewer` 必须指出至少一种可能失效原因；
- `risk_judge` 不能因为解释好听就 accept，必须看质量门槛。

## 10. L7：Result Auditor Prompt

用途：审计结果。

输入：

```json
{
  "candidate": {},
  "metrics": {},
  "backtest_summary": {},
  "similar_history": [],
  "quality_gates": {}
}
```

输出 schema：

```json
{
  "decision": "accept|reject|review",
  "reasons": ["string"],
  "risk_flags": ["string"],
  "metric_summary": {
    "ic": 0.03,
    "rank_ic": 0.04,
    "icir": 0.3,
    "annual_return": 0.12,
    "max_drawdown": -0.08,
    "turnover": 0.5
  },
  "next_actions": ["string"]
}
```

规则：

- 如果样本外指标缺失，不能 accept；
- 如果只看到样本内结果，最多 review；
- 如果失败，也要说明失败类型；
- 如果疑似重复历史失败表达式，必须标记。

## 11. L8：Research Reporter Prompt

用途：把整个 session 变成用户可读报告。

输出 Markdown 结构：

```text
# AI 因子研究报告

## 研究目标
## 数据与股票池
## 候选生成概况
## 通过候选
## 拒绝候选与失败原因
## 回测与风险审计
## 组合建议
## 下一轮研究方向
```

报告要求：

- 必须写清股票池、时间范围、持有期、成本假设；
- 必须同时展示成功和失败；
- 不能写“必然上涨”“确定有效”；
- 推荐只能写成条件性研究结论。

## 12. L9：Reflection Memory Prompt

用途：把本次研究结果压缩成可用于下一轮检索的经验。

输入：

```json
{
  "research_spec": {},
  "accepted_candidates": [],
  "rejected_candidates": [],
  "audit_report": {}
}
```

输出 schema：

```json
{
  "lessons": [
    {
      "pattern": "string",
      "outcome": "worked|failed|uncertain",
      "reason": "string",
      "reuse_when": ["string"],
      "avoid_when": ["string"]
    }
  ],
  "query_summary": "string"
}
```

规则：

- 失败经验和成功经验都要写；
- 不能把不确定结果写成稳定规律；
- `query_summary` 应便于后续相似检索。

## 13. Prompt 版本管理

建议后续新增：

```text
custom_backtester/custom_bt/ai_research/prompts/
  l0_system.md
  l1_research_spec.md
  l2_context_summary.md
  l3_hypothesis.md
  l4_expression_proposal.md
  l5_tool_plan.md
  l6_research_debate.md
  l7_audit.md
  l8_report.md
  l9_reflection.md
```

第一阶段可先用 Python 字符串模板实现，等流程稳定后再拆成独立 prompt 文件。
