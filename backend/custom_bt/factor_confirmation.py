"""One frozen post-PPO holdout pass, with durable per-candidate results and no tuning input."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from custom_bt.factor_generation import _single_factor_root, _close_panel
from custom_bt.factor_backtest import factor_id
from custom_bt.generation_splits import validate_splits
from repositories import snapshot_store
from repositories.factor_run_store import read_jsonl
from repositories.job_store import atomic_write_json


def _digest(path):
    return snapshot_store._file_hash(Path(path))


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _publish_jsonl(path, rows):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_clean(row), ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _archive_confirmation(root, run, final):
    run.update(candidate_count=final["candidate_count"], confirmed_count=final["confirmed_count"],
               accepted_count=final["confirmed_count"], confirmation_status="finished")
    atomic_write_json(root / "factor_run.json", run)
    try:
        from repositories.mysql_store import persist_factor_run
        persist_factor_run(root)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("MySQL sync failed after confirmation", exc_info=True)


def _confirm_factor_run(factor_run_dir, snapshot_root=None, progress_callback=None) -> dict:
    root = Path(factor_run_dir).expanduser().resolve()
    if not (root / "factor_run.json").is_file():
        raise ValueError("因子运行不存在")
    run = json.loads((root / "factor_run.json").read_text(encoding="utf-8"))
    if run.get("generation_status") != "finished" or run.get("policy_version") != 2:
        raise ValueError("请先完成新的两阶段 PPO 生成，旧 accepted 因子不能跳过确认")
    freeze_path = root / "generation_freeze.json"
    if not freeze_path.exists() or run.get("generation_freeze_sha256") != _digest(freeze_path):
        raise ValueError("生成冻结清单不存在或校验失败，请使用完整的新生成运行")
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    for name in ("candidate_sha256", "snapshot_id", "fields", "max_backtrack_days", "max_future_days", "operators", "hyperparameters"):
        if run.get(name) != frozen.get(name):
            raise ValueError("生成冻结数据或门槛已变化，禁止修改同一轮确认条件")
    if run["hyperparameters"]["quality"] != frozen["quality"] or run["hyperparameters"]["target_horizon"] != frozen["target_horizon"]:
        raise ValueError("生成冻结数据或门槛已变化，禁止修改同一轮确认条件")
    candidates_path = root / "candidate_factors.jsonl"
    candidate_hash = _digest(candidates_path)
    if run.get("candidate_sha256") != candidate_hash:
        raise ValueError("候选集合已变化，禁止使用该测试集重新筛选；请保留原始冻结运行")
    candidates = read_jsonl(candidates_path)
    runtime_path = Path(run["runtime_manifest"])
    if _digest(runtime_path) != frozen["runtime_sha256"]:
        raise ValueError("生成运行时清单已变化")
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    snapshot_id = run["snapshot_id"]
    if runtime["snapshot_id"] != snapshot_id:
        raise ValueError("运行与训练快照不一致")
    snapshot_store._verify(snapshot_id, snapshot_root)
    calendar = pd.read_parquet(snapshot_store.snapshot_path(snapshot_id, snapshot_root=snapshot_root), columns=["date"])["date"]
    validate_splits(runtime["splits"], calendar, int(run["hyperparameters"]["target_horizon"]), require_all=True)
    _single_factor_root()
    from single_factor.config import QualityConfig
    from single_factor.data import PanelData
    from single_factor.evaluator import SingleFactorEvaluator, SegmentMetrics
    from single_factor.expression import SingleFactorParser
    quality = QualityConfig(**run["hyperparameters"]["quality"])
    test_dir = Path(runtime["splits"]["test"]["cache_dir"])
    cache_hashes = {path.name: _digest(path) for path in sorted(test_dir.iterdir()) if path.is_file()}
    request = {"candidate_sha256": candidate_hash, "snapshot_id": snapshot_id,
               "runtime_sha256": _digest(runtime_path), "test_cache_sha256": cache_hashes,
               "quality": asdict(quality), "target_horizon": run["hyperparameters"]["target_horizon"],
               "max_backtrack_days": run["max_backtrack_days"], "max_future_days": run["max_future_days"],
               "policy_version": 2, "evaluation_version": _digest(Path(_single_factor_root()) / "single_factor" / "evaluator.py")}
    request_path = root / "confirmation_request.json"
    if request_path.exists():
        if json.loads(request_path.read_text(encoding="utf-8")) != request:
            raise ValueError("确认数据或门槛已变化，禁止重复使用测试集调整同一运行")
    else:
        atomic_write_json(request_path, request)
    final_path = root / "confirmation_manifest.json"
    if final_path.exists():
        final = json.loads(final_path.read_text(encoding="utf-8"))
        if final.get("status") == "finished":
            if final.get("confirmed_sha256") != _digest(root / "confirmed_factors.jsonl"):
                raise ValueError("已确认因子文件校验失败")
            if final.get("evaluations_sha256") != _digest(root / "test_evaluations.jsonl"):
                raise ValueError("测试评估结果文件校验失败")
            _archive_confirmation(root, run, final)
            return final
    atomic_write_json(final_path, {"status": "running", "run_id": root.name,
                                  "candidate_count": len(candidates)})
    evaluations_path = root / "test_evaluations.jsonl"
    # A process can die midway through the final append; only complete durable rows count.
    if evaluations_path.exists():
        payload = evaluations_path.read_bytes()
        if payload and not payload.endswith(b"\n"):
            payload = payload[:payload.rfind(b"\n") + 1]
            evaluations_path.write_bytes(payload)
    evaluations = read_jsonl(evaluations_path)
    completed = {row["factor_id"]: row for row in evaluations}
    ids = [record.get("factor_id") or factor_id(i, record["expression"]) for i, record in enumerate(candidates, 1)]
    if len(set(ids)) != len(ids) or set(completed) - set(ids) or len(completed) != len(evaluations):
        raise ValueError("候选或测试评估日志含重复/未知因子 ID")
    test_panel = None
    try:
        if len(completed) < len(candidates):
            test_panel = PanelData.from_memmap(test_dir, max_backtrack_days=int(run["max_backtrack_days"]),
                                              max_future_days=int(run["max_future_days"]))
        evaluator = SingleFactorEvaluator(None, int(request["target_horizon"]), quality=quality, test_panel=test_panel)
        parser = SingleFactorParser(run["fields"])
        for index, (candidate, identity) in enumerate(zip(candidates, ids), 1):
            if identity not in completed:
                metrics = None
                try:
                    train_ic = float(candidate["segments"]["train"]["ic"])
                    train_valid = {name: SegmentMetrics(**candidate["segments"][name]) for name in ("train", "valid")}
                    reason = evaluator._accept(train_valid)
                    if reason is None:
                        metrics = evaluator.evaluate_holdout(parser.parse(candidate["expression"]))
                        reason = evaluator.confirmation_rejection(train_ic, metrics)
                except Exception as exc:
                    reason = f"test evaluation error: {type(exc).__name__}: {exc}"
                row = {"factor_id": identity, "expression": candidate["expression"],
                       "test": asdict(metrics) if metrics is not None else None,
                       "confirmed": reason is None, "reason": reason,
                       "evaluated_at": datetime.now(timezone.utc).isoformat()}
                row = _clean(row)
                with evaluations_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                completed[identity] = row
            if progress_callback:
                progress_callback({"stage": "confirming", "processed": index, "candidate_count": len(candidates),
                                   "confirmed_count": sum(bool(row["confirmed"]) for row in completed.values())})
    finally:
        _close_panel(test_panel)
    if not evaluations_path.exists():
        evaluations_path.touch()
    confirmed = []
    for candidate, identity in zip(candidates, ids):
        result = completed[identity]
        if result["confirmed"]:
            confirmed.append({**candidate, "factor_id": identity, "status": "confirmed", "confirmed": True,
                              "segments": {**candidate["segments"], "test": result["test"]},
                              "confirmation_reason": None})
    _publish_jsonl(root / "confirmed_factors.jsonl", confirmed)
    final = {"status": "finished", "run_id": root.name, "candidate_count": len(candidates),
             "confirmed_count": len(confirmed), "rejected_count": len(candidates) - len(confirmed),
             "candidate_sha256": candidate_hash, "confirmed_sha256": _digest(root / "confirmed_factors.jsonl"),
             "evaluations_sha256": _digest(evaluations_path), "snapshot_id": snapshot_id,
             "finished_at": datetime.now(timezone.utc).isoformat()}
    atomic_write_json(final_path, final)
    _archive_confirmation(root, run, final)
    return final


def confirm_factor_run(factor_run_dir, snapshot_root=None, progress_callback=None) -> dict:
    root = Path(factor_run_dir).expanduser().resolve()
    if not (root / "factor_run.json").is_file():
        raise ValueError("因子运行不存在")
    with snapshot_store._request_lock(root, "confirmation"):
        try:
            return _confirm_factor_run(root, snapshot_root, progress_callback)
        except Exception as exc:
            path = root / "confirmation_manifest.json"
            current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if current.get("status") != "finished" and (root / "confirmation_request.json").exists():
                atomic_write_json(path, {**current, "status": "failed", "error": str(exc)})
            raise
