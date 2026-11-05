"""HTTP 路由：数据总览 / 字段 / 股票 / 候选股票池 / 算子查询。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from schemas import OperatorsResponse
from services import data_service

router = APIRouter()

@router.get('/api/data/master')
def get_master_info() -> Dict[str, Any]:
    return data_service.get_master_info()

@router.get('/api/data/fields')
def get_fields() -> Dict[str, Any]:
    return data_service.get_fields()

@router.get('/api/data/stocks')
def get_stocks(q: str=Query('', description='按股票代码或名称匹配'), limit: int=Query(0, ge=0, description='0 表示不截断'), offset: int=Query(0, ge=0)) -> Dict[str, Any]:
    return data_service.get_stocks(q, limit, offset)

@router.get('/api/universe/options')
def get_universe_options() -> Dict[str, Any]:
    return data_service.get_universe_options()

@router.get('/api/universe/stocks')
def get_universe_stocks(industries: List[str]=Query(default=[], description='行业（可重复）'), exchanges: List[str]=Query(default=[], description='SH/SZ/BJ/OTHER（可重复）'), boards: List[str]=Query(default=[], description='上市板块（可重复）'), sectors: List[str]=Query(default=[], description='库内 ListedSector 原值（可重复）'), listed_states: List[str]=Query(default=[], description='库内 ListedState 原值（可重复）'), q: str=Query('', description='按代码或名称匹配'), min_listed_days: int=Query(0, ge=0), as_of: str=Query('', description='上市天数截止日 YYYY-MM-DD，缺省今天'), limit: int=Query(50, ge=1, le=500), offset: int=Query(0, ge=0)) -> Dict[str, Any]:
    return data_service.get_universe_stocks(industries, exchanges, boards, sectors, listed_states, q, min_listed_days, as_of, limit, offset)

@router.get('/api/universe/codes')
def get_universe_codes(industries: List[str]=Query(default=[], description='行业（可重复）'), exchanges: List[str]=Query(default=[], description='SH/SZ/BJ/OTHER（可重复）'), boards: List[str]=Query(default=[], description='上市板块（可重复）'), sectors: List[str]=Query(default=[], description='库内 ListedSector 原值（可重复）'), listed_states: List[str]=Query(default=[], description='库内 ListedState 原值（可重复）'), q: str=Query('', description='按代码或名称匹配'), min_listed_days: int=Query(0, ge=0), as_of: str=Query('', description='上市天数截止日 YYYY-MM-DD，缺省今天')) -> Dict[str, Any]:
    return data_service.get_universe_codes(industries, exchanges, boards, sectors, listed_states, q, min_listed_days, as_of)

@router.get('/api/operators', response_model=OperatorsResponse)
def get_operators() -> Dict[str, Any]:
    return data_service.get_operators()
