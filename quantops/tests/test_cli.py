"""命令行入口：list / describe / eval，以及「同名目录被当成空包」时的报错文案。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """跑 `py -3 -m quantops ...`；强制 UTF-8 输出，让断言不受中文 Windows 代码页影响。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "quantops", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


@pytest.fixture()
def panel_csv(tmp_path) -> Path:
    path = tmp_path / "panel.csv"
    rows = ["date,code,close,volume,industry"]
    for code_idx, code in enumerate(["000001", "000002", "000003"]):
        for day in range(1, 6):
            rows.append(f"2024-01-0{day},{code},{10.0 + code_idx + day * 0.1},1000,{code_idx}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_list_json(panel_csv):
    proc = run_cli("list", "--json", cwd=PROJECT_DIR)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["total"] == 80
    assert len(payload["operators"]) == 80
    assert len(payload["categories"]) == 7


def test_list_filters_by_category_and_search():
    by_category = run_cli("list", "--category", "time_series", cwd=PROJECT_DIR)
    assert by_category.returncode == 0
    assert "共 34 个算子" in by_category.stdout

    by_search = run_cli("list", "--search", "corr", cwd=PROJECT_DIR)
    assert "ts_corr" in by_search.stdout


def test_describe_and_unknown_name():
    proc = run_cli("describe", "ts_mean", cwd=PROJECT_DIR)
    assert proc.returncode == 0
    assert "ts_mean" in proc.stdout and "时间序列" in proc.stdout

    unknown = run_cli("describe", "not_an_operator", cwd=PROJECT_DIR)
    assert unknown.returncode == 2
    assert "未知算子" in unknown.stderr


def test_eval_writes_alpha_column(panel_csv, tmp_path):
    out = tmp_path / "alpha.csv"
    proc = run_cli(
        "eval", "rank(ts_mean(close, 2))", "--csv", str(panel_csv), "--out", str(out),
        cwd=PROJECT_DIR,
    )
    assert proc.returncode == 0, proc.stderr
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "date,code,alpha"

    bad = run_cli("eval", "__import__('os')", "--csv", str(panel_csv), cwd=PROJECT_DIR)
    assert bad.returncode == 2
    assert "表达式求值失败" in bad.stderr


def test_namespace_package_shadow_gets_a_readable_error(tmp_path):
    """cwd 下有个同名空目录时，不能吐 "cannot import name 'catalog' (unknown location)"。"""
    (tmp_path / "quantops").mkdir()
    proc = run_cli("list", cwd=tmp_path)
    if proc.returncode == 0:
        pytest.skip("该环境里 quantops 是 site-packages 里的正规包，同名目录抢不走")
    assert "同名文件夹" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "cannot import name" not in proc.stderr
