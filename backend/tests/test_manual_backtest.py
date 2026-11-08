import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from repositories import company_source
from adapters.expressions import ExpressionError
from custom_bt.manual_backtest import (
    normalize_manual_expression,
    run_manual_backtest,
    validate_pool_id,
    validate_run_name,
)


def _panel() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-01", periods=25, freq="D")
    for index, date in enumerate(dates):
        for code, base in (("000001", 10.0), ("600000", 20.0)):
            price = base + index * 0.1 + (index % 3) * 0.05
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": price,
                    "close": price + 0.05,
                    "high": price + 0.2,
                    "low": price - 0.1,
                    "volume": 1000.0,
                    "amount": 20000.0,
                    "Ifsuspend": 0,
                    "if_up": 0,
                    "if_down": 0,
                }
            )
    return pd.DataFrame(rows)


def _company_pool(root: Path, signature: str = company_source.SOURCE_SIGNATURE) -> Path:
    pools_root = root / "pools"
    pool_dir = pools_root / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pool_id": "pool_a",
                "name": "pool_a",
                "data_source": "clickhouse",
                "source_signature": signature,
                "selection_start": "2024-01-01",
                "selection_end": "2024-01-25",
            }
        ),
        encoding="utf-8",
    )
    (pool_dir / "codes.txt").write_text("000001\n600000\n", encoding="utf-8")
    return pools_root


def _config() -> dict:
    return {
        "start_date": "2024-01-01",
        "end_date": "2024-01-25",
        "top_k": 1,
        "initial_cash": 1_000_000.0,
    }


def _write_panel(codes, fields, output_path, start_date, end_date, **unused):
    frame = _panel()
    frame = frame[frame.code.isin(codes)]
    frame = frame[(frame.date >= pd.Timestamp(start_date)) & (frame.date <= pd.Timestamp(end_date))]
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"unsupported expression fields: {missing}")
    frame[["date", "code", *fields]].to_parquet(output_path, index=False)


def test_normalize_expression_and_path_validation():
    assert normalize_manual_expression("close / delay(close, 20) - 1") == "close / delay(close, 20) - 1"
    assert validate_pool_id("测试股票池_a9883be5") == "测试股票池_a9883be5"
    for validate, value in [(normalize_manual_expression," "), (validate_run_name,"../escape"),
                            (validate_pool_id,"../escape")]:
        with pytest.raises(ValueError):
            validate(value)


def test_company_snapshot_backtest_writes_result_and_reuses_offline(tmp_path):
    pools = _company_pool(tmp_path)
    progress = []
    options = dict(pools_root=pools, output_root=tmp_path / "outputs", run_name="momentum_20",
                   expression="close / delay(close, 1) - 1", backtest_config=_config(),
                   pool_id="pool_a", snapshot_root=tmp_path / "snapshots", backtest_id="job_42")
    with patch.object(company_source,"write_pool_panel",side_effect=_write_panel) as writer:
        result = run_manual_backtest(**options, progress_callback=progress.append)
    assert writer.call_count == 1
    assert writer.call_args.args[0] == ["000001","600000"]
    assert result["run_key"] == "manual/job_42/momentum_20"
    assert result["data_source"] == "clickhouse"
    assert result["pool_id"] == "pool_a"
    assert result["n_stocks"] == 2
    assert "annual_return" in result["summary"]
    directory = tmp_path / "outputs/manual/job_42/momentum_20"
    for name in ("manifest.json","summary.json","daily_report.csv","annual_metrics.csv"):
        assert (directory / name).is_file()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result_type"] == "manual"
    assert manifest["canonical_expression"] == options["expression"]
    assert manifest["snapshot_id"] == result["snapshot_id"]
    assert [event["stage"] for event in progress] == ["loading_panel","evaluating","running","finished"]
    options["backtest_id"] = "job_43"
    with patch.object(company_source,"write_pool_panel",side_effect=AssertionError("offline")), \
         patch.object(company_source,"meta",side_effect=AssertionError("offline")):
        repeated = run_manual_backtest(**options,snapshot_id=result["snapshot_id"])
    assert repeated["snapshot_id"] == result["snapshot_id"]


def test_accepts_company_pool_payload_without_local_files(tmp_path):
    manifest = {"pool_id":"pool_mysql","data_source":"clickhouse",
                "source_signature":company_source.source_signature()}
    with patch.object(company_source,"write_pool_panel",side_effect=_write_panel) as writer:
        result = run_manual_backtest(tmp_path / "missing_pools",tmp_path / "outputs","mysql_pool_run",
                  "close",_config(),"pool_mysql",pool_manifest=manifest,pool_codes=["000001","600000"],
                  snapshot_root=tmp_path / "snapshots")
    assert result["pool_id"] == "pool_mysql"
    assert writer.call_count == 1


def test_old_local_pool_is_rejected_before_source_query(tmp_path):
    manifest = {"pool_id":"pool_local","data_source":"local","source_signature":"local_sig"}
    with patch.object(company_source,"write_pool_panel",side_effect=AssertionError("must not query")):
        with pytest.raises(ValueError,match="[Ll]ocal|ClickHouse"):
            run_manual_backtest(tmp_path / "pools",tmp_path / "outputs","demo","close",_config(),
                 "pool_local",pool_manifest=manifest,pool_codes=["000001"],snapshot_root=tmp_path / "snapshots")


def test_rejects_source_signature_mismatch(tmp_path):
    pools = _company_pool(tmp_path,signature="other")
    with pytest.raises(ValueError,match="signature"):
        run_manual_backtest(pools,tmp_path / "outputs","demo","close",_config(),"pool_a",
                            snapshot_root=tmp_path / "snapshots")


@pytest.mark.parametrize("expression", ["not_a_field + 1", "close +"])
def test_rejects_invalid_or_unknown_expression(tmp_path,expression):
    pools = _company_pool(tmp_path)
    with patch.object(company_source,"write_pool_panel",side_effect=_write_panel):
        with pytest.raises((ExpressionError, ValueError, SyntaxError)):
            run_manual_backtest(pools,tmp_path / "outputs","demo",expression,_config(),"pool_a",
                                snapshot_root=tmp_path / "snapshots")


def test_rejects_empty_snapshot_and_invalid_identifiers(tmp_path):
    pools = _company_pool(tmp_path)
    def write_empty(codes, fields, output_path, *args, **kwargs):
        _panel().iloc[:0][["date","code",*fields]].to_parquet(output_path,index=False)
    with patch.object(company_source,"write_pool_panel",side_effect=write_empty):
        with pytest.raises(ValueError,match="empty|no panel rows|no rows|快照"):
            run_manual_backtest(pools,tmp_path / "outputs","demo","close",_config(),"pool_a",
                                snapshot_root=tmp_path / "snapshots")
    for key, value in [("backtest_id","../escape"),("pool_id","../escape")]:
        options = dict(pools_root=pools,output_root=tmp_path / "outputs",run_name="demo",expression="close",
                       backtest_config=_config(),pool_id="pool_a",snapshot_root=tmp_path / "snapshots")
        options[key] = value
        with pytest.raises(ValueError,match="invalid"):
            run_manual_backtest(**options)
