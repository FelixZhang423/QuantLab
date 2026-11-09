"""HTTP 路由：PPO 因子生成参数默认值与提交。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from schemas import FactorGenerationRequest
from services import generation_service

router = APIRouter()

@router.get('/api/factor-generations/defaults')
def get_factor_generation_defaults(pool_id: Optional[str]=None) -> Dict[str, Any]:
    return generation_service.get_factor_generation_defaults(pool_id)

@router.post('/api/factor-generations', status_code=202)
def create_factor_generation(request: FactorGenerationRequest) -> Dict[str, Any]:
    return generation_service.create_factor_generation(request)


@router.post('/api/factor-runs/{run_id}/confirm', status_code=202)
def create_factor_confirmation(run_id: str) -> Dict[str, Any]:
    from services.factor_backtest_service import create_factor_confirmation as submit
    return submit(run_id)
