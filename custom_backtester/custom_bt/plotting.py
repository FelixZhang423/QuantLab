from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def save_summary_png(daily_report: pd.DataFrame, annual: pd.DataFrame, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    daily = daily_report.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    nav = daily["account"] / daily["account"].iloc[0] if not daily.empty else pd.Series(dtype=float)
    pnl = nav - 1.0
    fig = plt.figure(figsize=(15, 9))
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.0, 1.2])
    ax_curve = fig.add_subplot(gs[0])
    ax_dd = fig.add_subplot(gs[1])
    ax_table = fig.add_subplot(gs[2])
    if not daily.empty:
        ax_curve.plot(daily["date"], pnl, color="#1d3557", linewidth=2.0, label="PNL")
        ax_curve.axhline(0, color="black", linewidth=0.8, alpha=0.4)
        ax_curve.grid(True, alpha=0.25)
        ax_curve.legend(loc="best")
        ax_curve.set_title("Strategy PNL")
        ax_curve.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
        ax_dd.fill_between(daily["date"], daily["drawdown"], 0, color="#e76f51", alpha=0.45)
        ax_dd.grid(True, alpha=0.25)
        ax_dd.set_title("Drawdown")
        ax_dd.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    ax_table.axis("off")
    if not annual.empty:
        table = annual.copy()
        for col in ["return", "max_drawdown", "turnover", "cost", "win_rate"]:
            if col in table.columns:
                table[col] = table[col].map(lambda v: "-" if pd.isna(v) else f"{v:.2%}")
        if "sharpe" in table.columns:
            table["sharpe"] = table["sharpe"].map(lambda v: "-" if pd.isna(v) else f"{v:.2f}")
        ax_table.table(cellText=table.values, colLabels=table.columns, cellLoc="center", loc="center")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
