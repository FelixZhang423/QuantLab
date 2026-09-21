"""Command-line entry points for independent research data operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .exporter import ExportSources, export_snapshot
from .io import file_sha256, resolve_snapshot, validate_unique_keys
from .research_run import run_state_analysis
from .factor_values import materialize_factor_values
from .conditional_run import run_conditional_evaluation
from .selection import run_selection
from .schema import (
    BACKTEST_METRIC_REQUIRED_COLUMNS,
    FACTOR_METRIC_REQUIRED_COLUMNS,
    FACTOR_REQUIRED_COLUMNS,
    MARKET_REQUIRED_COLUMNS,
    TABLE_FILENAMES,
    UNIVERSE_REQUIRED_COLUMNS,
)


def _load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("YAML config requires PyYAML; use a JSON config instead") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("config must contain a mapping")
    return value


def validate_snapshot(data_root: str | Path, snapshot_id: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        snapshot = resolve_snapshot(data_root, snapshot_id)
    except (FileNotFoundError, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)], "snapshot": None}
    manifest_path = snapshot / "manifest.json"
    if not manifest_path.exists():
        return {"valid": False, "errors": [f"manifest is missing: {manifest_path}"], "snapshot": str(snapshot)}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"valid": False, "errors": [f"invalid manifest JSON: {exc}"], "snapshot": str(snapshot)}
    if manifest.get("snapshot_id") != snapshot.name:
        errors.append("manifest snapshot_id does not match directory name")
    listed = {str(item.get("path")): item for item in manifest.get("files", []) if isinstance(item, dict)}
    for filename in TABLE_FILENAMES:
        path = snapshot / filename
        if not path.exists():
            errors.append(f"required table is missing: {filename}")
            continue
        item = listed.get(filename)
        if item is None:
            errors.append(f"table is missing from manifest: {filename}")
        elif item.get("sha256") != file_sha256(path):
            errors.append(f"SHA-256 mismatch: {filename}")
    table_errors = _validate_tables(snapshot)
    errors.extend(table_errors)
    return {
        "valid": not errors,
        "errors": errors,
        "snapshot": str(snapshot),
        "snapshot_id": snapshot.name,
        "manifest_valid_flag": bool(manifest.get("valid", False)),
        "n_codes": manifest.get("n_codes"),
        "factor_count": manifest.get("factor_count"),
    }


def _validate_tables(snapshot: Path) -> list[str]:
    errors: list[str] = []
    try:
        market = pd.read_parquet(snapshot / "market.parquet")
        missing = set(MARKET_REQUIRED_COLUMNS) - set(market.columns)
        if missing:
            errors.append(f"market.parquet is missing columns: {sorted(missing)}")
        else:
            validate_unique_keys(market, ("date", "code"))
    except Exception as exc:
        errors.append(f"market.parquet validation failed: {exc}")
    try:
        universe = pd.read_csv(snapshot / "universe.csv")
        missing = set(UNIVERSE_REQUIRED_COLUMNS) - set(universe.columns)
        if missing:
            errors.append(f"universe.csv is missing columns: {sorted(missing)}")
        elif universe["code"].duplicated().any():
            errors.append("universe.csv contains duplicate codes")
    except Exception as exc:
        errors.append(f"universe.csv validation failed: {exc}")
    try:
        catalog = pd.read_parquet(snapshot / "factor_catalog.parquet")
        missing = set(FACTOR_REQUIRED_COLUMNS) - set(catalog.columns)
        if missing:
            errors.append(f"factor_catalog.parquet is missing columns: {sorted(missing)}")
    except Exception as exc:
        errors.append(f"factor_catalog.parquet validation failed: {exc}")
    try:
        metrics = pd.read_parquet(snapshot / "factor_metrics.parquet")
        missing = set(FACTOR_METRIC_REQUIRED_COLUMNS) - set(metrics.columns)
        if missing:
            errors.append(f"factor_metrics.parquet is missing columns: {sorted(missing)}")
    except Exception as exc:
        errors.append(f"factor_metrics.parquet validation failed: {exc}")
    try:
        backtests = pd.read_parquet(snapshot / "backtest_metrics.parquet")
        missing = set(BACKTEST_METRIC_REQUIRED_COLUMNS) - set(backtests.columns)
        if missing:
            errors.append(f"backtest_metrics.parquet is missing columns: {sorted(missing)}")
    except Exception as exc:
        errors.append(f"backtest_metrics.parquet validation failed: {exc}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent factor research data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export", help="export one immutable research snapshot")
    export_parser.add_argument("--config", required=True, help="YAML or JSON export config")
    export_parser.add_argument("--snapshot-id")
    export_parser.add_argument("--overwrite", action="store_true")
    validate_parser = subparsers.add_parser("validate", help="validate a research snapshot")
    validate_parser.add_argument("--data-root", default="research_data")
    validate_parser.add_argument("--snapshot-id")
    state_parser = subparsers.add_parser("states", help="derive rule-based market states from a snapshot")
    state_parser.add_argument("--data-root", default="research_data")
    state_parser.add_argument("--runs-root", default="research_runs")
    state_parser.add_argument("--snapshot-id")
    state_parser.add_argument("--volatility-window", type=int, default=20)
    state_parser.add_argument("--trend-threshold", type=float, default=0.002)
    state_parser.add_argument("--volatility-threshold", type=float, default=0.03)
    values_parser = subparsers.add_parser("values", help="compute factor values from snapshot market data")
    values_parser.add_argument("--data-root", default="research_data")
    values_parser.add_argument("--runs-root", default="research_runs")
    values_parser.add_argument("--snapshot-id")
    values_parser.add_argument("--factor-id", action="append", dest="factor_ids")
    values_parser.add_argument("--max-factors", type=int)
    conditional_parser = subparsers.add_parser("conditional", help="evaluate factor values by market state")
    conditional_parser.add_argument("--data-root", default="research_data")
    conditional_parser.add_argument("--values-run", required=True)
    conditional_parser.add_argument("--state-run", required=True)
    conditional_parser.add_argument("--runs-root", default="research_runs")
    conditional_parser.add_argument("--snapshot-id")
    conditional_parser.add_argument("--horizon", type=int, default=20)
    conditional_parser.add_argument("--max-factors", type=int)
    conditional_parser.add_argument("--train-ratio", type=float, default=0.6)
    conditional_parser.add_argument("--valid-ratio", type=float, default=0.2)
    select_parser = subparsers.add_parser("select", help="select factors for one state and time split")
    select_parser.add_argument("--data-root", default="research_data")
    select_parser.add_argument("--conditional-run", required=True)
    select_parser.add_argument("--runs-root", default="research_runs")
    select_parser.add_argument("--snapshot-id")
    select_parser.add_argument("--state-id", required=True)
    select_parser.add_argument("--category")
    select_parser.add_argument("--split", choices=["train", "valid", "test"], default="train")
    select_parser.add_argument("--top-n", type=int, default=10)
    select_parser.add_argument("--min-sample-count", type=int, default=10)
    select_parser.add_argument("--correlation-threshold", type=float, default=0.8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        config = _load_config(args.config)
        sources = ExportSources(
            market_panel=config["market_panel"],
            pool_dir=config["pool_dir"],
            factor_runs_root=config.get("factor_runs_root"),
            backtests_root=config.get("backtests_root"),
            pool_id=config.get("pool_id"),
        )
        result = export_snapshot(sources, config.get("output_root", "research_data"), args.snapshot_id, args.overwrite)
        print(json.dumps({"valid": True, "snapshot_id": result["snapshot_id"], "factor_count": result["factor_count"]}, ensure_ascii=False))
        return 0
    if args.command == "states":
        result = run_state_analysis(
            args.data_root,
            args.runs_root,
            args.snapshot_id,
            args.volatility_window,
            args.trend_threshold,
            args.volatility_threshold,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "values":
        result = materialize_factor_values(
            args.data_root,
            args.runs_root,
            args.snapshot_id,
            factor_ids=args.factor_ids,
            max_factors=args.max_factors,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["failed"] == 0 else 2
    if args.command == "conditional":
        result = run_conditional_evaluation(
            args.data_root,
            args.values_run,
            args.state_run,
            args.runs_root,
            args.snapshot_id,
            args.horizon,
            args.max_factors,
            args.train_ratio,
            args.valid_ratio,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["failed"] == 0 else 2
    if args.command == "select":
        result = run_selection(
            args.data_root,
            args.conditional_run,
            args.runs_root,
            args.snapshot_id,
            args.state_id,
            args.category,
            args.split,
            args.top_n,
            args.min_sample_count,
            args.correlation_threshold,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    result = validate_snapshot(args.data_root, args.snapshot_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
