from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from custom_bt.expressions import list_operators


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _compact_mapping(payload: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _compact_pool_manifest(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    compact = _compact_mapping(
        payload,
        [
            "pool_id",
            "name",
            "source_signature",
            "selection_start",
            "selection_end",
            "top_n",
            "n_stocks",
            "selection_days",
            "min_listed_days",
            "min_coverage",
            "exclude_suspended",
            "category",
            "market_code",
        ],
    )
    if "selected_codes" in payload and "n_stocks" not in compact:
        compact["n_stocks"] = len(payload.get("selected_codes") or [])
    compact["manifest_path"] = str(path)
    return compact


def _compact_factor_run(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    compact = _compact_mapping(
        payload,
        [
            "run_id",
            "pool_id",
            "source_signature",
            "runtime_id",
            "created_at",
            "accepted_count",
            "attempts",
            "target_reached",
            "attempts_exhausted",
        ],
    )
    compact["manifest_path"] = str(path)
    return compact


def _compact_saved_result(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    compact = _compact_mapping(
        payload,
        [
            "run_name",
            "run_id",
            "result_type",
            "pool_id",
            "source_signature",
            "created_at",
            "factor_count",
            "target_horizon",
            "composition_metrics",
            "metrics",
        ],
    )
    compact["manifest_path"] = str(path)
    return compact


def _pool_manifest_paths(pools_root: Path) -> list[Path]:
    if not pools_root.exists():
        return []
    return sorted(pools_root.glob("*/manifest.json"))


def _read_pool_manifests(pools_root: Path, limit: int) -> list[dict[str, Any]]:
    manifests = _pool_manifest_paths(pools_root)
    return [_compact_pool_manifest(path) for path in manifests[:limit]]


def _read_factor_runs(factor_runs_root: Path, limit: int) -> list[dict[str, Any]]:
    if not factor_runs_root.exists():
        return []
    manifests = sorted(
        factor_runs_root.glob("*/factor_run.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [_compact_factor_run(path) for path in manifests[:limit]]


def _read_saved_results(saved_results_root: Path, limit: int) -> list[dict[str, Any]]:
    if not saved_results_root.exists():
        return []
    manifests = sorted(
        saved_results_root.glob("**/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [_compact_saved_result(path) for path in manifests[:limit]]


def _operator_names() -> list[str]:
    return sorted({item["name"] for item in list_operators()})


def _select_pool(pools: list[dict[str, Any]], pool_id: str | None) -> dict[str, Any]:
    return pools[0] if pools else {}


def _find_pool_manifest(pools_root: Path, pool_id: str) -> dict[str, Any]:
    for path in _pool_manifest_paths(pools_root):
        pool = _compact_pool_manifest(path)
        if pool.get("pool_id") == pool_id:
            return pool
    raise ValueError(f"pool_id not found in pools_root: {pool_id}")


def _identity_lock(master_meta: dict[str, Any], pool: dict[str, Any]) -> dict[str, Any]:
    return {
        "pool_id": pool.get("pool_id", ""),
        "source_signature": pool.get("source_signature") or master_meta.get("source_signature", ""),
        "date_min": master_meta.get("date_min", ""),
        "date_max": master_meta.get("date_max", ""),
        "operator_registry_version": "local",
    }


def build_context_snapshot(
    master_store: str | Path,
    pools_root: str | Path,
    factor_runs_root: str | Path,
    saved_results_root: str | Path,
    pool_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Build a compact, local-only context snapshot for prompt construction."""

    master_path = Path(master_store)
    master_meta = _read_json(master_path / "meta.json")
    pools_root_path = Path(pools_root)
    pools = _read_pool_manifests(pools_root_path, limit)
    if pool_id:
        selected_pool = _find_pool_manifest(pools_root_path, pool_id)
        if all(pool.get("pool_id") != pool_id for pool in pools):
            pools = [selected_pool] + pools[: max(0, limit - 1)]
    else:
        selected_pool = _select_pool(pools, pool_id)
    identity_lock = _identity_lock(master_meta, selected_pool)

    return {
        "master_store": {
            "rows": master_meta.get("rows"),
            "n_stocks": master_meta.get("n_stocks"),
            "fields": master_meta.get("fields", []),
            "field_catalog": master_meta.get("field_catalog", []),
            "date_min": master_meta.get("date_min"),
            "date_max": master_meta.get("date_max"),
            "source_signature": master_meta.get("source_signature"),
            "source_csv": master_meta.get("source_csv"),
            "layout": master_meta.get("layout"),
        },
        "pools": pools,
        "selected_pool": selected_pool,
        "operators": _operator_names(),
        "recent_factor_runs": _read_factor_runs(Path(factor_runs_root), limit),
        "saved_results": _read_saved_results(Path(saved_results_root), limit),
        "identity_lock": identity_lock,
    }
