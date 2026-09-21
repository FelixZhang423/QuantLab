from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd


@dataclass
class IndustryPoolFilter:
    """Select a static or date-aware tradable stock universe."""

    industry: Optional[str | Sequence[str]] = None
    industry_column: str = "industry"
    mapping: Optional[pd.DataFrame] = None
    min_amount: Optional[float] = None
    exclude_suspended: bool = True
    min_listed_days: int = 0

    def _industry_values(self) -> Optional[set[str]]:
        if self.industry is None:
            return None
        if isinstance(self.industry, str):
            return {self.industry}
        return {str(value) for value in self.industry}

    def _apply_common_filters(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if "category" in result.columns:
            result = result[result["category"].astype(str).str.lower() == "stock"]
        if self.exclude_suspended and "Ifsuspend" in result.columns:
            result = result[pd.to_numeric(result["Ifsuspend"], errors="coerce") == 0]
        if "vol" in result.columns:
            result = result[pd.to_numeric(result["vol"], errors="coerce") > 0]
        elif "volume" in result.columns:
            result = result[pd.to_numeric(result["volume"], errors="coerce") > 0]
        if self.min_amount is not None:
            if "amount" not in result.columns:
                raise ValueError("min_amount requires an amount column")
            result = result[
                pd.to_numeric(result["amount"], errors="coerce") >= self.min_amount
            ]
        if self.min_listed_days > 0:
            if "ListedDate" not in result.columns or "date" not in result.columns:
                raise ValueError("min_listed_days requires ListedDate and date columns")
            listed = pd.to_datetime(result["ListedDate"], errors="coerce")
            current = pd.to_datetime(result["date"], errors="coerce")
            result = result[(current - listed).dt.days >= self.min_listed_days]
        return result

    def _apply_static_industry(self, frame: pd.DataFrame) -> pd.DataFrame:
        values = self._industry_values()
        if values is None:
            return frame
        if self.industry_column not in frame.columns:
            raise ValueError(
                f"industry column '{self.industry_column}' is missing; provide a mapping"
            )
        return frame[frame[self.industry_column].astype(str).isin(values)]

    def _attach_mapping(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.mapping is None:
            return frame
        required = {"code", "industry", "valid_from", "valid_to"}
        missing = required - set(self.mapping.columns)
        if missing:
            raise ValueError(f"industry mapping is missing columns: {sorted(missing)}")
        if "date" not in frame.columns:
            raise ValueError("date-aware industry mapping requires a date column")

        left = frame.copy()
        right = self.mapping.copy()
        left["date"] = pd.to_datetime(left["date"], errors="coerce")
        right["valid_from"] = pd.to_datetime(right["valid_from"], errors="coerce")
        right["valid_to"] = pd.to_datetime(right["valid_to"], errors="coerce")
        merged = left.merge(right[["code", "industry", "valid_from", "valid_to"]], on="code")
        valid = (
            (merged["date"] >= merged["valid_from"])
            & (merged["date"] <= merged["valid_to"])
        )
        return merged[valid]

    def select_by_date(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = self._attach_mapping(frame)
        if self.mapping is None:
            result = self._apply_static_industry(result)
        else:
            values = self._industry_values()
            if values is not None:
                result = result[result["industry"].astype(str).isin(values)]
        return self._apply_common_filters(result)

    def select(self, frame: pd.DataFrame) -> list[str]:
        result = self.select_by_date(frame)
        if "code" not in result.columns:
            raise ValueError("stock-pool filtering requires a code column")
        return sorted(result["code"].astype(str).dropna().unique().tolist())
