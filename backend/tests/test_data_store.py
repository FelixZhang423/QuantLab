"""Only shared columnar helpers remain; CSV cache construction was removed."""
import pandas as pd
import pytest
from repositories.local_store import normalize_code, read_panel


@pytest.mark.parametrize("value,expected", [(1,"000001"),("1.0","000001"),(" sh600000 ","SH600000")])
def test_normalize_code(value, expected):
    assert normalize_code(value) == expected


def test_read_panel_projects_parquet_columns(tmp_path):
    path = tmp_path / "panel.parquet"
    pd.DataFrame({"code":["000001"],"close":[10.0],"volume":[100]}).to_parquet(path)
    assert read_panel(path, columns=["code","close"]).columns.tolist() == ["code","close"]


def test_read_panel_rejects_csv(tmp_path):
    path = tmp_path / "panel.csv"
    path.write_text("code,close\n1,10\n")
    with pytest.raises(ValueError, match="Parquet"):
        read_panel(path)


def test_read_panel_directory_combines_parquet_only(tmp_path):
    pd.DataFrame({"close":[10]}).to_parquet(tmp_path / "a.parquet")
    pd.DataFrame({"close":[20]}).to_parquet(tmp_path / "b.parquet")
    (tmp_path / "ignored.csv").write_text("close\n30")
    assert read_panel(tmp_path).close.tolist() == [10,20]
