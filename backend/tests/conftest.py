from __future__ import annotations

import os

# Windows/Anaconda 下 torch(MKL) 与 matplotlib 会各自带一份 OpenMP runtime，
# 同时加载时可能直接 abort（libiomp5md.dll already initialized）。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# 测试不依赖 GUI；固定 Agg，避免 qtagg 在无显示环境里初始化。
os.environ.setdefault("MPLBACKEND", "Agg")

# 单测默认不碰真实 MySQL：需要联调时显式设置 QL_MYSQL_TEST=1。
if os.environ.get("QL_MYSQL_TEST") != "1":
    os.environ["QL_MYSQL_ENABLED"] = "0"
