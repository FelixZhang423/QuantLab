"""Immutable, verified Parquet materializations of company data; no network on reads."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

import pandas as pd
import pyarrow.parquet as pq

from repositories import company_source
from repositories.local_store import normalize_code

SNAPSHOT_VERSION = 1


def _root(snapshot_root=None) -> Path:
    if snapshot_root is None:
        from config.settings import SNAPSHOT_ROOT
        snapshot_root = SNAPSHOT_ROOT
    return Path(snapshot_root).expanduser().resolve()


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_path(snapshot_id: str, *, snapshot_root=None) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", str(snapshot_id)):
        raise ValueError("invalid snapshot_id; only registered Parquet snapshots are accepted")
    return _root(snapshot_root) / snapshot_id / "panel.parquet"


def snapshot_manifest(snapshot_id: str, *, snapshot_root=None) -> dict:
    path = snapshot_path(snapshot_id, snapshot_root=snapshot_root).parent / "manifest.json"
    if not path.exists():
        raise ValueError(f"快照不存在或未完成: {snapshot_id}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("snapshot_id") != snapshot_id or result.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError("snapshot identity/version mismatch")
    return result


def _verify(snapshot_id: str, snapshot_root=None) -> dict:
    manifest = snapshot_manifest(snapshot_id, snapshot_root=snapshot_root)
    path = snapshot_path(snapshot_id, snapshot_root=snapshot_root)
    checksums = json.loads((path.parent / "checksums.json").read_text(encoding="utf-8"))
    for name in ("panel.parquet", "manifest.json"):
        file = path.parent / name
        if not file.is_file() or _file_hash(file) != checksums.get(name):
            raise ValueError(f"snapshot checksum mismatch: {snapshot_id}/{name}")
    return manifest


def load_snapshot(snapshot_id: str, columns=None, *, snapshot_root=None) -> pd.DataFrame:
    manifest = _verify(snapshot_id, snapshot_root)
    available = {"date", "code", *manifest["fields"]}
    if columns is not None and set(columns) - available:
        raise ValueError(f"快照字段不完整: {sorted(set(columns) - available)}")
    frame = pd.read_parquet(snapshot_path(snapshot_id, snapshot_root=snapshot_root), columns=columns)
    frame.attrs["snapshot_id"] = snapshot_id
    return frame


@contextmanager
def _request_lock(root: Path, key: str):
    """OS locks release on process death, unlike stale lock-directory sentinels."""
    directory = root / ".locks"
    directory.mkdir(exist_ok=True)
    with (directory / key).open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 600
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("快照创建锁等待超时")
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def create_or_reuse_snapshot(codes, fields, start_date, end_date, *, pool_id,
                             snapshot_root=None, as_of=None, refresh=False) -> dict:
    codes = sorted({normalize_code(str(code)) for code in codes})
    fields = sorted(set(fields))
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if not codes or not fields or pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError("snapshot requires codes, fields and a valid date interval")
    # Bind both query and attachment semantics; changing source code invalidates reuse.
    query_version = _file_hash(Path(company_source.__file__))
    tables = [company_source.live_db.DAILY_TABLE]
    if set(fields) & company_source._DIM_FIELDS:
        tables.append(company_source.live_db.DIM_TABLE)
    if any(field.startswith(company_source.FUNDAMENTAL_PREFIX) for field in fields):
        tables.extend([company_source.FUNDAMENTAL_CODE_TABLE, company_source.FUNDAMENTAL_TABLE])
    if any(field.startswith(company_source.VALUATION_PREFIX) for field in fields):
        tables.append(company_source.VALUATION_TABLE)
    if any(field.startswith(company_source.DERIVATIVE_PREFIX) for field in fields):
        tables.extend([company_source.FUNDAMENTAL_CODE_TABLE, company_source.FUNDAMENTAL_TABLE,
                       company_source.DERIVATIVE_TABLE])
    settings = company_source.live_db.resolve_settings()
    source_identity = {name: str(getattr(settings, name, "")) for name in ("host", "port", "database")}
    request = dict(pool_id=pool_id, codes=codes, fields=fields,
                   start_date=str(start.date()), end_date=str(end.date()), as_of=as_of,
                   source_signature=company_source.source_signature(), source_identity=source_identity,
                   query_version=query_version, snapshot_version=SNAPSHOT_VERSION)
    key = _hash(request)
    root = _root(snapshot_root)
    root.mkdir(parents=True, exist_ok=True)
    with _request_lock(root, key):
        if not refresh:
            matches = []
            for path in root.glob("*/manifest.json"):
                if path.parent.name.startswith("."):
                    continue
                candidate = json.loads(path.read_text(encoding="utf-8"))
                if candidate.get("request_hash") == key:
                    matches.append(candidate)
            if matches:
                latest = max(matches, key=lambda item: item["created_at"])
                return _verify(latest["snapshot_id"], root)
        temporary = root / (".building-" + uuid4().hex)
        temporary.mkdir()
        try:
            panel_path = temporary / "panel.parquet"
            company_source.write_pool_panel(codes, fields, panel_path, request["start_date"], request["end_date"])
            schema = pq.read_schema(panel_path)
            missing = {"date", "code", *fields} - set(schema.names)
            if missing:
                raise ValueError(f"snapshot fields missing: {sorted(missing)}")
            index = pd.read_parquet(panel_path, columns=["date", "code"])
            if index.empty or index.duplicated(["date", "code"]).any():
                raise ValueError("snapshot is empty or contains duplicate date/code rows")
            dates = pd.to_datetime(index["date"])
            if dates.isna().any() or dates.min() < start or dates.max() > end:
                raise ValueError("snapshot dates outside requested interval")
            if not set(index["code"].astype(str)).issubset(codes):
                raise ValueError("snapshot contains unrequested stock codes")
            created_at = datetime.now(timezone.utc).isoformat()
            checksum = _file_hash(panel_path)
            snapshot_id = _hash([key, checksum, uuid4().hex])
            manifest = {**request, "snapshot_id": snapshot_id, "created_at": created_at,
                        "data_source": "clickhouse", "request_hash": key,
                        "as_of": as_of or created_at, "as_of_kind": "capture-label",
                        "tables": sorted(set(tables)),
                        "query_hash": _hash([request, query_version]), "schema_hash": _hash(str(schema)),
                        "rows": len(index), "n_stocks": int(index["code"].nunique()),
                        "date_min": str(dates.min().date()), "date_max": str(dates.max().date())}
            (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            checksums = {"panel.parquet": checksum, "manifest.json": _file_hash(temporary / "manifest.json")}
            (temporary / "checksums.json").write_text(json.dumps(checksums, indent=2), encoding="utf-8")
            temporary.rename(root / snapshot_id)
            return manifest
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def snapshot_stats(*, snapshot_root=None) -> dict:
    manifests = [json.loads(path.read_text(encoding="utf-8"))
                 for path in _root(snapshot_root).glob("*/manifest.json")
                 if re.fullmatch(r"[0-9a-f]{64}", path.parent.name)]
    return {"snapshot_count": len(manifests),
            "latest_snapshot_at": max((m["created_at"] for m in manifests), default=None)}
