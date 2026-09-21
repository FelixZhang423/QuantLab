"""Small research runs that consume only an independent snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .features import assign_rule_states, market_state_features
from .io import resolve_snapshot, write_json


def run_state_analysis(
    data_root: str | Path,
    runs_root: str | Path,
    snapshot_id: str | None = None,
    volatility_window: int = 20,
    trend_threshold: float = 0.002,
    volatility_threshold: float = 0.03,
) -> dict[str, Any]:
    snapshot = resolve_snapshot(data_root, snapshot_id)
    market = pd.read_parquet(snapshot / "market.parquet")
    features = market_state_features(market, volatility_window=volatility_window)
    states = assign_rule_states(
        features,
        trend_threshold=trend_threshold,
        volatility_threshold=volatility_threshold,
    )
    seed = json.dumps({"snapshot": snapshot.name, "window": volatility_window, "trend": trend_threshold, "volatility": volatility_threshold}, sort_keys=True)
    run_id = f"state_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha256(seed.encode()).hexdigest()[:8]}"
    run_dir = Path(runs_root).expanduser().resolve() / run_id
    if run_dir.exists():
        raise FileExistsError(f"research run already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    states.to_parquet(run_dir / "market_states.parquet", index=False)
    config = {
        "run_id": run_id,
        "snapshot_id": snapshot.name,
        "volatility_window": volatility_window,
        "trend_threshold": trend_threshold,
        "volatility_threshold": volatility_threshold,
        "state_method": "rule",
    }
    write_json(run_dir / "config.json", config)
    write_json(run_dir / "manifest.json", {
        **config,
        "state_count": int(len(states)),
        "labels": sorted(states["state_id"].dropna().astype(str).unique()),
        "files": ["market_states.parquet", "config.json", "manifest.json"],
    })
    return {"run_id": run_id, "snapshot_id": snapshot.name, "state_count": int(len(states)), "run_dir": str(run_dir)}
