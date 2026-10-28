"""开发态兜底：让 custom_bt 在 quantops 未安装时也能 import 到仓库里的算子库。

- 已 ``py -3 -m pip install -e ../quantops``（或库已在 sys.path 上）时什么都不做；
- 否则把**库的项目目录** ``<仓库根>/quantops`` 插到 sys.path 最前面。

两个不显然的点：
1. 插的必须是项目目录而不是仓库根——仓库根下也有一个叫 quantops 的文件夹（就是库的
   项目目录，本身没有 __init__.py），从仓库根运行时会先把它当成 namespace 包，
   ``import quantops.operators`` 直接失败。指向项目目录才不会歧义。
2. 用 ``insert(0)``：cwd 恰好在仓库根时，sys.path[0] 会记录一个 quantops 的
   namespace 片段；虽然按 PEP 420 后找到的正规包优先，但插到最前面就不用赌这条规则。
   find_spec 已经确认没有可导入的 quantops 才走到这一步，所以不会抢已安装的包。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def ensure_quantops_on_path() -> bool:
    """确保 `import quantops` 可用；返回是否真的补了 sys.path。"""
    spec = importlib.util.find_spec("quantops")
    if spec is not None and spec.origin is not None:
        return False  # 已安装 / 已在 sys.path 上，完全不动
    project_dir = Path(__file__).resolve().parents[2] / "quantops"
    if not (project_dir / "quantops" / "__init__.py").is_file():
        raise ImportError(
            "custom_bt 依赖 quantops 算子库：请执行 py -3 -m pip install -e <仓库根>\\quantops，"
            "或保持仓库目录结构完整（<仓库根>\\quantops\\quantops\\__init__.py）"
        )
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    return True


ensure_quantops_on_path()
