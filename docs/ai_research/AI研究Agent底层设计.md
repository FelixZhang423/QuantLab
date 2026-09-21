# AI 研究 Agent 底层设计

日期：2026-08-20

## 1. 定位

当前项目已经具备确定性的量化执行层：主数据缓存、股票池、统一表达式、PPO 因子生成、单因子回测、多因子组合和保存结果。AI 不应该替代这些确定性模块，也不应该直接给出无条件买卖建议。

AI 研究 Agent 的定位是“研究协作层”：

```text
用户研究想法
  -> 结构化研究任务 Research Spec
  -> 检索当前字段、股票池、历史因子和失败案例
  -> 生成可解释假设
  -> 生成受限表达式候选
  -> 调用现有表达式校验、回测、组合和审计工具
  -> 记录成功与失败
  -> 输出研究报告和下一轮建议
```

因此，第一版 Agent 的目标不是追求复杂多 Agent，而是先做一个可配置、可审计、可保存记忆的 `QuantResearchAgent` 底座。

## 2. 设计原则

1. **LLM 只生成结构化意图、假设、表达式和工具参数，不直接执行 Python 代码。**
2. **所有候选表达式必须经过字段白名单和操作符白名单校验。**
3. **所有回测、IC、RankIC、组合权重和风险指标都由现有确定性代码计算。**
4. **成功和失败候选都必须保存，避免 Agent 反复生成历史失败结构。**
5. **每次研究必须保存模型、提示词版本、数据版本、股票池、时间切分和回测配置。**
6. **第一版只做研究 Agent，不做实盘交易 Agent。**

## 3. 对 `提示词合集/` 的参考方式

`提示词合集/` 来自其他系统，只作为结构参考，不照搬原文。可借鉴的是提示词工程机制，而不是交易建议内容。

可吸收的模式：

1. **角色边界清晰**：原系统把市场、新闻、基本面、研究辩论、交易和风控拆开。当前项目应改造成字段侦察、假设生成、表达式生成、结果审计和报告总结，而不是照搬买入/卖出角色。
2. **工具优先**：原系统强调必须基于工具数据。当前项目也应要求 Agent 先读取主缓存、股票池、字段、操作符和历史实验，再生成表达式。
3. **标的一致性约束**：原系统约束股票代码不能改写。当前项目应约束 `pool_id`、`source_signature`、`runtime_id`、`factor_run_id`、日期切分和成本配置不能被模型静默改写。
4. **结构化输出抽取**：原系统用 JSON 抽取交易信号。当前项目应把 Research Spec、候选表达式、工具计划和审计结论都固定为 JSON schema。
5. **辩论机制**：原系统有看涨/看跌/经理裁决。当前项目不输出买卖辩论，而是做“因子有效性正方、因子风险反方、审计裁决”的研究辩论。
6. **风险多视角**：原系统有激进、中性、保守风险分析。当前项目可对应为“收益潜力审查、稳定性审查、过拟合/成本审查”。
7. **反思记忆**：原系统把历史决策经验注入下一轮。当前项目应把失败因子、重复结构、样本外失效、换手过高和相关性过高的案例注入下一轮候选生成。
8. **工具防死循环**：原系统限制工具调用次数并在报告生成后停止。当前项目也应设置每轮最大工具调用次数、最大候选数量和长任务必须用户确认。

必须避免的照搬：

- 不照搬“买入/持有/卖出”输出目标；
- 不照搬目标价、止损位等交易执行字段；
- 不要求模型给出确定交易建议；
- 不让模型为了“必须明确”而编造数据；
- 不把新闻/基本面 prompt 直接套到当前日频量价数据上。

基于这些参考，当前 Agent 的提示词应更像“量化研究流程控制器”，而不是“股票交易顾问”。

## 4. 单 Agent 的内部层次

第一版只暴露一个主 Agent：

```text
QuantResearchAgent
```

内部拆成 10 个模块：

```text
ResearchSpecCompiler
ContextRetriever
HypothesisGenerator
ExpressionProposer
ToolPlanner
ToolExecutor
ResearchDebate
ResultAuditor
ResearchReporter
MemoryWriter
```

### 4.1 ResearchSpecCompiler

职责：把用户自然语言研究目标编译为结构化任务。

输入示例：

```text
找一些适合 liquid_500 的中期量价因子，希望回撤小一点，持有 20 天。
```

输出示例：

```json
{
  "objective": "寻找中期量价 Alpha",
  "pool_id": "liquid_500_864dc25f",
  "target_horizon": 20,
  "holding_period": 20,
  "factor_style": ["price_volume", "medium_horizon"],
  "preferred_fields": ["close", "volume", "amount", "TurnoverRate", "vwap"],
  "metrics": ["ic", "rank_ic", "icir", "rank_icir", "annual_return", "max_drawdown", "turnover"],
  "constraints": ["no_lookahead", "operator_whitelist_only", "field_whitelist_only"],
  "success_criteria": {
    "min_valid_rank_ic": 0.02,
    "min_icir": 0.2,
    "max_turnover": 1.0,
    "require_positive_backtest": true
  }
}
```

### 4.2 ContextRetriever

职责：读取当前项目上下文，作为提示词和工具调用的事实基础。

读取内容：

- 主缓存元数据：股票数量、字段、日期范围、数据签名；
- 股票池列表：`pool_id`、数量、筛选区间；
- 操作符白名单：名称、分类、签名和示例；
- 因子运行：`factor_runs/<run_id>/factor_run.json`；
- 已保存回测：`outputs/saved_backtests/**/manifest.json`；
- 失败候选和拒绝理由：`accepted_factors.jsonl`、`rejected_candidates.jsonl`、组合拒绝日志。

第一版只做本地文件检索，不做向量数据库。后续再升级 RAG。

同时，ContextRetriever 必须输出“身份锁定信息”：

```json
{
  "identity_lock": {
    "pool_id": "liquid_500_864dc25f",
    "source_signature": "8afffe05...",
    "date_min": "2021-06-18",
    "date_max": "2026-06-16",
    "operator_registry_version": "local"
  }
}
```

后续所有工具计划都必须引用同一组身份信息，避免模型在多轮对话中悄悄换股票池、换数据版本或换时间切分。

### 4.3 HypothesisGenerator

职责：基于 Research Spec 和 Context 生成经济假设，而不是直接生成公式。

输出结构：

```json
{
  "hypothesis_id": "hyp_price_volume_001",
  "mechanism": "放量但价格不能继续上行可能代表资金分歧，后续存在反转压力。",
  "expected_direction": "negative",
  "horizon": 20,
  "preferred_fields": ["close", "volume", "TurnoverRate"],
  "failure_modes": ["高换手", "牛市趋势阶段失效", "和动量因子高度相关"]
}
```

### 4.4 ExpressionProposer

职责：把假设转成候选表达式。

硬约束：

- 只能使用 `ContextRetriever` 返回的字段；
- 只能使用 `operator_registry` 中存在的操作符；
- 必须输出 JSON 数组；
- 每个候选必须包含 `expression`、`canonical_hint`、`hypothesis_id`、`expected_direction`、`rationale`、`used_fields`、`used_operators`；
- 不允许输出 Python、SQL、自然语言伪公式或不存在字段。

候选示例：

```json
{
  "expression": "rank(ts_corr(rank(volume), rank(close), 10))",
  "expected_direction": "positive",
  "used_fields": ["volume", "close"],
  "used_operators": ["rank", "ts_corr"],
  "rationale": "成交量与价格同步性增强时，可能代表趋势确认。"
}
```

### 4.5 ToolPlanner

职责：决定调用哪些工具，以及工具参数。

第一版工具白名单：

```text
list_context
validate_expression
prepare_factor_candidates
run_factor_backtest
compose_factors
load_saved_results
write_experiment_memory
```

LLM 不能自由调用 shell，不能读写任意路径，只能生成这些工具的 JSON 参数。

工具调用控制：

- 每轮最多生成 `max_candidates_per_round` 个候选；
- 每轮最多执行 `max_tool_calls_per_round` 次工具计划；
- 工具调用失败时记录失败，不允许无限重试；
- 生成报告后本轮停止，不继续调用工具；
- 创建长耗时后台任务前必须由用户确认。

### 4.6 ToolExecutor

职责：把 ToolPlanner 的计划映射到现有 Python 函数。

第一版先实现底层接口和记录，不急着让 LLM 自动触发长任务。涉及长耗时任务时，仍复用现有 `platform_jobs.py` 的后台任务机制。

映射关系：

```text
validate_expression -> custom_bt.expressions.evaluate_expression / AST 校验
run_factor_generation -> custom_bt.factor_generation.run_factor_generation
run_factor_backtest -> custom_bt.factor_backtest.backtest_accepted_factors
compose_factors -> custom_bt.factor_composition.compose_factors
```

### 4.7 ResearchDebate

职责：把其他系统中的“多空辩论”改造成因子研究辩论。

第一版不一定调用真实多 Agent，可以在单 Agent 内部按三个视角生成审查意见：

```text
Evidence Advocate：支持因子有效性的证据
Skeptical Reviewer：质疑样本外、重复、过拟合和机制薄弱处
Risk Judge：裁决保留、拒绝或需要复验
```

输出结构：

```json
{
  "advocate": ["该因子通过 RankIC 门槛", "样本外收益为正"],
  "skeptic": ["换手率偏高", "与旧因子相关性高"],
  "judge": {
    "decision": "review",
    "required_checks": ["不同股票池复验", "成本敏感性测试"]
  }
}
```

### 4.8 ResultAuditor

职责：审计结果，不让 Agent 只挑好看的结果。

检查项：

- 样本内/验证/测试是否一致；
- IC 和 RankIC 是否稳定；
- 回测收益是否为正；
- 最大回撤是否过大；
- 换手率是否过高；
- 和已有因子是否重复；
- 表达式是否过度复杂；
- 是否只是在大量候选中挑出幸运结果；
- 是否有前视偏差风险。

### 4.9 ResearchReporter

职责：输出研究卡片。

报告必须包含：

- 研究目标；
- 使用数据、股票池、时间切分；
- 候选数量、通过数量、失败数量；
- Top 候选表达式；
- 关键指标；
- 失败原因分布；
- 审计风险；
- 下一轮搜索建议。

### 4.10 MemoryWriter

职责：把每次研究沉淀为可检索记录。

第一版存 JSON / JSONL：

```text
custom_backtester/outputs/ai_research/sessions/<session_id>/research_spec.json
custom_backtester/outputs/ai_research/sessions/<session_id>/context_snapshot.json
custom_backtester/outputs/ai_research/sessions/<session_id>/candidate_expressions.jsonl
custom_backtester/outputs/ai_research/sessions/<session_id>/tool_calls.jsonl
custom_backtester/outputs/ai_research/sessions/<session_id>/audit_report.json
custom_backtester/outputs/ai_research/sessions/<session_id>/research_report.md
custom_backtester/outputs/ai_research/memory/failed_candidates.jsonl
custom_backtester/outputs/ai_research/memory/accepted_candidates.jsonl
custom_backtester/outputs/ai_research/memory/reflections.jsonl
```

`reflections.jsonl` 专门保存复盘型记忆：

```json
{
  "memory_id": "mem_001",
  "pattern": "高换手量价反转因子",
  "lesson": "在 liquid_500 上验证期 IC 尚可，但测试期因交易成本后收益转负。",
  "avoid_next_time": ["减少短窗口 turnover 类表达式", "加入换手率上限审计"],
  "created_at": "2026-08-20T23:00:00"
}
```

## 5. Agent 底层配置

建议新增配置文件：

```text
custom_backtester/configs/ai_research_agent.yaml
```

配置结构：

```yaml
agent:
  name: QuantResearchAgent
  mode: prompt_only
  default_language: zh
  require_user_confirmation: true
  max_candidates_per_round: 30
  max_tool_calls_per_round: 8

llm:
  provider: none
  model: none
  temperature: 0.2
  top_p: 1.0
  response_format: json
  timeout_seconds: 120

research_defaults:
  pool_id: liquid_500_864dc25f
  target_horizon: 20
  holding_period: 20
  train_start: "2022-01-14"
  train_end: "2024-07-26"
  valid_start: "2024-01-25"
  valid_end: "2025-07-28"
  test_start: "2025-01-27"
  test_end: "2026-06-12"

quality_gates:
  min_coverage: 0.8
  min_valid_ic: 0.02
  min_valid_rank_ic: 0.02
  min_icir: 0.2
  max_turnover: 1.0
  require_positive_backtest: true

guardrails:
  allow_python_code: false
  allow_unknown_fields: false
  allow_unknown_operators: false
  allow_direct_trading: false
  require_identity_lock: true
  require_failure_memory: true
  require_reflection_memory: true
  require_audit_report: true
  require_tool_call_limit: true

paths:
  master_store: data_cache/master
  pools_root: data_cache/pools
  factor_runs_root: factor_runs
  saved_results_root: outputs/saved_backtests
  ai_research_root: outputs/ai_research
```

第一版 `llm.provider: none`，表示先生成 prompt、schema、上下文和工具层，不绑定具体模型。后续可以接 OpenAI、本地模型或其他 provider。

## 6. 提示词层次

提示词不应该是一段巨大的总 prompt，而应拆成可版本化的层：

```text
L0 System Guardrails
L1 Research Spec Compiler
L2 Context Summary
L3 Hypothesis Generator
L4 Expression Proposer
L5 Tool Planner
L6 Research Debate
L7 Result Auditor
L8 Research Reporter
L9 Reflection Memory
```

每一层都有固定输入、固定输出 schema 和版本号。

## 7. 第一阶段实现范围

第一阶段只实现 Agent 底座，不接真正 LLM：

1. 配置加载；
2. Research Spec 数据结构；
3. 当前项目上下文快照；
4. Prompt 构造器；
5. 实验记忆写入；
6. 单元测试；
7. 后续接 LLM 和前端页面的接口预留。

这样做的好处是：先把 Agent 的骨架和约束做严，再让模型进入系统。否则模型一接入就会开始乱编字段、乱调用工具、乱解释结果。

## 8. 第二阶段和第三阶段

第二阶段：接入实际 LLM provider。

- 把用户输入编译为 Research Spec；
- 生成候选表达式；
- 校验表达式；
- 把候选写入实验 session；
- 暂时不自动启动长耗时回测，先由用户确认。

第三阶段：接入工具执行闭环。

- 用户确认后创建后台任务；
- 回测完成后自动生成审计报告；
- 保存失败案例；
- 下一轮生成前检索历史失败。

## 9. 明确不做的事情

第一版不做：

- 自动下单；
- 自动改核心回测代码；
- 自动使用新闻或公告；
- 自动联网检索；
- 自动绕过用户确认提交长任务；
- 自由执行 shell；
- 将单次回测结果包装成投资建议。

这些限制是为了让系统可控、可复现，并且方便后续逐步升级。
