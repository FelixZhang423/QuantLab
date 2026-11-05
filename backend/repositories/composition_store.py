"""因子组合结果落盘：权重、摘要、admission log 与拒绝记录。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


def write_size_outputs(
    out_dir: Path,
    weights: Sequence[Mapping[str, Any]],
    admission_log: Sequence[Mapping[str, Any]],
) -> None:
    (out_dir / "factor_weights.json").write_text(
        json.dumps(list(weights), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "composition_admission_log.json").write_text(
        json.dumps(list(admission_log), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(list(weights)).to_csv(out_dir / "factor_weights.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([
        {
            "factor_id": row["factor_id"],
            "expression": row["expression"],
            "preprocessed_expression": row["preprocessed_expression"],
            "weight": row["weight"],
            "applied_to": row["applied_to"],
            "preprocess_method": row["preprocess"]["method"],
            "marginal_delta_ic": None if row["marginal"] is None else row["marginal"]["delta"].get("ic"),
            "marginal_delta_rank_ic": None if row["marginal"] is None else row["marginal"]["delta"].get("rank_ic"),
            "marginal_delta_icir": None if row["marginal"] is None else row["marginal"]["delta"].get("icir"),
            **{f"metric_{key}": value for key, value in row["metrics"].items()},
        }
        for row in weights
    ]).to_csv(out_dir / "composition_summary.csv", index=False, encoding="utf-8-sig")


def write_run_outputs(
    output_base: Path,
    composition_id: str,
    summary_rows: Sequence[Mapping[str, Any]],
    admission_log: Sequence[Mapping[str, Any]],
    rejections: Sequence[Mapping[str, Any]],
) -> None:
    run_dir = output_base / composition_id
    pd.DataFrame(list(summary_rows)).to_csv(
        run_dir / "composition_run_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([row for row in summary_rows if row.get("positive_total_return")]).to_csv(
        run_dir / "positive_composition_results.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (run_dir / "composition_admission_log.json").write_text(
        json.dumps(list(admission_log), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (run_dir / "composition_rejections.json").write_text(
        json.dumps(list(rejections), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
