from __future__ import annotations

import json
import traceback
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import pandas as pd
import yaml

from custom_bt.alpha import alpha_components, canonical_alpha_expression, combine_alphas, normalize_alpha_defs
from custom_bt.data import load_meta, load_pool_panel, load_store, normalize_code, read_panel
from custom_bt.engine import BacktestConfig, run_backtest
from custom_bt.pools import load_pool_codes, load_pool_manifest
from custom_bt.results import save_result


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    last_error: PermissionError | None = None
    for attempt in range(10):
        tmp.write_text(payload, encoding="utf-8")
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(min(0.1 * (attempt + 1), 1.0))
    try:
        path.write_text(payload, encoding="utf-8")
        return
    except PermissionError:
        return
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def load_job_status(job_dir: str | Path) -> Dict[str, Any]:
    path = Path(job_dir) / "status.json"
    if not path.exists():
        return {"status": "missing", "message": "任务状态文件不存在"}
    return json.loads(path.read_text(encoding="utf-8"))


def update_job_status(
    job_dir: str | Path,
    status: str,
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    job_dir = Path(job_dir)
    current = load_job_status(job_dir)
    if status in {"queued", "running"}:
        current.pop("traceback", None)
        current.pop("result", None)
        current.pop("progress", None)
    current.update({"status": status, "message": message, "updated_at": _now()})
    if extra:
        current.update(extra)
    _atomic_write_json(job_dir / "status.json", current)
    return current


def create_backtest_job(
    jobs_root: str | Path,
    data_path: str,
    outputs_path: str,
    run_name: str,
    expr: str,
    backtest: Dict[str, Any],
    pool_id: str | None = None,
    pools_root: str | Path | None = None,
) -> Path:
    jobs_root = Path(jobs_root)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    job_dir = jobs_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "data": data_path,
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
    _atomic_write_json(
        job_dir / "status.json",
        {
            "job_id": job_id,
            "status": "queued",
            "message": "任务已创建，等待后台进程启动",
            "created_at": _now(),
            "updated_at": _now(),
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
    data_path = Path(config["data"])
    bt_raw = config.get("backtest", {}) or {}
    pool_id = str(config.get("pool_id") or "").strip()
    if not pool_id:
        return load_store(data_path, bt_raw.get("start_date"), bt_raw.get("end_date")) if data_path.is_dir() else read_panel(data_path)

    pools_root = config.get("pools_root")
    if not pools_root:
        raise ValueError("pools_root is required when pool_id is set")
    pool_manifest = load_pool_manifest(pools_root, pool_id)
    source_signature = load_meta(data_path).get("source_signature") if data_path.is_dir() else None
    pool_signature = pool_manifest.get("source_signature")
    if source_signature and pool_signature and source_signature != pool_signature:
        raise ValueError("pool source signature does not match data store")
    codes = load_pool_codes(pools_root, pool_id)
    if data_path.is_dir():
        return load_pool_panel(data_path, codes, bt_raw.get("start_date"), bt_raw.get("end_date"))
    return _filter_panel(read_panel(data_path), bt_raw.get("start_date"), bt_raw.get("end_date"), codes)


def run_backtest_job(job_dir: str | Path) -> Path:
    job_dir = Path(job_dir)
    config = yaml.safe_load((job_dir / "config.yaml").read_text(encoding="utf-8")) or {}
    try:
        update_job_status(job_dir, "running", "正在加载数据")
        bt_raw = config.get("backtest", {})
        panel = _load_backtest_panel(config)
        update_job_status(job_dir, "running", f"数据加载完成，共 {len(panel)} 行，正在计算 alpha")
        if "alpha_csv" in config:
            alpha = pd.read_csv(config["alpha_csv"])
            canonical_expression = str(config["alpha_csv"])
        else:
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
