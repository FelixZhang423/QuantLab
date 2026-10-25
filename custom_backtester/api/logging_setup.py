"""后端日志落盘：应用日志与访问日志分开写到 `outputs/logs/`。

- 文件按**启动日期**命名（跨零点不换名，重启才换）：
    `outputs/logs/api_2026-10-15.log`          启动信息 / 错误 / 应用日志
    `outputs/logs/api_access_2026-10-15.log`   每个 HTTP 请求一行（uvicorn 访问日志）
- **控制台照旧全量输出**，落盘只是额外多一份，不影响你直接在终端看日志。
- 目录用 `QL_API_LOG_DIR` 改；`QL_API_LOG=0` 关闭落盘（行为与本模块引入前完全一致）。
- 中文按 UTF-8 写盘（显式 `encoding="utf-8"`），不受 Windows 控制台代码页影响 ——
  本仓库踩过「命令行中文变 GBK」的坑，日志文件里不能再踩一次。

三个实现上的不显然之处（都是真启动跑出来的，单测第一版恰好绕过了）：

1. **为什么要把 handler 塞进 uvicorn 的 LOGGING_CONFIG，而不是 `addHandler`**：
   `uvicorn.Config.__init__` 会用 `logging.config.dictConfig` 重新配置 `uvicorn` /
   `uvicorn.error` / `uvicorn.access` 三个 logger，dictConfig 对配置里列出的 logger 是
   **替换** handlers。先 addHandler 再 `uvicorn.run(...)` 的话，挂上去的 handler 会被冲掉。
   所以这里改的是那份配置本身，再通过 `log_config=` 传回去。
2. **访问日志必须用 `uvicorn.logging.AccessFormatter`**：uvicorn 打访问日志用的是位置参数
   （`logger.info('%s - "%s %s HTTP/%s" %d', client_addr, method, ...)`），
   `client_addr / request_line / status_code` 是那个 formatter 解析 args 后临时塞进 record 的，
   **不是 `extra`**。用普通 Formatter + 这些占位符会 KeyError，整行记录被丢弃
   （文件 0 字节，只在 stderr 刷 `--- Logging error ---`）。
3. **为什么用 `RotatingFileHandler` 而不是 `TimedRotatingFileHandler`**：后者按时间滚动时
   要改名，而 Windows 上被打开的文件不能改名（PermissionError）。按大小滚动没这个问题；
   「每天一个文件」由文件名里的日期完成。

另有一条纪律：**启动信息那两行只写 ASCII**，因为它同时打到控制台，而 Windows 控制台
默认代码页不是 UTF-8，中文会变成乱码（文件里明明是好的 UTF-8）。
"""
from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # custom_backtester/
DEFAULT_LOG_DIR = PROJECT_ROOT / "outputs" / "logs"

MAX_BYTES = 10 * 1024 * 1024  # 单文件 10MB
BACKUP_COUNT = 3  # 同一天最多保留 api_<日期>.log.1 ~ .3

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_FILE_FORMAT = "%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s"
# 这四个占位符由 uvicorn.logging.AccessFormatter 提供（见 uvicorn_log_config）
_ACCESS_FORMAT = "%(asctime)s\t%(client_addr)s\t%(request_line)s\t%(status_code)s"
_CONSOLE_FORMAT = "%(levelname)s\t%(name)s\t%(message)s"


@dataclass(frozen=True)
class LogPaths:
    """这一次启动写哪三个路径（目录 + 两个文件）。"""

    directory: Path
    app: Path
    access: Path


def logging_enabled() -> bool:
    """`QL_API_LOG=0/false/no/off` 时不落盘。"""
    return str(os.environ.get("QL_API_LOG", "1")).strip().lower() not in ("0", "false", "no", "off")


def resolve_log_dir(log_dir: Optional[Path] = None) -> Path:
    """日志目录：显式参数 > `QL_API_LOG_DIR` > `custom_backtester/outputs/logs`。"""
    if log_dir is not None:
        return Path(log_dir)
    from_env = os.environ.get("QL_API_LOG_DIR")
    return Path(from_env) if from_env else DEFAULT_LOG_DIR


def configure_logging(
    log_dir: Optional[Path] = None,
    *,
    enabled: Optional[bool] = None,
    stamp: Optional[str] = None,
) -> Optional[LogPaths]:
    """算好本次启动的日志路径并建目录；返回 None 表示不落盘。

    返回 None 时 `uvicorn_log_config(None)` 会给回 uvicorn 自带配置 —— 控制台照旧，
    只是没有文件（即本模块引入前的行为）。
    """
    if enabled is None:
        enabled = logging_enabled()
    if not enabled:
        return None
    directory = resolve_log_dir(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now().strftime("%Y-%m-%d")
    return LogPaths(
        directory=directory,
        app=directory / f"api_{stamp}.log",
        access=directory / f"api_access_{stamp}.log",
    )


def uvicorn_log_config(paths: Optional[LogPaths]) -> Dict[str, Any]:
    """uvicorn 默认日志配置 + 两个文件 handler。

    `paths is None`（落盘关掉）时返回 uvicorn **自带**那份配置的拷贝 —— 也就是本模块
    引入前的行为：控制台照旧全量。

    ⚠️ 这里千万不能返回 None。`uvicorn.Config(log_config=None)` 不是「用默认配置」，
    而是**完全跳过** `configure_logging()`（uvicorn 源码里那句 `if self.log_config is
    not None`），于是 uvicorn 的 logger 一个 handler 都没有：启动横幅、访问日志全部
    静默消失，只剩 WARNING 以上靠 logging.lastResort 漏到 stderr。真踩过。
    """
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    # dictConfig 默认 disable_existing_loggers=True，会把已建好的 api.* / custom_bt.*
    # logger 静音（谁在启动前 getLogger 过就中招）。显式关掉，日志宁可多不可少。
    config["disable_existing_loggers"] = False
    if paths is None:  # 不落盘：原样还回去，控制台行为与改动前逐字一致
        return config
    config["formatters"]["file_app"] = {"format": _FILE_FORMAT, "datefmt": _DATE_FORMAT}
    # 访问日志必须用 uvicorn 自己的 AccessFormatter：uvicorn 打访问日志时传的是
    # 位置参数（`logger.info('%s - "%s %s HTTP/%s" %d', client_addr, method, ...)`），
    # client_addr / request_line / status_code 是 AccessFormatter 解析 args 后**临时塞进
    # record** 的，不是 extra。用普通 Formatter + 这些占位符会 KeyError，记录被丢弃
    # （文件里会是空的，只在 stderr 刷 "--- Logging error ---"）。
    config["formatters"]["file_access"] = {
        "()": "uvicorn.logging.AccessFormatter",
        "fmt": _ACCESS_FORMAT,
        "datefmt": _DATE_FORMAT,
        "use_colors": False,  # 文件里不要 ANSI 颜色码
    }
    config["formatters"]["console"] = {"format": _CONSOLE_FORMAT, "datefmt": _DATE_FORMAT}
    config["handlers"]["file_app"] = _rotating_handler(paths.app, "file_app")
    config["handlers"]["file_access"] = _rotating_handler(paths.access, "file_access")
    config["handlers"]["console"] = {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stderr",
        "formatter": "console",
        "level": "INFO",
    }
    # uvicorn 自己的启动/错误 -> 应用日志文件
    config["loggers"]["uvicorn"]["handlers"].append("file_app")
    # 访问日志 -> 独立的访问日志文件（不混进应用日志）
    config["loggers"]["uvicorn.access"]["handlers"].append("file_access")
    # 应用自己的 logging.getLogger(...)（含 custom_bt.*）：控制台 + 文件
    config["root"] = {"handlers": ["console", "file_app"], "level": "INFO"}
    return config


def _rotating_handler(path: Path, formatter: str) -> Dict[str, Any]:
    return {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(path),
        "maxBytes": MAX_BYTES,
        "backupCount": BACKUP_COUNT,
        "encoding": "utf-8",
        "delay": True,  # 没有日志就不建空文件
        "formatter": formatter,
        "level": "INFO",
    }


def describe(paths: Optional[LogPaths]) -> str:
    """给启动日志用的一句话。

    故意用**纯 ASCII**：这行同时打到控制台，而 Windows 控制台的默认代码页不是 UTF-8，
    中文会显示成乱码（文件里是好好的 UTF-8）。控制台上说人话优先于说中文。
    """
    if paths is None:
        return "file logging off (QL_API_LOG=0)"
    return f"logging to {paths.app} (access: {paths.access.name})"
