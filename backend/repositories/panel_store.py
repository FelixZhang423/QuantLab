"""Historical panels are always materialized as verified immutable snapshots."""
from __future__ import annotations

import pandas as pd

from repositories import company_source, snapshot_store
from repositories.local_store import normalize_code
import ast
from custom_bt.engine import BacktestConfig


def expression_fields(expressions) -> list[str]:
    from custom_bt.canonical_expression import normalize_expression
    names = set()
    for expression in expressions:
        tree = ast.parse(normalize_expression(expression).replace("$", ""), mode="eval")
        calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        names.update(node.id for node in ast.walk(tree)
                     if isinstance(node, ast.Name) and id(node) not in calls)
    return sorted(names - {"True", "False"})


def expression_lookback(expressions) -> int:
    """Conservative finite row history for nested time-series operators."""
    from custom_bt.canonical_expression import normalize_expression
    from adapters.operator_registry import get_operator

    def history(node):
        child = max((history(item) for item in ast.iter_child_nodes(node)), default=0)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return child
        definition = get_operator(node.func.id)
        if definition is None or definition.category != "time_series":
            return child
        if any(isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.USub)
               for item in node.args[1:]):
            raise ValueError("Future-looking expression windows are not supported")
        values = [item.value for item in node.args[1:] if isinstance(item, ast.Constant)
                  and isinstance(item.value, (int, float))]
        values += [item.value.value for item in node.keywords
                   if item.arg in {"n", "d", "window", "lookback"}
                   and isinstance(item.value, ast.Constant) and isinstance(item.value.value, (int, float))]
        window = max((int(value) for value in values), default=1)
        if window < 0:
            raise ValueError("Future-looking expression windows are not supported")
        return child + window

    return max((history(ast.parse(normalize_expression(expr).replace("$", ""), mode="eval"))
                for expr in expressions), default=0)


def resolve_panel_snapshot(source, codes, config: BacktestConfig, *, pool_id="",
                        fields=None, snapshot_root=None, snapshot_id=None, as_of=None):
    company_source.resolve_data_source(source)
    required = sorted(set(fields or []) | {"open", "close", "Ifsuspend", "if_up", "if_down"})
    if snapshot_id:
        manifest = snapshot_store.snapshot_manifest(snapshot_id, snapshot_root=snapshot_root)
        if as_of is not None and manifest["as_of"] != as_of:
            raise ValueError("snapshot as_of does not match requested capture label")
        if pool_id and manifest["pool_id"] != pool_id:
            raise ValueError("snapshot pool_id does not match requested pool")
        if sorted({normalize_code(str(c)) for c in codes}) != manifest["codes"]:
            raise ValueError("snapshot stock codes do not match requested pool")
        if (pd.Timestamp(manifest["start_date"]) > pd.Timestamp(config.start_date)
                or pd.Timestamp(manifest["end_date"]) < pd.Timestamp(config.end_date)):
            raise ValueError("Snapshot date range is incomplete; explicitly create a new snapshot")
        missing = set(required) - set(manifest["fields"])
        if missing:
            raise ValueError(f"Snapshot fields are incomplete: {sorted(missing)}")
    else:
        manifest = snapshot_store.create_or_reuse_snapshot(
            codes, required, config.start_date, config.end_date,
            pool_id=pool_id, snapshot_root=snapshot_root, as_of=as_of)
        snapshot_id = manifest["snapshot_id"]
    return manifest


def load_panel_for_pool(source, codes, config: BacktestConfig, *, pool_id="",
                        fields=None, snapshot_root=None, snapshot_id=None, as_of=None, lookback_days=0):
    request_config = config
    if snapshot_id is None and lookback_days:
        from dataclasses import replace
        # Calendar margin covers weekends/holidays; missing listing history remains NaN.
        request_config = replace(config, start_date=str((pd.Timestamp(config.start_date)
                                 - pd.Timedelta(days=lookback_days * 3 + 30)).date()))
    manifest = resolve_panel_snapshot(source, codes, request_config, pool_id=pool_id, fields=fields,
                                      snapshot_root=snapshot_root, snapshot_id=snapshot_id, as_of=as_of)
    snapshot_id = manifest["snapshot_id"]
    columns = ["date", "code", *sorted(set(fields or []) | {"open", "close", "Ifsuspend", "if_up", "if_down"})]
    panel = snapshot_store.load_snapshot(snapshot_id, columns=columns, snapshot_root=snapshot_root)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["code", "date"])
    if lookback_days and pd.Timestamp(manifest["start_date"]) >= pd.Timestamp(config.start_date):
        raise ValueError("Snapshot lacks requested expression warmup; explicitly create an earlier snapshot")
    before = panel[panel["date"] < pd.Timestamp(config.start_date)]
    history = before.groupby("code", group_keys=False).tail(lookback_days) if lookback_days else before.iloc[:0]
    window = panel[(panel["date"] >= pd.Timestamp(config.start_date))
                   & (panel["date"] <= pd.Timestamp(config.end_date))]
    panel = pd.concat([history, window]).sort_values(["date", "code"]).reset_index(drop=True)
    panel.attrs["snapshot_id"] = snapshot_id
    return panel
