"""旧版组合/手动回测任务：创建 job、加载面板、执行并保存结果。"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import pandas as pd
import yaml

from custom_bt.alpha import alpha_components, canonical_alpha_expression, combine_alphas, normalize_alpha_defs
from custom_bt.engine import BacktestConfig, run_backtest
from repositories.job_store import atomic_write_json, now, update_job_status
from repositories.local_store import normalize_code
from repositories.snapshot_store import load_snapshot
from config.settings import SNAPSHOT_ROOT
from repositories.pool_store import load_pool_codes, load_pool_manifest
from services.report_service import save_result


def create_backtest_job(
    jobs_root: str | Path,
    snapshot_id: str,
    outputs_path: str,
    run_name: str,
    expr: str,
    backtest: Dict[str, Any],
    pool_id: str | None = None,
    pools_root: str | Path | None = None,
    snapshot_root: str | Path | None = None,
) -> Path:
    jobs_root = Path(jobs_root)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    job_dir = jobs_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "snapshot_id": snapshot_id,
        "snapshot_root": str(snapshot_root or SNAPSHOT_ROOT),
        "outputs": outputs_path,
        "run_name": run_name,
        "alphas": [{"name": "web_alpha", "expr": expr, "weight": 1.0}],
        "backtest": backtest,
    }
    selected_pool = str(pool_id or "").strip()
    if selected_pool:
        config["pool_id"] = selected_pool
        if pools_root is not None:
            config["pools_root"] = str(pools_root)
    (job_dir / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    atomic_write_json(
        job_dir / "status.json",
        {
            "job_id": job_id,
            "status": "queued",
            "message": "任务已创建，等待后台进程启动",
            "created_at": now(),
            "updated_at": now(),
            "run_name": run_name,
            "job_dir": str(job_dir.resolve()),
            "output_dir": str((Path(outputs_path) / run_name).resolve()),
        },
    )
    return job_dir


def _filter_panel(panel: pd.DataFrame, start_date: Any = None, end_date: Any = None, codes: list[str] | None = None) -> pd.DataFrame:
    if panel.empty:
        return panel
    filtered = panel.copy()
    filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
    if start_date is not None:
        filtered = filtered[filtered["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        filtered = filtered[filtered["date"] <= pd.Timestamp(end_date)]
    if codes is not None:
        selected = {normalize_code(code) for code in codes}
        filtered = filtered[filtered["code"].map(normalize_code).isin(selected)]
    return filtered.sort_values(["date", "code"]).reset_index(drop=True)


def _load_backtest_panel(config: Dict[str, Any]) -> pd.DataFrame:
    from repositories.snapshot_store import snapshot_manifest
    from repositories.panel_store import load_panel_for_pool, expression_fields, expression_lookback
    from repositories import company_source
    snapshot_id = config.get("snapshot_id")
    if not snapshot_id:
        raise ValueError("旧本地任务不支持，请使用 ClickHouse 快照重新提交")
    manifest = snapshot_manifest(snapshot_id, snapshot_root=config.get("snapshot_root"))
    codes = manifest["codes"]
    pool_id = config.get("pool_id") or manifest["pool_id"]
    if config.get("pool_id"):
        pool = load_pool_manifest(config["pools_root"], pool_id)
        company_source.resolve_data_source(None, pool)
        if pool.get("source_signature") != manifest["source_signature"]:
            raise ValueError("Pool source signature does not match snapshot")
        codes = load_pool_codes(config["pools_root"], pool_id)
    definitions = normalize_alpha_defs(config.get("alphas", []))
    expressions = [item["expr"] for item in definitions]
    return load_panel_for_pool("snapshot", codes, BacktestConfig(**config["backtest"]),
        pool_id=pool_id, snapshot_root=config.get("snapshot_root"), snapshot_id=snapshot_id,
        fields=expression_fields(expressions), lookback_days=expression_lookback(expressions))


def run_backtest_job(job_dir: str | Path) -> Path:
    job_dir = Path(job_dir)
    config = yaml.safe_load((job_dir / "config.yaml").read_text(encoding="utf-8")) or {}
    try:
        update_job_status(job_dir, "running", "正在加载数据")
        bt_raw = config.get("backtest", {})
        panel = _load_backtest_panel(config)
        update_job_status(job_dir, "running", f"数据加载完成，共 {len(panel)} 行，正在计算 alpha")
        alpha_defs = normalize_alpha_defs(config.get("alphas", []))
        alpha = combine_alphas(panel, alpha_defs)
        canonical_expression = canonical_alpha_expression(alpha_defs)
        update_job_status(job_dir, "running", "alpha 计算完成，正在执行回测")
        cfg = BacktestConfig(**bt_raw)
        result = run_backtest(panel, alpha, cfg)
        update_job_status(job_dir, "running", "回测完成，正在保存结果")
        metadata = {
            "result_type": "composite" if len(alpha_defs) > 1 else "manual",
            "canonical_expression": canonical_expression,
            "components": alpha_components(alpha_defs),
            "snapshot_id": config["snapshot_id"],
        }
        if config.get("pool_id"):
            metadata["pool_id"] = config["pool_id"]
        out_dir = save_result(
            result,
            config.get("outputs", "outputs/saved_backtests"),
            config["run_name"],
            config=config,
            metadata=metadata,
        )
        update_job_status(
            job_dir,
            "finished",
            "回测完成",
            {
                "output_dir": str(out_dir.resolve()),
                "summary": result.summary,
            },
        )
        return out_dir
    except Exception as exc:
        update_job_status(
            job_dir,
            "failed",
            str(exc),
            {"traceback": traceback.format_exc()},
        )
        raise
