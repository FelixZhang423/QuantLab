from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

from custom_bt.canonical_expression import canonicalize_alphagen, normalize_expression


_RESULT_FILES = (
    "daily_report.csv",
    "positions.csv",
    "trades.csv",
    "annual_metrics.csv",
    "summary.json",
    "summary.png",
)


def _infer_ids(source_root: Path, result_dir: Path, config: Dict[str, Any]) -> tuple[str, str]:
    pool_id = str(config.get("pool_id") or "")
    factor_run_id = str(config.get("factor_run_id") or "")
    parts = result_dir.relative_to(source_root).parts
    if "composites" in parts:
        marker = parts.index("composites")
        if not pool_id and marker >= 1:
            pool_id = parts[marker - 1]
        if not factor_run_id and marker >= 2:
            factor_run_id = parts[marker - 2]
    else:
        if not pool_id and len(parts) >= 3:
            pool_id = parts[-3]
        if not factor_run_id and len(parts) >= 2:
            factor_run_id = parts[-2]
    return pool_id or "unknown_pool", factor_run_id or "unknown_factor_run"


def _canonical_expression(expression: Any) -> str:
    value = str(expression or "").strip()
    if not value:
        return value
    try:
        return canonicalize_alphagen(value)
    except Exception:
        return normalize_expression(value)


def _load_composite_components(result_dir: Path) -> list[Dict[str, Any]]:
    weights_path = result_dir / "factor_weights.json"
    if not weights_path.exists():
        return []
    rows = json.loads(weights_path.read_text(encoding="utf-8"))
    components: list[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        expression = _canonical_expression(row.get("backtest_expression") or row.get("expression"))
        components.append(
            {
                "factor_id": row.get("factor_id"),
                "expression": expression,
                "weight": row.get("weight"),
                "generation_score": row.get("generation_score"),
                "rank": row.get("rank"),
            }
        )
    return components


def _normalize_composite_weights(path: Path) -> None:
    if not path.exists():
        return
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return
    normalized_rows = []
    for row in rows:
        item = dict(row)
        raw_expression = item.get("backtest_expression") or item.get("expression") or ""
        canonical = _canonical_expression(raw_expression)
        if item.get("expression") and item.get("expression") != canonical:
            item["alphagen_expression"] = item["expression"]
        item["expression"] = canonical
        item["backtest_expression"] = canonical
        item["canonical_expression"] = canonical
        normalized_rows.append(item)
    path.write_text(json.dumps(normalized_rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _result_metadata(source_root: Path, result_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any] | None:
    config = manifest.get("config", {}) or {}
    pool_id, factor_run_id = _infer_ids(source_root, result_dir, config)
    factor = config.get("factor")
    if isinstance(factor, dict):
        expression = factor.get("backtest_expression") or factor.get("expression") or ""
        result_type = "factor"
        generation_metrics = {
            key: factor.get(key)
            for key in ("ic", "rank_ic", "icir", "coverage", "score")
        }
    elif config.get("composite_expression"):
        expression = config["composite_expression"]
        result_type = "composite"
        generation_metrics = {}
    else:
        return None
    return {
        "result_type": result_type,
        "canonical_expression": _canonical_expression(expression),
        "pool_id": pool_id,
        "factor_run_id": factor_run_id,
        "generation_metrics": generation_metrics,
        "source_result_path": str(result_dir.resolve()),
        "components": _load_composite_components(result_dir) if result_type == "composite" else [],
    }


def migrate_factor_results(source_root: str | Path, destination_root: str | Path) -> Dict[str, list]:
    source_root = Path(source_root).expanduser().resolve()
    destination_root = Path(destination_root).expanduser().resolve()
    if not source_root.exists():
        raise FileNotFoundError(f"factor result source does not exist: {source_root}")

    report: Dict[str, list] = {"migrated": [], "skipped": [], "failed": []}
    for manifest_path in sorted(source_root.rglob("manifest.json")):
        result_dir = manifest_path.parent
        if not (result_dir / "daily_report.csv").exists() or not (result_dir / "summary.json").exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata = _result_metadata(source_root, result_dir, manifest)
            if metadata is None:
                continue
            destination = (
                destination_root
                / metadata["result_type"]
                / metadata["pool_id"]
                / metadata["factor_run_id"]
                / result_dir.name
            )
            destination_manifest = destination / "manifest.json"
            if destination_manifest.exists():
                existing = json.loads(destination_manifest.read_text(encoding="utf-8"))
                if (
                    existing.get("source_result_path") == metadata["source_result_path"]
                    and existing.get("components", []) == metadata.get("components", [])
                ):
                    report["skipped"].append(str(destination))
                    continue
            destination.mkdir(parents=True, exist_ok=True)
            for item in result_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, destination / item.name)
            _normalize_composite_weights(destination / "factor_weights.json")
            migrated_manifest = {
                **manifest,
                **metadata,
                "run_name": result_dir.name,
                "files": [item.name for item in destination.iterdir() if item.is_file()],
            }
            destination_manifest.write_text(
                json.dumps(migrated_manifest, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            report["migrated"].append(str(destination))
        except Exception as exc:
            report["failed"].append(
                {"source": str(result_dir), "error": f"{type(exc).__name__}: {exc}"}
            )
    return report
