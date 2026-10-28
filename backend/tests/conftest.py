from __future__ import annotations

import os

# 单测默认不碰真实 MySQL：需要联调时显式设置 QL_MYSQL_TEST=1。
if os.environ.get("QL_MYSQL_TEST") != "1":
    os.environ["QL_MYSQL_ENABLED"] = "0"
