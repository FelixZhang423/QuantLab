"""开发启动入口：在 custom_backtester 目录下执行 `py -3 -m api`。

控制台输出照旧（uvicorn 的启动信息、访问日志、报错都还在终端里），
额外把日志落盘到 `outputs/logs/`：`api_<日期>.log`（应用/错误）与
`api_access_<日期>.log`（每个请求一行）。细节与开关见 `api/logging_setup.py`。
"""
from __future__ import annotations

import logging
import os

import uvicorn

from api import logging_setup


def main() -> None:
    host = os.environ.get("QL_API_HOST", "127.0.0.1")
    port = int(os.environ.get("QL_API_PORT", "8000"))

    paths = logging_setup.configure_logging()
    config = uvicorn.Config(
        "api.main:app",
        host=host,
        port=port,
        reload=False,
        # QL_API_LOG=0 时这里是 uvicorn 自带配置的拷贝（不是 None！None 会让 uvicorn
        # 整个跳过日志配置，控制台一个字都不打），见 logging_setup 的注释。
        log_config=logging_setup.uvicorn_log_config(paths),
    )

    # Config(...) 构造时已经把日志配好了，所以这一行现在就同时进控制台和文件。
    # 纯 ASCII：控制台代码页不是 UTF-8，中文在这里会是乱码（文件里没这问题）。
    logging.getLogger(__name__).info(
        "custom_backtester API on http://%s:%s (QL_API_LOG=0 turns file logging off)",
        host,
        port,
    )
    logging.getLogger(__name__).info(logging_setup.describe(paths))

    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
