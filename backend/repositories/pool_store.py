"""股票池持久化：选样读取、codes/manifest 落盘与读取。"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from repositories.local_store import normalize_code

logger = logging.getLogger(__name__)


def write_pool(
    pools_path: Path,
    manifest_base: dict[str, Any],
    *,
    strict_top_n: bool,
    overwrite: bool,
    provenance: Optional[dict[str, Any]],
) -> dict:
    name = str(manifest_base.get("name") or "")
    selected = manifest_base.get("selected_stats") or []
    selected_codes = [str(row["code"]) for row in selected]
    digest = hashlib.sha256(
        json.dumps(manifest_base, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:8]
    pool_id = f"{name}_{digest}"
    pool_dir = pools_path / pool_id
    if pool_dir.exists() and not overwrite:
        raise FileExistsError(f"pool already exists: {pool_dir}")
    pool_dir.mkdir(parents=True, exist_ok=True)
    (pool_dir / "codes.txt").write_text("\n".join(selected_codes) + "\n", encoding="utf-8")
    pd.DataFrame(selected).to_csv(pool_dir / "selection_summary.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "pool_id": pool_id,
        "codes_file": "codes.txt",
        **manifest_base,
        # 下面两项只是元数据，不参与上面的 pool_id 摘要：同一组选股条件/代码
        # 无论来自哪次筛选，pool_id 都保持一致。
        "strict_top_n": strict_top_n,
        "provenance": provenance,
    }
    (pool_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    try:
        from repositories.mysql_store import persist_pool

        persist_pool(pool_dir)
    except Exception:
        logger.warning("MySQL persist failed for pool %s", pool_id, exc_info=True)
    return manifest


def load_pool_manifest(pools_root: str | Path, pool_id: str) -> dict:
    path = Path(pools_root).expanduser().resolve() / pool_id / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"pool manifest is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_pool_codes(pools_root: str | Path, pool_id: str) -> list[str]:
    manifest = load_pool_manifest(pools_root, pool_id)
    path = Path(pools_root).expanduser().resolve() / pool_id / manifest.get("codes_file", "codes.txt")
    if not path.exists():
        raise FileNotFoundError(f"pool code file is missing: {path}")
    return [normalize_code(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
