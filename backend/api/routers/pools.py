"""HTTP 路由：股票池列表、详情、删除与建池任务。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from schemas import PoolCreateRequest, PoolsResponse
from services import pool_service

router = APIRouter()

@router.get('/api/pools', response_model=PoolsResponse)
def get_pools() -> Dict[str, Any]:
    return pool_service.get_pools()

@router.get('/api/pools/{pool_id}')
def get_pool(pool_id: str) -> Dict[str, Any]:
    return pool_service.get_pool(pool_id)

@router.delete('/api/pools/{pool_id}')
def delete_pool(pool_id: str, confirm: bool=Query(False, description='必须显式传 true 才会删除')) -> Dict[str, Any]:
    return pool_service.delete_pool(pool_id, confirm)

@router.post('/api/pools', status_code=202)
def create_pool(request: PoolCreateRequest) -> Dict[str, Any]:
    return pool_service.create_pool(request)
