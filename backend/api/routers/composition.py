"""HTTP 路由：因子组合提交、组合历史与最新一期选股。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from schemas import FactorCompositionRequest
from services import composition_service

router = APIRouter()


@router.post('/api/factor-compositions', status_code=202)
def create_factor_composition(request: FactorCompositionRequest) -> Dict[str, Any]:
    return composition_service.create_factor_composition(request)


@router.get('/api/factor-compositions')
def get_factor_compositions(
    pool_id: Optional[str] = Query(None, description='按股票池过滤'),
    limit: int = Query(50, ge=1, le=500, description='返回条数上限'),
) -> Dict[str, Any]:
    return composition_service.get_factor_compositions(pool_id, limit)


@router.get('/api/factor-compositions/{composition_id}/screen')
def get_factor_composition_screen(
    composition_id: str,
    pool_id: str = Query(..., description='组合所属股票池'),
    size: Optional[int] = Query(None, ge=1, description='组合规模；省略则用默认规模'),
    limit: int = Query(200, ge=1, le=1000, description='返回排名行数上限'),
) -> Dict[str, Any]:
    return composition_service.get_factor_composition_screen(
        composition_id, pool_id, size=size, limit=limit
    )


@router.get('/api/factor-compositions/{composition_id}')
def get_factor_composition(
    composition_id: str,
    pool_id: str = Query(..., description='组合所属股票池'),
    size: Optional[int] = Query(None, ge=1, description='组合规模；省略则用默认规模'),
) -> Dict[str, Any]:
    return composition_service.get_factor_composition(composition_id, pool_id, size=size)
