# AI Research Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first foundation layer for a provider-agnostic AI quant research Agent: config loading, research schemas, local context retrieval, prompt construction, research debate scaffolding, tool-loop limits, and experiment/reflection memory.

**Architecture:** Add a small `custom_bt.ai_research` package that sits above the existing deterministic quant engine. The package does not call external LLM APIs in this phase; it builds strict JSON-oriented prompts, reads local platform context, locks identity by `pool_id + source_signature + date range + operator registry version`, and records research sessions under `outputs/ai_research`.

**Tech Stack:** Python dataclasses, PyYAML, JSON/JSONL files, existing `custom_bt` modules, pytest.

---

## File Structure

- Create: `custom_backtester/configs/ai_research_agent.yaml`
  - Default Agent configuration, guardrails, quality gates, paths, and model placeholder.
- Create: `custom_backtester/custom_bt/ai_research/__init__.py`
  - Public exports for the foundation package.
- Create: `custom_backtester/custom_bt/ai_research/config.py`
  - Load and normalize Agent config.
- Create: `custom_backtester/custom_bt/ai_research/schemas.py`
  - Dataclasses for `ResearchSpec`, `CandidateExpression`, `ResearchDebate`, and `ResearchSession`.
- Create: `custom_backtester/custom_bt/ai_research/context.py`
  - Build a local context snapshot from master metadata, pools, operators, factor runs, and saved results.
- Create: `custom_backtester/custom_bt/ai_research/prompts.py`
  - Build strict layered prompts for Research Spec, expression proposal, tool planning, research debate, audit, report, and reflection.
- Create: `custom_backtester/custom_bt/ai_research/memory.py`
  - Write JSON and JSONL session artifacts.
- Create: `custom_backtester/tests/test_ai_research_agent.py`
  - Tests for config, schemas, context retrieval, prompts, and memory.

## Task 1: Config Loader

**Files:**
- Create: `custom_backtester/configs/ai_research_agent.yaml`
- Create: `custom_backtester/custom_bt/ai_research/config.py`
- Test: `custom_backtester/tests/test_ai_research_agent.py`

- [x] **Step 1: Write failing test**

```python
def test_ai_agent_config_loads_defaults(tmp_path):
    from custom_bt.ai_research.config import load_agent_config

    config = load_agent_config(None)

    assert config["agent"]["name"] == "QuantResearchAgent"
    assert config["llm"]["provider"] == "none"
    assert config["guardrails"]["allow_unknown_fields"] is False
    assert config["paths"]["ai_research_root"] == "outputs/ai_research"
    assert config["agent"]["max_tool_calls_per_round"] == 8
    assert config["guardrails"]["require_identity_lock"] is True
    assert config["guardrails"]["require_reflection_memory"] is True
    assert config["guardrails"]["require_tool_call_limit"] is True
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_ai_agent_config_loads_defaults -q
```

Expected: import error because `custom_bt.ai_research.config` does not exist.

- [x] **Step 3: Implement config loader**

Implement `DEFAULT_AGENT_CONFIG` and `load_agent_config(path)` in `config.py`. If `path` is `None`, return defaults. If a YAML path is given, deep-merge it over defaults.

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_ai_agent_config_loads_defaults -q
```

Expected: pass.

## Task 2: Research Schemas

**Files:**
- Create: `custom_backtester/custom_bt/ai_research/schemas.py`
- Test: `custom_backtester/tests/test_ai_research_agent.py`

- [x] **Step 1: Write failing test**

```python
def test_research_spec_round_trip():
    from custom_bt.ai_research.schemas import ResearchSpec

    spec = ResearchSpec.from_mapping(
        {
            "objective": "寻找中期量价 Alpha",
            "pool_id": "liquid_500",
            "target_horizon": 20,
            "holding_period": 20,
            "preferred_fields": ["close", "volume"],
            "identity_lock": {"pool_id": "liquid_500", "source_signature": "sig_a"},
        }
    )

    payload = spec.to_dict()
    assert payload["objective"] == "寻找中期量价 Alpha"
    assert payload["pool_id"] == "liquid_500"
    assert payload["target_horizon"] == 20
    assert payload["preferred_fields"] == ["close", "volume"]
    assert payload["identity_lock"] == {"pool_id": "liquid_500", "source_signature": "sig_a"}
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_research_spec_round_trip -q
```

Expected: import error because `schemas.py` does not exist.

- [x] **Step 3: Implement dataclasses**

Implement:

```python
@dataclass
class ResearchSpec:
    objective: str
    pool_id: str = ""
    target_horizon: int = 20
    holding_period: int = 20
    factor_style: list[str] = field(default_factory=list)
    preferred_fields: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    identity_lock: dict[str, Any] = field(default_factory=dict)
```

Add `from_mapping()` and `to_dict()`.

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_research_spec_round_trip -q
```

Expected: pass.

## Task 3: Local Context Snapshot

**Files:**
- Create: `custom_backtester/custom_bt/ai_research/context.py`
- Test: `custom_backtester/tests/test_ai_research_agent.py`

- [x] **Step 1: Write failing test**

```python
def test_context_snapshot_reads_local_platform_state(tmp_path):
    import json
    from custom_bt.ai_research.context import build_context_snapshot

    master = tmp_path / "master"
    master.mkdir()
    (master / "meta.json").write_text(
        json.dumps(
            {
                "n_stocks": 2,
                "fields": ["close", "volume"],
                "date_min": "2024-01-01",
                "date_max": "2024-01-31",
                "source_signature": "sig_a",
            }
        ),
        encoding="utf-8",
    )
    pools_root = tmp_path / "pools"
    pool_dir = pools_root / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps({"pool_id": "pool_a", "n_stocks": 2, "source_signature": "sig_a"}),
        encoding="utf-8",
    )

    snapshot = build_context_snapshot(master, pools_root, tmp_path / "factor_runs", tmp_path / "saved")

    assert snapshot["master_store"]["n_stocks"] == 2
    assert snapshot["master_store"]["fields"] == ["close", "volume"]
    assert snapshot["pools"][0]["pool_id"] == "pool_a"
    assert "rank" in snapshot["operators"]
    assert snapshot["identity_lock"]["pool_id"] == "pool_a"
    assert snapshot["identity_lock"]["source_signature"] == "sig_a"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_context_snapshot_reads_local_platform_state -q
```

Expected: import error because `context.py` does not exist.

- [x] **Step 3: Implement context snapshot**

Implement `build_context_snapshot(master_store, pools_root, factor_runs_root, saved_results_root)`.

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_context_snapshot_reads_local_platform_state -q
```

Expected: pass.

## Task 4: Prompt Builders

**Files:**
- Create: `custom_backtester/custom_bt/ai_research/prompts.py`
- Test: `custom_backtester/tests/test_ai_research_agent.py`

- [x] **Step 1: Write failing test**

```python
def test_expression_prompt_includes_whitelists_and_json_contract():
    from custom_bt.ai_research.prompts import build_expression_proposal_prompt
    from custom_bt.ai_research.schemas import ResearchSpec

    spec = ResearchSpec(objective="寻找量价因子", pool_id="pool_a", preferred_fields=["close", "volume"])
    prompt = build_expression_proposal_prompt(
        spec,
        {"master_store": {"fields": ["close", "volume"]}, "operators": ["rank", "ts_mean"]},
        {"agent": {"max_candidates_per_round": 10}},
    )

    assert "只能使用白名单字段" in prompt
    assert "close" in prompt
    assert "rank" in prompt
    assert "candidate_id" in prompt
    assert "严格 JSON" in prompt
    assert "identity_lock" in prompt
    assert "past_failure_memory" in prompt
```

```python
def test_tool_debate_and_reflection_prompts_include_control_contracts():
    from custom_bt.ai_research.prompts import (
        build_research_debate_prompt,
        build_reflection_prompt,
        build_tool_plan_prompt,
    )
    from custom_bt.ai_research.schemas import ResearchSpec

    spec = ResearchSpec(
        objective="寻找量价因子",
        pool_id="pool_a",
        identity_lock={"pool_id": "pool_a", "source_signature": "sig_a"},
    )
    config = {"agent": {"max_tool_calls_per_round": 8}, "guardrails": {"require_identity_lock": True}}
    context = {"identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"}}

    tool_prompt = build_tool_plan_prompt(spec, [{"candidate_id": "cand_001"}], context, config)
    debate_prompt = build_research_debate_prompt({"candidate_id": "cand_001"}, {"rank_ic": 0.03}, [])
    reflection_prompt = build_reflection_prompt({"objective": "test"}, [], [])

    assert "max_tool_calls" in tool_prompt
    assert "8" in tool_prompt
    assert "Evidence Advocate" in debate_prompt
    assert "Skeptical Reviewer" in debate_prompt
    assert "Risk Judge" in debate_prompt
    assert "reflections.jsonl" in reflection_prompt
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_expression_prompt_includes_whitelists_and_json_contract -q
```

Expected: import error because `prompts.py` does not exist.

- [x] **Step 3: Implement prompt builders**

Implement `build_research_spec_prompt()`, `build_expression_proposal_prompt()`, `build_tool_plan_prompt()`, `build_research_debate_prompt()`, `build_audit_prompt()`, `build_report_prompt()`, and `build_reflection_prompt()` as deterministic string builders. These builders adapt patterns from `提示词合集/` only as mechanisms: tool-first, identity consistency, JSON contracts, debate roles, reflection memory, and loop limits. They must not include buy/hold/sell, target price, stop-loss, or direct trading advice.

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_expression_prompt_includes_whitelists_and_json_contract -q
```

Expected: pass.

## Task 5: Experiment Memory

**Files:**
- Create: `custom_backtester/custom_bt/ai_research/memory.py`
- Test: `custom_backtester/tests/test_ai_research_agent.py`

- [x] **Step 1: Write failing test**

```python
def test_experiment_store_writes_session_artifacts(tmp_path):
    import json
    from custom_bt.ai_research.memory import ExperimentStore

    store = ExperimentStore(tmp_path)
    session_dir = store.create_session("unit_session", {"objective": "test"})
    store.append_jsonl(session_dir / "candidate_expressions.jsonl", {"candidate_id": "cand_001", "status": "proposed"})
    store.append_memory("reflections", {"pattern": "high_turnover", "outcome": "failed"})

    assert (session_dir / "research_spec.json").exists()
    rows = [json.loads(line) for line in (session_dir / "candidate_expressions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["candidate_id"] == "cand_001"
    memory_rows = [json.loads(line) for line in (tmp_path / "memory" / "reflections.jsonl").read_text(encoding="utf-8").splitlines()]
    assert memory_rows[0]["pattern"] == "high_turnover"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_experiment_store_writes_session_artifacts -q
```

Expected: import error because `memory.py` does not exist.

- [x] **Step 3: Implement memory writer**

Implement `ExperimentStore.create_session()`, `write_json()`, `append_jsonl()`, and `append_memory()`.

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py::test_experiment_store_writes_session_artifacts -q
```

Expected: pass.

## Task 6: Full Verification

**Files:**
- Existing tests plus new `custom_backtester/tests/test_ai_research_agent.py`

- [x] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests/test_ai_research_agent.py -q
```

Expected: all AI research foundation tests pass.

- [x] **Step 2: Run related regression tests**

Run:

```powershell
python -m pytest tests/test_streamlit_app.py tests/test_factor_generation.py tests/test_platform_jobs.py tests/test_ai_research_agent.py -q
```

Expected: all selected tests pass.

- [x] **Step 3: Compile Python package**

Run:

```powershell
python -m compileall -q custom_bt app
```

Expected: exit code 0.
