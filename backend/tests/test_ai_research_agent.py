import json
from pathlib import Path

import pytest


def test_ai_agent_config_loads_defaults_and_merges_override(tmp_path):
    from custom_bt.ai_research.config import load_agent_config

    config = load_agent_config(None)

    assert config["agent"]["name"] == "QuantResearchAgent"
    assert config["agent"]["mode"] == "prompt_only"
    assert config["agent"]["max_candidates_per_round"] == 30
    assert config["agent"]["max_tool_calls_per_round"] == 8
    assert config["llm"]["provider"] == "none"
    assert config["guardrails"]["allow_unknown_fields"] is False
    assert config["guardrails"]["require_identity_lock"] is True
    assert config["guardrails"]["require_reflection_memory"] is True
    assert config["guardrails"]["require_tool_call_limit"] is True
    assert config["paths"]["ai_research_root"] == "outputs/ai_research"

    override_path = tmp_path / "agent.yaml"
    override_path.write_text(
        "\n".join(
            [
                "agent:",
                "  max_candidates_per_round: 12",
                "research_defaults:",
                "  pool_id: pool_override",
            ]
        ),
        encoding="utf-8",
    )

    merged = load_agent_config(override_path)

    assert merged["agent"]["name"] == "QuantResearchAgent"
    assert merged["agent"]["max_candidates_per_round"] == 12
    assert merged["agent"]["max_tool_calls_per_round"] == 8
    assert merged["research_defaults"]["pool_id"] == "pool_override"


def test_ai_agent_config_rejects_weakened_guardrails(tmp_path):
    from custom_bt.ai_research.config import load_agent_config

    override_path = tmp_path / "weak_guardrails.yaml"
    override_path.write_text(
        "\n".join(
            [
                "agent:",
                "  max_tool_calls_per_round: 99",
                "guardrails:",
                "  require_identity_lock: false",
                "  allow_unknown_fields: true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="guardrail"):
        load_agent_config(override_path)


def test_research_spec_and_candidate_round_trip_keep_identity_lock():
    from custom_bt.ai_research.schemas import CandidateExpression, ResearchSpec

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

    candidate = CandidateExpression.from_mapping(
        {
            "candidate_id": "cand_001",
            "hypothesis_id": "hyp_001",
            "expression": "rank(ts_mean(volume,20))",
            "expected_direction": "positive",
            "used_fields": ["volume"],
            "used_operators": ["rank", "ts_mean"],
            "rationale": "量能中期强度排序。",
        }
    )

    assert candidate.to_dict()["candidate_id"] == "cand_001"
    assert candidate.to_dict()["used_operators"] == ["rank", "ts_mean"]


def test_context_snapshot_reads_local_platform_state_and_identity_lock(tmp_path):
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

    factor_runs_root = tmp_path / "factor_runs"
    run_dir = factor_runs_root / "run_a"
    run_dir.mkdir(parents=True)
    (run_dir / "factor_run.json").write_text(
        json.dumps({"run_id": "run_a", "pool_id": "pool_a", "accepted_count": 7}),
        encoding="utf-8",
    )

    saved_root = tmp_path / "saved"
    result_dir = saved_root / "factor" / "pool_a" / "run_a"
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text(
        json.dumps({"run_name": "saved_a", "pool_id": "pool_a", "result_type": "factor"}),
        encoding="utf-8",
    )

    snapshot = build_context_snapshot(master, pools_root, factor_runs_root, saved_root)

    assert snapshot["master_store"]["n_stocks"] == 2
    assert snapshot["master_store"]["fields"] == ["close", "volume"]
    assert snapshot["pools"][0]["pool_id"] == "pool_a"
    assert snapshot["recent_factor_runs"][0]["run_id"] == "run_a"
    assert snapshot["saved_results"][0]["pool_id"] == "pool_a"
    assert "rank" in snapshot["operators"]
    assert snapshot["identity_lock"]["pool_id"] == "pool_a"
    assert snapshot["identity_lock"]["source_signature"] == "sig_a"
    assert snapshot["identity_lock"]["date_min"] == "2024-01-01"
    assert snapshot["identity_lock"]["operator_registry_version"] == "local"


def test_context_snapshot_respects_explicit_pool_id_beyond_limit(tmp_path):
    from custom_bt.ai_research.context import build_context_snapshot

    master = tmp_path / "master"
    master.mkdir()
    (master / "meta.json").write_text(
        json.dumps(
            {
                "fields": ["close"],
                "date_min": "2024-01-01",
                "date_max": "2024-01-31",
                "source_signature": "sig_a",
            }
        ),
        encoding="utf-8",
    )
    pools_root = tmp_path / "pools"
    for pool_id in ["pool_a", "pool_b"]:
        pool_dir = pools_root / pool_id
        pool_dir.mkdir(parents=True)
        (pool_dir / "manifest.json").write_text(
            json.dumps({"pool_id": pool_id, "n_stocks": 2, "source_signature": f"sig_{pool_id}"}),
            encoding="utf-8",
        )

    snapshot = build_context_snapshot(
        master,
        pools_root,
        tmp_path / "factor_runs",
        tmp_path / "saved",
        pool_id="pool_b",
        limit=1,
    )

    assert snapshot["selected_pool"]["pool_id"] == "pool_b"
    assert snapshot["identity_lock"]["pool_id"] == "pool_b"
    assert snapshot["identity_lock"]["source_signature"] == "sig_pool_b"


def test_context_snapshot_rejects_unknown_explicit_pool_id(tmp_path):
    from custom_bt.ai_research.context import build_context_snapshot

    master = tmp_path / "master"
    master.mkdir()
    (master / "meta.json").write_text(
        json.dumps({"fields": ["close"], "source_signature": "sig_a"}),
        encoding="utf-8",
    )
    pools_root = tmp_path / "pools"
    pool_dir = pools_root / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps({"pool_id": "pool_a", "n_stocks": 2, "source_signature": "sig_a"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pool_id"):
        build_context_snapshot(
            master,
            pools_root,
            tmp_path / "factor_runs",
            tmp_path / "saved",
            pool_id="missing_pool",
        )


def test_expression_prompt_includes_whitelists_identity_and_json_contract():
    from custom_bt.ai_research.prompts import build_expression_proposal_prompt
    from custom_bt.ai_research.schemas import ResearchSpec

    spec = ResearchSpec(
        objective="寻找量价因子",
        pool_id="pool_a",
        preferred_fields=["close", "volume"],
        identity_lock={"pool_id": "pool_a", "source_signature": "sig_a"},
    )
    prompt = build_expression_proposal_prompt(
        spec,
        {
            "master_store": {"fields": ["close", "volume"]},
            "operators": ["rank", "ts_mean"],
            "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
        },
        {"agent": {"max_candidates_per_round": 10}},
        past_failure_memory=[{"pattern": "high_turnover", "lesson": "短窗换手过高"}],
    )

    assert "只能使用白名单字段" in prompt
    assert "close" in prompt
    assert "rank" in prompt
    assert "candidate_id" in prompt
    assert "严格 JSON" in prompt
    assert "identity_lock" in prompt
    assert "past_failure_memory" in prompt
    assert "high_turnover" in prompt
    assert "买入" not in prompt
    assert "目标价" not in prompt


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
    config = {
        "agent": {"max_tool_calls_per_round": 8},
        "guardrails": {"require_identity_lock": True},
    }
    context = {"identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"}}

    tool_prompt = build_tool_plan_prompt(spec, [{"candidate_id": "cand_001"}], context, config)
    debate_prompt = build_research_debate_prompt({"candidate_id": "cand_001"}, {"rank_ic": 0.03}, [])
    reflection_prompt = build_reflection_prompt({"objective": "test"}, [], [])

    assert "max_tool_calls" in tool_prompt
    assert "8" in tool_prompt
    assert "identity_lock" in tool_prompt
    assert "Evidence Advocate" in debate_prompt
    assert "Skeptical Reviewer" in debate_prompt
    assert "Risk Judge" in debate_prompt
    assert "reflections.jsonl" in reflection_prompt


def test_prompt_builders_do_not_emit_direct_trading_targets():
    from custom_bt.ai_research.prompts import (
        build_audit_prompt,
        build_expression_proposal_prompt,
        build_reflection_prompt,
        build_report_prompt,
        build_research_debate_prompt,
        build_research_spec_prompt,
        build_tool_plan_prompt,
    )
    from custom_bt.ai_research.schemas import ResearchSpec

    spec = ResearchSpec(
        objective="寻找量价因子",
        pool_id="pool_a",
        identity_lock={"pool_id": "pool_a", "source_signature": "sig_a"},
    )
    context = {
        "master_store": {"fields": ["close", "volume"]},
        "pools": [{"pool_id": "pool_a"}],
        "operators": ["rank", "ts_mean"],
        "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
    }
    config = {
        "agent": {"max_candidates_per_round": 10, "max_tool_calls_per_round": 8},
        "research_defaults": {"pool_id": "pool_a", "target_horizon": 20},
        "quality_gates": {"min_valid_rank_ic": 0.02},
    }
    prompts = [
        build_research_spec_prompt("找中期量价因子", context, config),
        build_expression_proposal_prompt(spec, context, config),
        build_tool_plan_prompt(spec, [{"candidate_id": "cand_001"}], context, config),
        build_research_debate_prompt({"candidate_id": "cand_001"}, {"rank_ic": 0.03}, []),
        build_audit_prompt({"candidate_id": "cand_001"}, {"rank_ic": 0.03}, config["quality_gates"]),
        build_report_prompt(spec.to_dict(), [], [], {}),
        build_reflection_prompt(spec.to_dict(), [], []),
    ]
    forbidden_terms = ["买入", "卖出", "目标价", "止损", "buy", "sell", "target price", "stop loss"]

    for prompt in prompts:
        lowered = prompt.lower()
        for term in forbidden_terms:
            assert term not in lowered
        assert "## 组合建议" not in prompt


def test_experiment_store_writes_session_artifacts_and_memory(tmp_path):
    from custom_bt.ai_research.memory import ExperimentStore

    store = ExperimentStore(tmp_path)
    session_dir = store.create_session("unit_session", {"objective": "test"})
    store.write_json(session_dir / "context_snapshot.json", {"identity_lock": {"pool_id": "pool_a"}})
    store.append_jsonl(
        session_dir / "candidate_expressions.jsonl",
        {"candidate_id": "cand_001", "status": "proposed"},
    )
    store.append_memory("reflections", {"pattern": "high_turnover", "outcome": "failed"})

    assert (session_dir / "research_spec.json").exists()
    assert (session_dir / "context_snapshot.json").exists()

    rows = [
        json.loads(line)
        for line in (session_dir / "candidate_expressions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["candidate_id"] == "cand_001"

    memory_rows = [
        json.loads(line)
        for line in (tmp_path / "memory" / "reflections.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert memory_rows[0]["pattern"] == "high_turnover"
    assert Path(store.memory_path("accepted_candidates")).name == "accepted_candidates.jsonl"


def test_experiment_store_relative_root_writes_to_returned_paths(tmp_path, monkeypatch):
    from custom_bt.ai_research.memory import ExperimentStore

    monkeypatch.chdir(tmp_path)
    store = ExperimentStore(Path("outputs") / "ai_research")
    session_dir = store.create_session("relative_session", {"objective": "test"})
    memory_path = store.append_memory("reflections", {"pattern": "relative_root"})

    assert session_dir.is_absolute()
    assert (session_dir / "research_spec.json").exists()
    assert memory_path.is_absolute()
    assert memory_path.exists()
    assert not (tmp_path / "outputs" / "ai_research" / "outputs").exists()


def test_experiment_store_rejects_paths_outside_research_root(tmp_path):
    from custom_bt.ai_research.memory import ExperimentStore

    store = ExperimentStore(tmp_path)

    with pytest.raises(ValueError, match="session_id"):
        store.create_session("../escape", {"objective": "bad"})

    with pytest.raises(ValueError, match="research root"):
        store.write_json(tmp_path.parent / "escape.json", {"bad": True})

    with pytest.raises(ValueError, match="research root"):
        store.append_jsonl(tmp_path.parent / "escape.jsonl", {"bad": True})

    with pytest.raises(ValueError, match="memory_name"):
        store.append_memory("../reflections", {"bad": True})


def test_experiment_store_rejects_duplicate_session_id(tmp_path):
    from custom_bt.ai_research.memory import ExperimentStore

    store = ExperimentStore(tmp_path)
    store.create_session("unit_session", {"objective": "first"})

    with pytest.raises(FileExistsError):
        store.create_session("unit_session", {"objective": "second"})


def test_deepseek_env_settings_load_from_local_file(tmp_path):
    from custom_bt.ai_research.llm_client import load_local_env, resolve_llm_settings

    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=sk-test",
                "AI_RESEARCH_LLM_PROVIDER=deepseek",
                "AI_RESEARCH_LLM_MODEL=deepseek-v4-flash",
                "DEEPSEEK_CA_BUNDLE=C:/certs/cacert.pem",
            ]
        ),
        encoding="utf-8",
    )

    values = load_local_env(env_path)
    settings = resolve_llm_settings(
        {
            "llm": {
                "provider": "none",
                "model": "none",
                "temperature": 0.2,
                "top_p": 1.0,
                "timeout_seconds": 120,
            }
        },
        env_path=env_path,
        environ={},
    )

    assert values["DEEPSEEK_API_KEY"] == "sk-test"
    assert settings["provider"] == "deepseek"
    assert settings["model"] == "deepseek-v4-flash"
    assert settings["api_key"] == "sk-test"
    assert settings["base_url"] == "https://api.deepseek.com"
    assert settings["ca_bundle"] == "C:/certs/cacert.pem"


def test_deepseek_client_builds_json_chat_completion_request():
    from custom_bt.ai_research.llm_client import DeepSeekChatClient

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"answer": "ok"}'},
                        }
                    ],
                    "usage": {"total_tokens": 12},
                }
            ).encode("utf-8")

    def fake_opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    client = DeepSeekChatClient(
        api_key="sk-test",
        model="deepseek-v4-flash",
        timeout_seconds=9,
        opener=fake_opener,
    )

    response = client.complete_json("只输出 JSON", system_prompt="system")

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["messages"][0] == {"role": "system", "content": "system"}
    assert captured["timeout"] == 9
    assert response.parsed == {"answer": "ok"}
    assert response.usage == {"total_tokens": 12}


def test_deepseek_client_default_opener_uses_https_ssl_context(monkeypatch):
    from custom_bt.ai_research import llm_client
    from custom_bt.ai_research.llm_client import DeepSeekChatClient

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"answer": "ok"}'},
                        }
                    ],
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None, context=None):
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)

    client = DeepSeekChatClient(
        api_key="sk-test",
        model="deepseek-v4-flash",
        timeout_seconds=9,
    )
    response = client.complete_json("只输出 JSON")

    assert captured["timeout"] == 9
    assert captured["context"] is not None
    assert response.parsed == {"answer": "ok"}


def test_parse_json_content_accepts_fenced_json():
    from custom_bt.ai_research.llm_client import parse_json_content

    assert parse_json_content('```json\n{"status": "ok"}\n```') == {"status": "ok"}

    with pytest.raises(ValueError, match="valid JSON"):
        parse_json_content("not-json")


def test_ai_research_runner_creates_model_backed_research_spec_session(tmp_path):
    from custom_bt.ai_research.llm_client import LLMResponse
    from custom_bt.ai_research.runner import AIResearchRunner

    master = tmp_path / "data_cache" / "master"
    master.mkdir(parents=True)
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
    pool_dir = tmp_path / "data_cache" / "pools" / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps({"pool_id": "pool_a", "n_stocks": 2, "source_signature": "sig_a"}),
        encoding="utf-8",
    )

    class FakeClient:
        def complete_json(self, prompt, system_prompt=None):
            assert "Research Spec" in prompt
            parsed = {
                "objective": "寻找中期量价 Alpha",
                "pool_id": "pool_a",
                "target_horizon": 20,
                "holding_period": 20,
                "preferred_fields": ["close", "volume"],
                "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
            }
            return LLMResponse(
                content=json.dumps(parsed, ensure_ascii=False),
                parsed=parsed,
                raw={"id": "fake"},
                model="deepseek-v4-flash",
                finish_reason="stop",
                usage={"total_tokens": 1},
            )

    config = {
        "agent": {"max_tool_calls_per_round": 8, "max_candidates_per_round": 10},
        "llm": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "research_defaults": {"pool_id": "pool_a", "target_horizon": 20},
        "paths": {
            "master_store": "data_cache/master",
            "pools_root": "data_cache/pools",
            "factor_runs_root": "factor_runs",
            "saved_results_root": "outputs/saved_backtests",
            "ai_research_root": "outputs/ai_research",
        },
    }
    runner = AIResearchRunner(config=config, client=FakeClient(), project_root=tmp_path)

    result = runner.create_research_spec_session(
        "找中期量价因子",
        session_id="unit_model_session",
        pool_id="pool_a",
    )

    session_dir = result["session_dir"]
    assert session_dir.is_absolute()
    assert result["research_spec"]["pool_id"] == "pool_a"
    assert (session_dir / "research_spec.json").exists()
    assert (session_dir / "context_snapshot.json").exists()
    assert (session_dir / "research_spec_prompt.json").exists()
    assert (session_dir / "research_spec_llm_response.json").exists()


def test_validate_candidate_expression_uses_local_fields_and_operators():
    from custom_bt.ai_research.tools import validate_candidate_expression

    context = {
        "master_store": {"fields": ["close", "volume"]},
        "operators": ["rank", "ts_mean"],
        "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
    }

    ok = validate_candidate_expression(
        {"candidate_id": "cand_001", "expression": "rank(ts_mean(volume,2))"},
        context,
    )
    bad_field = validate_candidate_expression(
        {"candidate_id": "cand_002", "expression": "rank(amount)"},
        context,
    )
    bad_operator = validate_candidate_expression(
        {"candidate_id": "cand_003", "expression": "foo(close)"},
        context,
    )

    assert ok["status"] == "valid"
    assert ok["used_fields"] == ["volume"]
    assert ok["used_operators"] == ["rank", "ts_mean"]
    assert bad_field["status"] == "invalid"
    assert "amount" in bad_field["unknown_fields"]
    assert bad_operator["status"] == "invalid"
    assert "foo" in bad_operator["unknown_operators"]


def test_factor_backtest_adapter_accepts_local_agent_expression():
    import pandas as pd

    from custom_bt.factor_adapter import validate_backtest_expression

    panel = pd.DataFrame(
        [
            {"date": "2024-01-01", "code": "000001", "close": 10.0, "volume": 100.0},
            {"date": "2024-01-01", "code": "000002", "close": 11.0, "volume": 120.0},
            {"date": "2024-01-02", "code": "000001", "close": 10.5, "volume": 110.0},
            {"date": "2024-01-02", "code": "000002", "close": 10.8, "volume": 130.0},
            {"date": "2024-01-03", "code": "000001", "close": 10.7, "volume": 150.0},
            {"date": "2024-01-03", "code": "000002", "close": 11.2, "volume": 90.0},
        ]
    )

    translated = validate_backtest_expression("rank(ts_mean(volume,2))", panel)

    assert translated == "rank(ts_mean(volume,2))"


def test_ai_tool_executor_materializes_candidates_and_creates_backtest_job(tmp_path, monkeypatch):
    from custom_bt.ai_research.memory import ExperimentStore
    from custom_bt.ai_research.tool_executor import AIToolExecutor

    store = ExperimentStore(tmp_path / "outputs" / "ai_research")
    session_dir = store.create_session(
        "unit_tool_session",
        {
            "objective": "test",
            "pool_id": "pool_a",
            "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
        },
    )
    candidates = [
        {
            "candidate_id": "cand_001",
            "expression": "rank(ts_mean(volume,2))",
            "validation": {"status": "valid"},
        },
        {
            "candidate_id": "cand_002",
            "expression": "rank(amount)",
            "validation": {"status": "invalid"},
        },
    ]
    context = {
        "master_store": {"fields": ["close", "volume"], "source_signature": "sig_a"},
        "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
    }
    config = {
        "agent": {"max_tool_calls_per_round": 8},
        "research_defaults": {
            "pool_id": "pool_a",
            "target_horizon": 20,
            "train_start": "2022-01-01",
            "train_end": "2023-01-01",
            "valid_start": "2023-01-02",
            "valid_end": "2024-01-01",
            "test_start": "2024-01-02",
            "test_end": "2024-12-31",
        },
        "paths": {
            "master_store": "data_cache/master",
            "pools_root": "data_cache/pools",
            "factor_runs_root": "factor_runs",
            "saved_results_root": "outputs/saved_backtests",
            "ai_research_root": "outputs/ai_research",
            "jobs_root": "jobs",
        },
        "quality_gates": {"min_coverage": 0.8, "min_valid_ic": 0.02, "min_icir": 0.2},
    }
    created = {}

    def fake_create_platform_job(jobs_root, operation, payload):
        created["jobs_root"] = str(jobs_root)
        created["operation"] = operation
        created["payload"] = payload
        job_dir = tmp_path / "jobs" / "job_001"
        job_dir.mkdir(parents=True)
        return job_dir

    monkeypatch.setattr("custom_bt.ai_research.tool_executor.create_platform_job", fake_create_platform_job)

    executor = AIToolExecutor(
        config=config,
        context=context,
        store=store,
        session_dir=session_dir,
        project_root=tmp_path,
        candidates=candidates,
    )
    result = executor.execute_plan(
        {
            "tool_plan": [
                {
                    "tool_name": "create_factor_backtest_job",
                    "arguments": {"candidate_ids": ["cand_001", "cand_002"]},
                }
            ],
            "max_tool_calls": 8,
        }
    )

    assert result["tool_call_count"] == 1
    assert result["results"][0]["status"] == "created"
    assert created["operation"] == "backtest_factors"
    assert created["payload"]["expected_pool_id"] == "pool_a"
    factor_run_dir = Path(created["payload"]["factor_run_dir"])
    assert factor_run_dir.exists()
    manifest = json.loads((factor_run_dir / "factor_run.json").read_text(encoding="utf-8"))
    assert manifest["pool_id"] == "pool_a"
    assert manifest["source_signature"] == "sig_a"
    assert manifest["accepted_count"] == 1
    rows = [
        json.loads(line)
        for line in (factor_run_dir / "accepted_factors.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["candidate_id"] == "cand_001"
    assert rows[0]["backtest_expression"] == "rank(ts_mean(volume,2))"
    assert (session_dir / "tool_results.jsonl").exists()


def test_ai_tool_executor_can_run_created_job_when_enabled(tmp_path, monkeypatch):
    from custom_bt.ai_research.memory import ExperimentStore
    from custom_bt.ai_research.tool_executor import AIToolExecutor

    store = ExperimentStore(tmp_path / "outputs" / "ai_research")
    session_dir = store.create_session("unit_run_job_session", {"objective": "test"})
    context = {
        "master_store": {"fields": ["close", "volume"], "source_signature": "sig_a"},
        "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
    }
    config = {
        "agent": {"max_tool_calls_per_round": 8},
        "research_defaults": {"pool_id": "pool_a", "target_horizon": 20},
        "paths": {
            "master_store": "data_cache/master",
            "pools_root": "data_cache/pools",
            "factor_runs_root": "factor_runs",
            "saved_results_root": "outputs/saved_backtests",
            "jobs_root": "jobs",
        },
    }
    calls = {}

    def fake_create_platform_job(jobs_root, operation, payload):
        job_dir = tmp_path / "jobs" / "job_002"
        job_dir.mkdir(parents=True)
        calls["created"] = {"operation": operation, "payload": payload, "job_dir": str(job_dir)}
        return job_dir

    def fake_run_platform_job(job_dir):
        calls["ran"] = str(job_dir)
        return {"completed": 1, "failed": 0}

    monkeypatch.setattr("custom_bt.ai_research.tool_executor.create_platform_job", fake_create_platform_job)
    monkeypatch.setattr("custom_bt.ai_research.tool_executor.run_platform_job", fake_run_platform_job)

    executor = AIToolExecutor(
        config=config,
        context=context,
        store=store,
        session_dir=session_dir,
        project_root=tmp_path,
        candidates=[
            {
                "candidate_id": "cand_001",
                "expression": "rank(ts_mean(volume,2))",
                "validation": {"status": "valid"},
            }
        ],
        execute_long_jobs=True,
    )
    result = executor.execute_plan(
        {
            "tool_plan": [
                {"tool_name": "create_factor_backtest_job", "arguments": {"candidate_ids": ["cand_001"]}}
            ],
            "max_tool_calls": 8,
        }
    )

    assert result["results"][0]["status"] == "finished"
    assert calls["ran"].endswith("job_002")
    assert result["results"][0]["run_result"] == {"completed": 1, "failed": 0}


def test_ai_tool_executor_loads_saved_results(tmp_path):
    from custom_bt.ai_research.memory import ExperimentStore
    from custom_bt.ai_research.tool_executor import AIToolExecutor

    saved_dir = tmp_path / "outputs" / "saved_backtests" / "factor" / "pool_a" / "run_a"
    saved_dir.mkdir(parents=True)
    (saved_dir / "manifest.json").write_text(
        json.dumps({"result_type": "factor", "pool_id": "pool_a", "run_name": "factor_001"}),
        encoding="utf-8",
    )
    (saved_dir / "factor_backtest_summary.csv").write_text(
        "factor_id,backtest_sharpe\nfactor_001,1.23\n",
        encoding="utf-8",
    )
    store = ExperimentStore(tmp_path / "outputs" / "ai_research")
    session_dir = store.create_session("unit_load_results_session", {"objective": "test"})
    executor = AIToolExecutor(
        config={
            "agent": {"max_tool_calls_per_round": 8},
            "paths": {"saved_results_root": "outputs/saved_backtests"},
        },
        context={"identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"}},
        store=store,
        session_dir=session_dir,
        project_root=tmp_path,
        candidates=[],
    )

    result = executor.execute_plan(
        {
            "tool_plan": [
                {"tool_name": "load_saved_results", "arguments": {"pool_id": "pool_a", "result_type": "factor"}}
            ],
            "max_tool_calls": 8,
        }
    )

    payload = result["results"][0]["result"]
    assert payload["result_count"] == 1
    assert payload["results"][0]["pool_id"] == "pool_a"
    assert payload["summaries"][0]["factor_id"] == "factor_001"


def test_ai_research_runner_runs_candidate_tool_plan_session(tmp_path):
    from custom_bt.ai_research.llm_client import LLMResponse
    from custom_bt.ai_research.runner import AIResearchRunner

    master = tmp_path / "data_cache" / "master"
    master.mkdir(parents=True)
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
    pool_dir = tmp_path / "data_cache" / "pools" / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps({"pool_id": "pool_a", "n_stocks": 2, "source_signature": "sig_a"}),
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def complete_json(self, prompt, system_prompt=None):
            self.calls += 1
            if "Research Spec" in prompt:
                parsed = {
                    "objective": "寻找中期量价 Alpha",
                    "pool_id": "pool_a",
                    "target_horizon": 20,
                    "holding_period": 20,
                    "preferred_fields": ["close", "volume"],
                    "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
                }
            elif "候选因子表达式" in prompt:
                parsed = [
                    {
                        "candidate_id": "cand_001",
                        "hypothesis_id": "hyp_001",
                        "expression": "rank(ts_mean(volume,2))",
                        "expected_direction": "positive",
                        "rationale": "量能中期强度排序。",
                        "used_fields": ["volume"],
                        "used_operators": ["rank", "ts_mean"],
                    },
                    {
                        "candidate_id": "cand_002",
                        "hypothesis_id": "hyp_002",
                        "expression": "rank(amount)",
                        "expected_direction": "unknown",
                        "rationale": "应被本地字段校验拦截。",
                    },
                ]
            else:
                parsed = {
                    "tool_plan": [
                        {
                            "tool_name": "validate_expression",
                            "arguments": {"candidate_id": "cand_001", "expression": "rank(ts_mean(volume,2))"},
                        }
                    ],
                    "requires_user_confirmation": True,
                    "max_tool_calls": 8,
                    "stop_after_report": True,
                }
            return LLMResponse(
                content=json.dumps(parsed, ensure_ascii=False),
                parsed=parsed,
                raw={"id": f"fake_{self.calls}"},
                model="deepseek-v4-flash",
                finish_reason="stop",
                usage={"total_tokens": self.calls},
            )

    config = {
        "agent": {"max_tool_calls_per_round": 8, "max_candidates_per_round": 10},
        "llm": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "research_defaults": {"pool_id": "pool_a", "target_horizon": 20},
        "paths": {
            "master_store": "data_cache/master",
            "pools_root": "data_cache/pools",
            "factor_runs_root": "factor_runs",
            "saved_results_root": "outputs/saved_backtests",
            "ai_research_root": "outputs/ai_research",
        },
    }
    runner = AIResearchRunner(config=config, client=FakeClient(), project_root=tmp_path)

    result = runner.run_research_session(
        "找中期量价因子",
        session_id="unit_full_session",
        pool_id="pool_a",
    )

    session_dir = result["session_dir"]
    candidate_rows = [
        json.loads(line)
        for line in (session_dir / "candidate_expressions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    validation_rows = [
        json.loads(line)
        for line in (session_dir / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["summary"]["candidate_count"] == 2
    assert result["summary"]["valid_candidate_count"] == 1
    assert candidate_rows[0]["candidate_id"] == "cand_001"
    assert validation_rows[0]["status"] == "valid"
    assert validation_rows[1]["status"] == "invalid"
    assert (session_dir / "expression_proposal_prompt.json").exists()
    assert (session_dir / "tool_plan.json").exists()
    assert (session_dir / "report.md").exists()
    assert (tmp_path / "outputs" / "ai_research" / "memory" / "reflections.jsonl").exists()


def test_ai_research_runner_executes_tool_plan_when_enabled(tmp_path, monkeypatch):
    from custom_bt.ai_research.llm_client import LLMResponse
    from custom_bt.ai_research.runner import AIResearchRunner
    import custom_bt.ai_research.runner as runner_module

    master = tmp_path / "data_cache" / "master"
    master.mkdir(parents=True)
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
    pool_dir = tmp_path / "data_cache" / "pools" / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps({"pool_id": "pool_a", "n_stocks": 2, "source_signature": "sig_a"}),
        encoding="utf-8",
    )
    calls = {}

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def complete_json(self, prompt, system_prompt=None):
            self.calls += 1
            if "Research Spec" in prompt:
                parsed = {
                    "objective": "寻找中期量价 Alpha",
                    "pool_id": "pool_a",
                    "target_horizon": 20,
                    "holding_period": 20,
                    "preferred_fields": ["close", "volume"],
                    "identity_lock": {"pool_id": "pool_a", "source_signature": "sig_a"},
                }
            elif "候选因子表达式" in prompt:
                parsed = [
                    {
                        "candidate_id": "cand_001",
                        "expression": "rank(ts_mean(volume,2))",
                        "expected_direction": "positive",
                    }
                ]
            else:
                parsed = {
                    "tool_plan": [
                        {"tool_name": "create_factor_backtest_job", "arguments": {"candidate_ids": ["cand_001"]}}
                    ],
                    "max_tool_calls": 8,
                }
            return LLMResponse(
                content=json.dumps(parsed, ensure_ascii=False),
                parsed=parsed,
                raw={"id": f"fake_{self.calls}"},
                model="deepseek-v4-flash",
            )

    class FakeExecutor:
        def __init__(self, **kwargs):
            calls["executor_init"] = kwargs

        def execute_plan(self, tool_plan):
            calls["tool_plan"] = tool_plan
            return {
                "tool_call_count": 1,
                "created_job_count": 1,
                "finished_job_count": 0,
                "results": [{"tool_name": "create_factor_backtest_job", "status": "created"}],
            }

    monkeypatch.setattr(runner_module, "AIToolExecutor", FakeExecutor, raising=False)

    config = {
        "agent": {"max_tool_calls_per_round": 8, "max_candidates_per_round": 10},
        "llm": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "research_defaults": {"pool_id": "pool_a", "target_horizon": 20},
        "paths": {
            "master_store": "data_cache/master",
            "pools_root": "data_cache/pools",
            "factor_runs_root": "factor_runs",
            "saved_results_root": "outputs/saved_backtests",
            "ai_research_root": "outputs/ai_research",
            "jobs_root": "jobs",
        },
    }
    runner = AIResearchRunner(config=config, client=FakeClient(), project_root=tmp_path)

    result = runner.run_research_session(
        "找中期量价因子",
        session_id="unit_execute_session",
        pool_id="pool_a",
        execute_tools=True,
        execute_long_jobs=True,
    )

    assert calls["executor_init"]["execute_long_jobs"] is True
    assert calls["executor_init"]["candidates"][0]["candidate_id"] == "cand_001"
    assert calls["tool_plan"]["tool_plan"][0]["tool_name"] == "create_factor_backtest_job"
    assert result["summary"]["executed_tool_call_count"] == 1
    assert result["summary"]["created_job_count"] == 1
    assert result["tool_execution"]["results"][0]["status"] == "created"
    assert (result["session_dir"] / "tool_execution.json").exists()


def test_ai_research_cli_run_uses_runner_and_prints_summary(capsys, monkeypatch, tmp_path):
    from custom_bt.ai_research import cli as ai_cli

    calls = {}

    class FakeRunner:
        def __init__(self, config_path, project_root, env_path):
            calls["init"] = {
                "config_path": str(config_path),
                "project_root": str(project_root),
                "env_path": str(env_path),
            }

        def run_research_session(
            self,
            user_intent,
            session_id=None,
            pool_id=None,
            max_candidates=None,
            execute_tools=False,
            execute_long_jobs=False,
        ):
            calls["run"] = {
                "user_intent": user_intent,
                "session_id": session_id,
                "pool_id": pool_id,
                "max_candidates": max_candidates,
                "execute_tools": execute_tools,
                "execute_long_jobs": execute_long_jobs,
            }
            return {
                "session_dir": tmp_path / "outputs" / "ai_research" / "sessions" / "cli_session",
                "summary": {"candidate_count": 2, "valid_candidate_count": 1},
            }

    monkeypatch.setattr(ai_cli, "AIResearchRunner", FakeRunner)

    ai_cli.main(
        [
            "run",
            "找中期量价因子",
            "--config",
            "configs/ai_research_agent.yaml",
            "--project-root",
            str(tmp_path),
            "--env",
            ".env.local",
            "--session-id",
            "cli_session",
            "--pool",
            "pool_a",
            "--max-candidates",
            "2",
            "--execute-tools",
            "--execute-long-jobs",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert calls["run"]["user_intent"] == "找中期量价因子"
    assert calls["run"]["session_id"] == "cli_session"
    assert calls["run"]["pool_id"] == "pool_a"
    assert calls["run"]["max_candidates"] == 2
    assert calls["run"]["execute_tools"] is True
    assert calls["run"]["execute_long_jobs"] is True
    assert output["summary"]["valid_candidate_count"] == 1
    assert output["session_dir"].endswith("cli_session")
