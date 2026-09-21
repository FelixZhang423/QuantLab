"""Materialize generated factor values into independent partitioned files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .expression_engine import ExpressionError, evaluate_expression
from .io import resolve_snapshot, write_json


def materialize_factor_values(
    data_root: str | Path,
    runs_root: str | Path,
    snapshot_id: str | None = None,
    factor_ids: Iterable[str] | None = None,
    max_factors: int | None = None,
) -> dict[str, Any]:
    snapshot = resolve_snapshot(data_root, snapshot_id)
    market = pd.read_parquet(snapshot / "market.parquet")
    catalog = pd.read_parquet(snapshot / "factor_catalog.parquet")
    catalog = catalog[catalog["accepted"].fillna(True).astype(bool)].copy()
    requested = None if factor_ids is None else {str(item) for item in factor_ids}
    if requested is not None:
        catalog = catalog[catalog["factor_id"].astype(str).isin(requested)]
    catalog = catalog.sort_values("factor_id").reset_index(drop=True)
    if max_factors is not None:
        if max_factors <= 0:
            raise ValueError("max_factors must be positive")
        catalog = catalog.head(max_factors)
    seed = json.dumps({"snapshot": snapshot.name, "factors": catalog["factor_id"].astype(str).tolist()}, sort_keys=True)
    run_id = f"values_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha256(seed.encode()).hexdigest()[:8]}"
    run_dir = Path(runs_root).expanduser().resolve() / run_id
    if run_dir.exists():
        raise FileExistsError(f"factor value run already exists: {run_dir}")
    value_root = run_dir / "factor_values"
    value_root.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    computed = 0
    for record in catalog.to_dict("records"):
        factor_id = str(record["factor_id"])
        expression = str(record.get("expression") or record.get("canonical_expression") or "").strip()
        output_dir = value_root / f"factor_id={factor_id}"
        try:
            values = evaluate_expression(expression, market)
            values["factor_id"] = factor_id
            values = values[["date", "code", "factor_id", "value"]]
            output_dir.mkdir(parents=True, exist_ok=False)
            values.to_parquet(output_dir / "values.parquet", index=False)
            valid = int(values["value"].notna().sum())
            rows.append({
                "factor_id": factor_id,
                "expression": expression,
                "status": "computed",
                "rows": int(len(values)),
                "valid_values": valid,
                "coverage": float(valid / len(values)) if len(values) else 0.0,
            })
            computed += 1
        except Exception as exc:
            rows.append({
                "factor_id": factor_id,
                "expression": expression,
                "status": "failed",
                "rows": 0,
                "valid_values": 0,
                "coverage": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            })
    manifest = {
        "run_id": run_id,
        "snapshot_id": snapshot.name,
        "requested": int(len(catalog)),
        "computed": computed,
        "failed": int(len(rows) - computed),
        "errors": [row for row in rows if row["status"] == "failed"],
        "factors": rows,
    }
    write_json(run_dir / "factor_values_manifest.json", manifest)
    return {"run_id": run_id, "snapshot_id": snapshot.name, "requested": len(catalog), "computed": computed, "failed": len(rows) - computed, "run_dir": str(run_dir)}
