from __future__ import annotations

import hashlib
import subprocess
import sys
import json
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
FIELD_DOC_PATH = next(iter(WORKSPACE_ROOT.glob("v_stock_daily_full_*.md")), WORKSPACE_ROOT / "v_stock_daily_full_字段说明.md")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit("请先安装 streamlit：pip install streamlit") from exc

from custom_bt.data import list_store_fields, load_meta, load_store_stock_list, stock_list_path
from custom_bt.docs import enrich_fields, enrich_operators
from custom_bt.jobs import create_backtest_job, load_job_status, update_job_status
from custom_bt.platform_jobs import create_platform_job
from custom_bt.results import list_runs
from custom_bt.expressions import list_operators


SUMMARY_LABELS = {
    "total_return": "总收益",
    "annual_return": "年化收益",
    "sharpe": "夏普比率",
    "max_drawdown": "最大回撤",
    "calmar": "Calmar",
    "win_rate": "胜率",
    "average_turnover": "平均换手",
    "total_cost": "总成本",
    "annual_cost": "年化成本",
    "number_of_trades": "交易次数",
    "average_holding_count": "平均持仓数",
}


SUMMARY_RATE_KEYS = {
    "total_return",
    "annual_return",
    "max_drawdown",
    "win_rate",
    "average_turnover",
    "total_cost",
    "annual_cost",
}

SAVED_RATE_COLUMNS = ["换手率", "最大回撤", "年化收益", "总收益"]
ANNUAL_RATE_COLUMNS = ["收益", "最大回撤", "换手", "成本", "胜率"]


ANNUAL_LABELS = {
    "year": "年份",
    "return": "收益",
    "sharpe": "夏普",
    "max_drawdown": "最大回撤",
    "turnover": "换手",
    "cost": "成本",
    "win_rate": "胜率",
}


STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "finished": "已完成",
    "failed": "失败",
    "missing": "状态缺失",
}


def _parse_multiline_values(value: str) -> list[str]:
    values = []
    seen = set()
    for raw in str(value).replace(",", "\n").splitlines():
        item = raw.strip()
        if item and item not in seen:
            values.append(item)
            seen.add(item)
    return values


def _parse_optional_float(value: str) -> float | None:
    text = str(value).strip()
    return None if not text else float(text)


def _parse_int_values(value: str) -> list[int]:
    values = []
    seen = set()
    for item in _parse_multiline_values(value):
        number = int(item)
        if number not in seen:
            values.append(number)
            seen.add(number)
    return values


def _resolve_app_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def _master_store_ready(store_dir: str | Path) -> bool:
    path = Path(store_dir)
    return (path / "meta.json").is_file() and (path / "stocks").is_dir()


def _latest_active_job_dir(jobs_root: str | Path) -> Path | None:
    root = Path(jobs_root)
    if not root.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for status_path in root.glob("*/status.json"):
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status.get("status") not in {"queued", "running"}:
            continue
        candidates.append((status_path.parent.stat().st_mtime, status_path.parent))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _visible_job_dir(jobs_root: str | Path) -> Path | None:
    current = st.session_state.get("current_job_dir")
    if current:
        path = Path(str(current))
        if (path / "status.json").exists():
            return path
    return _latest_active_job_dir(jobs_root)


def _factor_generation_run_dir(job_dir: str | Path) -> Path | None:
    path = Path(job_dir)
    config_path = path / "platform_job.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if config.get("operation") != "generate_factors":
        return None
    payload = config.get("payload") or {}
    pool_id = str(payload.get("pool_id") or "").strip()
    factor_runs_root = payload.get("factor_runs_root")
    if not pool_id or not factor_runs_root:
        return None
    runtime_key = {
        "pool_id": pool_id,
        "fields": list(payload.get("fields") or []),
        "splits": {
            name: {
                "cache_start": str(value.get("cache_start", "")),
                "cache_end": str(value.get("cache_end", "")),
            }
            for name, value in sorted((payload.get("splits") or {}).items())
        },
        "max_backtrack_days": int(payload.get("max_backtrack_days", 100)),
        "target_horizon": int(payload.get("target_horizon", 20)),
        "max_future_days": int(payload.get("max_future_days", 20)),
    }
    runtime_id = hashlib.sha256(json.dumps(runtime_key, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    generation_config = payload.get("generation_config") or {}
    run_id = str(generation_config.get("run_id") or f"{pool_id}_{runtime_id}")
    return Path(factor_runs_root).expanduser().resolve() / run_id


def _load_factor_generation_progress(job_dir: str | Path) -> dict[str, object]:
    run_dir = _factor_generation_run_dir(job_dir)
    if run_dir is None:
        return {}
    state_path = run_dir / "run_state.json"
    if not state_path.exists():
        return {"factor_run_dir": str(run_dir)}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"factor_run_dir": str(run_dir)}
    state["factor_run_dir"] = str(run_dir)
    return state


def _load_yaml_defaults(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _default_source_path() -> Path:
    return PROJECT_ROOT.parent.parent / "数据" / "daily_with_maindata_v2.csv"


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def _load_pool_manifests(pools_root: str | Path) -> pd.DataFrame:
    rows = []
    root = Path(pools_root)
    if not root.exists():
        return pd.DataFrame(columns=["pool_id", "name", "n_stocks", "selection_start", "selection_end"])
    for path in sorted(root.glob("*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(data)
    if not rows:
        return pd.DataFrame(columns=["pool_id", "name", "n_stocks", "selection_start", "selection_end"])
    return pd.DataFrame(rows).sort_values(["name", "pool_id"], na_position="last").reset_index(drop=True)


def _load_factor_run_manifests(factor_runs_root: str | Path) -> pd.DataFrame:
    rows = []
    root = Path(factor_runs_root)
    if not root.exists():
        return pd.DataFrame(columns=["run_id", "pool_id", "accepted_count", "created_at"])
    for path in sorted(root.glob("*/factor_run.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data.setdefault("run_id", path.parent.name)
        rows.append(data)
    if not rows:
        return pd.DataFrame(columns=["run_id", "pool_id", "accepted_count", "created_at"])
    return pd.DataFrame(rows).sort_values("run_id", ascending=False).reset_index(drop=True)


def _load_accepted_factor_table(factor_run_dir: str | Path) -> pd.DataFrame:
    path = Path(factor_run_dir) / "accepted_factors.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return pd.DataFrame(rows)


def _load_factor_backtest_summary(path: str | Path) -> pd.DataFrame:
    summary_path = Path(path) / "factor_backtest_summary.csv"
    if not summary_path.exists():
        return pd.DataFrame()
    return pd.read_csv(summary_path)


def _list_factor_backtest_result_dirs(results_root: str | Path) -> list[Path]:
    root = Path(results_root)
    factor_root = root / "factor" if (root / "factor").exists() else root
    if not factor_root.exists():
        return []
    paths = [path.parent for path in factor_root.rglob("factor_backtest_summary.csv") if path.is_file()]
    return sorted(set(paths), key=lambda path: path.stat().st_mtime, reverse=True)


def _format_summary_value(key: str, value: object) -> object:
    if _is_missing(value):
        return "-"
    if key in SUMMARY_RATE_KEYS:
        return f"{float(value) * 100:.2f}%"
    if isinstance(value, (int, float)):
        return f"{float(value):.4f}"
    return value


def _summary_frame(summary: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [{"指标": SUMMARY_LABELS.get(key, key), "值": _format_summary_value(key, value)} for key, value in summary.items()]
    )


def _summary_cards(summary: dict) -> list[dict[str, object]]:
    return [
        {"label": SUMMARY_LABELS.get(key, key), "value": _format_summary_value(key, value)}
        for key, value in summary.items()
    ]


def _render_summary_cards(summary: dict) -> None:
    cards = _summary_cards(summary)
    if not cards:
        return
    cols_per_row = 4
    for start in range(0, len(cards), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, card in zip(cols, cards[start:start + cols_per_row]):
            col.metric(card["label"], card["value"])


def _annual_frame(annual: pd.DataFrame) -> pd.DataFrame:
    if annual.empty:
        return annual
    frame = annual.rename(columns=ANNUAL_LABELS).copy()
    for col in ANNUAL_RATE_COLUMNS:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce") * 100.0
    return frame


def _alpha_expr_from_run(run: dict) -> str:
    canonical_expression = str(run.get("canonical_expression", "")).strip()
    if canonical_expression:
        return canonical_expression
    alphas = run.get("config", {}).get("alphas", [])
    exprs = [str(item.get("expr", "")).strip() for item in alphas if item.get("expr")]
    return " + ".join(exprs) if exprs else "-"


def _note_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "note.md"


def _load_note(run_dir: str | Path) -> str:
    path = _note_path(run_dir)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _save_note(run_dir: str | Path, note: str) -> None:
    _note_path(run_dir).write_text(note, encoding="utf-8")


def _note_preview(note: str, limit: int = 80) -> str:
    text = " ".join(note.split())
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit - 1] + "..."


def _display_text(value: object) -> str:
    if _is_missing(value):
        return ""
    return str(value)


def _saved_runs_table(runs: list[dict]) -> pd.DataFrame:
    rows = []
    for run in runs:
        summary = run.get("summary", {}) or {}
        backtest = run.get("config", {}).get("backtest", {}) or {}
        generation = run.get("generation_metrics", {}) or {}
        preprocess = run.get("factor_preprocess", {}) or {}
        preprocess_method = preprocess.get("method", "") if isinstance(preprocess, dict) else str(preprocess)
        composition_metrics = run.get("composition_metrics", {}) or {}
        if not generation:
            generation_prefix = "generation_"
            generation = {
                key[len(generation_prefix):]: value
                for key, value in run.items()
                if key.startswith(generation_prefix)
            }
        rows.append(
            {
                "canonical_expression": _alpha_expr_from_run(run),
                "result_type": _display_text(run.get("result_type")),
                "pool_id": _display_text(run.get("pool_id")),
                "factor_run_id": _display_text(run.get("factor_run_id")),
                "composition_id": _display_text(run.get("composition_id")),
                "组合规模": _display_text(run.get("max_factors")),
                "选择指标": _display_text(run.get("selection_metric")),
                "mutual IC 阈值": _display_text(run.get("mutual_ic_threshold")),
                "权重方法": _display_text(run.get("weight_method")),
                "因子预处理": _display_text(preprocess_method),
                "组合 IC": composition_metrics.get("ic"),
                "组合 Rank IC": composition_metrics.get("rank_ic"),
                "组合 ICIR": composition_metrics.get("icir"),
                "组合 Rank ICIR": composition_metrics.get("rank_icir"),
                "PPO IC": generation.get("ic"),
                "PPO Rank IC": generation.get("rank_ic"),
                "PPO ICIR": generation.get("icir"),
                "PPO Coverage": generation.get("coverage"),
                "PPO Score": generation.get("score"),
                "运行名称": _display_text(run.get("run_name")),
                "表达式": _alpha_expr_from_run(run),
                "夏普比": summary.get("sharpe"),
                "换手率": None if _is_missing(summary.get("average_turnover")) else float(summary.get("average_turnover")) * 100.0,
                "最大回撤": None if _is_missing(summary.get("max_drawdown")) else float(summary.get("max_drawdown")) * 100.0,
                "年化收益": None if _is_missing(summary.get("annual_return")) else float(summary.get("annual_return")) * 100.0,
                "总收益": None if _is_missing(summary.get("total_return")) else float(summary.get("total_return")) * 100.0,
                "开始日期": _display_text(backtest.get("start_date")),
                "结束日期": _display_text(backtest.get("end_date")),
                "TopK": _display_text(backtest.get("top_k")),
                "备注": _note_preview(_load_note(run.get("path", ""))),
                "创建时间": _display_text(run.get("created_at")),
                "_path": _display_text(run.get("path")),
            }
        )
    return pd.DataFrame(rows)


def _download_button(path: Path, label: str, scope: str) -> None:
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, key=f"download:{scope}:{path.name}")


def _request_rerun() -> None:
    rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun is None:
        st.warning("当前 Streamlit 版本不支持自动刷新，请手动刷新页面查看任务状态。")
        return
    rerun()


def _format_fields(fields: list[dict[str, str]]) -> pd.DataFrame:
    frame = pd.DataFrame(enrich_fields(fields, FIELD_DOC_PATH))
    if frame.empty:
        return frame
    return frame.rename(
        columns={"name": "字段名", "dtype": "类型", "source": "来源", "description": "解释"}
    )


def _format_operators() -> pd.DataFrame:
    frame = pd.DataFrame(enrich_operators(list_operators()))
    if frame.empty:
        return frame
    return frame.rename(
        columns={
            "name": "操作符",
            "category": "分类",
            "category_cn": "分类名称",
            "description_cn": "解释",
            "example": "示例",
        }
    )


@st.cache_data(show_spinner=False)
def _load_stock_table_cached(store_dir: str, marker: float) -> pd.DataFrame:
    _ = marker
    stocks = load_store_stock_list(store_dir)
    if not stocks:
        return pd.DataFrame()
    return pd.DataFrame(stocks).rename(
        columns={
            "code": "股票代码",
            "rows": "数据行数",
            "start_date": "开始日期",
            "end_date": "结束日期",
            "latest_date": "最近日期",
            "latest_open": "最近开盘价",
            "latest_close": "最近收盘价",
            "latest_volume": "最近成交量",
            "latest_amount": "最近成交额",
        }
    )


def _start_background_job(job_dir: Path) -> None:
    log_path = job_dir / "job.log"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "custom_bt.cli", "run-job", "--job-dir", str(job_dir)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )
    update_job_status(job_dir, "queued", "后台进程已启动，等待进入计算阶段", {"pid": process.pid, "log_path": str(log_path.resolve())})


def _start_platform_background_job(job_dir: Path) -> None:
    log_path = job_dir / "job.log"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "custom_bt.cli", "run-platform-job", "--job-dir", str(job_dir)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )
    update_job_status(
        job_dir,
        "queued",
        "平台任务已提交到后台，等待执行",
        {"pid": process.pid, "log_path": str(log_path.resolve())},
    )


def _submit_platform_job(operation: str, payload: dict, key: str) -> None:
    try:
        job_dir = create_platform_job(jobs_path, operation, payload)
        _start_platform_background_job(job_dir)
        st.session_state["current_job_dir"] = str(job_dir)
        st.success(f"平台任务已提交：{job_dir}")
        _request_rerun()
    except Exception as exc:
        st.error(f"平台任务提交失败：{exc}")


def _render_result_dir(run_dir: Path, scope: str) -> None:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    daily_path = run_dir / "daily_report.csv"
    annual_path = run_dir / "annual_metrics.csv"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        generation = manifest.get("generation_metrics", {}) or {}
        optimization = manifest.get("optimization", {}) or {}
        preprocess = manifest.get("factor_preprocess", {}) or {}
        preprocess_method = preprocess.get("method", "-") if isinstance(preprocess, dict) else (preprocess or "-")
        weight_method = manifest.get("weight_method") or optimization.get("method") or "-"
        composition_metrics = manifest.get("composition_metrics", {}) or {}
        st.subheader("结果元数据")
        st.dataframe(
            pd.DataFrame(
                [
                    {"字段": "结果类型", "值": manifest.get("result_type", "-")},
                    {"字段": "规范表达式", "值": manifest.get("canonical_expression", "-")},
                    {"字段": "股票池", "值": manifest.get("pool_id", "-")},
                    {"字段": "因子运行", "值": manifest.get("factor_run_id", "-")},
                    {"字段": "组合 ID", "值": manifest.get("composition_id", "-")},
                    {"字段": "来源因子运行", "值": ",".join(str(item) for item in manifest.get("source_factor_run_ids", []) or [])},
                    {"字段": "组合规模", "值": manifest.get("max_factors", "-")},
                    {"字段": "选择指标", "值": manifest.get("selection_metric", "-")},
                    {"字段": "mutual IC 阈值", "值": manifest.get("mutual_ic_threshold", "-")},
                    {"字段": "权重方法", "值": weight_method},
                    {"字段": "因子预处理", "值": preprocess_method},
                    {"字段": "Target Horizon", "值": manifest.get("target_horizon", "-")},
                    {"字段": "组合 IC", "值": composition_metrics.get("ic")},
                    {"字段": "组合 Rank IC", "值": composition_metrics.get("rank_ic")},
                    {"字段": "组合 ICIR", "值": composition_metrics.get("icir")},
                    {"字段": "组合 Rank ICIR", "值": composition_metrics.get("rank_icir")},
                    {"字段": "PPO IC", "值": generation.get("ic")},
                    {"字段": "PPO Rank IC", "值": generation.get("rank_ic")},
                    {"字段": "PPO ICIR", "值": generation.get("icir")},
                    {"字段": "PPO Coverage", "值": generation.get("coverage")},
                    {"字段": "PPO Score", "值": generation.get("score")},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        weights_path = run_dir / "factor_weights.json"
        if weights_path.exists():
            try:
                weights = json.loads(weights_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                weights = []
            if weights:
                st.subheader("组合因子权重")
                st.dataframe(pd.DataFrame(weights), use_container_width=True, hide_index=True, key=f"weights:{scope}")
    if summary_path.exists():
        st.subheader("汇总指标")
        _render_summary_cards(json.loads(summary_path.read_text(encoding="utf-8")))
    st.subheader("备注")
    note = st.text_area("备注内容", _load_note(run_dir), height=120, key=f"run-note:{scope}")
    if st.button("保存备注", key=f"save-note:{scope}"):
        _save_note(run_dir, note)
        st.success("备注已保存")
    if daily_path.exists():
        daily = pd.read_csv(daily_path)
        daily["date"] = pd.to_datetime(daily["date"])
        daily["净值"] = daily["account"] / daily["account"].iloc[0]
        daily["PNL"] = daily["净值"] - 1.0
        daily["回撤"] = daily["drawdown"]
        st.subheader("PNL / 回撤曲线")
        st.line_chart(daily.set_index("date")[["PNL", "回撤"]])
    if annual_path.exists():
        st.subheader("年度指标")
        st.dataframe(
            _annual_frame(pd.read_csv(annual_path)),
            use_container_width=True,
            column_config={
                "收益": st.column_config.NumberColumn(format="%.2f%%"),
                "最大回撤": st.column_config.NumberColumn(format="%.2f%%"),
                "换手": st.column_config.NumberColumn(format="%.2f%%"),
                "成本": st.column_config.NumberColumn(format="%.2f%%"),
                "胜率": st.column_config.NumberColumn(format="%.2f%%"),
                "夏普": st.column_config.NumberColumn(format="%.4f"),
            },
        )
    files = [
        ("daily_report.csv", "下载每日报告"),
        ("annual_metrics.csv", "下载年度指标"),
        ("trades.csv", "下载交易明细"),
        ("positions.csv", "下载持仓明细"),
        ("summary.png", "下载汇总图片"),
    ]
    for name, label in files:
        _download_button(run_dir / name, label, scope)


def _render_job_status(job_dir: Path, scope: str) -> None:
    status = load_job_status(job_dir)
    status_name = status.get("status", "missing")
    st.subheader("后台任务状态")
    c1, c2, c3 = st.columns(3)
    c1.metric("状态", STATUS_LABELS.get(status_name, status_name))
    c2.metric("运行名称", status.get("run_name", "-"))
    c3.metric("进程 PID", status.get("pid", "-"))
    st.write(status.get("message", ""))
    progress = status.get("progress") or {}
    if progress:
        if any(key in progress for key in ["rows_read", "rows_written", "stocks_touched"]):
            p1, p2, p3 = st.columns(3)
            p1.metric("已读取行数", f"{int(progress.get('rows_read', 0)):,}")
            p2.metric("已保留行数", f"{int(progress.get('rows_written', 0)):,}")
            p3.metric("已处理股票数", f"{int(progress.get('stocks_touched', 0)):,}")
        if any(key in progress for key in ["candidate_count", "accepted_count", "rejected_count", "current_size", "completed_sizes"]):
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("候选因子", f"{int(progress.get('candidate_count', 0)):,}")
            p2.metric("入池因子", f"{int(progress.get('accepted_count', 0)):,}")
            p3.metric("拒绝因子", f"{int(progress.get('rejected_count', 0)):,}")
            p4.metric("当前规模", progress.get("current_size", "-"))
            completed_sizes = progress.get("completed_sizes") or []
            if completed_sizes:
                st.caption("已完成组合规模：" + ",".join(str(item) for item in completed_sizes))
    factor_progress = _load_factor_generation_progress(job_dir)
    if factor_progress:
        g1, g2, g3 = st.columns(3)
        g1.metric("合格因子", f"{int(factor_progress.get('accepted_count', 0)):,}")
        g2.metric("目标数", f"{int(factor_progress.get('target_count', 0)):,}")
        g3.metric("尝试次数", f"{int(factor_progress.get('attempts', 0)):,}")
        if factor_progress.get("latest_checkpoint"):
            st.caption("最新检查点: " + str(factor_progress.get("latest_checkpoint")))
    with st.expander("状态详情", expanded=False):
        st.json(status)
        log_path = status.get("log_path")
        if log_path and Path(log_path).exists():
            st.text_area(
                "后台日志",
                Path(log_path).read_text(encoding="utf-8", errors="replace")[-6000:],
                height=220,
                key=f"job-log:{scope}:{job_dir.name}",
            )
    if status_name == "finished":
        output_dir = Path(status.get("output_dir", ""))
        if output_dir.exists():
            _render_result_dir(output_dir, f"{scope}:{job_dir.name}")
        if status.get("result"):
            with st.expander("平台任务结果", expanded=True):
                st.json(status["result"])
    elif status_name == "failed":
        st.error(status.get("message", "任务失败"))
        if status.get("traceback"):
            with st.expander("错误堆栈"):
                st.code(status["traceback"])
    elif status_name in {"queued", "running"}:
        st.info("当前不会自动刷新；点击下面按钮查看最新状态。")
        if st.button("手动刷新任务状态", key=f"refresh-job:{scope}:{job_dir.name}"):
            _request_rerun()


st.set_page_config(page_title="独立因子回测系统", layout="wide")
st.title("独立因子回测系统")

platform_cfg = _load_yaml_defaults(PROJECT_ROOT / "configs" / "platform.yaml")
generation_cfg = _load_yaml_defaults(PROJECT_ROOT / "configs" / "factor_generation.yaml")
default_factor_fields = generation_cfg.get("fields", platform_cfg.get("factor_fields", []))

data_path = _resolve_app_path(st.sidebar.text_input("数据缓存目录", "data_cache/stock_daily"))
master_path = _resolve_app_path(st.sidebar.text_input("主数据缓存", "data_cache/master"))
pools_path = _resolve_app_path(st.sidebar.text_input("股票池目录", "data_cache/pools"))
factor_runs_path = _resolve_app_path(st.sidebar.text_input("因子运行目录", "factor_runs"))
factor_outputs_path = _resolve_app_path(st.sidebar.text_input("因子回测输出", "outputs/saved_backtests"))
outputs_path = _resolve_app_path(st.sidebar.text_input("结果输出目录", "outputs/saved_backtests"))
jobs_path = _resolve_app_path(st.sidebar.text_input("任务目录", "outputs/jobs"))
start_date = st.sidebar.text_input("开始日期", "2021-06-18")
end_date = st.sidebar.text_input("结束日期", "2026-06-16")
top_k = st.sidebar.number_input("持仓数量 TopK", min_value=1, value=50)
initial_cash = st.sidebar.number_input("初始资金", min_value=10000.0, value=100000000.0, step=1000000.0)
buy_cost = st.sidebar.number_input("买入成本率", value=0.0015, format="%.5f")
sell_cost = st.sidebar.number_input("卖出成本率", value=0.0015, format="%.5f")
slippage = st.sidebar.number_input("滑点", value=0.0005, format="%.5f")
min_cost = st.sidebar.number_input("最低手续费", value=5.0, format="%.2f")
max_weight = st.sidebar.number_input("单票最大权重", min_value=0.001, value=0.02, format="%.4f")
run_name = st.sidebar.text_input("本次运行名称", "web_run")

meta = load_meta(data_path) if data_path.exists() else {}
master_meta = load_meta(master_path) if master_path.exists() else {}
master_ready = _master_store_ready(master_path)
fields = list_store_fields(data_path) if data_path.exists() else []
field_table = _format_fields(fields)
operator_table = _format_operators()

visible_job_dir = _visible_job_dir(jobs_path)
with st.sidebar.expander("当前任务", expanded=visible_job_dir is not None):
    if visible_job_dir is None:
        st.caption("现在没有正在运行的任务。")
    else:
        current_status = load_job_status(visible_job_dir)
        st.write(f"**状态**：{STATUS_LABELS.get(current_status.get('status', 'missing'), current_status.get('status', 'missing'))}")
        st.write(f"**任务**：{current_status.get('job_id', visible_job_dir.name)}")
        st.write(f"**操作**：{current_status.get('operation', '-')}")
        st.write(current_status.get("message", ""))
        progress = current_status.get("progress") or {}
        if progress:
            if any(key in progress for key in ["rows_read", "rows_written", "stocks_touched"]):
                st.caption(
                    "进度："
                    f"已读 {int(progress.get('rows_read', 0)):,} 行 / "
                    f"保留 {int(progress.get('rows_written', 0)):,} 行 / "
                    f"处理 {int(progress.get('stocks_touched', 0)):,} 只股票"
                )
            if any(key in progress for key in ["candidate_count", "accepted_count", "current_size", "completed_sizes"]):
                completed = progress.get("completed_sizes") or []
                st.caption(
                    "组合进度："
                    f"候选 {int(progress.get('candidate_count', 0)):,} / "
                    f"入池 {int(progress.get('accepted_count', 0)):,} / "
                    f"当前规模 {progress.get('current_size', '-')}"
                )
                if completed:
                    st.caption("已完成规模：" + ",".join(str(item) for item in completed))
        if current_status.get("updated_at"):
            st.caption(f"更新时间：{current_status['updated_at']}")
        factor_progress = _load_factor_generation_progress(visible_job_dir)
        if factor_progress:
            st.caption(
                "因子进度："
                f"{int(factor_progress.get('accepted_count', 0)):,}/"
                f"{int(factor_progress.get('target_count', 0)):,} 合格，"
                f"{int(factor_progress.get('attempts', 0)):,} 次尝试"
            )
        st.caption("完整日志和历史任务请去「后台任务」页签。")
        if st.button("刷新当前任务", key=f"sidebar-refresh-job:{visible_job_dir.name}"):
            st.session_state["current_job_dir"] = str(visible_job_dir)
            _request_rerun()

tab_platform, tab_run, tab_fields, tab_stocks, tab_pools, tab_factors, tab_factor_results, tab_composition, tab_ops, tab_jobs, tab_runs = st.tabs(
    ["平台任务", "回测", "数据字段", "股票列表", "股票池", "因子生成", "因子回测", "因子组合", "操作符", "后台任务", "已保存结果"]
)

with tab_run:
    backtest_data_path = master_path if master_ready else data_path
    backtest_meta = master_meta if master_ready else meta
    manual_pool_table = _load_pool_manifests(pools_path)
    manual_pool_options = ["全量数据（不限制股票池）"]
    if not manual_pool_table.empty:
        manual_pool_options.extend(manual_pool_table["pool_id"].astype(str).tolist())
    if not backtest_data_path.exists():
        st.warning("数据缓存目录不存在，请先运行 prepare/update 导入数据。")
    else:
        cols = st.columns(4)
        cols[0].metric("股票数", backtest_meta.get("n_stocks", "-"))
        cols[1].metric("数据行数", backtest_meta.get("rows", "-"))
        cols[2].metric("起始日期", backtest_meta.get("date_min", "-"))
        cols[3].metric("结束日期", backtest_meta.get("date_max", "-"))

        selected_pool_label = st.selectbox("手动回测股票池", manual_pool_options, key="platform-manual-backtest-pool")
        selected_pool_id = None if selected_pool_label == manual_pool_options[0] else selected_pool_label
        expr = st.text_area("Alpha 表达式", "close / delay(close, 20) - 1", height=120, key="alpha-expression")
        if st.button("提交后台回测任务", type="primary"):
            backtest = {
                "start_date": start_date,
                "end_date": end_date,
                "top_k": int(top_k),
                "initial_cash": float(initial_cash),
                "buy_cost": float(buy_cost),
                "sell_cost": float(sell_cost),
                "slippage": float(slippage),
                "min_cost": float(min_cost),
                "max_weight_per_stock": float(max_weight),
            }
            try:
                job_dir = create_backtest_job(
                    jobs_root=jobs_path,
                    data_path=str(backtest_data_path),
                    outputs_path=str(outputs_path),
                    run_name=run_name,
                    expr=expr,
                    backtest=backtest,
                    pool_id=selected_pool_id,
                    pools_root=str(pools_path),
                )
                _start_background_job(job_dir)
                st.session_state["current_job_dir"] = str(job_dir)
                st.success(f"任务已提交：{job_dir}")
                _request_rerun()
            except Exception as exc:
                st.error(f"提交任务失败：{exc}")

        current_job = st.session_state.get("current_job_dir")
        if current_job:
                _render_job_status(Path(current_job), "current")

with tab_platform:
    st.subheader("主数据与平台任务")
    st.caption("大数据导入、PPO 生成和批量回测都会在后台执行，页面不会被长时间计算阻塞。")
    if not master_ready:
        st.warning("主缓存尚未完成：请先在本页提交并等待“构建 / 更新主数据缓存”任务完成，再创建股票池。")
    source_default = str(_default_source_path())
    source_csv = st.text_input("主数据 CSV/TSV 路径", source_default, key="platform-source-csv")
    import_fields = st.text_area(
        "主缓存字段（每行一个，也支持逗号）",
        "\n".join(str(item) for item in platform_cfg.get("factor_fields", [])),
        height=150,
        key="platform-import-fields",
    )
    import_limit = st.text_input("限制导入行数（留空表示全量）", "", key="platform-import-limit")
    import_chunksize = st.number_input("导入分块大小", min_value=1000, value=200000, step=1000, key="platform-chunksize")
    import_overwrite = st.checkbox("覆盖已有 master cache", value=False, key="platform-import-overwrite")
    if st.button("构建 / 更新主数据缓存", type="primary", key="platform-prepare-master"):
        try:
            limit_rows = int(import_limit.strip()) if import_limit.strip() else None
            fields_for_import = _parse_multiline_values(import_fields)
            if not fields_for_import:
                raise ValueError("至少选择一个主缓存字段")
            _submit_platform_job(
                "prepare_master",
                {
                    "csv_path": str(_resolve_app_path(source_csv)),
                    "store_dir": str(master_path),
                    "fields": fields_for_import,
                    "chunksize": int(import_chunksize),
                    "limit_rows": limit_rows,
                    "overwrite": bool(import_overwrite),
                    "delimiter": platform_cfg.get("delimiter"),
                },
                "platform-prepare-master",
            )
        except Exception as exc:
            st.error(f"主缓存任务参数错误：{exc}")
    if master_meta:
        st.json(
            {
                "store": str(master_path),
                "rows": master_meta.get("rows"),
                "n_stocks": master_meta.get("n_stocks"),
                "date_min": master_meta.get("date_min"),
                "date_max": master_meta.get("date_max"),
                "source_signature": master_meta.get("source_signature"),
            }
        )

with tab_fields:
    st.subheader("当前可用数据字段")
    if not FIELD_DOC_PATH.exists():
        st.warning(f"未找到字段说明文件：{FIELD_DOC_PATH}")
    if not field_table.empty:
        search = st.text_input("搜索字段", "")
        show = field_table
        if search:
            mask = show.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            show = show[mask]
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("没有读取到字段。请先导入数据。")

with tab_stocks:
    st.subheader("当前股票信息列表")
    stock_root = data_path / "stocks"
    if not stock_root.exists():
        st.info("没有读取到股票文件。请先导入数据。")
    else:
        cache_path = stock_list_path(data_path)
        if not cache_path.exists():
            st.info('还没有股票列表缓存。请先运行：python -m custom_bt.cli stock-list --data "data_cache\\stock_daily"')
        if st.button("刷新股票列表显示", key="load-stock-list"):
            clear_cache = getattr(_load_stock_table_cached, "clear", None)
            if clear_cache:
                clear_cache()
        if cache_path.exists():
            marker = cache_path.stat().st_mtime
            stock_table = _load_stock_table_cached(str(data_path), marker)
            if stock_table.empty:
                st.info("没有读取到股票信息。")
            else:
                code_search = st.text_input("搜索股票代码", "", key="stock-code-search")
                show = stock_table
                if code_search:
                    show = show[show["股票代码"].astype(str).str.contains(code_search, case=False, na=False)]
                cols = st.columns(3)
                cols[0].metric("股票数量", len(stock_table))
                cols[1].metric("总数据行数", int(stock_table["数据行数"].sum()))
                cols[2].metric("当前筛选数量", len(show))
                st.dataframe(
                    show,
                    use_container_width=True,
                    hide_index=True,
                    key="stock-info-table",
                    column_config={
                        "最近开盘价": st.column_config.NumberColumn(format="%.4f"),
                        "最近收盘价": st.column_config.NumberColumn(format="%.4f"),
                        "最近成交量": st.column_config.NumberColumn(format="%.0f"),
                        "最近成交额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )

with tab_pools:
    pool_cfg = _load_yaml_defaults(PROJECT_ROOT / "configs" / "pools" / "liquid_500.yaml")
    st.subheader("创建股票池")
    pool_name = st.text_input("股票池名称", str(pool_cfg.get("name", "liquid_500")), key="platform-pool-name")
    pool_start = st.text_input("筛选开始日期", str(pool_cfg.get("selection_start", start_date)), key="platform-pool-start")
    pool_end = st.text_input("筛选结束日期", str(pool_cfg.get("selection_end", end_date)), key="platform-pool-end")
    pool_top_n = st.number_input("股票池数量（0 表示不限制）", min_value=0, value=int(pool_cfg.get("top_n") or 500), key="platform-pool-top-n")
    pool_min_days = st.number_input("最少上市天数", min_value=0, value=int(pool_cfg.get("min_listed_days", 250)), key="platform-pool-listed-days")
    pool_min_coverage = st.number_input("最小覆盖率", min_value=0.0, max_value=1.0, value=float(pool_cfg.get("min_coverage", 0.9)), format="%.3f", key="platform-pool-coverage")
    pool_category = st.text_input("股票类别（可选）", str(pool_cfg.get("category") or ""), key="platform-pool-category")
    pool_market_code = st.text_input("市场代码（可选）", str(pool_cfg.get("market_code") or ""), key="platform-pool-market")
    pool_exclude_suspended = st.checkbox("排除停牌数据", value=bool(pool_cfg.get("exclude_suspended", True)), key="platform-pool-suspended")
    if not master_ready:
        st.info("当前 master cache 不可用，创建股票池按钮将在导入完成后启用。")
    if st.button("创建股票池", type="primary", key="platform-create-pool", disabled=not master_ready):
        _submit_platform_job(
            "create_pool",
            {
                "store_dir": str(master_path),
                "pools_root": str(pools_path),
                "name": pool_name.strip(),
                "selection_start": pool_start.strip(),
                "selection_end": pool_end.strip(),
                "top_n": None if int(pool_top_n) == 0 else int(pool_top_n),
                "min_listed_days": int(pool_min_days),
                "min_coverage": float(pool_min_coverage),
                "exclude_suspended": bool(pool_exclude_suspended),
                "category": pool_category.strip() or None,
                "market_code": pool_market_code.strip() or None,
                "overwrite": False,
            },
            "platform-create-pool",
        )
    st.subheader("股票池列表")
    pool_table = _load_pool_manifests(pools_path)
    if pool_table.empty:
        st.info("尚未创建股票池，请先执行 create-pool。")
    else:
        st.dataframe(pool_table, use_container_width=True, hide_index=True, key="pool-manifest-table")
        selected_pool = st.selectbox("当前股票池", pool_table["pool_id"].tolist(), key="platform-pool-select")
        if selected_pool:
            codes_path = pools_path / selected_pool / "codes.txt"
            if codes_path.exists():
                count = len([line for line in codes_path.read_text(encoding="utf-8").splitlines() if line.strip()])
                st.caption(f"代码数量: {count}")

with tab_factors:
    st.subheader("提交 PPO 因子生成任务")
    if not master_ready:
        st.info("请先完成 master cache 导入。")
    generation_pool_table = _load_pool_manifests(pools_path)
    if generation_pool_table.empty:
        st.info("请先在股票池页创建股票池。")
    else:
        generation_pool = st.selectbox(
            "生成使用的股票池",
            generation_pool_table["pool_id"].tolist(),
            key="platform-generation-pool",
        )
        generation_fields_text = st.text_area(
            "PPO 因子字段",
            "\n".join(str(item) for item in default_factor_fields),
            height=150,
            key="platform-generation-fields",
        )
        configured_splits = generation_cfg.get("splits", {})
        train_cfg = configured_splits.get("train", {})
        valid_cfg = configured_splits.get("valid", {})
        test_cfg = configured_splits.get("test", {})
        train_start = st.text_input("训练开始", str(train_cfg.get("cache_start", "2022-01-14")), key="platform-train-start")
        train_end = st.text_input("训练结束", str(train_cfg.get("cache_end", "2024-07-26")), key="platform-train-end")
        valid_start = st.text_input("验证开始", str(valid_cfg.get("cache_start", "2024-01-25")), key="platform-valid-start")
        valid_end = st.text_input("验证结束", str(valid_cfg.get("cache_end", "2025-07-28")), key="platform-valid-end")
        test_start = st.text_input("测试开始", str(test_cfg.get("cache_start", "2025-01-27")), key="platform-test-start")
        test_end = st.text_input("测试结束", str(test_cfg.get("cache_end", "2026-06-12")), key="platform-test-end")
        generation_target_count = st.number_input("目标合格因子数", min_value=1, value=int(generation_cfg.get("target_factor_count", 50)), key="platform-generation-target")
        generation_attempts = st.number_input("最大尝试次数", min_value=1, value=int(generation_cfg.get("max_attempts", 100000)), key="platform-generation-attempts")
        if st.button("启动 PPO 因子生成", type="primary", key="platform-generate-factors", disabled=not master_ready):
            fields_for_generation = _parse_multiline_values(generation_fields_text)
            generation_payload_config = dict(generation_cfg)
            generation_payload_config.update(
                {
                    "fields": fields_for_generation,
                    "splits": {
                        "train": {"cache_start": train_start, "cache_end": train_end},
                        "valid": {"cache_start": valid_start, "cache_end": valid_end},
                        "test": {"cache_start": test_start, "cache_end": test_end},
                    },
                    "target_factor_count": int(generation_target_count),
                    "max_attempts": int(generation_attempts),
                }
            )
            _submit_platform_job(
                "generate_factors",
                {
                    "master_store": str(master_path),
                    "pools_root": str(pools_path),
                    "pool_id": generation_pool,
                    "runtime_root": str(PROJECT_ROOT / "data_cache" / "factor_runtime"),
                    "factor_runs_root": str(factor_runs_path),
                    "fields": fields_for_generation,
                    "splits": generation_payload_config["splits"],
                    "max_backtrack_days": int(generation_cfg.get("max_backtrack_days", 100)),
                    "target_horizon": int(generation_cfg.get("target_horizon", 20)),
                    "max_future_days": int(generation_cfg.get("max_future_days", 20)),
                    "generation_config": generation_payload_config,
                },
                "platform-generate-factors",
            )
    st.subheader("PPO 因子生成结果")
    factor_runs = _load_factor_run_manifests(factor_runs_path)
    if factor_runs.empty:
        st.info("尚未发现 PPO 因子运行结果。")
    else:
        st.dataframe(factor_runs, use_container_width=True, hide_index=True, key="factor-run-table")
        selected_run = st.selectbox("选择因子运行", factor_runs["run_id"].tolist(), key="factor-run-select")
        accepted_table = _load_accepted_factor_table(factor_runs_path / selected_run)
        if accepted_table.empty:
            st.info("这个运行尚无合格因子。")
        else:
            st.dataframe(accepted_table, use_container_width=True, hide_index=True, key="accepted-factor-table")

with tab_factor_results:
    st.subheader("提交合格因子批量回测")
    backtest_factor_runs = _load_factor_run_manifests(factor_runs_path)
    if backtest_factor_runs.empty:
        st.info("请先完成一次 PPO 因子生成。")
    else:
        backtest_run_id = st.selectbox(
            "选择因子运行",
            backtest_factor_runs["run_id"].tolist(),
            key="platform-backtest-factor-run",
        )
        backtest_run_dir = factor_runs_path / backtest_run_id
        backtest_run_manifest = {}
        manifest_path = backtest_run_dir / "factor_run.json"
        if manifest_path.exists():
            backtest_run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        st.caption(f"绑定股票池：{backtest_run_manifest.get('pool_id', '-')}")
        factor_bt_start = st.text_input("因子回测开始", start_date, key="platform-factor-bt-start")
        factor_bt_end = st.text_input("因子回测结束", end_date, key="platform-factor-bt-end")
        factor_bt_top_k = st.number_input("因子回测 TopK", min_value=1, value=int(top_k), key="platform-factor-bt-topk")
        if st.button("启动合格因子批量回测", type="primary", key="platform-backtest-factors", disabled=not master_ready):
            _submit_platform_job(
                "backtest_factors",
                {
                    "master_store": str(master_path),
                    "pools_root": str(pools_path),
                    "factor_run_dir": str(backtest_run_dir),
                    "outputs_root": str(factor_outputs_path),
                    "expected_pool_id": backtest_run_manifest.get("pool_id"),
                    "backtest_config": {
                        "start_date": factor_bt_start,
                        "end_date": factor_bt_end,
                        "top_k": int(factor_bt_top_k),
                        "initial_cash": float(initial_cash),
                        "buy_cost": float(buy_cost),
                        "sell_cost": float(sell_cost),
                        "slippage": float(slippage),
                        "min_cost": float(min_cost),
                        "max_weight_per_stock": float(max_weight),
                    },
                },
                "platform-backtest-factors",
            )
    st.subheader("合格因子回测结果")
    result_dirs = _list_factor_backtest_result_dirs(factor_outputs_path)
    if not result_dirs:
        st.info("尚未找到因子回测结果。")
    else:
        result_options = [str(path.relative_to(factor_outputs_path)) for path in result_dirs]
        selected_result = st.selectbox("选择因子回测", result_options, key="factor-result-select")
        result_table = _load_factor_backtest_summary(factor_outputs_path / selected_result)
        if result_table.empty:
            st.info("这个回测任务没有总结数据。")
        else:
            st.dataframe(result_table, use_container_width=True, hide_index=True, key="factor-result-table")
            _download_button(
                factor_outputs_path / selected_result / "factor_backtest_summary.csv",
                "下载因子回测汇总",
                f"factor-result:{selected_result}",
            )

with tab_composition:
    st.subheader("AlphaGen 风格因子组合")
    st.caption("组合流程只消费已经合格的单因子：先按指标排序，再做 mutual IC 去重，最后优化权重并回测多个组合规模。")
    composition_pool_table = _load_pool_manifests(pools_path)
    composition_factor_runs = _load_factor_run_manifests(factor_runs_path)
    if not master_ready:
        st.info("请先完成 master cache 导入。")
    if composition_pool_table.empty:
        st.info("请先在股票池页创建股票池。")
    elif composition_factor_runs.empty:
        st.info("请先完成一次 PPO 因子生成。")
    else:
        composition_pool = st.selectbox(
            "组合使用的股票池",
            composition_pool_table["pool_id"].astype(str).tolist(),
            key="platform-composition-pool",
        )
        available_composition_runs = composition_factor_runs
        if "pool_id" in available_composition_runs.columns:
            available_composition_runs = available_composition_runs[
                available_composition_runs["pool_id"].astype(str) == str(composition_pool)
            ]
        if available_composition_runs.empty:
            st.warning("当前股票池下没有可用于组合的因子运行。")
        else:
            composition_run_id = st.selectbox(
                "选择单因子运行",
                available_composition_runs["run_id"].astype(str).tolist(),
                key="platform-composition-factor-run",
            )
            composition_metric = st.selectbox(
                "组合排序指标",
                ["score", "ic", "rank_ic", "icir", "coverage", "backtest_sharpe"],
                key="platform-composition-metric",
            )
            c1, c2, c3 = st.columns(3)
            min_score_text = c1.text_input("最低 Score（空表示不限制）", "0", key="platform-composition-min-score")
            min_ic_text = c2.text_input("最低 IC（空表示不限制）", "", key="platform-composition-min-ic")
            min_rank_ic_text = c3.text_input("最低 Rank IC（空表示不限制）", "", key="platform-composition-min-rank-ic")
            c4, c5, c6 = st.columns(3)
            min_coverage_text = c4.text_input("最低 Coverage（空表示不限制）", "0", key="platform-composition-min-coverage")
            min_sharpe_text = c5.text_input("最低单因子回测 Sharpe（空表示不限制）", "", key="platform-composition-min-sharpe")
            mutual_ic_threshold = c6.number_input("mutual IC 阈值", min_value=0.0, max_value=1.0, value=0.99, format="%.4f", key="platform-composition-mutual-ic")
            m1, m2, m3 = st.columns(3)
            composition_target_horizon = m1.number_input("组合 IC 目标周期", min_value=1, value=int(generation_cfg.get("target_horizon", 20)), key="platform-composition-target-horizon")
            marginal_ic_text = m2.text_input("最低边际 IC 改善", "0", key="platform-composition-marginal-ic")
            marginal_rank_ic_text = m3.text_input("最低边际 Rank IC 改善", "", key="platform-composition-marginal-rank-ic")
            m4, m5 = st.columns(2)
            marginal_icir_text = m4.text_input("最低边际 ICIR 改善", "", key="platform-composition-marginal-icir")
            marginal_rank_icir_text = m5.text_input("最低边际 Rank ICIR 改善", "", key="platform-composition-marginal-rank-icir")
            sweep_text = st.text_area(
                "组合规模扫描（每行一个，也支持逗号）",
                "10,20,30,40,50,60,70,80,90,100",
                height=80,
                key="platform-composition-sweep",
            )
            composition_max_factors = st.number_input("最多组合因子数", min_value=1, max_value=100, value=100, key="platform-composition-max-factors")
            composition_top_k = st.number_input("组合回测 TopK", min_value=1, value=int(top_k), key="platform-composition-topk")
            if st.button("启动因子组合", type="primary", key="platform-compose-factors", disabled=not master_ready):
                try:
                    sweep_sizes = _parse_int_values(sweep_text)
                    if not sweep_sizes:
                        raise ValueError("至少填写一个组合规模")
                    _submit_platform_job(
                        "compose_factors",
                        {
                            "master_store": str(master_path),
                            "pools_root": str(pools_path),
                            "pool_id": composition_pool,
                            "factor_run_dirs": [str(factor_runs_path / composition_run_id)],
                            "outputs_root": str(outputs_path),
                            "backtest_config": {
                                "start_date": start_date,
                                "end_date": end_date,
                                "top_k": int(composition_top_k),
                                "initial_cash": float(initial_cash),
                                "buy_cost": float(buy_cost),
                                "sell_cost": float(sell_cost),
                                "slippage": float(slippage),
                                "min_cost": float(min_cost),
                                "max_weight_per_stock": float(max_weight),
                            },
                            "selection_metric": composition_metric,
                            "min_score": _parse_optional_float(min_score_text),
                            "min_ic": _parse_optional_float(min_ic_text),
                            "min_rank_ic": _parse_optional_float(min_rank_ic_text),
                            "min_coverage": _parse_optional_float(min_coverage_text),
                            "min_backtest_sharpe": _parse_optional_float(min_sharpe_text),
                            "mutual_ic_threshold": float(mutual_ic_threshold),
                            "sweep_sizes": sweep_sizes,
                            "max_factors": int(composition_max_factors),
                            "objective_type": "mse",
                            "target_horizon": int(composition_target_horizon),
                            "min_marginal_ic_improvement": _parse_optional_float(marginal_ic_text),
                            "min_marginal_rank_ic_improvement": _parse_optional_float(marginal_rank_ic_text),
                            "min_marginal_icir_improvement": _parse_optional_float(marginal_icir_text),
                            "min_marginal_rank_icir_improvement": _parse_optional_float(marginal_rank_icir_text),
                        },
                        "platform-compose-factors",
                    )
                except Exception as exc:
                    st.error(f"因子组合任务参数错误：{exc}")
    st.subheader("已保存组合结果")
    composite_runs = [item for item in list_runs(outputs_path) if item.get("result_type") == "composite"]
    if not composite_runs:
        st.info("还没有保存过组合回测结果。")
    else:
        composite_table = _saved_runs_table(composite_runs)
        columns = [
            column
            for column in [
                "运行名称",
                "pool_id",
                "composition_id",
                "组合规模",
                "选择指标",
                "mutual IC 阈值",
                "权重方法",
                "因子预处理",
                "组合 IC",
                "组合 Rank IC",
                "组合 ICIR",
                "夏普比",
                "年化收益",
                "最大回撤",
                "总收益",
                "创建时间",
            ]
            if column in composite_table.columns
        ]
        st.dataframe(composite_table[columns], use_container_width=True, hide_index=True, key="composition-saved-table")
        st.caption("点击「已保存结果」页签里的对应记录，可以查看曲线、指标、组合表达式和权重明细。")

with tab_ops:
    st.subheader("当前可用操作符")
    if operator_table.empty:
        st.info("没有注册操作符。")
    else:
        search = st.text_input("搜索操作符", "")
        filtered = operator_table
        if search:
            mask = filtered.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            filtered = filtered[mask]
        for category in filtered["分类名称"].drop_duplicates().tolist():
            with st.expander(category, expanded=True):
                group = filtered[filtered["分类名称"] == category]
                st.dataframe(group[["操作符", "分类", "解释", "示例"]], use_container_width=True, hide_index=True)

with tab_jobs:
    st.subheader("后台任务")
    job_dirs = sorted([p for p in jobs_path.glob("*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True) if jobs_path.exists() else []
    if not job_dirs:
        st.info("还没有后台任务。")
    else:
        selected_job = st.selectbox("选择任务", [p.name for p in job_dirs])
        selected_dir = next(p for p in job_dirs if p.name == selected_job)
        if st.button("查看这个任务"):
            st.session_state["current_job_dir"] = str(selected_dir)
            _request_rerun()
        _render_job_status(selected_dir, "jobs")

with tab_runs:
    st.subheader("已保存回测结果")
    runs = [item for item in list_runs(outputs_path) if Path(item.get("path", "")).name != "jobs"]
    if not runs:
        st.info("还没有保存过回测结果。")
    else:
        runs_table = _saved_runs_table(runs)
        visible_cols = [
            "运行名称",
            "表达式",
            "夏普比",
            "换手率",
            "最大回撤",
            "年化收益",
            "总收益",
            "开始日期",
            "结束日期",
            "TopK",
            "备注",
            "创建时间",
        ]
        visible_cols.extend(
            column
            for column in [
                "result_type",
                "pool_id",
                "factor_run_id",
                "composition_id",
                "组合规模",
                "选择指标",
                "mutual IC 阈值",
                "权重方法",
                "因子预处理",
                "组合 IC",
                "组合 Rank IC",
                "组合 ICIR",
                "canonical_expression",
                "PPO IC",
                "PPO Rank IC",
                "PPO ICIR",
                "PPO Coverage",
                "PPO Score",
            ]
            if column in runs_table.columns and column not in visible_cols
        )
        selection = st.dataframe(
            runs_table[visible_cols],
            use_container_width=True,
            hide_index=True,
            key="saved-runs-table",
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "表达式": st.column_config.TextColumn(width="large"),
                "夏普比": st.column_config.NumberColumn(format="%.4f"),
                "换手率": st.column_config.NumberColumn(format="%.2f%%"),
                "最大回撤": st.column_config.NumberColumn(format="%.2f%%"),
                "年化收益": st.column_config.NumberColumn(format="%.2f%%"),
                "总收益": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        selected_rows = selection.selection.rows if selection and selection.selection else []
        if selected_rows:
            selected_row = runs_table.iloc[selected_rows[0]]
            with st.expander(f"结果详情：{selected_row['运行名称']}", expanded=True):
                _render_result_dir(Path(selected_row["_path"]), f"saved:{selected_row['运行名称']}")



