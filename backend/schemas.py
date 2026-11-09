"""API 请求体 schema。路由模块只从这里导入，不再内联定义。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PoolCreateRequest(BaseModel):
    name: str
    selection_start: str
    selection_end: str
    industries: List[str] = Field(default_factory=list)
    exchanges: List[str] = Field(default_factory=list)
    boards: List[str] = Field(default_factory=list)
    sectors: List[str] = Field(default_factory=list)
    listed_states: List[str] = Field(default_factory=list)
    q: str = ""
    min_listed_days: int = 0
    top_n: Optional[int] = None
    min_coverage: float = 0.0
    exclude_suspended: bool = True
    overwrite: bool = False
    # 预览表格手动勾选的代码；None = 使用筛选结果中的全部可建池股票。
    # 空列表是显式「一只都没选」，返回 422，避免静默退化成全选。
    selected_codes: Optional[List[str]] = None


class FactorGenerationSplit(BaseModel):
    cache_start: str
    cache_end: str


class FactorGenerationRequest(BaseModel):
    snapshot_id: Optional[str] = None
    as_of: Optional[str] = None
    pool_id: str
    run_name: Optional[str] = None
    fields: Optional[List[str]] = None
    operators: Optional[List[str]] = None
    splits: Optional[Dict[str, FactorGenerationSplit]] = None
    max_backtrack_days: Optional[int] = None
    target_horizon: Optional[int] = None
    max_future_days: Optional[int] = None
    target_factor_count: Optional[int] = None
    max_attempts: Optional[int] = None
    rollout_timesteps: Optional[int] = None
    seed: Optional[int] = None
    device: Optional[str] = None
    quality: Optional[Dict[str, Optional[float]]] = None


class FactorBacktestRequest(BaseModel):
    snapshot_id: Optional[str] = None
    as_of: Optional[str] = None
    factor_run_id: str
    factor_ids: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    top_k: int = 50
    initial_cash: float = 100_000_000.0
    rebalance_freq: str = "1D"
    commission: float = 0.0003
    transfer_fee: float = 0.00001
    stamp_duty: float = 0.0005
    # Explicit historic all-in fees override the components for that side.
    buy_cost: Optional[float] = None
    sell_cost: Optional[float] = None
    slippage: float = 0.001
    min_cost: float = 5.0
    max_weight_per_stock: float = 0.03


class ManualBacktestRequest(BaseModel):
    snapshot_id: Optional[str] = None
    as_of: Optional[str] = None
    expression: str
    pool_id: str
    run_name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    top_k: int = 50
    initial_cash: float = 100_000_000.0
    rebalance_freq: str = "1D"
    commission: float = 0.0003
    transfer_fee: float = 0.00001
    stamp_duty: float = 0.0005
    # Explicit historic all-in fees override the components for that side.
    buy_cost: Optional[float] = None
    sell_cost: Optional[float] = None
    slippage: float = 0.001
    min_cost: float = 5.0
    max_weight_per_stock: float = 0.03


# ---------- 响应模型（稳定端点） ----------


class HealthResponse(BaseModel):
    ok: bool
    service: str


class OperatorInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    category: str
    category_cn: Optional[str] = None
    canonical_name: Optional[str] = None
    description_cn: Optional[str] = None
    example: Optional[str] = None
    generation_enabled: Optional[bool] = None
    manual_enabled: Optional[bool] = None
    aliases: List[str] = Field(default_factory=list)


class OperatorsResponse(BaseModel):
    total: int
    operators: List[OperatorInfo]


class PoolInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    pool_id: str = ""
    name: str = ""
    data_source: Optional[str] = None
    n_stocks: int = 0
    selection_start: Optional[str] = None
    selection_end: Optional[str] = None
    top_n: Optional[int] = None
    min_listed_days: Optional[int] = None
    min_coverage: Optional[float] = None
    exclude_suspended: Optional[bool] = None
    created_at: Optional[str] = None
    status: Optional[str] = None
    storage: Optional[str] = None


class PoolsResponse(BaseModel):
    total: int
    pools: List[PoolInfo]
    storage: Optional[str] = None


class ResultSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_name: str = ""
    run_key: str = ""
    created_at: Optional[str] = None
    result_type: Optional[str] = None
    canonical_expression: Optional[str] = None
    pool_id: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)


class ResultsResponse(BaseModel):
    total: int
    results: List[ResultSummaryResponse]
