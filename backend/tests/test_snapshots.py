import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from repositories import company_source, snapshot_store


@pytest.fixture
def source(monkeypatch):
    calls = []

    def write(codes, fields, output_path, start_date, end_date):
        calls.append((codes, fields))
        frame = pd.DataFrame({"date": pd.to_datetime([start_date, end_date]),
                              "code": [codes[0]] * 2,
                              **{field: [10.0, 11.0] for field in fields}})
        frame.to_parquet(output_path, index=False)
        return {}

    monkeypatch.setattr(company_source, "write_pool_panel", write)
    return calls


def create(root, **options):
    return snapshot_store.create_or_reuse_snapshot(
        ["000001"], ["close", "open"], "2024-01-01", "2024-01-03",
        pool_id="pool", snapshot_root=root, **options)


def test_create_reuse_refresh_and_offline_load(tmp_path, source):
    first = create(tmp_path)
    assert create(tmp_path)["snapshot_id"] == first["snapshot_id"]
    assert len(source) == 1
    for name in ("as_of", "query_hash", "source_signature", "schema_hash", "rows", "snapshot_version"):
        assert name in first
    frame = snapshot_store.load_snapshot(first["snapshot_id"], ["close"], snapshot_root=tmp_path)
    assert frame.columns.tolist() == ["close"]
    refreshed = create(tmp_path, refresh=True)
    assert refreshed["snapshot_id"] != first["snapshot_id"]
    assert snapshot_store.snapshot_manifest(first["snapshot_id"], snapshot_root=tmp_path) == first


def test_concurrent_request_queries_once(tmp_path, source):
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: create(tmp_path), range(4)))
    assert len({r["snapshot_id"] for r in results}) == 1
    assert len(source) == 1


def test_corruption_is_not_silently_replaced(tmp_path, source):
    manifest = create(tmp_path)
    snapshot_store.snapshot_path(manifest["snapshot_id"], snapshot_root=tmp_path).write_bytes(b"broken")
    with pytest.raises(ValueError, match="checksum"):
        snapshot_store.load_snapshot(manifest["snapshot_id"], snapshot_root=tmp_path)
    assert len(source) == 1


def test_missing_field_does_not_publish(tmp_path, monkeypatch):
    def write(codes, fields, output_path, *args):
        pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "code": [codes[0]]}).to_parquet(output_path)
    monkeypatch.setattr(company_source, "write_pool_panel", write)
    with pytest.raises(ValueError, match="fields"):
        create(tmp_path)
    assert not list(tmp_path.glob("*/manifest.json"))


def test_reject_path_traversal_and_csv(tmp_path):
    for name in ("../outside", "file.csv"):
        with pytest.raises(ValueError):
            snapshot_store.snapshot_path(name, snapshot_root=tmp_path)
