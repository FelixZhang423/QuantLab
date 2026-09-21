# AI Research Agent 全流程说明

本文档说明当前 `custom_backtester` 中 AI 研究 Agent 的实际运行流程。这里的“AI 研究”不是独立交易系统，而是一个位于本地量化平台之上的研究编排层：它把自然语言研究目标交给 DeepSeek 生成结构化研究计划和候选因子，再用本地字段、操作符、回测和组合模块做校验与执行。

当前实现入口以 CLI 为主，Streamlit 暂未提供独立的 AI 研究页签。

## 1. 总览

完整链路如下：

```text
用户研究意图
  -> 读取 AI 配置和本地环境变量
  -> 构建本地平台 context snapshot
  -> DeepSeek 生成 Research Spec
  -> DeepSeek 生成候选因子表达式
  -> 本地表达式校验
  -> DeepSeek 生成工具调用计划 tool_plan
  -> 可选执行本地工具
       -> 创建/运行因子生成、候选回测、因子组合等平台 job
  -> 写入 session 产物、报告和长期 memory
```

关键代码位置：

- `configs/ai_research_agent.yaml`：当前 AI Agent 配置。
- `custom_bt/ai_research/runner.py`：主流程编排器。
- `custom_bt/ai_research/llm_client.py`：DeepSeek JSON 调用客户端。
- `custom_bt/ai_research/context.py`：本地平台状态快照。
- `custom_bt/ai_research/prompts.py`：Research Spec、表达式、工具计划等 prompt。
- `custom_bt/ai_research/tools.py`：候选表达式本地校验。
- `custom_bt/ai_research/tool_executor.py`：模型 tool plan 到本地平台工具的安全映射。
- `custom_bt/ai_research/memory.py`：session 文件和长期记忆存储。
- `custom_bt/cli.py`：主平台 CLI 中的 `ai-research` 命令。
- `custom_bt/ai_research/cli.py`：AI 研究模块的独立 CLI。

## 2. 运行前置条件

AI 研究链路依赖本地平台已经有可用的数据和股票池：

- 主缓存：`data_cache/master/meta.json`
- 股票池：`data_cache/pools/<pool_id>/manifest.json`
- 操作符注册表：来自 `custom_bt.expressions.list_operators()`
- 可选历史因子运行：`factor_runs/*/factor_run.json`
- 可选历史回测结果：`outputs/saved_backtests/**/manifest.json`

当前默认股票池是：

```text
liquid_500_864dc25f
```

当前默认 AI 配置文件是：

```powershell
configs/ai_research_agent.yaml
```

DeepSeek API key 从 `.env.local` 或进程环境变量读取。推荐本地 `.env.local` 格式：

```text
DEEPSEEK_API_KEY=你的本地密钥
AI_RESEARCH_LLM_PROVIDER=deepseek
AI_RESEARCH_LLM_MODEL=deepseek-v4-flash
```

不要把真实 key 写入文档、日志或版本库。

## 3. 配置加载

入口创建 `AIResearchRunner` 时会先加载配置：

```python
AIResearchRunner(
    config_path="configs/ai_research_agent.yaml",
    project_root=".",
    env_path=".env.local",
)
```

配置加载逻辑在 `custom_bt/ai_research/config.py`：

- 如果不传配置文件，使用 `DEFAULT_AGENT_CONFIG`。
- 如果传 YAML，则把 YAML 深度合并到默认配置上。
- 合并后会校验 guardrails，防止把安全约束改弱。

当前关键配置：

- provider：`deepseek`
- model：`deepseek-v4-flash`
- response_format：`json`
- max_candidates_per_round：默认 30
- max_tool_calls_per_round：最多 8
- AI session 根目录：`outputs/ai_research`
- jobs 根目录：`jobs`
- saved results 根目录：`outputs/saved_backtests`

强制 guardrails：

- 不允许 AI 输出 Python 代码。
- 不允许使用未知字段。
- 不允许使用未知操作符。
- 不允许输出直接交易建议。
- 必须保留 identity lock。
- 必须保留失败/反思 memory。
- 每轮工具调用数量必须受限。

## 4. LLM 调用方式

DeepSeek 客户端在 `custom_bt/ai_research/llm_client.py`。

运行时会从两个地方合并环境变量：

1. `.env.local`
2. 当前进程环境变量

进程环境变量优先级更高。

当前只支持 provider 为 `deepseek`。如果 provider 不是 `deepseek`，会报：

```text
unsupported llm provider
```

实际请求发送到：

```text
https://api.deepseek.com/chat/completions
```

请求特征：

- `stream: false`
- `response_format: {"type": "json_object"}`
- `thinking: {"type": "disabled"}`
- system prompt 使用统一 guardrails
- user prompt 是当前阶段的结构化 prompt

响应会经过 `parse_json_content()` 解析，支持直接 JSON，也支持被 Markdown fenced code 包裹的 JSON。解析失败会报：

```text
LLM response content is not valid JSON
```

## 5. 本地 Context Snapshot

每次 AI session 开始前，runner 会调用：

```python
build_context_snapshot(
    master_store,
    pools_root,
    factor_runs_root,
    saved_results_root,
    pool_id=...
)
```

这个快照是 AI 的“研究边界”，主要包含：

- 主缓存信息：行数、股票数、字段清单、字段 catalog、日期范围、source signature。
- 股票池列表：pool id、股票数、筛选窗口、流动性/覆盖率条件等。
- 当前选中的股票池：`selected_pool`
- 本地可用操作符：`operators`
- 最近 factor runs：`recent_factor_runs`
- 已保存回测结果：`saved_results`
- identity lock：`pool_id + source_signature + date_min + date_max + operator_registry_version`

identity lock 很重要，它用于防止模型在后续工具计划里静默改股票池、数据源签名或时间范围。

如果显式传入的 `--pool` 不存在，context 构建会直接失败，不会让模型凭空继续。

## 6. 第一阶段：Research Spec

用户输入是一句自然语言研究目标，例如：

```powershell
python -m custom_bt.cli ai-research "找一个中期量价因子，优先使用 close 和 volume，只生成 1 个候选"
```

runner 会先构造 Research Spec prompt：

```python
build_research_spec_prompt(user_intent, context, config)
```

DeepSeek 必须返回严格 JSON，最终被转换为 `ResearchSpec`：

```json
{
  "objective": "寻找一个中期量价因子",
  "pool_id": "liquid_500_864dc25f",
  "target_horizon": 20,
  "holding_period": 20,
  "factor_style": ["中期量价因子"],
  "preferred_fields": ["close", "volume"],
  "metrics": ["return", "sharpe", "max_drawdown"],
  "constraints": [],
  "success_criteria": {},
  "identity_lock": {}
}
```

`ResearchSpec.objective` 是必填项。缺失会报错。

这一阶段会落盘：

- `research_spec.json`
- `context_snapshot.json`
- `research_spec_prompt.json`
- `research_spec_llm_response.json`

## 7. 第二阶段：候选因子生成

Research Spec 生成后，runner 会构造表达式生成 prompt：

```python
build_expression_proposal_prompt(
    research_spec,
    context,
    config,
    past_failure_memory=[],
)
```

这一层给模型的硬边界包括：

- 只能使用 `allowed_fields`
- 只能使用 `allowed_operators`
- 不能输出 Python、SQL、自然语言伪公式
- 候选数量不能超过 `max_candidates`
- 必须输出严格 JSON 对象，候选放在 `candidates` 数组

候选会被转换为 `CandidateExpression`：

```json
{
  "candidate_id": "cand_001",
  "hypothesis_id": "hyp_001",
  "expression": "rank(ts_mean(volume,20))",
  "expected_direction": "positive",
  "rationale": "20 日平均成交量排名，反映资金活跃度",
  "used_fields": ["volume"],
  "used_operators": ["rank", "ts_mean"],
  "complexity_estimate": 3,
  "risk_flags": ["流动性风险"]
}
```

这一阶段会落盘：

- `expression_proposal_prompt.json`
- `expression_proposal_llm_response.json`
- `candidate_expressions.jsonl`

## 8. 第三阶段：本地表达式校验

所有候选不会直接进入回测，必须先经过本地校验：

```python
validate_candidate_expressions(candidates, context)
```

校验逻辑在 `custom_bt/ai_research/tools.py`：

1. 用 Python AST 解析表达式，先排除语法错误。
2. 收集表达式里使用的字段名和操作符名。
3. 检查字段是否存在于 `context["master_store"]["fields"]`。
4. 检查操作符是否存在于本地 `operators` 白名单。
5. 构造一个小型 synthetic panel。
6. 调用现有表达式引擎 `evaluate_expression()` 真跑一遍。

通过后状态为：

```json
{
  "candidate_id": "cand_001",
  "expression": "rank(ts_mean(volume,20))",
  "status": "valid",
  "used_fields": ["volume"],
  "used_operators": ["rank", "ts_mean"],
  "unknown_fields": [],
  "unknown_operators": [],
  "errors": []
}
```

只有 `status == "valid"` 的候选才会进入下一阶段工具计划。

校验结果会落盘：

- `validation_results.jsonl`

同时，候选记录里会追加 `validation` 字段。

## 9. 第四阶段：工具计划 Tool Plan

runner 会把 valid candidates 交给 DeepSeek，让它生成工具调用计划：

```python
build_tool_plan_prompt(research_spec, valid_candidates, context, config)
```

当前工具白名单：

```text
list_context
validate_expression
write_experiment_memory
create_factor_generation_job
create_factor_backtest_job
create_composition_job
load_saved_results
```

模型输出必须类似：

```json
{
  "tool_plan": [
    {
      "tool_name": "create_factor_backtest_job",
      "arguments": {
        "candidate_ids": ["cand_001"]
      }
    }
  ],
  "requires_user_confirmation": true,
  "max_tool_calls": 8,
  "stop_after_report": true
}
```

注意：生成 tool plan 不等于已经执行工具。默认情况下，runner 只是把工具计划写入 session。

这一阶段会落盘：

- `tool_plan_prompt.json`
- `tool_plan_llm_response.json`
- `tool_plan.json`

## 10. 第五阶段：工具执行开关

AI 研究命令有两个重要开关：

```text
--execute-tools
--execute-long-jobs
```

它们的效果不同。

### 10.1 默认模式：只生成研究计划，不执行工具

命令：

```powershell
python -m custom_bt.cli ai-research "找一个中期量价因子" --max-candidates 3
```

会执行：

- DeepSeek 生成 Research Spec
- DeepSeek 生成候选表达式
- 本地表达式校验
- DeepSeek 生成 tool plan
- 写入本地 report 和 memory

不会执行：

- 不创建平台 job
- 不运行回测
- 不运行 PPO 生成
- 不运行组合

`tool_execution.json` 会是空执行摘要。

### 10.2 `--execute-tools`：执行工具计划，但长任务只创建 job

命令：

```powershell
python -m custom_bt.cli ai-research "找一个中期量价因子" --execute-tools
```

会执行 tool plan。

如果工具是轻量工具，比如：

- `list_context`
- `validate_expression`
- `write_experiment_memory`
- `load_saved_results`

会立即执行。

如果工具是长任务，比如：

- `create_factor_generation_job`
- `create_factor_backtest_job`
- `create_composition_job`

只会创建 `jobs/<job_id>/platform_job.json` 和 `status.json`，状态为 queued，不会同步跑完。

之后可以手动运行：

```powershell
python -m custom_bt.cli run-platform-job --job-dir jobs/<job_id>
```

### 10.3 `--execute-tools --execute-long-jobs`：执行工具计划并同步跑长任务

命令：

```powershell
python -m custom_bt.cli ai-research "找一个中期量价因子，只生成 1 个候选并回测" --max-candidates 1 --execute-tools --execute-long-jobs
```

会执行 tool plan，并且对长任务调用：

```python
run_platform_job(job_dir)
```

因此会真正跑完本地平台 job，例如：

- AI 候选表达式物化成 factor run
- 创建 `backtest_factors` job
- 同步运行回测
- 写入 `outputs/saved_backtests`

## 11. Tool Executor 如何映射到本地平台

工具执行器在 `custom_bt/ai_research/tool_executor.py`。

执行前会先检查：

- tool name 是否在白名单。
- tool_plan 数量是否超过 `max_tool_calls`。
- tool arguments 是否是 JSON object。
- 如果 arguments 里带了 `pool_id` 或 `source_signature`，必须和 identity lock 一致。

长任务工具映射如下：

| AI 工具名 | 本地平台 operation |
|---|---|
| `create_factor_generation_job` | `generate_factors` |
| `create_factor_backtest_job` | `backtest_factors` |
| `create_composition_job` | `compose_factors` |

平台 job 由 `custom_bt.platform_jobs.create_platform_job()` 创建，并由 `custom_bt.platform_jobs.run_platform_job()` 执行。

### 11.1 AI 候选如何进入回测链路

如果 tool plan 要回测候选，但没有提供已有 `factor_run_dir`，执行器会先把 valid candidates 物化成一个本地 factor run：

```text
factor_runs/ai_<session_id>_<digest>/
  accepted_factors.jsonl
  factor_run.json
```

`accepted_factors.jsonl` 里每条 AI 候选都会写成平台已接受因子：

```json
{
  "candidate_id": "cand_001",
  "expression": "rank(ts_mean(volume,20))",
  "canonical_expression": "rank(ts_mean(volume,20))",
  "backtest_expression": "rank(ts_mean(volume,20))",
  "accepted": true,
  "reason": "ai_research_candidate",
  "pool_id": "liquid_500_864dc25f",
  "runtime_id": "ai_research_session"
}
```

随后 `create_factor_backtest_job` 会创建一个 `backtest_factors` job，payload 指向这个 factor run。这样 AI 生成表达式就进入了现有 `backtest_accepted_factors()` 链路。

### 11.2 AI 触发 PPO 因子生成

如果模型选择 `create_factor_generation_job`，执行器会构造 `generate_factors` payload：

- master store
- pools root
- pool id
- runtime root
- factor runs root
- 字段列表
- train/valid/test splits
- target horizon
- max backtrack/future days
- generation config
- quality gates

字段会经过白名单检查。未知字段会被拒绝。

### 11.3 AI 触发因子组合

如果模型选择 `create_composition_job`，执行器会构造 `compose_factors` payload：

- factor run dirs
- pool id
- outputs root
- backtest config
- selection metric
- min score / min IC / min Rank IC / min coverage
- mutual IC threshold
- sweep sizes
- max factors
- target horizon

如果只提供 candidate ids，也可以先把 AI 候选物化成 factor run，再进入组合链路。

## 12. Session 产物结构

每次 AI 研究都会创建一个目录：

```text
outputs/ai_research/sessions/<session_id>/
```

常见文件：

```text
research_spec.json
context_snapshot.json
research_spec_prompt.json
research_spec_llm_response.json
expression_proposal_prompt.json
expression_proposal_llm_response.json
candidate_expressions.jsonl
validation_results.jsonl
tool_plan_prompt.json
tool_plan_llm_response.json
tool_plan.json
tool_execution.json
tool_results.jsonl
materialized_factor_run.json
summary.json
report.md
```

不是每次都有全部文件。例如没有执行工具时，不会有 `materialized_factor_run.json`。

长期记忆写在：

```text
outputs/ai_research/memory/reflections.jsonl
```

runner 当前会在每次 session 结束后写入一个简短 reflection：

```json
{
  "session_id": "...",
  "objective": "...",
  "candidate_count": 1,
  "valid_candidate_count": 1
}
```

## 13. 当前真实端到端示例

本地已有一次真实链路 session：

```text
outputs/ai_research/sessions/fullchain_deepseek_20260821_realrun
```

这次输入目标是：

```text
真实链路 smoke：找一个中期量价因子，优先使用 close 和 volume，只生成1个候选，并创建候选回测任务
```

实际结果：

- DeepSeek 生成 1 个候选。
- 本地校验通过 1 个。
- 工具计划选择 `create_factor_backtest_job`。
- 因为运行时启用了 `--execute-tools --execute-long-jobs`，所以回测 job 被创建并同步跑完。
- job id：`20260821_013706_2e8b032a`
- 物化 factor run：`factor_runs/ai_fullchain_deepseek_20260821_realrun_0c7e122a19`
- 回测输出：`outputs/saved_backtests/factor/liquid_500_864dc25f/ai_fullchain_deepseek_20260821_realrun_0c7e122a19`

候选表达式：

```text
rank(ts_mean(volume,20))
```

回测 summary 中显示：

- completed：1
- failed：0
- skipped：0

该候选的回测指标本身并不代表可用结论。这个 smoke 的意义是验证“DeepSeek -> 本地校验 -> 工具计划 -> factor run 物化 -> 平台 job -> 回测输出”的链路是通的。

## 14. 常用命令

### 14.1 只生成研究 session，不执行工具

```powershell
python -m custom_bt.cli ai-research "找 3 个中期量价因子，优先使用 close、volume、amount" --max-candidates 3
```

### 14.2 生成并执行工具计划，但长任务只入队

```powershell
python -m custom_bt.cli ai-research "找 3 个中期量价因子，并创建候选回测任务" --max-candidates 3 --execute-tools
```

### 14.3 生成、执行工具计划，并同步跑完长任务

```powershell
python -m custom_bt.cli ai-research "找 1 个中期量价因子，并真实回测" --max-candidates 1 --execute-tools --execute-long-jobs
```

### 14.4 使用独立 AI Research CLI

```powershell
python -m custom_bt.ai_research.cli run "找 1 个中期量价因子" --max-candidates 1 --execute-tools
```

### 14.5 手动执行 queued 平台 job

```powershell
python -m custom_bt.cli run-platform-job --job-dir jobs/<job_id>
```

### 14.6 指定 session id 和股票池

```powershell
python -m custom_bt.cli ai-research "找一个低换手量价因子" --session-id my_research_001 --pool liquid_500_864dc25f --max-candidates 1
```

注意：session id 必须是简单文件名，不能包含路径分隔符。如果同名 session 已存在，会报错，避免覆盖历史研究记录。

## 15. 当前已实现和未实现的边界

### 已实现

- DeepSeek JSON 调用。
- `.env.local` 本地 key 读取。
- AI config 合并与 guardrails 校验。
- 本地平台 context snapshot。
- Research Spec 生成。
- 候选表达式生成。
- 本地表达式校验。
- 工具计划生成。
- 工具白名单和调用数量限制。
- identity lock 检查。
- AI 候选物化为 factor run。
- 创建/运行本地平台 job。
- 接入 `generate_factors`、`backtest_factors`、`compose_factors`。
- 读取已保存结果。
- session 产物落盘。
- 简短本地 report。
- reflections 长期记忆。
- CLI 入口。
- DeepSeek 真实 smoke 已跑通。

### 当前未完整自动化

- Streamlit 里还没有 AI 研究专用页面。
- `require_user_confirmation` 目前通过 CLI flag 表达，不是交互式确认弹窗。
- prompt 中已有 debate、audit、report、reflection 层，但 runner 当前没有自动串起 L6/L7/L8/L9 的模型调用；现在使用本地 `report.md` 和简短 reflections。
- 还不是多轮自动研究循环；一次命令就是一轮 session。
- memory 当前是追加写入，尚未做相似记忆检索召回。
- 工具执行是同步命令式流程；queued job 的持续监控仍依赖现有 jobs/status 文件和平台入口。

## 16. 常见问题排查

### 16.1 缺少 DeepSeek API key

现象：

```text
DEEPSEEK_API_KEY is required for DeepSeek provider
```

处理：

- 检查 `.env.local` 是否在 `custom_backtester` 根目录。
- 检查是否有 `DEEPSEEK_API_KEY=...`。
- 检查命令是否传了正确的 `--project-root` 和 `--env`。

### 16.2 provider 不支持

现象：

```text
unsupported llm provider: xxx
```

当前只实现 DeepSeek。把配置或环境变量改为：

```text
AI_RESEARCH_LLM_PROVIDER=deepseek
```

### 16.3 股票池不存在

现象：

```text
pool_id not found in pools_root
```

处理：

- 确认 `data_cache/pools/<pool_id>/manifest.json` 存在。
- 不确定 pool id 时，先查看 `data_cache/pools` 下的目录。

### 16.4 候选表达式校验失败

常见原因：

- 字段不在 master cache 字段白名单。
- 操作符不在本地操作符注册表。
- 表达式语法不是本地表达式引擎支持的格式。
- 表达式能解析但无法在 synthetic panel 上执行。

校验结果看：

```text
outputs/ai_research/sessions/<session_id>/validation_results.jsonl
```

### 16.5 工具计划被拒绝

常见原因：

- tool name 不在白名单。
- tool call 数量超过 8。
- tool arguments 不是 JSON object。
- arguments 中的 `pool_id` 或 `source_signature` 与 identity lock 不一致。

工具执行结果看：

```text
outputs/ai_research/sessions/<session_id>/tool_execution.json
outputs/ai_research/sessions/<session_id>/tool_results.jsonl
```

### 16.6 只创建了 job，没有真实跑

这是正常行为。只传 `--execute-tools` 时，长任务只创建 queued job。

要真实跑，有两种方式：

```powershell
python -m custom_bt.cli run-platform-job --job-dir jobs/<job_id>
```

或下次直接传：

```powershell
--execute-tools --execute-long-jobs
```

### 16.7 SSL 证书库 ASN1 报错

如果在 `alphagen` 环境调用 DeepSeek 时看到：

```text
ssl.SSLError: [ASN1: NOT_ENOUGH_DATA] not enough data
```

这通常不是 DeepSeek API 返回错误，而是当前 Python/Conda 环境读取 Windows 系统证书库时失败。当前客户端已经优先使用 `certifi` 的 `cacert.pem` 来创建 HTTPS SSL context，以绕开这个 Windows 证书库问题。

如果还需要手动指定 CA 文件，可以在 `.env.local` 里加：

```text
DEEPSEEK_CA_BUNDLE=F:\anaconda3\envs\alphagen\lib\site-packages\certifi\cacert.pem
```

## 17. 最推荐的使用方式

调试新研究方向时：

```powershell
python -m custom_bt.cli ai-research "找 3 个中期量价因子，要求字段简单、低复杂度" --max-candidates 3
```

确认候选和工具计划合理后，再创建 job：

```powershell
python -m custom_bt.cli ai-research "找 3 个中期量价因子，并创建候选回测任务" --max-candidates 3 --execute-tools
```

如果只想做一个小样本真实链路验证：

```powershell
python -m custom_bt.cli ai-research "找 1 个中期量价因子，并真实回测" --max-candidates 1 --execute-tools --execute-long-jobs
```

这样可以避免模型一上来创建过多长任务，也方便逐步检查 session 产物。
