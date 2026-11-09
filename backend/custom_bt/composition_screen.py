"""最新一期组合选股结果。

组合回测给出历史净值；这里额外生成「信号日收盘 → 下一交易日开盘」的选股清单，
用于在 Web 结果页直接查看综合分排名、单因子贡献和下一交易日可买状态。

口径与 ``custom_bt.engine.run_backtest`` 保持一致：
- 信号使用上一交易日收盘后的组合 alpha；
- 下一交易日开盘买入；
- 停牌、开盘价缺失/非法、涨停（新买入）不可买。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查，避免与 factor_composition 循环导入
    from custom_bt.factor_composition import SelectedComponent


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _flag(value: Any, expected: float = 1.0) -> bool:
    number = _finite(value)
    return bool(number is not None and number == expected)


def _ymd(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _normalise_panel(panel: pd.DataFrame) -> pd.DataFrame:
    frame = panel.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame = frame.dropna(subset=["date"]).sort_values(["date", "code"]).reset_index(drop=True)
    for column in ("open", "Ifsuspend", "if_up", "if_down", "close"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _execution_status(
    code: str,
    next_date: pd.Timestamp | None,
    next_rows: pd.DataFrame,
) -> tuple[bool | None, str | None]:
    """返回 (下一开盘是否可买, 阻塞原因)。

    ``next_date is None`` 表示本次数据还没有下一交易日，状态是「待开盘校验」。
    """
    if next_date is None:
        return None, None
    if code not in next_rows.index:
        return False, "next_open_missing_row"
    row = next_rows.loc[code]
    if row.get("Ifsuspend") != 0:
        return False, "next_open_suspended"
    open_price = _finite(row.get("open"))
    if open_price is None or open_price <= 0:
        return False, "next_open_missing"
    if _flag(row.get("if_up")):
        return False, "next_open_limit_up"
    return True, None


def build_latest_screen(
    composite: pd.DataFrame,
    components: "list[SelectedComponent]",
    panel: pd.DataFrame,
    top_k: int,
    *,
    max_weight_per_stock: float = 0.03,
    row_limit: int | None = None,
    signal_date: Any | None = None,
) -> dict[str, Any]:
    """生成组合选股清单。

    ``signal_date`` 省略时取综合分的最新日期（组合刚跑完的默认口径）；
    显式指定时用该日收盘信号 + 面板中的下一交易日行情复算可买状态，
    供「刷新选股清单」在数据更新后重算历史信号日。

    返回字典中 ``rows`` 带单因子贡献，默认包含全部排名行；显式传
    ``row_limit`` 时受其限制，但仍会覆盖全部选中行——停牌/涨停会让选中
    向下补位，可能远低于 top_k。``flat_rows`` 是全市场的扁平记录，供落盘
    CSV 使用。
    """
    if int(top_k) < 1:
        raise ValueError("top_k must be positive")
    if not 0 < float(max_weight_per_stock) <= 1:
        raise ValueError("max_weight_per_stock must be in (0, 1]")
    if not components:
        raise ValueError("screen requires at least one component")

    scores = composite[["date", "code", "alpha"]].copy()
    scores["date"] = pd.to_datetime(scores["date"], errors="coerce")
    scores["code"] = scores["code"].astype(str).str.zfill(6)
    scores["alpha"] = pd.to_numeric(scores["alpha"], errors="coerce")
    scores = scores.dropna(subset=["date", "alpha"])
    if scores.empty:
        raise ValueError("composite alpha has no finite values for screening")
    if signal_date is None:
        signal_date = pd.Timestamp(scores["date"].max())
    else:
        signal_date = pd.Timestamp(signal_date)
        if signal_date not in set(scores["date"]):
            raise ValueError(
                f"signal_date {signal_date.strftime('%Y-%m-%d')} 没有可用的组合分，"
                "请选择面板内有信号的交易日"
            )
    current = scores[scores["date"] == signal_date].drop_duplicates("code", keep="first")
    current = current.sort_values(["alpha", "code"], ascending=[False, True]).reset_index(drop=True)
    current["rank"] = np.arange(1, len(current) + 1)

    data = _normalise_panel(panel)
    panel_dates = sorted(pd.Timestamp(item) for item in data["date"].dropna().unique())
    later_dates = [item for item in panel_dates if item > signal_date]
    next_date = later_dates[0] if later_dates else None
    signal_rows = data[data["date"] == signal_date].set_index("code")
    next_rows = data[data["date"] == next_date].set_index("code") if next_date is not None else pd.DataFrame()
    if next_date is None:
        # 没有下一交易日时按排名选 top_k，执行层留待下一交易日开盘校验。
        selected_flags = (current["rank"] <= int(top_k)).tolist()
    else:
        selected_flags = []
        selected_total = 0
        for code in current["code"].tolist():
            buyable, _reason = _execution_status(code, next_date, next_rows)
            take = bool(buyable) and selected_total < int(top_k)
            selected_flags.append(take)
            if take:
                selected_total += 1

    selected_count = int(sum(selected_flags))
    planned_weight = min(1.0 / max(selected_count, 1), float(max_weight_per_stock)) if selected_count else 0.0

    z_by_factor: list[pd.Series] = []
    for component in components:
        frame = component.zalpha[["date", "code", "alpha"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["code"] = frame["code"].astype(str).str.zfill(6)
        frame = frame[frame["date"] == signal_date].drop_duplicates("code", keep="first")
        frame["alpha"] = pd.to_numeric(frame["alpha"], errors="coerce")
        z_by_factor.append(frame.set_index("code")["alpha"])

    factors = [
        {
            "factor_id": component.factor_id,
            "expression": component.candidate.canonical_expression,
            "preprocessed_expression": component.candidate.backtest_expression,
            "weight": float(component.weight),
            "training_ic": _finite(component.candidate.raw.get("training_ic")),
            "direction": int(component.candidate.raw.get("direction", 1) or 1),
        }
        for component in components
    ]

    def row_payload(record: Any, *, include_contributions: bool) -> dict[str, Any]:
        code = str(record.code)
        rank = int(record.rank)
        selected = bool(selected_flags[rank - 1])
        rank_selected = rank <= int(top_k)
        buyable, blocked_reason = _execution_status(code, next_date, next_rows)
        if next_date is None:
            status = "pending_next_open" if selected else "not_selected"
        elif selected and buyable:
            status = "buyable"
        elif rank_selected and blocked_reason is not None:
            status = "blocked"
        else:
            status = "not_selected"

        signal_row = signal_rows.loc[code] if code in signal_rows.index else None
        next_row = next_rows.loc[code] if code in next_rows.index else None
        contributions: list[dict[str, Any]] = []
        if include_contributions:
            for index, component in enumerate(components):
                z_value = _finite(z_by_factor[index].get(code, np.nan))
                if z_value is None:
                    z_value = 0.0
                weight = float(component.weight)
                contributions.append(
                    {
                        "factor_id": component.factor_id,
                        "zscore": z_value,
                        "weight": weight,
                        "contribution": z_value * weight,
                    }
                )
        return {
            "rank": rank,
            "code": code,
            "composite_score": float(record.alpha),
            "selected": selected,
            "rank_selected": rank_selected,
            "target_weight": planned_weight if selected else 0.0,
            "status": status,
            "blocked_reason": blocked_reason,
            "signal_date": _ymd(signal_date),
            "signal_ifsuspend": None if signal_row is None else _finite(signal_row.get("Ifsuspend")),
            "signal_if_up": None if signal_row is None else _finite(signal_row.get("if_up")),
            "execution_date": _ymd(next_date),
            "next_open": None if next_row is None else _finite(next_row.get("open")),
            "next_ifsuspend": None if next_row is None else _finite(next_row.get("Ifsuspend")),
            "next_if_up": None if next_row is None else _finite(next_row.get("if_up")),
            "buyable_next_open": buyable,
            "contributions": contributions,
        }

    records = list(current.itertuples(index=False))
    flat_rows = [row_payload(record, include_contributions=False) for record in records]
    # 不可买时选中会按排名向下补位，rows 必须覆盖所有 selected，而不只是 top_k。
    if row_limit is None:
        limit = len(records)
    else:
        selected_ranks = [rank for rank, take in enumerate(selected_flags, start=1) if take]
        limit = max(int(row_limit), int(top_k), max(selected_ranks, default=0), 1)
        limit = min(limit, len(records))
    rows = [row_payload(record, include_contributions=True) for record in records[:limit]]
    buyable_count = None if next_date is None else int(sum(1 for row in flat_rows if row["selected"] and row["buyable_next_open"] is True))
    return {
        "signal_date": _ymd(signal_date),
        "execution_date": _ymd(next_date),
        "execution_pending": next_date is None,
        "panel_end_date": _ymd(panel_dates[-1]) if panel_dates else None,
        "top_k": int(top_k),
        "max_weight_per_stock": float(max_weight_per_stock),
        "planned_weight_per_stock": planned_weight,
        "total_ranked": int(len(current)),
        "selected_count": selected_count,
        "buyable_count": buyable_count,
        "factors": factors,
        "rows": rows,
        "flat_rows": flat_rows,
    }
