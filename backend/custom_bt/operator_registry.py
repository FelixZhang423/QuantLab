"""算子元数据注册表（转发层）。

``OperatorDefinition`` 与 canonical 定义已搬进独立库 quantops（``quantops.registry``），
这里只做转发，保持既有 import 路径不变。

唯一留在本仓库的是 ``load_alphagen_operator_classes``：它依赖本仓库的
``single_factor/_vendor/alphagen``，属于项目内部耦合，不进通用库。
"""
from __future__ import annotations

from importlib import import_module
import sys
from pathlib import Path
from typing import Dict, List, Type

from custom_bt import _quantops_boot  # noqa: F401  （未安装 quantops 时补 sys.path）
from quantops.registry import (  # noqa: F401
    OperatorDefinition,
    _CORE_DEFINITIONS,
    canonical_name,
    generation_operator_names,
    get_operator,
    list_operator_definitions,
)

__all__ = [
    "OperatorDefinition",
    "canonical_name",
    "generation_operator_names",
    "get_operator",
    "list_operator_definitions",
    "load_alphagen_operator_classes",
    "load_alphagen_operator_map",
]


def load_alphagen_operator_map() -> Dict[str, Type]:
    """canonical 算子名 → AlphaGen 算子类，仅包含 PPO 可采样的算子。"""
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    module = import_module("single_factor._vendor.alphagen.data.expression")
    mapping: Dict[str, Type] = {}
    for definition in list_operator_definitions():
        if not definition.generation_enabled or definition.alphagen_name is None:
            continue
        mapping[definition.canonical_name] = getattr(module, definition.alphagen_name)
    return mapping


def load_alphagen_operator_classes() -> List[Type]:
    return list(load_alphagen_operator_map().values())
