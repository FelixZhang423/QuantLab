"""命令行入口：

    py -3 -m quantops list [--category time_series] [--search ts_] [--json]
    py -3 -m quantops describe ts_mean
    py -3 -m quantops eval "rank(ts_mean(close, 20))" --csv panel.csv [--out alpha.csv]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd


def _import_api():
    """导入公开 API；被同名目录当成空包时，把 PEP 420 的怪错误翻译成人话。

    cwd 下有个叫 quantops 的文件夹时（例如本库自己的项目目录），Python 先把它解析成
    namespace 包，随后 `from quantops import catalog` 只会报
    "cannot import name 'catalog' from 'quantops' (unknown location)" —— 看不出原因。
    """
    try:
        from quantops import catalog, categories, describe, evaluate
        from quantops.errors import ExpressionError
    except ImportError as exc:
        package = sys.modules.get("quantops")
        if getattr(package, "__file__", None) is None:
            raise SystemExit(
                f"无法导入 quantops：当前目录 {Path.cwd()} 下有个同名文件夹，"
                "Python 把它当成了空包（PEP 420 namespace package）。\n"
                "请换一个目录运行，或先进入库的项目目录（cd <仓库根>\\quantops）再执行。"
            ) from exc
        raise
    return catalog, categories, describe, evaluate, ExpressionError


catalog, categories, describe, evaluate, ExpressionError = _import_api()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantops", description="quantops 算子库命令行")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="列出算子（可按分类 / 关键字过滤）")
    list_parser.add_argument("--category", default=None, help="分类 key 或中文名，如 time_series / 时间序列")
    list_parser.add_argument("--search", default=None, help="按算子名 / 说明 / 示例模糊搜索")
    list_parser.add_argument("--json", action="store_true", help="输出 JSON（含富化字段）")

    describe_parser = sub.add_parser("describe", help="查看单个算子详情")
    describe_parser.add_argument("name", help="算子名，如 ts_mean")
    describe_parser.add_argument("--json", action="store_true", help="输出 JSON")

    eval_parser = sub.add_parser("eval", help="对 CSV 面板求值表达式")
    eval_parser.add_argument("expr", help="表达式，如 rank(ts_mean(close, 20))")
    eval_parser.add_argument("--csv", required=True, help="输入面板 CSV（需含 date / code 列）")
    eval_parser.add_argument("--out", default=None, help="把结果写成 CSV（默认只打印前几行）")
    eval_parser.add_argument("--name", default="alpha", help="输出列名（默认 alpha）")
    eval_parser.add_argument("--head", type=int, default=10, help="打印行数（默认 10）")
    return parser


def _cmd_list(args: argparse.Namespace) -> int:
    items = catalog()
    if args.category:
        items = [item for item in items if item["category"] == args.category or item["category_cn"] == args.category]
    if args.search:
        needle = args.search.lower()
        items = [
            item
            for item in items
            if needle in f"{item['name']}{item['description_cn']}{item['example']}".lower()
        ]
    if args.json:
        payload = {"total": len(items), "categories": categories(), "operators": items}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("分类：" + "，".join(f"{item['label']}({item['key']}) {item['count']}" for item in categories()))
    print(f"共 {len(items)} 个算子")
    width = max((len(item["name"]) for item in items), default=4)
    for item in items:
        print(f"{item['name']:<{width}}  [{item['category_cn']}]  {item['description_cn']}")
        print(f"{'':<{width}}  例：{item['example']}")
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    try:
        item = describe(args.name)
    except KeyError as exc:
        print(f"未知算子：{args.name}（{exc}）", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0
    print(f"{item['name']}（{item['category_cn']} / {item['category']}）")
    print(f"  canonical：{item['canonical_name']}")
    print(f"  说明：{item['description_cn']}")
    print(f"  示例：{item['example']}")
    print(f"  因子生成可用：{'是' if item['generation_enabled'] else '否'}；手动配置可用：{'是' if item['manual_enabled'] else '否'}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    panel = pd.read_csv(args.csv)
    try:
        out = evaluate(args.expr, panel, output_name=args.name)
    except ExpressionError as exc:
        print(f"表达式求值失败：{exc}", file=sys.stderr)
        return 2
    if args.out:
        out.to_csv(args.out, index=False)
        print(f"已写出 {args.out}（{len(out)} 行）")
        return 0
    print(out.head(args.head).to_string(index=False))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {"list": _cmd_list, "describe": _cmd_describe, "eval": _cmd_eval}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
