from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import yaml

from custom_bt.alpha import alpha_components, canonical_alpha_expression, combine_alphas, normalize_alpha_defs
from custom_bt.data import (
    CORE_COLUMNS,
    build_master_store,
    list_store_fields,
    load_store,
    read_panel,
    save_store_stock_list,
    update_store,
)
from custom_bt.engine import BacktestConfig, run_backtest
from custom_bt.expressions import available_fields, list_operators
from custom_bt.factor_backtest import backtest_accepted_factors
from custom_bt.factor_composition import compose_factors
from custom_bt.factor_generation import run_factor_generation
from custom_bt.jobs import run_backtest_job
from custom_bt.migrate_results import migrate_factor_results
from custom_bt.pools import create_pool
from custom_bt.platform_jobs import run_platform_job
from custom_bt.results import list_runs, save_result
from custom_bt.ai_research.runner import AIResearchRunner


def _load_config(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_path(value: str | Path, config_path: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(config_path).expanduser().resolve().parent / path
    return path.resolve()


def prepare_cmd(args: argparse.Namespace) -> None:
    cols = None if args.all_columns else CORE_COLUMNS
    result = update_store(args.csv, args.out, chunksize=args.chunksize, columns=cols)
    print(json.dumps(result, indent=2))


def prepare_master_cmd(args: argparse.Namespace) -> None:
    cfg = _load_config(args.config)
    result = build_master_store(
        csv_path=_resolve_path(cfg["source_csv"], args.config),
        store_dir=_resolve_path(cfg.get("master_store", "data_cache/master"), args.config),
        fields=cfg.get("factor_fields", cfg.get("fields", [])),
        chunksize=int(cfg.get("chunksize", 200_000)),
        limit_rows=cfg.get("limit_rows"),
        overwrite=bool(cfg.get("overwrite", False)),
        delimiter=cfg.get("delimiter"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def create_pool_cmd(args: argparse.Namespace) -> None:
    cfg = _load_config(args.config)
    codes = cfg.get("codes")
    if cfg.get("codes_file"):
        codes = [
            line.strip()
            for line in _resolve_path(cfg["codes_file"], args.config).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    result = create_pool(
        store_dir=_resolve_path(cfg["master_store"], args.config),
        pools_root=_resolve_path(cfg.get("pools_root", "data_cache/pools"), args.config),
        name=str(cfg["name"]),
        selection_start=str(cfg["selection_start"]),
        selection_end=str(cfg["selection_end"]),
        top_n=None if cfg.get("top_n") is None else int(cfg["top_n"]),
        min_listed_days=int(cfg.get("min_listed_days", 0)),
        min_coverage=float(cfg.get("min_coverage", 0.0)),
        exclude_suspended=bool(cfg.get("exclude_suspended", True)),
        category=cfg.get("category"),
        market_code=cfg.get("market_code"),
        codes=codes,
        overwrite=bool(cfg.get("overwrite", False)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def generate_factors_cmd(args: argparse.Namespace) -> None:
    cfg = _load_config(args.config)
    result = run_factor_generation(
        master_store=_resolve_path(cfg["master_store"], args.config),
        pools_root=_resolve_path(cfg["pools_root"], args.config),
        pool_id=args.pool,
        runtime_root=_resolve_path(cfg.get("runtime_root", "data_cache/factor_runtime"), args.config),
        factor_runs_root=_resolve_path(cfg.get("factor_runs_root", "factor_runs"), args.config),
        fields=cfg["fields"],
        splits=cfg["splits"],
        max_backtrack_days=int(cfg.get("max_backtrack_days", 100)),
        target_horizon=int(cfg.get("target_horizon", 20)),
        max_future_days=int(cfg.get("max_future_days", cfg.get("target_horizon", 20))),
        generation_config=cfg,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def backtest_factors_cmd(args: argparse.Namespace) -> None:
    cfg = _load_config(args.config)
    factor_run = Path(args.factor_run).expanduser()
    if not factor_run.is_absolute():
        factor_run = _resolve_path(cfg.get("factor_runs_root", "factor_runs"), args.config) / factor_run
    result = backtest_accepted_factors(
        master_store=_resolve_path(cfg["master_store"], args.config),
        pools_root=_resolve_path(cfg["pools_root"], args.config),
        factor_run_dir=factor_run,
        outputs_root=_resolve_path(cfg.get("outputs_root", "outputs/saved_backtests"), args.config),
        backtest_config=cfg["backtest"],
        expected_pool_id=args.pool,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def _parse_int_list(value: str | None) -> List[int] | None:
    if value is None or not str(value).strip():
        return None
    return [int(item.strip()) for item in str(value).replace(",", "\n").splitlines() if item.strip()]


def compose_factors_cmd(args: argparse.Namespace) -> None:
    cfg = _load_config(args.config)
    factor_runs_root = _resolve_path(cfg.get("factor_runs_root", "factor_runs"), args.config)
    factor_run_dirs = []
    for item in args.factor_run:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = factor_runs_root / path
        factor_run_dirs.append(path)
    result = compose_factors(
        master_store=_resolve_path(cfg["master_store"], args.config),
        pools_root=_resolve_path(cfg["pools_root"], args.config),
        pool_id=args.pool,
        factor_run_dirs=factor_run_dirs,
        outputs_root=_resolve_path(cfg.get("outputs_root", "outputs/saved_backtests"), args.config),
        backtest_config=cfg["backtest"],
        selection_metric=args.selection_metric,
        min_score=args.min_score,
        min_ic=args.min_ic,
        min_rank_ic=args.min_rank_ic,
        min_coverage=args.min_coverage,
        min_backtest_sharpe=args.min_backtest_sharpe,
        mutual_ic_threshold=args.mutual_ic_threshold,
        sweep_sizes=_parse_int_list(args.sweep_sizes),
        max_factors=args.max_factors,
        objective_type=args.objective_type,
        target_horizon=args.target_horizon,
        min_marginal_ic_improvement=args.min_marginal_ic_improvement,
        min_marginal_rank_ic_improvement=args.min_marginal_rank_ic_improvement,
        min_marginal_icir_improvement=args.min_marginal_icir_improvement,
        min_marginal_rank_icir_improvement=args.min_marginal_rank_icir_improvement,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def fields_cmd(args: argparse.Namespace) -> None:
    if Path(args.data).is_dir():
        fields = list_store_fields(args.data)
    else:
        fields = available_fields(read_panel(args.data))
    print(json.dumps(fields, ensure_ascii=False, indent=2))


def operators_cmd(args: argparse.Namespace) -> None:
    print(json.dumps(list_operators(), ensure_ascii=False, indent=2))


def backtest_cmd(args: argparse.Namespace) -> None:
    cfg_raw = _load_config(args.alpha_config)
    bt_raw = cfg_raw.get("backtest", {})
    panel = load_store(args.data, bt_raw.get("start_date"), bt_raw.get("end_date")) if Path(args.data).is_dir() else read_panel(args.data)
    if "alpha_csv" in cfg_raw:
        alpha = pd.read_csv(cfg_raw["alpha_csv"])
        canonical_expression = str(cfg_raw["alpha_csv"])
    else:
        alpha_defs = normalize_alpha_defs(cfg_raw.get("alphas", []))
        alpha = combine_alphas(panel, alpha_defs)
        canonical_expression = canonical_alpha_expression(alpha_defs)
    is_composite = cfg_raw.get("result_type") == "composite" or len(cfg_raw.get("alphas", [])) > 1
    cfg = BacktestConfig(**bt_raw)
    result = run_backtest(panel, alpha, cfg)
    out_dir = save_result(
        result,
        "outputs/saved_backtests",
        args.run_name,
        config=cfg_raw,
        metadata={
            "result_type": "composite" if is_composite else "manual",
            "canonical_expression": canonical_expression,
            "components": alpha_components(alpha_defs) if "alpha_defs" in locals() else [],
        },
    )
    print(f"saved outputs to {out_dir.resolve()}")


def runs_cmd(args: argparse.Namespace) -> None:
    print(json.dumps(list_runs(args.outputs), ensure_ascii=False, indent=2))


def migrate_results_cmd(args: argparse.Namespace) -> None:
    report = migrate_factor_results(args.source, args.destination)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def stock_list_cmd(args: argparse.Namespace) -> None:
    result = save_store_stock_list(args.data, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_job_cmd(args: argparse.Namespace) -> None:
    out_dir = run_backtest_job(args.job_dir)
    print(f"job finished, saved outputs to {out_dir.resolve()}")


def run_platform_job_cmd(args: argparse.Namespace) -> None:
    result = run_platform_job(args.job_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def ai_research_cmd(args: argparse.Namespace) -> None:
    runner = AIResearchRunner(
        config_path=args.config,
        project_root=args.project_root,
        env_path=args.env,
    )
    result = runner.run_research_session(
        args.intent,
        session_id=args.session_id,
        pool_id=args.pool,
        max_candidates=args.max_candidates,
        execute_tools=args.execute_tools,
        execute_long_jobs=args.execute_long_jobs,
    )
    print(
        json.dumps(
            {
                "session_dir": str(result["session_dir"]),
                "summary": result["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Custom independent stock backtester.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["prepare", "update"]:
        p_prepare = sub.add_parser(name)
        p_prepare.add_argument("--csv", required=True)
        p_prepare.add_argument("--out", required=True, help="Store directory, e.g. data_cache/stock_daily")
        p_prepare.add_argument("--chunksize", type=int, default=200_000)
        p_prepare.add_argument("--all-columns", action="store_true", help="Try to load every CSV column.")
    p_prepare.set_defaults(func=prepare_cmd)
    p_master = sub.add_parser("prepare-master")
    p_master.add_argument("--config", required=True)
    p_master.set_defaults(func=prepare_master_cmd)
    p_pool = sub.add_parser("create-pool")
    p_pool.add_argument("--config", required=True)
    p_pool.set_defaults(func=create_pool_cmd)
    p_generate = sub.add_parser("generate-factors")
    p_generate.add_argument("--pool", required=True)
    p_generate.add_argument("--config", required=True)
    p_generate.set_defaults(func=generate_factors_cmd)
    p_factor_backtest = sub.add_parser("backtest-factors")
    p_factor_backtest.add_argument("--pool", required=True)
    p_factor_backtest.add_argument("--factor-run", required=True)
    p_factor_backtest.add_argument("--config", required=True)
    p_factor_backtest.set_defaults(func=backtest_factors_cmd)
    p_compose = sub.add_parser("compose-factors")
    p_compose.add_argument("--pool", required=True)
    p_compose.add_argument("--factor-run", required=True, action="append")
    p_compose.add_argument("--config", required=True)
    p_compose.add_argument("--selection-metric", default="score")
    p_compose.add_argument("--min-score", type=float, default=None)
    p_compose.add_argument("--min-ic", type=float, default=None)
    p_compose.add_argument("--min-rank-ic", type=float, default=None)
    p_compose.add_argument("--min-coverage", type=float, default=None)
    p_compose.add_argument("--min-backtest-sharpe", type=float, default=None)
    p_compose.add_argument("--mutual-ic-threshold", type=float, default=0.99)
    p_compose.add_argument("--sweep-sizes", default=None, help="Comma/newline separated sizes, e.g. 10,20,30")
    p_compose.add_argument("--max-factors", type=int, default=100)
    p_compose.add_argument("--objective-type", default="mse")
    p_compose.add_argument("--target-horizon", type=int, default=20)
    p_compose.add_argument("--min-marginal-ic-improvement", type=float, default=None)
    p_compose.add_argument("--min-marginal-rank-ic-improvement", type=float, default=None)
    p_compose.add_argument("--min-marginal-icir-improvement", type=float, default=None)
    p_compose.add_argument("--min-marginal-rank-icir-improvement", type=float, default=None)
    p_compose.set_defaults(func=compose_factors_cmd)
    p_migrate = sub.add_parser("migrate-results")
    p_migrate.add_argument("--source", default="outputs/factor_backtests")
    p_migrate.add_argument("--destination", default="outputs/saved_backtests")
    p_migrate.set_defaults(func=migrate_results_cmd)
    p_backtest = sub.add_parser("backtest")
    p_backtest.add_argument("--data", required=True)
    p_backtest.add_argument("--alpha-config", required=True)
    p_backtest.add_argument("--run-name", required=True)
    p_backtest.set_defaults(func=backtest_cmd)
    p_fields = sub.add_parser("fields")
    p_fields.add_argument("--data", required=True)
    p_fields.set_defaults(func=fields_cmd)
    p_ops = sub.add_parser("operators")
    p_ops.set_defaults(func=operators_cmd)
    p_runs = sub.add_parser("runs")
    p_runs.add_argument("--outputs", default="outputs")
    p_runs.set_defaults(func=runs_cmd)
    p_stock_list = sub.add_parser("stock-list")
    p_stock_list.add_argument("--data", required=True, help="Store directory, e.g. data_cache/stock_daily")
    p_stock_list.add_argument("--out", default=None, help="Optional output CSV. Default: <data>/stock_list.csv")
    p_stock_list.set_defaults(func=stock_list_cmd)
    p_job = sub.add_parser("run-job")
    p_job.add_argument("--job-dir", required=True)
    p_job.set_defaults(func=run_job_cmd)
    p_platform_job = sub.add_parser("run-platform-job")
    p_platform_job.add_argument("--job-dir", required=True)
    p_platform_job.set_defaults(func=run_platform_job_cmd)
    p_ai = sub.add_parser("ai-research")
    p_ai.add_argument("intent", help="Natural language research goal.")
    p_ai.add_argument("--config", default="configs/ai_research_agent.yaml")
    p_ai.add_argument("--project-root", default=".")
    p_ai.add_argument("--env", default=".env.local")
    p_ai.add_argument("--session-id", default=None)
    p_ai.add_argument("--pool", default=None)
    p_ai.add_argument("--max-candidates", type=int, default=None)
    p_ai.add_argument("--execute-tools", action="store_true")
    p_ai.add_argument("--execute-long-jobs", action="store_true")
    p_ai.set_defaults(func=ai_research_cmd)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
