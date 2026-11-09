"""Small Parquet/company-client fixtures; no production cache importer is used."""
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from repositories import company_source
from repositories.clickhouse import LiveDBSettings
from repositories.snapshot_store import create_or_reuse_snapshot
from custom_bt.pools import create_pool_from_company

_FRAME = None


def write_company_fixture(source, snapshot_root, **unused):
    global _FRAME
    _FRAME = pd.read_parquet(source).rename(columns={"timestamps":"date","vol":"volume"})
    _FRAME["date"] = pd.to_datetime(_FRAME["date"])
    _FRAME["code"] = _FRAME["code"].astype(str).str.zfill(6)
    for name in ("Ifsuspend","if_up","if_down"):
        if name not in _FRAME:
            _FRAME[name] = 0
    snapshot_root = Path(snapshot_root)
    snapshot_root.mkdir(parents=True,exist_ok=True)
    _FRAME.to_parquet(snapshot_root / "fixture.parquet",index=False)


def fake_panel_writer(codes, fields, output_path, start_date, end_date, **unused):
    frame = _FRAME[_FRAME.code.isin(codes)]
    frame = frame[(frame.date >= pd.Timestamp(start_date)) & (frame.date <= pd.Timestamp(end_date))]
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"fixture missing fields: {missing}")
    frame[["date","code",*fields]].to_parquet(output_path,index=False)
    return {"panel_path":str(output_path),"rows":len(frame)}


class SelectionClient:
    def query(self, sql):
        if "AS days" in sql:
            return [{"days":_FRAME.date.nunique()}]
        grouped = _FRAME.groupby("code").amount.agg(["mean","count"])
        return [{"code":code,"valid_rows":int(row["count"]),"avg_amount":row["mean"]}
                for code,row in grouped.iterrows()]


def fixture_pool(snapshot_root, pools_root, name, selection_start, selection_end, **options):
    pool = create_pool_from_company(pools_root,name,selection_start,selection_end,
             settings=LiveDBSettings(),client=SelectionClient(),**options)
    fields = [name for name in _FRAME.columns if name not in {"date","code"}]
    with patch.object(company_source,"write_pool_panel",fake_panel_writer):
        snapshot = create_or_reuse_snapshot(pool["selected_codes"],fields,selection_start,selection_end,
                        pool_id=pool["pool_id"],snapshot_root=snapshot_root)
    pool["snapshot_id"] = snapshot["snapshot_id"]
    return pool


def publish_confirmed(run_dir, rows=None):
    """Publish an already-confirmed test fixture through the real checksum contract."""
    import hashlib
    import json
    from custom_bt.factor_backtest import factor_id
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "confirmed_factors.jsonl"
    if rows is None:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = []
    for index, row in enumerate(rows, 1):
        record = {**row, "status": "confirmed", "confirmed": True}
        record.setdefault("factor_id", factor_id(index, record["expression"]))
        records.append(record)
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    (root / "confirmation_manifest.json").write_text(json.dumps({
        "status": "finished", "confirmed_count": len(records),
        "confirmed_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8")
    return records
