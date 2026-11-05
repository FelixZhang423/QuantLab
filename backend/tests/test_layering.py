"""分层守卫：接口层可以向下依赖，服务/仓储/配置不能反向依赖。

不引入 import-linter 依赖，用 AST 做一个最小检查，CI 里随 pytest 一起跑。
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

FORBIDDEN = {
    "services": {"api", "fastapi"},
    "repositories": {"api", "services", "fastapi"},
    "workers": {"api", "services"},
    "config": {"api", "services", "repositories"},
    "custom_bt": {"api", "services"},
    "adapters": {"api", "services", "repositories"},
    "infra": {"api", "services", "repositories"},
}


def _files(package: str):
    root = BACKEND / package
    return sorted(root.rglob("*.py")) if root.is_dir() else []


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno


def test_layer_imports() -> None:
    violations: list[str] = []
    # 这些文件仍是「流水线/接口层」，暂时直接调 services.report_service；
    # 后续迁到 services/ 或顶层 cli/ 后删掉例外。
    custom_bt_exceptions = {
        "factor_backtest.py",
        "factor_composition.py",
        "manual_backtest.py",
    }
    for package, forbidden in FORBIDDEN.items():
        for path in _files(package):
            if package == "custom_bt" and path.name in custom_bt_exceptions:
                continue
            for module, lineno in _imports(path):
                root = module.split(".")[0]
                if root in forbidden:
                    rel = path.relative_to(BACKEND)
                    violations.append(f"{rel}:{lineno}: {package} 不能 import {module}")
    assert not violations, "\n".join(violations)


def test_shared_modules_do_not_import_web_layer() -> None:
    violations: list[str] = []
    for name in ("common.py", "errors.py"):
        path = BACKEND / name
        if not path.is_file():
            continue
        for module, lineno in _imports(path):
            if module.split(".")[0] in {"api", "services", "fastapi"}:
                violations.append(f"{name}:{lineno}: 不能 import {module}")
    assert not violations, "\n".join(violations)
