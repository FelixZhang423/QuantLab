"""启动平台任务子进程（与 Streamlit 端共用 outputs/jobs 状态机）。

API 只负责创建任务目录并立刻返回；真正的 create_pool / prepare_master 等
操作由独立进程执行，避免阻塞 HTTP 请求。子进程不接收 ClickHouse 凭据。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def spawn_platform_job(job_dir: str | Path) -> None:
    """在后台执行 ``py -3 -m custom_bt.cli run-platform-job --job-dir <job_dir>``。

    标准输出/错误写到任务目录的 runner.log；Windows 下隐藏控制台窗口。
    启动失败（Popen 抛错）由调用方负责把 status.json 标成 failed。
    """
    path = Path(job_dir)
    log_path = path / "runner.log"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    with log_path.open("ab") as log_file:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "custom_bt.cli",
                "run-platform-job",
                "--job-dir",
                str(path),
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )
